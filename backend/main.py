import os
import uuid
import shutil
import subprocess
import numpy as np
import yt_dlp
import librosa
import soundfile as sf
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydub import AudioSegment
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

def get_fingering(pitch):
    offsets = [64, 59, 55, 50, 45, 40]
    candidates = []
    for s_idx, offset in enumerate(offsets):
        fret = pitch - offset
        if 0 <= fret <= 22:
            string_num = s_idx + 1
            score = 0
            if 7 <= fret <= 15: score += 20
            if string_num <= 3: score += 10
            candidates.append((score, string_num, fret))
    if not candidates: return 6, 0
    candidates.sort(key=lambda x: x[0], reverse=True)
    return int(candidates[0][1]), int(candidates[0][2])

def process_midi_to_json(midi_data):
    if not midi_data or not midi_data.instruments: return []
    notes = midi_data.instruments[0].notes
    notes.sort(key=lambda x: x.start)
    # Filter out very short "leakage" notes
    notes = [n for n in notes if (n.end - n.start) > 0.06]
    
    json_notes = []
    for n in notes:
        s, f = get_fingering(n.pitch)
        json_notes.append({
            "id": str(uuid.uuid4())[:8],
            "s": int(s), "f": int(f), 
            "t": float(n.start), "d": float(n.end - n.start), 
            "p": int(n.pitch)
        })
    return json_notes

def generate_spectrogram(audio_path):
    if not os.path.exists(audio_path): return []
    try:
        y, sr = librosa.load(audio_path)
        S = np.abs(librosa.stft(y))
        return librosa.power_to_db(S**2, ref=np.max)[:, ::10].astype(float).tolist()
    except: return []

def get_vision_data(audio_path):
    if not os.path.exists(audio_path): return []
    try:
        model_output, _, _ = predict(audio_path, ICASSP_2022_MODEL_PATH)
        return model_output['note'][::5].astype(float).tolist()
    except: return []

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir): raise HTTPException(status_code=404)
    cropped_path = os.path.join(session_dir, "cropped.wav")
    stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
    
    available_stems = {}
    vision_layers = {}
    for s in ["guitar", "piano", "other", "vocals", "bass"]:
        path = os.path.join(stem_base, f"{s}.wav")
        if os.path.exists(path):
            available_stems[s] = f"http://localhost:8000/output/{session_id}/htdemucs_6s/cropped/{s}.wav"
            vision_layers[s] = get_vision_data(path)
    
    y, sr = librosa.load(cropped_path)
    source = os.path.join(stem_base, "guitar.wav") if os.path.exists(os.path.join(stem_base, "guitar.wav")) else cropped_path
    _, midi_data, _ = predict(source, ICASSP_2022_MODEL_PATH)
    
    return {
        "session_id": session_id,
        "notes": process_midi_to_json(midi_data),
        "stems": available_stems,
        "vision_layers": vision_layers,
        "spectrogram": generate_spectrogram(cropped_path),
        "original": f"http://localhost:8000/output/{session_id}/cropped.wav",
        "midi": f"http://localhost:8000/output/{session_id}/solo.mid",
        "duration": float(len(y) / sr)
    }

@app.post("/process")
async def process_audio(file: UploadFile = File(None), youtube_url: str = Form(None), start_time: float = Form(...), end_time: float = Form(...)):
    session_id = str(uuid.uuid4())
    session_dir = os.path.abspath(os.path.join(UPLOAD_DIR, session_id))
    os.makedirs(session_dir, exist_ok=True)
    input_path = os.path.join(session_dir, "input.audio")
    if youtube_url:
        success = False
        for cookie_cmd in [["--cookies-from-browser", "chrome"], []]:
            try:
                cmd = ["yt-dlp", "-f", "18/best", "-x", "--audio-format", "wav", "--ffmpeg-location", "/usr/local/bin/ffmpeg", "--extractor-args", "youtube:player_client=android", "-o", input_path, "--no-playlist"] + cookie_cmd + [youtube_url]
                subprocess.run(cmd, check=True)
                if os.path.exists(input_path + ".wav"):
                    input_path += ".wav"; success = True; break
            except: continue
        if not success: raise HTTPException(status_code=500)
    elif file:
        with open(input_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    
    audio = AudioSegment.from_file(input_path)
    cropped_path = os.path.join(session_dir, "cropped.wav")
    audio[int(start_time*1000):int(end_time*1000)].export(cropped_path, format="wav")
    subprocess.run(["demucs", "-n", "htdemucs_6s", "-o", session_dir, cropped_path], check=True)
    
    stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
    available_stems = {}
    vision_layers = {}
    for s in ["guitar", "piano", "other", "vocals", "bass"]:
        path = os.path.join(stem_base, f"{s}.wav")
        if os.path.exists(path):
            available_stems[s] = f"http://localhost:8000/output/{session_id}/htdemucs_6s/cropped/{s}.wav"
            vision_layers[s] = get_vision_data(path)
            
    source = os.path.join(stem_base, "guitar.wav") if "guitar" in available_stems else cropped_path
    _, midi_data, _ = predict(source, ICASSP_2022_MODEL_PATH)
    midi_data.write(os.path.join(session_dir, "solo.mid"))
    
    return {
        "session_id": session_id,
        "notes": process_midi_to_json(midi_data),
        "stems": available_stems,
        "vision_layers": vision_layers,
        "spectrogram": generate_spectrogram(cropped_path),
        "original": f"http://localhost:8000/output/{session_id}/cropped.wav",
        "midi": f"http://localhost:8000/output/{session_id}/solo.mid",
        "duration": float(len(audio[int(start_time*1000):int(end_time*1000)]) / 1000)
    }

@app.post("/retranscribe")
async def retranscribe(session_id: str = Form(...), target: str = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    source_path = os.path.join(session_dir, "lasso_preview.wav") if target == "lasso_preview" else None
    if not source_path:
        for root, dirs, files in os.walk(session_dir):
            if f"{target}.wav" in files: source_path = os.path.join(root, f"{target}.wav"); break
    if not source_path: raise HTTPException(status_code=404)
    _, midi_data, _ = predict(source_path, ICASSP_2022_MODEL_PATH, onset_threshold=0.3, frame_threshold=0.15)
    return {"notes": process_midi_to_json(midi_data)}

@app.post("/preview_selection")
async def preview_selection(session_id: str = Form(...), start_time: float = Form(...), end_time: float = Form(...), min_midi: int = Form(...), max_midi: int = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    y, sr = librosa.load(os.path.join(session_dir, "cropped.wav"))
    S = librosa.stft(y)
    f_mask = (librosa.fft_frequencies(sr=sr) >= librosa.midi_to_hz(min_midi)) & (librosa.fft_frequencies(sr=sr) <= librosa.midi_to_hz(max_midi))
    t_mask = (librosa.frames_to_time(np.arange(S.shape[1]), sr=sr) >= start_time) & (librosa.frames_to_time(np.arange(S.shape[1]), sr=sr) <= end_time)
    S_masked = np.zeros_like(S)
    S_masked[np.ix_(f_mask, t_mask)] = S[np.ix_(f_mask, t_mask)]
    sf.write(os.path.join(session_dir, "lasso_preview.wav"), librosa.istft(S_masked), sr)
    return {"preview_url": f"http://localhost:8000/output/{session_id}/lasso_preview.wav?t={uuid.uuid4()}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
