# TabMaker Architecture

TabMaker pairs a lightweight local FastAPI + React workspace with a stateless, scale-to-zero NVIDIA L4 GPU inference worker on Google Cloud Run and Gemini 4 multimodal reasoning.

## Data Flow

1. **Targeted Slice Ingestion (`backend/ingest.py`)**
   - Uses `yt-dlp --download-sections` (with `ffmpeg` slice fallback) to extract only `[start_time, end_time]` at 44.1 kHz 16-bit WAV (`cropped.wav`) and aligned video (`solo.mp4`).
2. **Stateless Cloud GPU Analysis (`cloud_worker/pipeline.py`, `backend/cloud_client.py`)**
   - Runs `Beat This!` (`File2Beats`) on the full mix for beat/downbeat timestamps and BPM.
   - Runs `BS-Roformer-SW` via `audio-separator` on CUDA to isolate `guitar.wav` and synthesize `backing.wav`.
   - Runs `mt3-infer` + `torchcrepe` (`full`, 5ms hop, periodicity-gated) to extract 6-string guitar notes (`E2` MIDI 40 to `E6` MIDI 88), fusing stair-stepped bends and capping physical bends at `<= 4.0` semitones.
   - Stateless execution: temporary files are deleted in `finally:`, and the container scales to zero (`--min-instances=0`) when idle.
3. **Video Gatekeeper & 6-String Key-Aware Solver (`backend/copilot/video_gatekeeper.py`, `backend/transcription/fingering_optimizer.py`)**
   - Samples frames from `solo.mp4` (`t=0..duration`) and uses `gemini-4-argon` to detect fretboard visibility and extract time-windowed `neck_priors`.
   - Solves globally optimal 6-string `(string, fret)` assignments via dynamic programming conditioned on detected key/mode, `target_fret`, bend physics, and `neck_priors`.
4. **Multimodal Audio + Tab Polish (`backend/copilot/tab_polish.py`)**
   - Sends 16 kHz mono isolated guitar audio, optional video frames, and candidate note cues to `gemini-4-carbon`, locking acoustic timestamps and validating `p == TUNING_OFFSETS[s-1] + f`.
5. **Beat-Aligned Engraving & Playback (`frontend/src/utils/alphaTexConverter.ts`, `AlphaTabViewer.tsx`, `CleanTabScore.tsx`)**
   - Converts notes + `downbeats` into measure-accurate AlphaTex (choosing 16th vs. triplet grids per bar with explicit rests and bend/slide/vibrato markers).
   - Synchronizes AlphaTab and the interactive 6-string SVG editor playhead at 60 FPS with Lead Guitar, Backing Track, Full Mix, or MIDI Synth playback.
