import numpy as np
import pytest
from backend.transcription.pitch_tracker import (
    detect_bends_in_contour,
    fuse_bend_note_pairs,
    postprocess_note_events,
    quantize_notes_to_grid,
    NoteEvent,
)
from backend.transcription.fingering_optimizer import (
    estimate_key_and_box,
    optimize_tab_fingerings,
)


def test_detect_bends_in_contour_full_bend():
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = np.linspace(60.0, 62.0, 50)
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is not None
    assert bend_info["type"] == "full"
    assert pytest.approx(bend_info["semitones"], abs=0.25) == 2.0
    assert bend_info["target_pitch"] == 62


def test_detect_bends_in_contour_half_bend():
    time_frames = np.linspace(0, 0.4, 40)
    pitch_contour = np.linspace(62.0, 63.0, 40)
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=62)
    assert bend_info is not None
    assert bend_info["type"] == "half"
    assert pytest.approx(bend_info["semitones"], abs=0.25) == 1.0
    assert bend_info["target_pitch"] == 63


def test_detect_bends_rejects_impossible_octave_jump():
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = np.linspace(60.0, 75.0, 50)  # +15 semitones impossible bend
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is None


def test_detect_bends_in_contour_release():
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = np.linspace(62.0, 60.0, 50)
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is not None
    assert bend_info["type"] == "release"
    assert bend_info["target_pitch"] == 60


def test_detect_bends_in_contour_no_bend():
    time_frames = np.linspace(0, 0.5, 50)
    pitch_contour = 60.0 + 0.1 * np.sin(2 * np.pi * 5 * time_frames)
    bend_info = detect_bends_in_contour(time_frames, pitch_contour, base_pitch=60)
    assert bend_info is None


def test_fuse_bend_note_pairs_merges_staircase_bend():
    notes = [
        NoteEvent(id="n1", p=67, t=1.0, d=0.20, s=2, f=8),
        NoteEvent(id="n2", p=69, t=1.22, d=0.35, s=2, f=10),
    ]
    onset_times = np.array([1.0, 1.22])
    onset_env = np.array([1.0, 0.15])  # No fresh pick attack at n2
    fused = fuse_bend_note_pairs(notes, onset_times=onset_times, onset_env=onset_env)
    assert len(fused) == 1
    assert fused[0].p == 67
    assert fused[0].bend is not None
    assert fused[0].bend["type"] == "full"
    assert fused[0].d == pytest.approx(0.57, abs=0.02)


def test_six_string_optimizer_supports_low_e_and_target_fret():
    low_notes = [
        {"id": "1", "p": 40, "t": 0.0, "d": 0.4},   # E2 (string 6 open)
        {"id": "2", "p": 43, "t": 0.45, "d": 0.4},  # G2 (string 6 fret 3)
        {"id": "3", "p": 45, "t": 0.9, "d": 0.4},   # A2 (string 6 fret 5 or string 5 open)
        {"id": "4", "p": 40, "t": 1.35, "d": 0.6},  # E2 tonic resolution
    ]
    solved, key_info = postprocess_note_events(low_notes, target_fret=0, bpm=120.0)
    assert len(solved) == 4
    assert solved[0]["s"] == 6 and solved[0]["f"] == 0
    assert solved[1]["s"] == 6 and solved[1]["f"] == 3
    assert "E" in key_info["key"]


def test_postprocess_clamps_impossible_bends_and_respects_neck_priors():
    raw = [
        {"id": "1", "p": 67, "t": 0.0, "d": 0.3, "bend": {"type": "bend", "semitones": 15.2, "target_pitch": 82}},
        {"id": "2", "p": 67, "t": 0.5, "d": 0.3, "bend": {"type": "full", "semitones": 2.0, "target_pitch": 69}},
    ]
    priors = [{"t_start": 0.0, "t_end": 2.0, "min_fret": 11, "max_fret": 14}]
    solved, _ = postprocess_note_events(raw, target_fret=8, bpm=120.0, neck_priors=priors)
    assert solved[0].get("bend") is None  # 15.2 semitones dropped
    assert solved[1].get("bend") is not None
    assert 11 <= solved[1]["f"] <= 14  # G4 on string 3 fret 12 matches video neck prior


def test_postprocess_deduplicates_multi_program_same_pitch():
    raw = [
        {"id": "g1", "p": 67, "t": 1.00, "d": 0.25, "velocity": 0.85},
        {"id": "g2", "p": 67, "t": 1.03, "d": 0.35, "velocity": 0.70},
        {"id": "g3", "p": 70, "t": 1.50, "d": 0.30, "velocity": 0.80},
    ]
    solved, _ = postprocess_note_events(raw, target_fret=8, bpm=120.0)
    assert len(solved) == 2
    assert solved[0]["p"] == 67
    assert solved[0]["d"] == pytest.approx(0.38, abs=0.02)
    assert solved[1]["p"] == 70


def test_quantize_notes_to_grid():
    raw_notes = [
        NoteEvent(id="1", p=60, t=0.02, d=0.48, s=3, f=5),
        NoteEvent(id="2", p=62, t=0.51, d=0.46, s=3, f=7),
    ]
    quantized = quantize_notes_to_grid(raw_notes, bpm=120, time_sig=(4, 4))
    assert len(quantized) == 2
    assert quantized[0].t == pytest.approx(0.0, abs=0.05)
    assert quantized[1].t == pytest.approx(0.5, abs=0.05)
