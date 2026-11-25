from backend.copilot.gemini_client import GeminiClient
from backend.copilot.video_gatekeeper import analyze_video_feasibility
from backend.copilot.tab_polish import deterministic_tab_polish, polish_tab, infer_key_from_notes


def test_gemini_client_defaults_and_key_detection():
    client = GeminiClient(api_key="test_key_12345")
    assert client.has_valid_key() is True
    assert client.DEFAULT_FAST_MODEL == "gemini-4-argon"
    assert client.DEFAULT_PRO_MODEL == "gemini-4-carbon"

    empty_client = GeminiClient(api_key="")
    assert empty_client.api_key == ""


def test_infer_key_from_notes():
    notes = [
        {"p": 60, "t": 0.0, "d": 0.5},
        {"p": 63, "t": 0.5, "d": 0.5},
        {"p": 60, "t": 1.0, "d": 0.5},
        {"p": 67, "t": 1.5, "d": 0.5},
        {"p": 60, "t": 2.0, "d": 0.5},
    ]
    key_est = infer_key_from_notes(notes)
    assert "C" in key_est


def test_deterministic_tab_polish_respects_target_fret():
    notes = [
        {"id": "1", "p": 63, "t": 0.0, "d": 0.5, "s": 1, "f": 0},
        {"id": "2", "p": 67, "t": 0.5, "d": 0.5, "s": 1, "f": 0},
    ]
    polished = deterministic_tab_polish(notes, target_fret=8)
    assert len(polished) == 2
    assert polished[0]["s"] == 3 and polished[0]["f"] == 8
    assert polished[1]["s"] == 2 and polished[1]["f"] == 8


def test_analyze_video_feasibility_no_video():
    res = analyze_video_feasibility(video_path=None, duration=10.0)
    assert res["is_live_guitar"] is False
    assert res["mode"] == "theory_audio"
    assert res["neck_priors"] == []


def test_polish_tab_fallback_without_creds():
    notes = [
        {"id": "1", "p": 63, "t": 0.0, "d": 0.5, "s": 1, "f": 0},
        {"id": "2", "p": 67, "t": 0.5, "d": 0.5, "s": 1, "f": 0},
    ]
    client = GeminiClient(api_key="")
    client.get_auth_token = lambda: ""  # force deterministic fallback
    res = polish_tab(notes, video_path=None, duration=5.0, target_fret=8, gemini_client=client)
    assert res["success"] is True
    assert res["ai_applied"] is False
    assert len(res["notes"]) == 2
    assert res["notes"][0]["f"] == 8
