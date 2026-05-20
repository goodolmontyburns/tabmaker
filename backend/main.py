import os
import sys
import uuid
import shutil
import json
import subprocess
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
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["*"])

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"GLOBAL ERROR: {exc}")
    return JSONResponse(status_code=500, content={"message": str(exc)})

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=UPLOAD_DIR), name="output")

def get_fingering(pitch, target_fret=5, prefer_open=True):
    """Simple fingering picker with target fret bias, prioritizing open strings and bass strings for low pitches"""
    offsets = [64, 59, 55, 50, 45, 40]
    candidates = []
    for s_idx, offset in enumerate(offsets):
        fret = pitch - offset
        if 0 <= fret <= 22:
            score = 0
            if prefer_open and fret == 0:
                score += 100  # Open String Priority
            if prefer_open and pitch <= 50 and s_idx in [4, 5]:
                score += 50   # Bass strings (A and Low E) preference for low pitches
            score -= abs(fret - target_fret)
            candidates.append((score, s_idx + 1, fret))
    if not candidates: return 6, 0
    candidates.sort(key=lambda x: x[0], reverse=True)
    return int(candidates[0][1]), int(candidates[0][2])

def save_notes_to_midi(notes, midi_path):
    try:
        import pretty_midi
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=24) # Acoustic Guitar (nylon)
        for n in notes:
            pitch = int(n.get("p", 60))
            start = float(n.get("t", 0))
            end = start + float(n.get("d", 0.1))
            note = pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end)
            instrument.notes.append(note)
        midi.instruments.append(instrument)
        midi.write(midi_path)
    except Exception as e:
        print(f"Error saving MIDI file: {e}")

def process_midi_to_json(midi_data):
    if not midi_data or not midi_data.instruments: return []
    raw_notes = midi_data.instruments[0].notes
    raw_notes.sort(key=lambda x: x.start)
    
    # --- OCTAVE OVERTONE CORRECTION PASS ---
    # Detect and correct isolated high notes that are physically impossible to play
    # (> 5 frets away from the local average of surrounding notes within 2.0s).
    for n in raw_notes:
        neighbors = [other for other in raw_notes if other is not n and abs(other.start - n.start) <= 2.0]
        if neighbors:
            neighbor_frets = []
            for neighbor in neighbors:
                _, nf = get_fingering(neighbor.pitch, target_fret=5)
                neighbor_frets.append(nf)
            avg_fret = sum(neighbor_frets) / len(neighbor_frets)
        else:
            avg_fret = 5.0
            
        p = int(n.pitch)
        _, f = get_fingering(p, target_fret=5)
        
        while p - 12 >= 40:
            p_dropped = p - 12
            _, f_dropped = get_fingering(p_dropped, target_fret=5)
            # If the note fret is more than 5 frets away from the local average,
            # and dropping it brings it closer to the average:
            if abs(f - avg_fret) > 5 and abs(f_dropped - avg_fret) < abs(f - avg_fret):
                p = p_dropped
                f = f_dropped
            else:
                break
        n.pitch = p
    
    # --- PRONG C: STRUM GROUPING ---
    chord_groups = []
    if raw_notes:
        current_group = [raw_notes[0]]
        for i in range(1, len(raw_notes)):
            # If notes are within 100ms, they are part of a strummed chord
            if raw_notes[i].start - current_group[-1].start < 0.100:
                current_group.append(raw_notes[i])
            else:
                chord_groups.append(current_group)
                current_group = [raw_notes[i]]
        chord_groups.append(current_group)

    json_notes = []
    
    for group in chord_groups:
        # --- PRONG A: HAND-SPAN HARD CONSTRAINT ---
        # 1. Determine a "base" pitch from the majority of the chord
        # Usually the lowest notes are the "anchor" in blues
        sorted_by_pitch = sorted(group, key=lambda x: x.pitch)
        anchor_pitch = sorted_by_pitch[0].pitch
        
        corrected_pitches = []
        for n in group:
            p = int(n.pitch)
            # Find the fingering for this note relative to a neutral 5th fret area
            _, f_at_5 = get_fingering(p, target_fret=5)
            _, anchor_f_at_5 = get_fingering(int(anchor_pitch), target_fret=5)
            
            # RECURSIVE Reach Guard: 
            # If this note is > 6 frets away from the anchor, drop it an octave
            while abs(f_at_5 - anchor_f_at_5) > 6 and p - 12 >= 40:
                p -= 12
                _, f_at_5 = get_fingering(p, target_fret=5)
            
            corrected_pitches.append(p)

        # 2. Final Fingering Assignment
        used_strings = set()
        # Sort notes in chord by pitch (high to low) to assign strings 1 -> 6
        chord_items = []
        for i, n in enumerate(group):
            chord_items.append({'p': corrected_pitches[i], 't': n.start, 'd': n.end - n.start})
        
        for item in sorted(chord_items, key=lambda x: x['p'], reverse=True):
            s, f = get_fingering(item['p'], target_fret=5)
            
            # Prevent string overlap in chord
            if s in used_strings:
                for alt_s in range(1, 7):
                    if alt_s not in used_strings:
                        off = [64, 59, 55, 50, 45, 40][alt_s-1]
                        alt_f = item['p'] - off
                        if 0 <= alt_f <= 22:
                            s, f = alt_s, alt_f
                            break
            
            used_strings.add(s)
            json_notes.append({
                "id": str(uuid.uuid4())[:8],
                "s": int(s), "f": int(f), 
                "t": float(item['t']), "d": float(item['d']), "p": int(item['p'])
            })

    return json_notes

