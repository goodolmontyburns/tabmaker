import os
import uuid
import shutil
import json
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydub import AudioSegment

from backend.ingest import ingest_youtube_slice
from backend.cloud_client import call_cloud_gpu_worker
from backend.transcription.pitch_tracker import extract_notes_and_bends, postprocess_note_events
from backend.transcription.fingering_optimizer import estimate_key_and_box
from backend.copilot.gemini_client import GeminiClient, _load_dotenv_if_present
from backend.copilot.video_gatekeeper import analyze_video_feasibility
from backend.copilot.tab_polish import polish_tab

_load_dotenv_if_present()

app = FastAPI(title="TabMaker Studio Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"GLOBAL ERROR: {exc}")
    return JSONResponse(status_code=500, content={"message": str(exc)})


UPLOAD_DIR = os.path.abspath("temp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=UPLOAD_DIR), name="output")

JOBS: Dict[str, Dict[str, Any]] = {}


def save_notes_to_midi(notes: List[Dict[str, Any]], midi_path: str) -> None:
    try:
        import pretty_midi
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=27)
        for n in notes:
            pitch = max(0, min(127, int(n.get("p", 60))))
            start = max(0.0, float(n.get("t", 0.0)))
            end = start + max(0.05, float(n.get("d", 0.1)))
            instrument.notes.append(pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end))
        midi.instruments.append(instrument)
        midi.write(midi_path)
    except Exception as e:
        print(f"Error saving MIDI file: {e}")


def _set_job(job_id: Optional[str], stage: str, progress: int, status: str = "running", **extra: Any) -> None:
    if not job_id or job_id not in JOBS:
        return
    JOBS[job_id].update({"stage": stage, "progress": progress, "status": status, **extra})


