# TabMaker v2: Design Document

**Date:** 2026-08-22  
**Author:** Pair Programming Agent & User  
**Status:** Approved  

---

## 1. Executive Summary

TabMaker v2 is a modern overhaul of the AI-powered guitar transcription web application. It transforms raw audio/video (from YouTube or audio uploads) into accurate, playable guitar tablature with clean, readable notation and synchronized audio playback.

The system addresses the core limitations of the legacy codebase (which relied on generic, unspecialized models like Spotify's Basic Pitch and heuristic fret guessing) by introducing:
1. **SOTA Stem Separation (BS-Roformer / Mel-Band Roformer)** for artifact-free guitar isolation.
2. **Continuous Pitch & Bend Tracking (CREPE / pYIN)** to capture real guitar articulations (bends, releases, vibrato, slides).
3. **Video Vision Gatekeeper & Dual-Mode Gemini 3.7 Flash Polish**: Detects whether video frames show active fretboard playing. If visible, it uses multimodal video frames to lock string/fret positions; if static (e.g. audio-only YouTube tracks like Clapton's *"I'm Tore Down"*), it applies music theory reasoning (blues box patterns, key detection) to polish fingerings and bends.
4. **Clean, Understated UI**: A simplified, high-contrast SVG score layout free of clutter and heavy styling.
5. **Ground Truth Benchmark**: Verification against the official human transcription of Eric Clapton's *"I'm Tore Down"* solo (measures 46–69).

---

## 2. Architecture & Data Flow

```
[ YouTube URL / Audio File ]
            |
            v
[ 1. Ingestion Engine (yt-dlp / ffmpeg) ]
      |                      |
  (Audio Stream)       (Sampled Video Frames)
      |                      |
      v                      v
[ 2. Stem Isolation ]   [ 3. Video Vision Gatekeeper ]
(BS-Roformer / Demucs)       |
      |                      +---> (Static/No Fretboard) -> Mode A: Theory + Audio Polish
      v                      +---> (Fretboard Visible)   -> Mode B: Multimodal Video + Audio Polish
[ 4. Neural Pitch & Bend ]   |
 (Notes + Pitch Contours)    |
      |                      |
      +----------> [ 5. Gemini 3.7 Flash Polish Engine ] <----------+
                                     |
                                     v
                       [ 6. Validated Tablature JSON ]
                                     |
                     +---------------+---------------+
                     |                               |
                     v                               v
         [ 7. Minimal SVG Tab Score ]     [ 8. Multi-Format Export ]
           - Real-time Audio Sync           - Vector PDF (jsPDF)
           - Click-to-Edit Frets/Strings    - Standard MIDI / MusicXML
           - Clean Measure & Beat Dividers
```

---

## 3. Core Modules & Specifications

### 3.1 Backend Ingestion & Source Separation
- **Audio Extraction**: `yt-dlp` fetches best audio at 44.1kHz 16-bit WAV.
- **Stem Separation**: BS-Roformer / Mel-Band Roformer model splits the guitar lead with minimal bleed.
- **Pitch & Articulation Tracking**: 
  - Onsets and frame pitches extracted via high-resolution neural pitch tracking.
  - Continuous pitch trajectories calculate bend intervals (1/2-step, full-step `b`, pre-bend, release `r`, slide `/`, `\`).

### 3.2 Video Vision Gatekeeper & Gemini 3.7 Flash Integration
- **Gatekeeper**: Samples 4 frames across the solo. Calculates structural frame variance. If frame variance is low or no guitarist is detected, routes to **Mode A**; otherwise routes to **Mode B**.
- **Gemini API Access**: Standardized client initialization supporting `GEMINI_API_KEY` / `GOOGLE_API_KEY` via environment variables, `.env`, or UI settings fallback.
- **AI Polish Engine**:
  - Ingests detected note list, bend metadata, and video frames (if applicable).
  - Infers key signature and scale framework (e.g. C Blues / Pentatonic).
  - Eliminates harmonic overtone false positives.
  - Optimizes fret positions into humanly playable hand boxes (e.g. frets 8–11 for C blues soloing).
  - Formats output as structured Tab JSON.

### 3.3 Frontend UI & Tablature Rendering
- **Design Aesthetic**: Clean, subtle, highly readable layout. No dark glassmorphism, heavy gradients, or unnecessary visual noise.
- **Interactive SVG Engine**:
  - Clean 6-line staff with high-contrast fret indicators.
  - Measure bar lines with measure numbering and beat dots (4/4 time).
  - Bend arches with target pitch indicators (`10b12`, `8b10`).
  - Interactive fret reassignment: click any note to pop up ergonomically valid alternative strings.
  - 60 FPS playhead with direct DOM attribute transformations (no React re-render lag).
  - Web Audio API synthesizer for instant audio playback of the transcribed tab.

---

## 4. Verification & Ground Truth Benchmark

1. **Clapton Ground Truth Test**:
   - Reference: `/Users/gbaird/Downloads/OFFICIAL IM TORE DOWN CHORDS & TABS by Eric Clapton @ Ultimate-Guitar.Com.pdf` (measures 46–69).
   - Audio input: `https://www.youtube.com/watch?v=vRcUufCKwOo` (1:19 to 2:03).
   - Benchmark script scores note pitch accuracy, rhythmic placement, and fret box alignment against ground truth.
2. **Playwright E2E Test**:
   - Headless browser automation testing all user interactions.
   - Captures screenshots of the workflow: upload -> transcription -> AI polish -> note editing -> PDF download.