def correct_overtones_in_json_notes(notes):
    notes.sort(key=lambda x: x["t"])
    for n in notes:
        neighbors = [other for other in notes if other is not n and abs(other["t"] - n["t"]) <= 2.0]
        if neighbors:
            neighbor_frets = [neighbor["f"] for neighbor in neighbors]
            avg_fret = sum(neighbor_frets) / len(neighbor_frets)
        else:
            avg_fret = 5.0
            
        p = int(n["p"])
        _, f = get_fingering(p, target_fret=5)
        
        while p - 12 >= 40:
            p_dropped = p - 12
            _, f_dropped = get_fingering(p_dropped, target_fret=5)
            if abs(f - avg_fret) > 5 and abs(f_dropped - avg_fret) < abs(f - avg_fret):
                p = p_dropped
                f = f_dropped
            else:
                break
        
        if p != n["p"]:
            n["p"] = p
            n["s"], n["f"] = get_fingering(p, target_fret=5)
            
    return notes

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir): raise HTTPException(status_code=404)
    
    # Check cache
    cache_path = os.path.join(session_dir, "session.json")
    if os.path.exists(cache_path):
        data = None
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Error loading session cache JSON: {e}")
            
        if data:
            try:
                # Apply overtone correction pass on the fly to cached sessions
                if "notes" in data:
                    data["notes"] = correct_overtones_in_json_notes(data["notes"])
                
                # Check if vision layers are empty and need regeneration
                vision_layers = data.get("vision_layers", {})
                stems = data.get("stems", {})
                needs_regeneration = False
                
                if stems:
                    for stem_name in stems.keys():
                        if not vision_layers.get(stem_name) or len(vision_layers[stem_name]) == 0:
                            needs_regeneration = True
                            break
                
                if needs_regeneration:
                    print(f"Vision layers for session {session_id} are empty. Regenerating on the fly...")
                    stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
                    for s in stems.keys():
                        stem_wav_path = os.path.join(stem_base, f"{s}.wav")
                        if os.path.exists(stem_wav_path):
                            vision_layers[s] = get_vision_data(stem_wav_path)
                    data["vision_layers"] = vision_layers
                
                with open(cache_path, "w") as f:
                    json.dump(data, f)
            except Exception as e:
                print(f"Error updating/writing session cache: {e}")
            return data

    cropped_path = os.path.join(session_dir, "cropped.wav")
    stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
    available_stems = {}
    vision_layers = {}
    for s in ["guitar", "piano", "other", "vocals", "bass"]:
        path = os.path.join(stem_base, f"{s}.wav")
        if os.path.exists(path):
            available_stems[s] = f"http://localhost:8000/output/{session_id}/htdemucs_6s/cropped/{s}.wav"
            vision_layers[s] = get_vision_data(path)
    source = os.path.join(stem_base, "guitar.wav") if os.path.exists(os.path.join(stem_base, "guitar.wav")) else cropped_path
    _, midi_data, _ = predict(source, ICASSP_2022_MODEL_PATH)
    midi_data.write(os.path.join(session_dir, "solo.mid"))
    
    response_data = {
        "session_id": session_id,
        "notes": process_midi_to_json(midi_data),
        "stems": available_stems,
        "vision_layers": vision_layers,
        "spectrogram": generate_spectrogram(cropped_path),
        "original": f"http://localhost:8000/output/{session_id}/cropped.wav",
        "midi": f"http://localhost:8000/output/{session_id}/solo.mid",
        "duration": float(librosa.get_duration(path=cropped_path))
    }
    
    # Save cache
    try:
        with open(cache_path, "w") as f:
            json.dump(response_data, f)
    except Exception as e:
        print(f"Error writing session cache: {e}")
        
    return response_data

