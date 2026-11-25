import os
import io
import json
from typing import List, Dict, Any, Optional
import numpy as np
from backend.copilot.gemini_client import GeminiClient
from backend.copilot.video_gatekeeper import analyze_video_feasibility
from backend.transcription.fingering_optimizer import (
    STRING_OFFSETS,
    estimate_key_and_box,
    optimize_tab_fingerings,
)

TUNING_OFFSETS = [64, 59, 55, 50, 45, 40]  # Strings 1..6: E4, B3, G3, D3, A2, E2

SYSTEM_INSTRUCTION = """You are an expert guitar transcriber and session musician.
You will receive:
1. The isolated guitar solo audio clip (16kHz mono WAV).
2. Optional sampled video frames from the solo performance showing the guitarist's fretting hand.
3. Acoustic note detections (id, MIDI pitch p, onset time t in seconds, duration d, current string s, fret f, bend, slide, vibrato) plus detected beats/BPM.

Your job is to verify and polish the tablature WITHOUT hallucinating timestamps or inventing notes from another song:
- Keep note onset times `t` anchored to the provided acoustic events.
- Identify the true musical key and scale (e.g., "C Minor Blues", "A Dorian", "E Minor Pentatonic").
- Prune obvious non-guitar bleed or harmonic overtone ghosts (especially weak octave/fifth ghosts or low accompaniment notes during rests) ONLY when clearly contradicted by the audio. Retain at least 70% of real lead notes.
- Optimize string `s` (1..6) and fret `f` (0..24) so consecutive fast notes fit comfortably within a human 4-5 fret hand box and match any visible neck position in the video frames.
- Preserve pitch consistency: p MUST equal [64, 59, 55, 50, 45, 40][s-1] + f.
- Verify bends: quarter (0.5), half (1.0), full (2.0), 1.5 (3.0), 2.0 (4.0), bend_release, or release. Never exceed 4.0 semitones and never put an upward bend on fret 0.
- Return strictly valid JSON."""


def infer_key_from_notes(notes: List[Dict[str, Any]]) -> str:
    """Duration- and cadence-weighted key estimation."""
    return estimate_key_and_box(notes)["key"]


