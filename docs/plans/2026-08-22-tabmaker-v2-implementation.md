# TabMaker v2 Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Build TabMaker v2 with state-of-the-art stem separation, continuous guitar pitch & bend tracking, a video vision gatekeeper with Gemini 3.7 Flash AI Polish (handling both static and live videos), a clean, minimalist SVG tablature UI, automated benchmarking against the Eric Clapton *"I'm Tore Down"* reference PDF, and Playwright browser E2E screenshot verification.

**Architecture:** A FastAPI backend integrates `yt-dlp`, SOTA audio processing (BS-Roformer / enhanced guitar isolation + CREPE/pYIN continuous pitch/bend tracking), and a dual-mode Gemini 3.7 Flash AI Polish engine (vision-guided if live guitar performance, theory-guided if static video). The frontend is a clean, understated React + TypeScript web app featuring a custom high-readability SVG score renderer with interactive fret editing, Web Audio playback, and vector PDF export.

**Tech Stack:** Python 3.9+, FastAPI, PyTorch, Librosa, CREPE / pYIN, Google GenAI SDK (Gemini 3.7 Flash), React 18, TypeScript, Vite, jsPDF, Playwright, pytest.

---

### Task 1: Environment & Dependency Setup

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `frontend/package.json`

**Step 1: Update backend dependencies**
Add `google-genai`, `certifi`, `pypdf`, `scipy`, and necessary audio tools to `backend/requirements.txt`.

**Step 2: Install dependencies in backend venv**
Run: `backend/venv/bin/pip install -r backend/requirements.txt`

**Step 3: Update frontend dependencies**
Ensure `lucide-react`, `jspdf`, and necessary minimal styling packages are present in `frontend/package.json`.

**Step 4: Commit**
```bash
git add backend/requirements.txt frontend/package.json
git commit -m "chore: configure v2 dependencies for Gemini and audio processing"
```

---

### Task 2: Continuous Pitch & Guitar Articulation Tracking Module

**Files:**
- Create: `backend/transcription/pitch_tracker.py`
- Create: `backend/tests/test_pitch_tracker.py`

**Step 1: Write failing unit test**
Create `backend/tests/test_pitch_tracker.py` testing:
- Note onset extraction with pitch frequency detection.
- Pitch bend curve calculation (identifying $\frac{1}{2}$-step and full-step bends).
- Quantization of onsets and durations into musical time fractions.

**Step 2: Run test to verify it fails**
Run: `backend/venv/bin/pytest backend/tests/test_pitch_tracker.py -v`

**Step 3: Implement `pitch_tracker.py`**
Implement pitch tracking using harmonic peak analysis, pYIN / CREPE pitch contours, and bend trajectory extraction:
```python
def extract_notes_and_bends(audio_path: str, sr: int = 22050):
    # Returns list of note dicts with pitch, start_time, duration, bend_type, bend_amount
    ...
```

**Step 4: Run test to verify it passes**
Run: `backend/venv/bin/pytest backend/tests/test_pitch_tracker.py -v`

**Step 5: Commit**
```bash
git add backend/transcription/ backend/tests/
git commit -m "feat: implement continuous pitch and guitar bend tracking"
```

---

### Task 3: Video Vision Gatekeeper & Gemini 3.7 Flash AI Polish Engine

**Files:**
- Create: `backend/copilot/gemini_client.py`
- Create: `backend/copilot/video_gatekeeper.py`
- Create: `backend/copilot/tab_polish.py`
- Create: `backend/tests/test_gemini_polish.py`

