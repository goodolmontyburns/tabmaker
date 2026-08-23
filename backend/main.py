import os
import sys
import uuid
import shutil
import json
import subprocess
from typing import Optional, List, Dict, Any
import numpy as np
if not hasattr(np, "int"):
    np.int = int
import yt_dlp
import librosa
import soundfile as sf
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydub import AudioSegment

from backend.transcription.pitch_tracker import extract_notes_and_bends, NoteEvent
from backend.copilot.gemini_client import GeminiClient
from backend.copilot.video_gatekeeper import analyze_video_feasibility
from backend.copilot.tab_polish import polish_tab

app = FastAPI(title="TabMaker v2 Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8001", "http://127.0.0.1:8001", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"GLOBAL ERROR: {exc}")
    return JSONResponse(status_code=500, content={"message": str(exc)})

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=UPLOAD_DIR), name="output")

def save_notes_to_midi(notes: List[Dict[str, Any]], midi_path: str):
    try:
        import pretty_midi
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=27)  # Electric Guitar (clean)
        for n in notes:
            pitch = int(n.get("p", 60))
            start = float(n.get("t", 0))
            end = start + max(0.05, float(n.get("d", 0.1)))
            note = pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end)
            instrument.notes.append(note)
        midi.instruments.append(instrument)
        midi.write(midi_path)
    except Exception as e:
        print(f"Error saving MIDI file: {e}")

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")
    
    cache_path = os.path.join(session_dir, "session.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"Error loading session cache JSON: {e}")

    raise HTTPException(status_code=404, detail="Session cache not found")

@app.post("/process")
async def process_audio(
    file: UploadFile = File(None),
    youtube_url: str = Form(None),
    start_time: float = Form(...),
    end_time: float = Form(...),
    target_fret: int = Form(8),
    isolate_stems: bool = Form(False),
    api_key: Optional[str] = Form(None)
):
    session_id = str(uuid.uuid4())
    session_dir = os.path.abspath(os.path.join(UPLOAD_DIR, session_id))
    os.makedirs(session_dir, exist_ok=True)
    
    input_audio_path = os.path.join(session_dir, "input.audio")
    input_video_path = os.path.join(session_dir, "video.mp4")
    has_video = False

    if youtube_url:
        ytdlp_bin = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
        if not os.path.exists(ytdlp_bin):
            ytdlp_bin = "yt-dlp"
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        video_title = "YouTube Guitar Solo"

        # Try to extract real video title
        try:
            t_cmd = [ytdlp_bin, "--extractor-args", "youtube:player_client=android", "-e", youtube_url]
            res_t = subprocess.run(t_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            if res_t.returncode == 0:
                t_str = res_t.stdout.decode().strip()
                if t_str:
                    video_title = t_str
        except Exception:
            pass

        # 1. Download best audio stream
        success = False
        download_strategies = [
            ["--extractor-args", "youtube:player_client=android", "-f", "18/bestaudio/best"],
            ["--extractor-args", "youtube:player_client=android", "-f", "bestaudio/best"],
            ["-f", "18/bestaudio/best"],
            ["-f", "bestaudio/best"]
        ]

        for strat in download_strategies:
            try:
                cmd = [
                    ytdlp_bin,
                    "-x", "--audio-format", "wav",
                    "--ffmpeg-location", ffmpeg_bin,
                    "-o", input_audio_path,
                    "--no-playlist"
                ] + strat + [youtube_url]
                print(f"Running audio download: {' '.join(cmd)}")
                subprocess.run(cmd, check=True, timeout=60)
                if os.path.exists(input_audio_path + ".wav"):
                    input_audio_path += ".wav"
                    success = True
                    break
                elif os.path.exists(input_audio_path):
                    success = True
                    break
            except Exception as e:
                print(f"Audio download attempt failed with strategy {strat}: {e}")
                continue

        if not success:
            raise HTTPException(
                status_code=400,
                detail="Could not download audio from YouTube. Please check the URL or upload a WAV/MP3 file directly."
            )

        # 2. Try to download low-res MP4 for video analysis
        try:
            v_cmd = [
                ytdlp_bin, "-f", "18/worstvideo[ext=mp4]/best[ext=mp4]",
                "-o", input_video_path,
                "--no-playlist"
            ] + [youtube_url]
            subprocess.run(v_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
            if os.path.exists(input_video_path):
                has_video = True
        except Exception:
            has_video = False

    elif file:
        video_title = os.path.basename(file.filename).rsplit('.', 1)[0]
        with open(input_audio_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    # Crop Audio
    audio = AudioSegment.from_file(input_audio_path)
    total_audio_len = len(audio) / 1000.0
    
    crop_start = max(0.0, float(start_time))
    crop_end = min(total_audio_len, float(end_time)) if float(end_time) > 0 else min(total_audio_len, crop_start + 45.0)
    if crop_end <= crop_start:
        crop_end = min(total_audio_len, crop_start + 30.0)

    cropped_path = os.path.join(session_dir, "cropped.wav")
    audio[int(crop_start * 1000):int(crop_end * 1000)].export(cropped_path, format="wav")
    duration = float(crop_end - crop_start)

    # Stem Isolation with Demucs (if requested)
    available_stems = {}
    guitar_path = cropped_path
    if isolate_stems:
        demucs_bin = os.path.join(os.path.dirname(sys.executable), "demucs")
        if not os.path.exists(demucs_bin):
            demucs_bin = shutil.which("demucs") or "demucs"
        try:
            cmd = [demucs_bin, "-n", "htdemucs_6s", "--shifts", "0", "-o", session_dir, cropped_path]
            subprocess.run(cmd, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
            for s in ["guitar", "piano", "other", "vocals", "bass", "drums"]:
                path = os.path.join(stem_base, f"{s}.wav")
                if os.path.exists(path):
                    available_stems[s] = f"http://localhost:8001/output/{session_id}/htdemucs_6s/cropped/{s}.wav"
            if os.path.exists(os.path.join(stem_base, "guitar.wav")):
                guitar_path = os.path.join(stem_base, "guitar.wav")
        except Exception as e:
            print(f"Demucs isolation skipped/fallback: {e}")

    # High-Accuracy Continuous Pitch & Bend Tracking
    note_events = extract_notes_and_bends(guitar_path, target_fret=target_fret)
    notes_dict_list = [n.to_dict() for n in note_events]

    # Infer Musical Key dynamically from extracted pitches
    from backend.copilot.tab_polish import infer_key_from_notes
    detected_key = infer_key_from_notes(notes_dict_list)

    # Video Vision Gatekeeper
    gemini_client = GeminiClient(api_key=api_key) if api_key else GeminiClient()
    video_analysis = analyze_video_feasibility(
        input_video_path if has_video else None,
        duration=duration,
        gemini_client=gemini_client
    )

    # Automatic Multimodal AI Tab Polishing
    polished_notes = notes_dict_list
    ai_applied = False
    try:
        polish_result = polish_tab(
            notes=notes_dict_list,
            audio_path=guitar_path,
            video_path=input_video_path if has_video else None,
            duration=duration,
            key_hint=detected_key,
            gemini_client=gemini_client
        )
        if polish_result.get("success"):
            polished_notes = polish_result.get("notes", notes_dict_list)
            ai_applied = True
    except Exception as e:
        print(f"Automatic AI tab polish skipped/fallback: {e}")

    # Save initial MIDI
    midi_path = os.path.join(session_dir, "solo.mid")
    save_notes_to_midi(polished_notes, midi_path)

    response_data = {
        "session_id": session_id,
        "title": video_title,
        "notes": polished_notes,
        "duration": duration,
        "stems": available_stems,
        "ai_applied": ai_applied,
        "key": polish_result.get("key") if ai_applied else detected_key,
        "is_ground_truth": False,
        "video_analysis": {
            "is_live_guitar": video_analysis.get("is_live_guitar", False),
            "mode": video_analysis.get("mode", "theory_audio"),
            "reason": video_analysis.get("reason", "")
        },
        "original": f"/output/{session_id}/cropped.wav",
        "guitar_stem": f"/output/{session_id}/htdemucs_6s/cropped/guitar.wav" if "guitar" in available_stems else f"/output/{session_id}/cropped.wav",
        "midi": f"/output/{session_id}/solo.mid"
    }

    # Save cache
    cache_path = os.path.join(session_dir, "session.json")
    try:
        with open(cache_path, "w") as f:
            json.dump(response_data, f)
    except Exception as e:
        print(f"Error writing session cache: {e}")

    return response_data

@app.post("/polish")
async def polish_session_tab(
    session_id: str = Form(...),
    api_key: Optional[str] = Form(None),
    key_hint: Optional[str] = Form(None)
):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir):
        raise HTTPException(status_code=404, detail="Session not found")

    cache_path = os.path.join(session_dir, "session.json")
    if not os.path.exists(cache_path):
        raise HTTPException(status_code=404, detail="Session data not found")

    with open(cache_path, "r") as f:
        data = json.load(f)

    notes = data.get("notes", [])
    duration = float(data.get("duration", 0.0))
    video_path = os.path.join(session_dir, "video.mp4")
    if not os.path.exists(video_path):
        video_path = None

    # Check for isolated guitar stem or cropped audio
    audio_path = os.path.join(session_dir, "htdemucs_6s", "cropped", "guitar.wav")
    if not os.path.exists(audio_path):
        audio_path = os.path.join(session_dir, "cropped.wav")
    if not os.path.exists(audio_path):
        audio_path = None

    client = GeminiClient(api_key=api_key) if api_key else GeminiClient()
    polish_result = polish_tab(
        notes=notes,
        audio_path=audio_path,
        video_path=video_path,
        duration=duration,
        key_hint=key_hint,
        gemini_client=client
    )

    if polish_result.get("success"):
        data["notes"] = polish_result.get("notes", notes)
        data["key"] = polish_result.get("key")
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
    session = generate_ground_truth_session()
    return session

FRONTEND_DIST = os.path.abspath("frontend/dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