@app.post("/process")
async def process_audio(file: UploadFile = File(None), youtube_url: str = Form(None), start_time: float = Form(...), end_time: float = Form(...)):
    session_id = str(uuid.uuid4())
    session_dir = os.path.abspath(os.path.join(UPLOAD_DIR, session_id))
    os.makedirs(session_dir, exist_ok=True)
    input_path = os.path.join(session_dir, "input.audio")
    if youtube_url:
        success = False
        ytdlp_bin = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
        if not os.path.exists(ytdlp_bin):
            ytdlp_bin = "yt-dlp"
            
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        
        for cookie_cmd in [["--cookies-from-browser", "chrome"], []]:
            try:
                cmd = [ytdlp_bin, "-f", "18/best", "-x", "--audio-format", "wav", "--ffmpeg-location", ffmpeg_bin, "--extractor-args", "youtube:player_client=android", "-o", input_path, "--no-playlist"] + cookie_cmd + [youtube_url]
                print(f"Running download command: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)
                if os.path.exists(input_path + ".wav"):
                    input_path += ".wav"
                    success = True
                    break
            except Exception as e:
                print(f"yt-dlp download attempt failed with cookie_cmd {cookie_cmd}: {e}")
                continue
        if not success:
            raise HTTPException(status_code=500, detail="Failed to download audio from YouTube using yt-dlp.")
    elif file:
        with open(input_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    audio = AudioSegment.from_file(input_path)
    cropped_path = os.path.join(session_dir, "cropped.wav")
    audio[int(start_time*1000):int(end_time*1000)].export(cropped_path, format="wav")
    demucs_bin = os.path.join(os.path.dirname(sys.executable), "demucs")
    if not os.path.exists(demucs_bin):
        demucs_bin = "demucs"
    subprocess.run([demucs_bin, "-n", "htdemucs_6s", "-o", session_dir, cropped_path], check=True)
    stem_base = os.path.join(session_dir, "htdemucs_6s", "cropped")
    available_stems = {}
    vision_layers = {}
    for s in ["guitar", "piano", "other", "vocals", "bass"]:
        path = os.path.join(stem_base, f"{s}.wav")
        if os.path.exists(path):
            available_stems[s] = f"http://localhost:8000/output/{session_id}/htdemucs_6s/cropped/{s}.wav"
            vision_layers[s] = get_vision_data(path)
    source = os.path.join(stem_base, "guitar.wav") if "guitar" in available_stems else os.path.join(stem_base, "other.wav")
    if not os.path.exists(source): source = cropped_path
    _, midi_data, _ = predict(source, ICASSP_2022_MODEL_PATH)
    midi_data.write(os.path.join(session_dir, "solo.mid"))
    
    response_data = {
        "session_id": session_id,
        "notes": process_midi_to_json(midi_data),
        "stems": available_stems,
        "vision_layers": vision_layers,
        "spectrogram": generate_spectrogram(cropped_path),
        "original": f"http://localhost:8000/output/{session_id}/cropped.wav",
        "midi": f"http://localhost:8000/output/{session_id}/solo.mid",
        "duration": float(librosa.get_duration(path=cropped_path))
    }
    
    # Save cache
    cache_path = os.path.join(session_dir, "session.json")
    try:
        with open(cache_path, "w") as f:
            json.dump(response_data, f)
    except Exception as e:
        print(f"Error writing session cache: {e}")
        
    return response_data

@app.post("/retranscribe")
async def retranscribe(session_id: str = Form(...), target: str = Form(...)):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    source_path = os.path.join(session_dir, "lasso_preview.wav") if target == "lasso_preview" else None
    if not source_path:
        for root, dirs, files in os.walk(session_dir):
            if f"{target}.wav" in files: source_path = os.path.join(root, f"{target}.wav"); break
    if not source_path: raise HTTPException(status_code=404)
    _, midi_data, _ = predict(source_path, ICASSP_2022_MODEL_PATH, onset_threshold=0.3, frame_threshold=0.15)
    
    new_notes = process_midi_to_json(midi_data)
    
    # Update cache if it exists
    cache_path = os.path.join(session_dir, "session.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            data["notes"] = new_notes
            with open(cache_path, "w") as f:
                json.dump(data, f)
            # Rewrite MIDI file
            save_notes_to_midi(new_notes, os.path.join(session_dir, "solo.mid"))
        except Exception as e:
            print(f"Error updating cache on retranscribe: {e}")
            
    return {"notes": new_notes}

@app.post("/session/{session_id}/notes")
async def save_session_notes(session_id: str, payload: dict):
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    if not os.path.exists(session_dir): raise HTTPException(status_code=404)
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
    
    # Save notes to MIDI file so it is updated
    save_notes_to_midi(notes, os.path.join(session_dir, "solo.mid"))
    return {"status": "success"}

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

def generate_spectrogram(audio_path):
    if not os.path.exists(audio_path): return []
    try:
        y, sr = librosa.load(audio_path)
        S = np.abs(librosa.stft(y))
        db = librosa.power_to_db(S**2, ref=np.max)[:, ::10].astype(float)
        db = np.nan_to_num(db, nan=-80.0, posinf=0.0, neginf=-80.0)
        return db.tolist()
    except Exception as e:
        print(f"Error generating spectrogram: {e}")
        return []

def get_vision_data(audio_path):
    if not os.path.exists(audio_path): return []
    try:
        model_output, _, _ = predict(audio_path, ICASSP_2022_MODEL_PATH)
        return model_output['note'].astype(float)[::5].tolist()
    except: return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