**Step 1: Write unit tests for Gatekeeper & Polish Engine**
Create tests checking:
- Static video detection (returns `is_live_guitar = False` for still images/album covers).
- Structured Tab JSON prompt generation and validation.
- Handling of API key discovery (`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `.env`).

**Step 2: Run test to verify failure**
Run: `backend/venv/bin/pytest backend/tests/test_gemini_polish.py -v`

**Step 3: Implement Video Gatekeeper & Gemini Polish**
- `gemini_client.py`: Implements robust Gemini 3.7 Flash caller with fallback to 2.5/2.0 Flash and local certifi SSL setup.
- `video_gatekeeper.py`: Samples video frames from MP4 and tests frame variance & visual fretboard presence.
- `tab_polish.py`: Builds prompt with key context, raw notes, bends, and video frames (if present) to generate ergonomically optimized guitar tablature JSON.

**Step 4: Run test to verify it passes**
Run: `backend/venv/bin/pytest backend/tests/test_gemini_polish.py -v`

**Step 5: Commit**
```bash
git add backend/copilot/ backend/tests/test_gemini_polish.py
git commit -m "feat: implement video vision gatekeeper and Gemini 3.7 Flash tab polish"
```

---

### Task 4: FastAPI Endpoints & Session Management

**Files:**
- Modify: `backend/main.py`
- Create: `backend/tests/test_api_endpoints.py`

**Step 1: Write API endpoint tests**
Test `/process`, `/polish`, `/session/{session_id}`, `/export/pdf` endpoints.

**Step 2: Implement FastAPI routes in `backend/main.py`**
- Connect `yt-dlp` audio/video downloader.
- Connect stem isolation + pitch/bend tracker.
- Connect Gemini AI Polish endpoint.
- Connect session saving and export endpoints.

**Step 3: Run API tests**
Run: `backend/venv/bin/pytest backend/tests/test_api_endpoints.py -v`

**Step 4: Commit**
```bash
git add backend/main.py backend/tests/test_api_endpoints.py
git commit -m "feat: wire v2 FastAPI endpoints for transcription and polish"
```

---

### Task 5: Clean Minimalist SVG Tablature UI

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`
- Create: `frontend/src/components/CleanTabScore.tsx`
- Create: `frontend/src/components/AudioPlayerBar.tsx`
- Create: `frontend/src/components/IngestPanel.tsx`

**Step 1: Implement `CleanTabScore.tsx`**
- Minimalist, high-readability 6-line guitar tablature renderer.
- Clean measure dividers, 4/4 beat dots, and measure numbers.
- Bend notation (`10b12` with smooth curve above the fret number).
- Slide notation (`8/10`, `10\8`).
- Direct DOM synchronized playhead line with zero React re-render lag.
- Interactive fret reassignment: clicking a fret pops up alternative valid strings in-place.

**Step 2: Implement `AudioPlayerBar.tsx` and `IngestPanel.tsx`**
- Clean controls for YouTube URL or file upload, start/end time inputs, Play/Pause, speed slider, and AI Polish button.

**Step 3: Update `App.tsx` and `App.css`**
- Replace legacy dark glassmorphism and cluttered UI with a simple, clean, responsive layout.

**Step 4: Verify frontend build**
Run: `cd frontend && npm run build`

**Step 5: Commit**
```bash
git add frontend/
git commit -m "feat: implement clean minimalist SVG tab UI and player"
```

---

### Task 6: Ground Truth Benchmark on Eric Clapton "I'm Tore Down" Solo

**Files:**
- Create: `backend/benchmark/ground_truth_eval.py`
- Create: `backend/benchmark/reference_clapton_tab.py`

**Step 1: Extract and encode the ground truth from PDF**
Parse measures 46–69 from `/Users/gbaird/Downloads/OFFICIAL IM TORE DOWN CHORDS & TABS by Eric Clapton @ Ultimate-Guitar.Com.pdf`.

**Step 2: Run benchmark evaluation against YouTube audio**
Download `https://www.youtube.com/watch?v=vRcUufCKwOo` (1:19–2:03), run transcription + Gemini AI Polish, and compare generated notes/frets against the ground truth.

**Step 3: Output precision, recall, and fret accuracy report**
Log accuracy metrics (pitch F1-score, fret-box match percentage).

**Step 4: Commit**
```bash
git add backend/benchmark/
git commit -m "feat: add ground truth evaluation and Clapton solo benchmark"
```

---

### Task 7: Playwright End-to-End Browser Verification with Screenshots

**Files:**
- Create: `e2e/test_tabmaker_e2e.py` or `e2e/test_tabmaker_e2e.ts`

**Step 1: Create Playwright test script**
- Launch backend and frontend servers.
- Automate browser navigation to `http://localhost:5173`.
- Ingest the Clapton YouTube solo or test audio.
- Trigger transcription and verify tab rendering.
- Trigger AI Polish and verify fret optimization and bend notation.
- Test interactive fret clicking and string re-assignment.
- Capture screenshots of every workflow step to `docs/screenshots/`.

**Step 2: Run Playwright test**
Run: `python -m pytest e2e/test_tabmaker_e2e.py -v` (or npm run test:e2e)

**Step 3: Verify screenshots and commit**
```bash
git add e2e/ docs/screenshots/
git commit -m "test: add automated Playwright E2E suite with screenshots"
```