def deterministic_tab_polish(
    notes: List[Dict[str, Any]],
    target_fret: Optional[int] = None,
    neck_priors: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    6-string biomechanical lead polisher:
    1. Enforces guitar pitch range (E2 MIDI 40..E6 MIDI 88) & valid <= 4.0 semitone bends.
    2. Caps simultaneous overlap at <= 2 voices per onset cluster (preserving double-stops).
    3. Solves globally optimal 6-string fretboard fingerings via Viterbi DP.
    """
    if not notes:
        return []

    clean: List[Dict[str, Any]] = []
    for n in notes:
        p = int(n.get("p", 60))
        if not (40 <= p <= 88):
            continue
        item = dict(n)
        bend = item.get("bend")
        if isinstance(bend, dict):
            semis = float(bend.get("semitones", 0.0))
            if semis > 4.0 or semis < 0.35:
                item["bend"] = None
        clean.append(item)

    clean.sort(key=lambda x: float(x.get("t", 0.0)))

    # Group near-simultaneous onsets (<= 50ms) and keep at most 2 highest-salience voices
    pruned: List[Dict[str, Any]] = []
    i = 0
    while i < len(clean):
        cluster = [clean[i]]
        j = i + 1
        base_t = float(clean[i].get("t", 0.0))
        while j < len(clean) and (float(clean[j].get("t", 0.0)) - base_t) <= 0.055:
            cluster.append(clean[j])
            j += 1

        if len(cluster) == 1:
            pruned.append(cluster[0])
        else:
            cluster.sort(
                key=lambda x: (
                    float(x.get("velocity", 0.7)) * 2.0
                    + (0.5 if x.get("bend") else 0.0)
                    + float(x.get("p", 60)) * 0.01
                ),
                reverse=True,
            )
            kept = cluster[:2]
            avg_t = min(float(k.get("t", 0.0)) for k in kept)
            for k in kept:
                k["t"] = avg_t
            pruned.extend(kept)
        i = j

    key_info = estimate_key_and_box(pruned, user_target_fret=target_fret)
    return optimize_tab_fingerings(
        pruned,
        target_fret=target_fret,
        key_info=key_info,
        neck_priors=neck_priors,
    )


def _downsample_wav_for_gemini(audio_path: Optional[str]) -> Optional[bytes]:
    """Reads and resamples WAV to 16kHz mono PCM16 bytes for multimodal Gemini listening."""
    if not audio_path or not os.path.exists(audio_path):
        return None
    try:
        import scipy.io.wavfile as wavfile
        import scipy.signal as signal

        sr, data = wavfile.read(audio_path)
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        if data.dtype == np.int16:
            data = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            data = data.astype(np.float32) / 2147483648.0
        else:
            data = data.astype(np.float32)

        target_sr = 16000
        if sr != target_sr and len(data) > 0:
            num_samples = int(len(data) * target_sr / sr)
            data = signal.resample(data, num_samples)

        data_int16 = np.clip(data * 32767.0, -32768.0, 32767.0).astype(np.int16)
        buf = io.BytesIO()
        wavfile.write(buf, target_sr, data_int16)
        return buf.getvalue()
    except Exception as e:
        print(f"Failed to downsample audio file {audio_path}: {e}")
        try:
            with open(audio_path, "rb") as af:
                return af.read()
        except Exception:
            return None


def _strip_json_fences(raw_text: str) -> str:
    txt = (raw_text or "").strip()
    if "```json" in txt:
        txt = txt.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in txt:
        txt = txt.split("```", 1)[1].split("```", 1)[0].strip()
    return txt


def polish_tab(
    notes: List[Dict[str, Any]],
    audio_path: Optional[str] = None,
    video_path: Optional[str] = None,
    duration: float = 0.0,
    key_hint: Optional[str] = None,
    bpm: float = 120.0,
    target_fret: Optional[int] = None,
    video_info: Optional[Dict[str, Any]] = None,
    gemini_client: Optional[GeminiClient] = None,
    deep_polish: bool = False,
) -> Dict[str, Any]:
    """
    Polishes transcribed solo using Gemini 4 (`gemini-4-argon` for fast automatic pass,
    `gemini-4-carbon` for explicit deep polish), falling back cleanly to 6-string Viterbi.
    """
    client = gemini_client or GeminiClient()
    v_info = video_info or analyze_video_feasibility(video_path, duration=duration, gemini_client=client)
    neck_priors = v_info.get("neck_priors") or []

    key_info = estimate_key_and_box(notes, user_target_fret=target_fret)
    key_est = key_hint or key_info["key"]

    if not notes:
        return {
            "success": True,
            "key": key_est,
            "tempo_bpm": round(bpm, 1),
            "mode": v_info.get("mode", "theory_audio"),
            "gatekeeper_reason": v_info.get("reason", "No notes detected"),
            "ai_applied": False,
            "notes": [],
        }

    deterministic_notes = deterministic_tab_polish(notes, target_fret=target_fret, neck_priors=neck_priors)

    if not client.has_valid_key():
        return {
            "success": True,
            "key": key_est,
            "tempo_bpm": round(bpm, 1),
            "mode": v_info.get("mode", "theory_audio"),
            "gatekeeper_reason": v_info.get("reason", "Local 6-string deterministic polish"),
            "ai_applied": False,
            "notes": deterministic_notes,
        }

    audio_bytes = _downsample_wav_for_gemini(audio_path)
    sample_frames = v_info.get("sample_frames", []) if v_info.get("is_live_guitar") else None

    cues = [
        {
            "id": str(n.get("id", f"n_{i+1}")),
            "p": int(n.get("p", 60)),
            "t": round(float(n.get("t", 0.0)), 3),
            "d": round(float(n.get("d", 0.1)), 3),
            "s": int(n.get("s", 1)),
            "f": int(n.get("f", 0)),
            "bend": n.get("bend"),
            "slide": n.get("slide"),
            "vibrato": bool(n.get("vibrato", False)),
        }
        for i, n in enumerate(deterministic_notes)
    ]

    neck_prior_text = json.dumps(neck_priors) if neck_priors else "None detected"
    user_prompt = f"""Polish this {duration:.1f}s guitar solo transcription.
Estimated Key: {key_est}
Detected Tempo: {bpm:.1f} BPM
Video Analysis Mode: {v_info.get('mode')} ({v_info.get('reason')})
Video Neck Position Priors: {neck_prior_text}
Target Fret Hint: {target_fret if target_fret is not None else 'Auto'}

Candidate acoustic notes (JSON):
```json
{json.dumps(cues)}
```

Listen to the attached guitar stem audio (and inspect any attached video frames) and return strictly valid JSON in this format:
{{
  "key_detected": "<Key and scale>",
  "tempo_bpm": {round(bpm, 1)},
  "notes": [
    {{
      "id": "<matching id>",
      "p": 67,
      "t": 1.25,
      "d": 0.25,
      "s": 2,
      "f": 8,
      "bend": {{"type": "full", "semitones": 2.0, "target_pitch": 69}} or null,
      "slide": null,
      "vibrato": false
    }}
  ]
}}"""

    chosen_model = GeminiClient.DEFAULT_PRO_MODEL if deep_polish else GeminiClient.DEFAULT_FAST_MODEL
    resp = client.generate_content(
        prompt=user_prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        image_bytes_list=sample_frames,
        audio_bytes=audio_bytes,
        audio_mime="audio/wav",
        model=chosen_model,
        temperature=0.0,
    )

    if resp.get("success"):
        try:
            parsed = json.loads(_strip_json_fences(resp.get("raw_text", "")))
            ai_notes = parsed.get("notes", [])
            if isinstance(ai_notes, list) and len(ai_notes) >= max(1, int(len(deterministic_notes) * 0.60)):
                orig_by_id = {c["id"]: c for c in cues}
                validated: List[Dict[str, Any]] = []
                for idx, n in enumerate(ai_notes):
                    nid = str(n.get("id") or f"n_{idx+1}")
                    s = max(1, min(6, int(n.get("s", 1))))
                    p = int(n.get("p", 60))
                    orig = orig_by_id.get(nid)
                    t_val = float(n.get("t", orig["t"] if orig else 0.0))
                    if orig and abs(t_val - orig["t"]) > 0.12:
                        t_val = orig["t"]
                    d_val = max(0.05, float(n.get("d", orig["d"] if orig else 0.1)))

                    f = p - TUNING_OFFSETS[s - 1]
                    if not (0 <= f <= 24):
                        f = max(0, min(24, int(n.get("f", 0))))
                        p = TUNING_OFFSETS[s - 1] + f

                    bend = n.get("bend")
                    if isinstance(bend, dict):
                        semis = float(bend.get("semitones", 0.0))
                        if semis <= 0.3 or semis > 4.0 or f == 0:
                            bend = None
                        else:
                            bend = {
                                "type": str(bend.get("type", "full")),
                                "semitones": round(semis, 1),
                                "target_pitch": int(round(p + semis)) if bend.get("type") != "release" else p,
                            }
                    else:
                        bend = None

                    validated.append({
                        "id": nid,
                        "p": p,
                        "t": round(max(0.0, t_val), 3),
                        "d": round(d_val, 3),
                        "s": s,
                        "f": f,
                        "bend": bend,
                        "slide": n.get("slide") if n.get("slide") in ("/", "\\") else None,
                        "vibrato": bool(n.get("vibrato", False)),
                    })

                validated.sort(key=lambda x: x["t"])

                # Guard against LLM introducing rapid >4-fret span violations
                has_span_violation = False
                for k in range(1, len(validated)):
                    dt_k = validated[k]["t"] - validated[k - 1]["t"]
                    f_a, f_b = validated[k - 1]["f"], validated[k]["f"]
                    if dt_k < 0.20 and f_a > 0 and f_b > 0 and abs(f_b - f_a) > 4:
                        has_span_violation = True
                        break
                if has_span_violation:
                    key_est_out = parsed.get("key_detected", key_est)
                    k_info = estimate_key_and_box(validated, user_target_fret=target_fret)
                    validated = optimize_tab_fingerings(
                        validated,
                        target_fret=target_fret,
                        key_info=k_info,
                        neck_priors=neck_priors,
                    )

                return {
                    "success": True,
                    "key": parsed.get("key_detected", key_est),
                    "tempo_bpm": float(parsed.get("tempo_bpm", bpm)),
                    "mode": v_info.get("mode", "theory_audio"),
                    "gatekeeper_reason": v_info.get("reason", ""),
                    "ai_applied": True,
                    "model_used": resp.get("model_used", chosen_model),
                    "provider": resp.get("provider", "gemini"),
                    "notes": validated,
                }
        except Exception as e:
            print(f"Error parsing Gemini 4 polish response: {e}")

    return {
        "success": True,
        "key": key_est,
        "tempo_bpm": round(bpm, 1),
        "mode": v_info.get("mode", "theory_audio"),
        "gatekeeper_reason": v_info.get("reason", "6-string deterministic fallback"),
        "ai_applied": False,
        "notes": deterministic_notes,
    }
