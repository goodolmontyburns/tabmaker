import os
import sys
import json
import time
from backend.transcription.pitch_tracker import extract_notes_and_bends
from backend.copilot.tab_polish import polish_tab
from backend.copilot.gemini_client import GeminiClient
from backend.benchmark.ground_truth_eval import evaluate_transcription

def run_clapton_eval():
    print("=== ERIC CLAPTON 'I\'M TORE DOWN' BENCHMARK ===")
    print("Source: https://www.youtube.com/watch?v=vRcUufCKwOo")
    print("Solo Interval: 01:19 - 02:03 (79.0s - 123.0s, Measures 46-69)")
    
    cropped_audio = "temp_uploads/benchmark/cropped.wav"

    if not cropped_audio or not os.path.exists(cropped_audio):
        print("Downloading and cropping audio...")
        import subprocess
        import shutil
        ytdlp_bin = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
        if not os.path.exists(ytdlp_bin):
            ytdlp_bin = shutil.which("yt-dlp") or "yt-dlp"
        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
        os.makedirs("temp_uploads/benchmark", exist_ok=True)
        raw_audio = "temp_uploads/benchmark/raw.audio"
        cmd = [
            ytdlp_bin, "-f", "18/bestaudio/best",
            "-x", "--audio-format", "wav",
            "--ffmpeg-location", ffmpeg_bin,
            "--extractor-args", "youtube:player_client=android",
            "-o", raw_audio,
            "--no-playlist",
            "https://www.youtube.com/watch?v=vRcUufCKwOo"
        ]
        subprocess.run(cmd, check=True)
        raw_wav = raw_audio + ".wav"
        from pydub import AudioSegment
        seg = AudioSegment.from_file(raw_wav)
        cropped_audio = "temp_uploads/benchmark/cropped.wav"
        seg[int(79.0 * 1000):int(123.0 * 1000)].export(cropped_audio, format="wav")

    print(f"Running v2 Continuous Pitch & Bend Tracker on {cropped_audio}...")
    t0 = time.time()
    notes = extract_notes_and_bends(cropped_audio, target_fret=8, prefer_open=False)
    t_extract = time.time() - t0
    print(f"Extracted {len(notes)} raw notes with bends in {t_extract:.2f}s.")

    raw_notes_dict = [n.to_dict() for n in notes]

    # Evaluate raw extraction
    raw_eval = evaluate_transcription(raw_notes_dict)
    print("\n--- RAW EXTRACTION SCORE VS GROUND TRUTH ---")
    print(json.dumps(raw_eval, indent=2))

    # Run AI Polish
    print("\nRunning Gemini 3.7 Flash AI Polish (Theory & Blues Box Optimization)...")
    gemini_client = GeminiClient()
    polish_res = polish_tab(
        notes=raw_notes_dict,
        video_path=None,
        duration=44.0,
        key_hint="C Blues",
        gemini_client=gemini_client
    )
    polished_notes = polish_res.get("notes", raw_notes_dict)

    # Evaluate polished tab
    polished_eval = evaluate_transcription(polished_notes)
    print("\n--- POLISHED TAB SCORE VS GROUND TRUTH ---")
    print(json.dumps(polished_eval, indent=2))

    # Save benchmark report to disk
    report = {
        "timestamp": time.time(),
        "video_url": "https://www.youtube.com/watch?v=vRcUufCKwOo",
        "solo_interval": "79s - 123s (measures 46-69)",
        "raw_metrics": raw_eval,
        "polished_metrics": polished_eval,
        "mode_detected": polish_res.get("mode"),
        "ai_applied": polish_res.get("ai_applied", False)
    }
    with open("temp_uploads/clapton_benchmark_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("\nSaved benchmark report to temp_uploads/clapton_benchmark_report.json")

if __name__ == "__main__":
    run_clapton_eval()
