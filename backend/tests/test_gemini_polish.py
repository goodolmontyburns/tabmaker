import pytest
from backend.copilot.gemini_client import GeminiClient
from backend.copilot.video_gatekeeper import compute_frame_variance, analyze_video_feasibility
from backend.copilot.tab_polish import deterministic_tab_polish, polish_tab, infer_key_from_notes

def test_gemini_client_key_detection():
    client = GeminiClient(api_key="test_key_12345")
    assert client.has_valid_key() is True
    
    empty_client = GeminiClient(api_key="")
    # Unless env has a key, it should be empty or detect env key
    if not empty_client.api_key:
        assert empty_client.has_valid_key() is False

def test_infer_key_from_notes():
    # Notes in C major / C blues: pitches 60 (C), 63 (Eb), 65 (F), 67 (G), 70 (Bb)
    notes = [
        {"p": 60, "t": 0.0, "d": 0.5},
        {"p": 63, "t": 0.5, "d": 0.5},
        {"p": 60, "t": 1.0, "d": 0.5},
        {"p": 67, "t": 1.5, "d": 0.5},
        {"p": 60, "t": 2.0, "d": 0.5}
    ]
    key_est = infer_key_from_notes(notes)
    assert "C" in key_est

def test_deterministic_tab_polish_blues_box():
    # In C blues (pitch 60 = C4, pitch 63 = Eb4, pitch 65 = F4, pitch 67 = G4)
    # Target fret 8 (frets 8-11 box)
    # Pitch 60 on string 3 (offset 55) -> fret 5, or on string 2 (offset 59) -> fret 1
    # Pitch 63 (Eb4) -> string 2 (offset 59) -> fret 4, or string 1 (offset 64) -> impossible, or string 3 (55) -> fret 8
    # Pitch 67 (G4) -> string 1 (offset 64) -> fret 3, or string 2 (59) -> fret 8
    notes = [
        {"id": "1", "p": 63, "t": 0.0, "d": 0.5, "s": 1, "f": 0},
        {"id": "2", "p": 67, "t": 0.5, "d": 0.5, "s": 1, "f": 0}
    ]
    polished = deterministic_tab_polish(notes, target_fret=8)
    assert len(polished) == 2
    # Pitch 63 with target fret 8 should select string 3, fret 8 (55 + 8 = 63)
    assert polished[0]["s"] == 3
    assert polished[0]["f"] == 8
    # Pitch 67 with target fret 8 should select string 2, fret 8 (59 + 8 = 67)
    assert polished[1]["s"] == 2
    assert polished[1]["f"] == 8

def test_analyze_video_feasibility_no_video():
    res = analyze_video_feasibility(video_path=None, duration=10.0)
    assert res["is_live_guitar"] is False
    assert res["mode"] == "theory_audio"

def test_polish_tab_fallback():
    notes = [
        {"id": "1", "p": 63, "t": 0.0, "d": 0.5, "s": 1, "f": 0},
        {"id": "2", "p": 67, "t": 0.5, "d": 0.5, "s": 1, "f": 0}
    ]
    res = polish_tab(notes, video_path=None, duration=5.0)
    assert res["success"] is True
    assert len(res["notes"]) == 2
    assert res["notes"][0]["f"] == 8
