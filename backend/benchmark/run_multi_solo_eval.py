"""
Autonomous Multi-Solo End-to-End Evaluation Suite.
Tests TabMaker across previously submitted YouTube URLs and cached solo WAVs
through the FastAPI backend (/process) -> Cloud Run L4 GPU -> Gemini 4 -> AlphaTex.
"""
import os
import json
import time
import httpx
from typing import Dict, Any, List
from backend.benchmark.ground_truth_eval import evaluate_transcription

BASE_URL = os.environ.get("TABMAKER_API_URL", "http://127.0.0.1:8000")


def _audit_notes(notes: List[Dict[str, Any]], duration: float) -> Dict[str, Any]:
    offsets = [64, 59, 55, 50, 45, 40]
    impossible_bends = []
    tuning_mismatches = 0
    span_violations = 0
    bends = 0
    slides = 0
    vibratos = 0
    strings_used = set()

    sorted_n = sorted(notes, key=lambda x: float(x.get("t", 0.0)))
    for i, n in enumerate(sorted_n):
        s = int(n.get("s", 1))
        f = int(n.get("f", 0))
        p = int(n.get("p", 60))
        strings_used.add(s)
        if not (1 <= s <= 6 and 0 <= f <= 24) or (offsets[s - 1] + f != p):
            tuning_mismatches += 1
        b = n.get("bend")
        if isinstance(b, dict):
            bends += 1
            if float(b.get("semitones", 0.0)) > 4.0:
                impossible_bends.append(b.get("semitones"))
        if n.get("slide"):
            slides += 1
        if n.get("vibrato"):
            vibratos += 1
        if i > 0:
            dt = float(n.get("t", 0.0)) - float(sorted_n[i - 1].get("t", 0.0))
            f_prev = int(sorted_n[i - 1].get("f", 0))
            if dt < 0.20 and f > 0 and f_prev > 0 and abs(f - f_prev) > 4:
                span_violations += 1

    density = len(notes) / max(1.0, duration)
    return {
        "note_count": len(notes),
        "notes_per_sec": round(density, 2),
        "bends": bends,
        "impossible_bends": impossible_bends,
        "slides": slides,
        "vibratos": vibratos,
        "tuning_mismatches": tuning_mismatches,
        "rapid_span_violations": span_violations,
        "strings_used": sorted(strings_used),
    }


def run_suite(out_report_path: str = "temp_uploads/multi_solo_eval_report.json") -> Dict[str, Any]:
    cases = [
        {
            "name": "clapton_im_tore_down",
            "type": "youtube",
            "url": "https://www.youtube.com/watch?v=vRcUufCKwOo",
            "start": 79.0,
            "end": 123.0,
            "target_fret": 8,
            "is_clapton_gt": True,
        },
        {
            "name": "freddie_king_san_ho_zay",
            "type": "youtube",
            "url": "https://www.youtube.com/watch?v=aUYcv0RTtKc",
            "start": 0.0,
            "end": 25.0,
            "target_fret": None,
            "is_clapton_gt": False,
        },
        {
            "name": "youtube_solo_RYKYMUFestk",
            "type": "youtube",
            "url": "https://www.youtube.com/watch?v=RYKYMUFestk",
            "start": 15.0,
            "end": 45.0,
            "target_fret": None,
            "is_clapton_gt": False,
        },
        {
            "name": "cached_user_solo_5bae8f74",
            "type": "file",
            "path": "backend/temp_uploads/5bae8f74-9503-4760-b409-d4ccf1634a68/cropped.wav",
            "start": 0.0,
            "end": 35.0,
            "target_fret": None,
            "is_clapton_gt": False,
        },
        {
            "name": "cached_user_solo_ca6d528b",
            "type": "file",
            "path": "backend/temp_uploads/ca6d528b-a1e5-4639-9ceb-e492a4ea6df4/cropped.wav",
            "start": 0.0,
            "end": 40.0,
            "target_fret": None,
            "is_clapton_gt": False,
        },
    ]

    results: Dict[str, Any] = {"timestamp": time.time(), "cases": {}}
    with httpx.Client(timeout=360.0) as client:
        health = client.get(f"{BASE_URL}/health").json()
        results["health"] = health
        print("Health:", health)

        for c in cases:
            name = c["name"]
            print(f"\n=== Running case: {name} ===")
            t0 = time.time()
            try:
                data = {
                    "start_time": str(c["start"]),
                    "end_time": str(c["end"]),
                }
                if c["target_fret"] is not None:
                    data["target_fret"] = str(c["target_fret"])

                if c["type"] == "youtube":
                    data["youtube_url"] = c["url"]
                    resp = client.post(f"{BASE_URL}/process", data=data)
                else:
                    if not os.path.exists(c["path"]):
                        print(f"Skipping {name}: missing {c['path']}")
                        continue
                    with open(c["path"], "rb") as f:
                        resp = client.post(
                            f"{BASE_URL}/process",
                            data=data,
                            files={"file": (os.path.basename(c["path"]), f, "audio/wav")},
                        )

                elapsed = round(time.time() - t0, 2)
                if resp.status_code != 200:
                    print(f"FAIL {name}: HTTP {resp.status_code} {resp.text[:300]}")
                    results["cases"][name] = {"status": "error", "code": resp.status_code, "detail": resp.text[:400]}
                    continue

                payload = resp.json()
                notes = payload.get("notes", [])
                dur = float(payload.get("duration", 0.0))
                audit = _audit_notes(notes, dur)
                entry: Dict[str, Any] = {
                    "status": "ok",
                    "elapsed_sec": elapsed,
                    "session_id": payload.get("session_id"),
                    "title": payload.get("title"),
                    "key": payload.get("key"),
                    "bpm": payload.get("bpm"),
                    "beats_count": len(payload.get("beats", [])),
                    "downbeats_count": len(payload.get("downbeats", [])),
                    "cloud_gpu_used": payload.get("cloud_gpu_used"),
                    "has_isolated_stem": payload.get("has_isolated_stem"),
                    "stem_metrics": payload.get("stem_metrics"),
                    "ai_applied": payload.get("ai_applied"),
                    "model_used": payload.get("model_used"),
                    "video_mode": payload.get("video_analysis", {}).get("mode"),
                    "audit": audit,
                }
                if c["is_clapton_gt"]:
                    entry["clapton_eval"] = evaluate_transcription(notes)
                    pre = payload.get("pre_polish_notes")
                    if pre:
                        entry["clapton_pre_polish_eval"] = evaluate_transcription(pre)
                results["cases"][name] = entry
                print(json.dumps(entry, indent=2))
            except Exception as e:
                print(f"EXCEPTION {name}: {e}")
                results["cases"][name] = {"status": "exception", "error": str(e)}

    os.makedirs(os.path.dirname(out_report_path), exist_ok=True)
    with open(out_report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved evaluation report to {out_report_path}")
    return results


if __name__ == "__main__":
    run_suite()
