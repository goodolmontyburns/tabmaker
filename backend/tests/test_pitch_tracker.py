import numpy as np
import pytest
from backend.transcription.pitch_tracker import (
    extract_notes_and_bends,
    detect_bends_in_contour,
    quantize_notes_to_grid,
    NoteEvent
)

def test_detect_bends_in_contour_full_bend():
    # 0.5s duration at 100fps
    # Pitch starts at 60 (C4) and rises smoothly to 62 (D4) = full bend (+2 semitones)
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = np.linspace(60.0, 62.0, 50)
    
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is not None
    assert bend_info["type"] in ["bend", "full"]
    assert pytest.approx(bend_info["semitones"], abs=0.25) == 2.0
    assert bend_info["target_pitch"] == 62

def test_detect_bends_in_contour_half_bend():
    # Pitch starts at 62 (D4) and rises to 63 (Eb4) = half bend (+1 semitone)
    time_frames = np.linspace(0, 0.4, 40)
    pitch_contour = np.linspace(62.0, 63.0, 40)
    
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=62)
    assert bend_info is not None
    assert bend_info["type"] in ["bend", "half"]
    assert pytest.approx(bend_info["semitones"], abs=0.25) == 1.0
    assert bend_info["target_pitch"] == 63

def test_detect_bends_in_contour_release():
    # Pitch starts high at 62 and drops to 60 = release bend
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = np.linspace(62.0, 60.0, 50)
    
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is not None
    assert bend_info["type"] == "release"
    assert bend_info["target_pitch"] == 60

def test_detect_bends_in_contour_no_bend():
    # Stable pitch around 60 (slight vibrato of +/- 0.1 semitone)
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = 60.0 + 0.1 * np.sin(2 * np.pi * 5 * time_frames)
    
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is None or bend_info["type"] == "none"

def test_quantize_notes_to_grid():
    raw_notes = [
        NoteEvent(id="1", p=60, t=0.02, d=0.48, s=3, f=5),
        NoteEvent(id="2", p=62, t=0.51, d=0.46, s=3, f=7),
    ]
    quantized = quantize_notes_to_grid(raw_notes, bpm=120, time_sig=(4, 4))
    assert len(quantized) == 2
    assert quantized[0].t == pytest.approx(0.0, abs=0.05)
    assert quantized[1].t == pytest.approx(0.5, abs=0.05)
