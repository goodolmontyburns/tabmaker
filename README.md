# TabMaker: AI-Powered Guitar Transcription

TabMaker is an advanced web application designed specifically for transcribing complex guitar solos (like classic blues) that traditional AI often struggles with. By combining state-of-the-art stem isolation with interactive spectral editing and a "Guitarist's Brain" logic filter, TabMaker produces playable, professionally formatted tablature.

## 🚀 Key Features

- **High-Fidelity "Deep" Ingestion**: Bypasses low-quality video audio to fetch 256kbps high-bitrate streams at 44.1kHz.
- **Harmonic Tilt Filtering**: Uses FFmpeg to dampen overtones and boost fundamentals, forcing the AI to hear the correct octave.
- **Interactive Spectral Lasso**: A 2D frequency map where you can visually identify solo "blobs" and draw boxes to isolate specific time/pitch segments.
- **Guitarist's Brain Logic**:
  - **Strum Grouping**: Automatically merges rapid-fire notes into cohesive chords.
  - **Note Stitching**: Heals fragmented notes caused by heavy vibrato or recording noise.
  - **Recursive Octave Guard**: Strictly forbids impossible frets (like 22 vs 2) by snapping outliers to the correct octave box.
- **Pro SVG Tab Renderer**: 
  - **Area Selection**: Click and drag to highlight phrases and shift them independently across the neck.
  - **Octave Snapping Slider**: Move the neck position slider to instantly snap notes into the most playable "box."
  - **Meter Visualization**: Real-time beat markers (metronome dots) and tie lines for sustained notes.
- **Twangy Audit Synth**: A resonant sawtooth-based synthesizer to audit your tab's melody and rhythm.
- **Professional Export**: Multi-page PDF export formatted for real-world use.

## 🛠 Installation & Setup

### Prerequisites
- Python 3.9+
- Node.js 18+
- FFmpeg (Installed via `brew install ffmpeg`)

### 1. Backend Setup (Python)
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# First run will download AI models (Demucs/Basic Pitch)
python main.py
```

### 2. Frontend Setup (React)
```bash
cd frontend
npm install
npm run dev
```
Access the app at: `http://localhost:5173`

## 🎸 How to Use

1. **Ingest**: Paste a YouTube URL or upload a file. Use the manual Time Inputs to select your solo.
2. **Spectral Lasso**: Visually identify the solo blobs. Drag your mouse to create a 2D box.
3. **Verify**: Click **"Listen to Selection"** to hear the isolated "ghost" audio.
4. **Transcribe**: Click **"Assign Selection as Solo"** to generate the initial tab.
5. **Optimize**:
   - **Area Select**: Drag across the tab to highlight a phrase.
   - **Position Shift**: Move the slider to snap that phrase to a specific fret box (e.g. Fret 10).
   - **Manual Tweak**: Click any note to cycle it through different strings.
6. **Save**: Export your final work as a **PDF** or **MIDI**.

## 🏗 Architecture
See `ARCHITECTURE.md` for a deep dive into the STFT/iSTFT masking and logic filters.
