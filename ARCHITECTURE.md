# TabMaker Architecture

TabMaker is an AI-powered web application designed to isolate guitar solos from audio sources and transcribe them into interactive guitar tablature.

## Tech Stack

### Backend (Python / FastAPI)
- **Framework**: FastAPI for a high-performance asynchronous API.
- **Audio Processing**: 
  - `librosa`: For spectral analysis, STFT/iSTFT masking, and spectrogram generation.
  - `pydub`: For audio slicing and format conversion.
- **AI Models**:
  - `Demucs (htdemucs_6s)`: Hybrid Transformer model for high-fidelity stem separation (Guitar, Piano, Bass, Drums, Vocals, Other).
  - `Basic Pitch`: Spotify's neural network for high-resolution audio-to-MIDI transcription.
- **Persistence**: File-based session management in `temp_uploads/` with session ID tracking.

### Frontend (React / TypeScript)
- **Bundler**: Vite for fast development and optimized builds.
- **Audio Visualization**: Custom HTML5 Canvas implementation for the **Interactive Spectral Lasso** (spectrogram with AI overlays).
- **Tablature Rendering**: Custom **SVG-based Renderer** (bypassing external libraries for 100% reliability).
  - Features: Multi-measure layout, 12/8 time support, rhythmic stems/flags, and a moving playhead.
- **Audio Engine**: Web Audio API for a plucky "Twangy" guitar synthesizer to audit transcriptions.
- **Export**: `jsPDF` for multi-page, professionally formatted PDF tablature.

## Handling Large Files (Machine Learning Models)

To keep the repository lightweight and follow best practices, we do **not** commit the following to Git:
1. **Virtual Environments (`venv/`)**: These contain the multi-gigabyte TensorFlow/Torch installations.
2. **Model Weights**: Files like `.pth` or `.h5` are automatically downloaded by the libraries (`demucs`, `basic-pitch`) on the first run and stored in the user's local cache (e.g., `~/.cache`).
3. **User Data**: The `temp_uploads/` folder is ignored to protect privacy and storage.

Users can set up the project by running:
```bash
# Backend
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

## System Workflow
1. **Ingest**: YouTube URL (via `yt-dlp` with browser cookies) or local file.
2. **Isolate**: `htdemucs_6s` separates the solo from the backing track.
3. **Verify**: User uses the **Spectral Lasso** to visually confirm the solo and listen to "ghost" audio.
4. **Optimize**: Interactive UI allows the user to shift the "box" (neck position) or manually reassign notes to different strings.
5. **Export**: Save the final result as a PDF or raw MIDI.