def run_transcription_pipeline(
    session_id: str,
    session_dir: str,
    cropped_path: str,
    video_path: Optional[str],
    duration: float,
    video_title: str,
    target_fret: Optional[int],
    api_key: Optional[str],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    cloud_worker_url = os.environ.get("CLOUD_WORKER_URL", "").strip()
    guitar_path = cropped_path
    backing_path: Optional[str] = None
    has_isolated_stem = False
    beats: List[float] = []
    downbeats: List[float] = []
    bpm = 120.0
    raw_notes: List[Dict[str, Any]] = []
    stem_metrics: Dict[str, Any] = {}
    cloud_used = False

    # 1. Run Cloud Run L4 GPU Worker (Beat This! + BS-RoFormer-SW + MT3 + TorchCREPE)
    if cloud_worker_url:
        _set_job(job_id, "Running Cloud GPU stem separation & pitch tracking...", 30)
        try:
            gpu_res, guitar_bytes, backing_bytes = call_cloud_gpu_worker(
                cropped_path,
                worker_url=cloud_worker_url,
                target_fret=target_fret,
                solo_mode=True,
            )
            cloud_used = True
            beats = gpu_res.get("beats", [])
            downbeats = gpu_res.get("downbeats", [])
            bpm = float(gpu_res.get("bpm", 120.0))
            raw_notes = gpu_res.get("raw_notes", [])
            stem_metrics = gpu_res.get("stem_metrics", {})

            stems_dir = os.path.join(session_dir, "stems")
            os.makedirs(stems_dir, exist_ok=True)
            if guitar_bytes:
                g_out = os.path.join(stems_dir, "guitar.wav")
                with open(g_out, "wb") as gf:
                    gf.write(guitar_bytes)
                guitar_path = g_out
                has_isolated_stem = bool(gpu_res.get("has_isolated_stem", True))
            if backing_bytes:
                b_out = os.path.join(stems_dir, "backing.wav")
                with open(b_out, "wb") as bf:
                    bf.write(backing_bytes)
                backing_path = b_out
        except Exception as e:
            print(f"Cloud GPU worker call failed ({e}); falling back to local CPU extraction")

    # 2. Local CPU fallback if Cloud Worker is unconfigured or unavailable
    if not cloud_used:
        _set_job(job_id, "Extracting notes & pitch contours locally...", 45)
        note_events = extract_notes_and_bends(guitar_path, target_fret=target_fret, bpm=bpm)
        raw_notes = [n.to_dict() for n in note_events]

    # 3. Cropped Video Fretboard Gatekeeper (Gemini 4 Argon)
    _set_job(job_id, "Inspecting video frames for fretboard position...", 65)
    gemini_client = GeminiClient(api_key=api_key) if api_key else GeminiClient()
    video_info = analyze_video_feasibility(
        video_path,
        duration=duration,
        gemini_client=gemini_client,
    )
    neck_priors = video_info.get("neck_priors") or []

    # 4. 6-String Key-Aware & Video-Prior Viterbi Solving
    _set_job(job_id, "Solving 6-string fretboard fingerings & bends...", 75)
    solved_notes, key_info = postprocess_note_events(
        raw_notes,
        target_fret=target_fret,
        bpm=bpm,
        neck_priors=neck_priors,
    )
    detected_key = key_info["key"]

    # 5. Gemini 4 Argon Fast Multimodal Audio+Tab Polish
    _set_job(job_id, "Polishing tablature with Gemini 4...", 88)
    polished_notes = solved_notes
    ai_applied = False
    final_key = detected_key
    final_bpm = bpm
    polish_model = None
    try:
        polish_res = polish_tab(
            notes=solved_notes,
            audio_path=guitar_path,
            video_path=video_path,
            duration=duration,
            key_hint=detected_key,
            bpm=bpm,
            target_fret=target_fret,
            video_info=video_info,
            gemini_client=gemini_client,
            deep_polish=False,
        )
        if polish_res.get("success"):
            polished_notes = polish_res.get("notes", solved_notes)
            ai_applied = bool(polish_res.get("ai_applied", False))
            final_key = polish_res.get("key") or detected_key
            final_bpm = float(polish_res.get("tempo_bpm", bpm))
            polish_model = polish_res.get("model_used")
    except Exception as e:
        print(f"Gemini polish fallback: {e}")

    midi_path = os.path.join(session_dir, "solo.mid")
    save_notes_to_midi(polished_notes, midi_path)

    available_stems: Dict[str, str] = {}
    if has_isolated_stem:
        available_stems["guitar"] = f"/output/{session_id}/stems/guitar.wav"
    if backing_path and os.path.exists(backing_path):
        available_stems["backing"] = f"/output/{session_id}/stems/backing.wav"

    response_data = {
        "session_id": session_id,
        "title": video_title,
        "notes": polished_notes,
        "pre_polish_notes": solved_notes,
        "raw_note_count": len(raw_notes),
        "duration": duration,
        "bpm": round(final_bpm, 1),
        "beats": beats,
        "downbeats": downbeats,
        "stems": available_stems,
        "has_isolated_stem": has_isolated_stem,
        "stem_metrics": stem_metrics,
        "cloud_gpu_used": cloud_used,
        "ai_applied": ai_applied,
        "model_used": polish_model,
        "key": final_key,
        "is_ground_truth": False,
        "video_analysis": {
            "is_live_guitar": video_info.get("is_live_guitar", False),
            "mode": video_info.get("mode", "theory_audio"),
            "reason": video_info.get("reason", ""),
            "neck_region": video_info.get("neck_region"),
            "neck_priors": neck_priors,
        },
        "original": f"/output/{session_id}/cropped.wav",
        "guitar_stem": available_stems.get("guitar", f"/output/{session_id}/cropped.wav"),
        "backing_stem": available_stems.get("backing"),
        "midi": f"/output/{session_id}/solo.mid",
    }

    cache_path = os.path.join(session_dir, "session.json")
    with open(cache_path, "w") as f:
        json.dump(response_data, f)

    return response_data


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cloud_worker_configured": bool(os.environ.get("CLOUD_WORKER_URL", "").strip()),
        "gcp_project": os.environ.get("GCP_PROJECT_ID", "tabmaker-studio-2026"),
    }


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    cache_path = os.path.join(session_dir, "session.json")
    if not os.path.exists(cache_path):
        raise HTTPException(status_code=404, detail="Session not found")
    with open(cache_path, "r") as f:
        return json.load(f)


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _prepare_audio_and_video(
    session_dir: str,
    youtube_url: Optional[str],
    uploaded_file_path: Optional[str],
    uploaded_filename: Optional[str],
    start_time: float,
    end_time: float,
):
    if youtube_url:
        return ingest_youtube_slice(youtube_url, session_dir, start_time=start_time, end_time=end_time)

    if uploaded_file_path and os.path.exists(uploaded_file_path):
        title = os.path.basename(uploaded_filename or "Uploaded Solo").rsplit(".", 1)[0]
        audio = AudioSegment.from_file(uploaded_file_path)
        total_len = len(audio) / 1000.0
        crop_start = max(0.0, float(start_time))
        crop_end = min(total_len, float(end_time)) if float(end_time) > crop_start else min(total_len, crop_start + 45.0)
        if crop_end <= crop_start:
            crop_end = min(total_len, crop_start + 30.0)
        cropped_path = os.path.join(session_dir, "cropped.wav")
        audio[int(crop_start * 1000):int(crop_end * 1000)].set_frame_rate(44100).set_channels(2).export(
            cropped_path, format="wav"
        )
        return cropped_path, None, round(crop_end - crop_start, 3), title

    raise HTTPException(status_code=400, detail="Provide either youtube_url or an audio file.")


