# TabMaker Architecture

TabMaker is an AI-powered web application that handles the entire lifecycle of guitar solo transcription, from spectral isolation to professional tablature rendering.

## Tech Stack

### Backend (Python / FastAPI)
- **Framework**: FastAPI for high-performance, asynchronous endpoints.
- **Audio Intelligence**:
  - `Demucs (htdemucs_6s)`: Hybrid Transformer model for 6-stem high-fidelity isolation.
  - `Basic Pitch`: Spotify's multi-pitch estimation model for audio-to-MIDI conversion.
- **Logic Filters ("The Guitarist's Brain")**:
  - **Harmonic Tilt**: FFmpeg shelf EQ filter (`lowshelf=f=500:g=3, highshelf=f=2000:g=-10`) applied before transcription to suppress overtone "ghosts."
  - **Temporal Stitching**: Bridging algorithm that merges notes of identical pitch occurring within 100ms gaps.
  - **Strum Grouping**: Logic that consolidates note onsets within 80ms into a single physical chord event.
  - **Recursive Reach Guard**: Pitch-normalizer that drops outlier notes by 12-semitone increments until they fit within a 6-fret "human hand" span.
- **Spectral Masking**: iSTFT-based reconstruction that zeros out all frequency bins outside the user's Lasso coordinates for "Ghost Audio" previews.

### Frontend (React / TypeScript)
- **Interactive Spectrogram**: Custom HTML5 Canvas implementation supporting 2D Lasso selection, multi-track overlays, and real-time playhead sync.
- **Pro SVG Tab Renderer**: Built from scratch to bypass 3rd-party library bugs.
  - **Octave Snapping Engine**: Real-time logic that recalculates both string AND octave as the neck position slider moves.
  - **Area Selection Logic**: Time-range based masking that allows localized neck optimization.
  - **Meter Engine**: Draws beat-correlated markers and sustain-ties based on BPM-to-seconds mapping.
- **Synth Engine**: Web Audio API implementation using a Sawtooth/Square waveform mix and resonant low-pass filter for a "plucky" guitar timbre.

## Data Persistence & Export
- **Session Tracking**: Session IDs stored in `localStorage` map to directories in `temp_uploads/`.
- **WAV Export**: Direct serving of isolated AI stems.
- **PDF Export**: `jsPDF` multi-line drawing logic that maps SVG coordinates to printable PT units.

## System Workflow
1. **Deep Ingest**: High-bitrate stream extraction via `yt-dlp` forced to 44.1kHz.
2. **Spectral Selection**: User-guided isolation via the Lasso tool.
3. **Optimized Transcription**: Backend logic filters ensure a playable initial result.
4. **Interactive Refinement**: User fine-tunes fingering via the Neck Slider and individual note cycling.
5. **Final Output**: PDF or MIDI generation.
