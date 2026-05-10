import os
import uuid
import shutil
import subprocess
import yt_dlp
from pydub import AudioSegment
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH
from main import midi_to_alphatex

UPLOAD_DIR = "temp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def run_test(youtube_url, start_time, end_time):
    session_id = str(uuid.uuid4())
    session_dir = os.path.abspath(os.path.join(UPLOAD_DIR, session_id))
    os.makedirs(session_dir, exist_ok=True)
    print(f"Session directory: {session_dir}")

    input_path = os.path.join(session_dir, "input.audio")

    try:
        # 1. Fetch Audio
        print(f"Downloading {youtube_url}...")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': input_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            }],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([youtube_url])
            input_path += ".wav"
            print(f"Downloaded to {input_path}")
        except Exception as e:
            print(f"YouTube download failed: {e}")
            print("Using fallback local test audio file.")
            fallback_path = "/Users/gbaird/Projects/tabmaker/backend/venv/lib/python3.9/site-packages/music21/audioSearch/test_audio.wav"
            if os.path.exists(fallback_path):
                shutil.copy(fallback_path, input_path)
                # Ensure input_path reflects the copied file
                # If fallback was wav, it's already wav.
                print(f"Copied fallback to {input_path}")
            else:
                print("Fallback file not found.")
                return

        # 2. Crop
        print(f"Cropping from {start_time} to {end_time}...")
        audio = AudioSegment.from_file(input_path)
        # Check duration for fallback file
        duration = len(audio) / 1000.0
        if start_time > duration:
            print(f"Start time {start_time} is beyond duration {duration}. Adjusting to 0.")
            start_time = 0.0
        if end_time > duration:
            print(f"End time {end_time} is beyond duration {duration}. Adjusting to end.")
            end_time = duration
        
        cropped_path = os.path.join(session_dir, "cropped.wav")
        cropped_audio = audio[int(start_time*1000):int(end_time*1000)]
        cropped_audio.export(cropped_path, format="wav")
        print(f"Cropped to {cropped_path}")

        # 3. Isolate Guitar with Demucs
        print("Running Demucs (htdemucs_6s)...")
        subprocess.run([
            "demucs", 
            "-n", "htdemucs_6s",
            "--two-stems", "guitar",
            "-o", session_dir,
            cropped_path
        ], check=True)
        
        guitar_path = os.path.join(session_dir, "htdemucs_6s", "cropped", "guitar.wav")
        
        if not os.path.exists(guitar_path):
             print("Guitar stem not found, falling back to cropped audio.")
             guitar_path = cropped_path
        else:
            print(f"Guitar stem isolated at {guitar_path}")
        
        # 4. Transcribe to MIDI with Basic Pitch
        print("Running Basic Pitch...")
        model_output, midi_data, note_events = predict(
            guitar_path,
            ICASSP_2022_MODEL_PATH
        )
        print("Transcription complete.")
        
        # 5. Convert MIDI to alphaTex
        alphatex = midi_to_alphatex(midi_data)
        print("\n--- AlphaTex Result ---")
        print(alphatex)
        print("-----------------------")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    youtube_url = "https://www.youtube.com/watch?v=RYKYMUFestk"
    start_time = 45.0
    end_time = 60.0
    run_test(youtube_url, start_time, end_time)