@app.post("/process")
async def process_audio(
    file: UploadFile = File(None),
    youtube_url: Optional[str] = Form(None),
    start_time: float = Form(0.0),
    end_time: float = Form(30.0),
    target_fret: Optional[int] = Form(None),
    api_key: Optional[str] = Form(None),
):
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    uploaded_path = None
    uploaded_name = None
    if file is not None:
        uploaded_name = file.filename
        uploaded_path = os.path.join(session_dir, "input.audio")
        with open(uploaded_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)

    try:
        cropped_path, video_path, duration, title = await asyncio.to_thread(
            _prepare_audio_and_video,
            session_dir,
            youtube_url.strip() if youtube_url else None,
            uploaded_path,
            uploaded_name,
            start_time,
            end_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = await asyncio.to_thread(
        run_transcription_pipeline,
        session_id,
        session_dir,
        cropped_path,
        video_path,
        duration,
        title,
        target_fret,
        api_key,
        None,
    )
    return result


@app.post("/process_async")
async def process_audio_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(None),
    youtube_url: Optional[str] = Form(None),
    start_time: float = Form(0.0),
    end_time: float = Form(30.0),
    target_fret: Optional[int] = Form(None),
    api_key: Optional[str] = Form(None),
):
    session_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    uploaded_path = None
    uploaded_name = None
    if file is not None:
        uploaded_name = file.filename
        uploaded_path = os.path.join(session_dir, "input.audio")
        with open(uploaded_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)

    JOBS[job_id] = {
        "job_id": job_id,
        "session_id": session_id,
        "status": "running",
        "stage": "Downloading targeted solo slice...",
        "progress": 10,
        "result": None,
        "error": None,
    }

    def _worker():
        try:
            cropped_path, video_path, duration, title = _prepare_audio_and_video(
                session_dir,
                youtube_url.strip() if youtube_url else None,
                uploaded_path,
                uploaded_name,
                start_time,
                end_time,
            )
            res = run_transcription_pipeline(
                session_id=session_id,
                session_dir=session_dir,
                cropped_path=cropped_path,
                video_path=video_path,
                duration=duration,
                video_title=title,
                target_fret=target_fret,
                api_key=api_key,
                job_id=job_id,
            )
            _set_job(job_id, "Complete", 100, status="completed", result=res)
        except Exception as e:
            _set_job(job_id, "Failed", 100, status="failed", error=str(e))

    background_tasks.add_task(_worker)
    return {"job_id": job_id, "session_id": session_id}


@app.post("/polish")
async def polish_session_tab(
    session_id: str = Form(...),
    api_key: Optional[str] = Form(None),
    key_hint: Optional[str] = Form(None),
):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    cache_path = os.path.join(session_dir, "session.json")
    if not os.path.exists(cache_path):
        raise HTTPException(status_code=404, detail="Session data not found")

    with open(cache_path, "r") as f:
        data = json.load(f)

    notes = data.get("notes", [])
    duration = float(data.get("duration", 0.0))
    bpm = float(data.get("bpm", 120.0))
    video_path = os.path.join(session_dir, "solo.mp4")
    if not os.path.exists(video_path):
        video_path = None

    audio_path = os.path.join(session_dir, "stems", "guitar.wav")
    if not os.path.exists(audio_path):
        audio_path = os.path.join(session_dir, "cropped.wav")
    if not os.path.exists(audio_path):
        audio_path = None

    client = GeminiClient(api_key=api_key) if api_key else GeminiClient()
    polish_result = await asyncio.to_thread(
        polish_tab,
        notes=notes,
        audio_path=audio_path,
        video_path=video_path,
        duration=duration,
        key_hint=key_hint or data.get("key"),
        bpm=bpm,
        gemini_client=client,
        deep_polish=True,
    )

    if polish_result.get("success"):
        data["notes"] = polish_result.get("notes", notes)
        data["key"] = polish_result.get("key") or data.get("key")
        data["bpm"] = polish_result.get("tempo_bpm", bpm)
        data["ai_applied"] = polish_result.get("ai_applied", False)
        data["polish_mode"] = polish_result.get("mode")

        with open(cache_path, "w") as f:
            json.dump(data, f)
        save_notes_to_midi(data["notes"], os.path.join(session_dir, "solo.mid"))

    return polish_result


@app.post("/session/{session_id}/notes")
async def save_session_notes(session_id: str, payload: dict):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    cache_path = os.path.join(session_dir, "session.json")
    notes = payload.get("notes", [])
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            data["notes"] = notes
            with open(cache_path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error updating notes in cache: {e}")

    save_notes_to_midi(notes, os.path.join(session_dir, "solo.mid"))
    return {"status": "success"}


@app.get("/benchmark/ground_truth")
async def get_ground_truth_session_endpoint():
    from backend.benchmark.export_ground_truth_session import generate_ground_truth_session
    return generate_ground_truth_session()


FRONTEND_DIST = os.path.abspath("frontend/dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
