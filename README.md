# TabMaker: AI-Powered Guitar Transcription

TabMaker is an advanced web application designed specifically for transcribing complex guitar solos (like classic blues) that traditional AI often struggles with. By combining state-of-the-art stem isolation with an interactive spectral editing interface, TabMaker gives the user the power to "point" the AI toward the correct notes.

## 🚀 Key Features

- **High-Fidelity Isolation**: Uses Meta's `htdemucs_6s` (Hybrid Transformer) model to separate Guitar, Piano, Bass, Drums, and Vocals.
- **Interactive Spectral Lasso**: A custom-built frequency map (Spectrogram) where you can visually identify solo "blobs" and draw boxes to isolate them.
- **Ghost Audio Preview**: Lasso an area on the map and listen to *only* those frequencies to verify it's the guitar before transcribing.
- **Lead Guitar Optimizer**: An intelligent fingering algorithm that prefers the "blues box" (high strings, frets 5-15) and avoids awkward open-string jumps.
- **Custom SVG Tab Renderer**: A robust, zero-dependency renderer that supports 12/8 time, rhythmic stems, and interactive click-to-reassign fingering.
- **Blues Audit Synth**: A warm, twangy guitar synthesizer that plays your transcribed tab so you can audit the melody against the original.
- **Session Persistence**: Automatically resumes your last session so you never have to re-download from YouTube.

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
# Note: First run will take time as it downloads AI models (Demucs/Basic Pitch)
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

1. **Ingest**: Paste a YouTube URL or upload an audio file.
2. **Trim**: Select the specific segment of the song containing the solo.
3. **Isolate & Verify**: 
   - Use the **Stem Mixer** to listen to the isolated tracks.
   - Use the **Spectral Lasso** to draw a box around high-pitched guitar frequencies.
   - Click **"Listen to Selection"** to hear the isolated "ghost" audio.
4. **Refine**: Click **"Assign Selection as Solo"** to generate the initial tab.
5. **Optimize**:
   - Use the **Neck Position Slider** to shift the solo into your preferred "box" (e.g., Fret 12).
   - **Click individual notes** to cycle them through all possible guitar string positions.
6. **Save**: Export your final transcription as a **PDF** or **MIDI** file.

## 🏗 Architecture
See `ARCHITECTURE.md` for a deep dive into the technical stack and machine learning pipeline.
