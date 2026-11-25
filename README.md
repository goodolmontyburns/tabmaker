# TabMaker: Cloud-Accelerated Guitar Solo Transcription

TabMaker converts guitar solos from YouTube URLs or uploaded audio files into playable 6-string guitar tablature with synchronized audio playback, interactive fingering editing, and AlphaTex/PDF/MIDI export.

## Architecture Overview

TabMaker splits work cleanly between a lightweight local gateway on your computer and serverless AI on Google Cloud:

1. **Local Gateway (FastAPI + React/AlphaTab)**
   - Downloads only the requested solo time slice (`yt-dlp --download-sections` + `ffmpeg` at 44.1 kHz stereo WAV and cropped `solo.mp4`).
   - Serves the web UI, manages local session files (`temp_uploads/`), and runs the 6-string key-aware Viterbi fingering optimizer.
2. **Cloud Run NVIDIA L4 GPU Worker (`cloud_worker/`)** — *Scales to zero when idle*
   - **`Beat This!`**: Tracks real beat timestamps, downbeats (measure boundaries), and tempo directly from the full mix.
   - **`BS-Roformer-SW` (via `audio-separator`)**: 6-stem separation extracting an isolated `guitar.wav` stem and a `backing.wav` accompaniment track.
   - **`MT3` + `TorchCREPE (full)`**: Multi-pitch guitar note transcription fused with 5ms continuous $F_0$ pitch contours to capture quarter/half/full/1.5-step bends, pre-bend releases, slides, and vibrato.
3. **Multimodal Copilot (`Gemini 4 Argon` & `Gemini 4 Carbon`)**
   - **`gemini-4-argon`**: Inspects frames from the cropped solo video to detect whether the guitarist's fretting hand is visible and extract time-windowed fret-box priors.
   - **`gemini-4-carbon`**: Listens to the isolated guitar audio alongside candidate detections and video priors to refine key/scale, prune residual bleed, and optimize 6-string fingerings.

## Local Setup

### Prerequisites
- Python 3.9+ (3.11+ recommended)
- Node.js 18+
- FFmpeg (`brew install ffmpeg`)
- Google Cloud CLI (`gcloud`) or `GEMINI_API_KEY`

### 1. Environment Configuration
Create a `.env` file in the project root:
```bash
GCP_PROJECT_ID=tabmaker-studio-2026
CLOUD_WORKER_URL=https://<your-cloud-run-worker-url>
# Optional: uses prepaid Gemini API credits first, falling back to Vertex AI ADC
GEMINI_API_KEY=
```

### 2. Backend (Port 8000)
```bash
source backend/venv/bin/activate
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend (Port 5173 in dev, or served statically from `:8000`)
```bash
cd frontend
npm install
npm run dev
```

## Testing & Benchmarks
```bash
PYTHONPATH=. backend/venv/bin/pytest backend/tests -v
```
