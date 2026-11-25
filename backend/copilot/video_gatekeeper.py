import os
import io
import json
import shutil
import subprocess
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from PIL import Image
from backend.copilot.gemini_client import GeminiClient


def extract_video_frames(
    video_path: str,
    duration: float,
    num_frames: int = 6,
) -> List[Tuple[float, bytes]]:
    """
    Extracts evenly spaced JPEG frames from the cropped solo video (t=0..duration).
    Returns list of (timestamp_sec, jpeg_bytes).
    """
    if not video_path or not os.path.exists(video_path) or duration <= 0:
        return []

    ffmpeg_bin = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    start_t = min(duration * 0.08, 0.5)
    end_t = max(start_t + 0.2, duration * 0.92)
    timestamps = np.linspace(start_t, end_t, num_frames)
    frames: List[Tuple[float, bytes]] = []

    for idx, t in enumerate(timestamps):
        tmp_img = f"/tmp/tabmaker_frame_{idx}_{os.getpid()}.jpg"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{float(t):.2f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            tmp_img,
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
            if os.path.exists(tmp_img):
                with open(tmp_img, "rb") as f:
                    frames.append((round(float(t), 2), f.read()))
                os.remove(tmp_img)
        except Exception:
            if os.path.exists(tmp_img):
                os.remove(tmp_img)

    return frames


def compute_frame_variance(frame_bytes_list: List[bytes]) -> float:
    """Computes normalized mean absolute pixel difference across sample frames."""
    if len(frame_bytes_list) < 2:
        return 0.0

    images = []
    for b in frame_bytes_list:
        try:
            img = Image.open(io.BytesIO(b)).convert("L").resize((128, 128))
            images.append(np.array(img, dtype=np.float32))
        except Exception:
            continue

    if len(images) < 2:
        return 0.0

    diffs = [np.mean(np.abs(images[i + 1] - images[i])) for i in range(len(images) - 1)]
    return float(np.mean(diffs))


def _strip_json_fences(raw_text: str) -> str:
    txt = (raw_text or "").strip()
    if "```json" in txt:
        txt = txt.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in txt:
        txt = txt.split("```", 1)[1].split("```", 1)[0].strip()
    return txt


def _sanitize_neck_priors(raw_priors: Any, duration: float) -> List[Dict[str, Any]]:
    if not isinstance(raw_priors, list):
        return []
    priors = []
    for item in raw_priors:
        if not isinstance(item, dict):
            continue
        try:
            t_start = max(0.0, float(item.get("t_start", 0.0)))
            t_end = min(max(t_start + 0.5, float(item.get("t_end", duration))), duration + 1.0)
            min_f = max(0, min(24, int(item.get("min_fret", 0))))
            max_f = max(min_f, min(24, int(item.get("max_fret", min_f + 4))))
            priors.append({
                "t_start": round(t_start, 2),
                "t_end": round(t_end, 2),
                "min_fret": min_f,
                "max_fret": max_f,
            })
        except Exception:
            continue
    return priors


def analyze_video_feasibility(
    video_path: Optional[str],
    duration: float,
    gemini_client: Optional[GeminiClient] = None,
) -> Dict[str, Any]:
    """
    Determines whether cropped solo video shows an active guitarist with visible fretboard,
    and extracts time-windowed neck position priors via Gemini 4 Argon.
    """
    if not video_path or not os.path.exists(video_path):
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "No video stream provided (audio-only mode)",
            "neck_region": None,
            "neck_priors": [],
            "sample_frames": [],
        }

    timestamped_frames = extract_video_frames(video_path, duration=duration, num_frames=6)
    frame_bytes = [b for _, b in timestamped_frames]
    if not frame_bytes:
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "Could not extract video frames from solo slice",
            "neck_region": None,
            "neck_priors": [],
            "sample_frames": [],
        }

    variance = compute_frame_variance(frame_bytes)
    if variance < 2.0:
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": f"Static video track / album artwork (motion variance {variance:.2f})",
            "neck_region": None,
            "neck_priors": [],
            "sample_frames": frame_bytes,
        }

    if gemini_client and gemini_client.has_valid_key():
        frame_times_desc = ", ".join(f"Frame {i+1}: t={t:.2f}s" for i, (t, _) in enumerate(timestamped_frames))
        prompt = f"""Analyze these {len(timestamped_frames)} frames from a {duration:.1f}s guitar solo video ({frame_times_desc}).
Determine if a guitarist's fretting hand and guitar fretboard inlays (frets 3, 5, 7, 9, 12, 15, 17, etc.) are clearly visible enough to estimate fret position.

Return JSON strictly in this schema:
{{
  "is_live_guitar": true,
  "neck_region": "frets 7-12",
  "neck_priors": [
    {{"t_start": 0.0, "t_end": 12.0, "min_fret": 7, "max_fret": 11}}
  ],
  "reason": "Brief observation of hand position or why fretboard is not visible"
}}
If the video is an album cover, lyric video, crowd shot, fast-cut music video, or the fretboard cannot be read reliably, set "is_live_guitar": false and "neck_priors": []."""

        res = gemini_client.generate_content(
            prompt=prompt,
            image_bytes_list=frame_bytes,
            model=GeminiClient.DEFAULT_FAST_MODEL,
            temperature=0.0,
        )
        if res.get("success"):
            try:
                parsed = json.loads(_strip_json_fences(res.get("raw_text", "{}")))
                is_live = bool(parsed.get("is_live_guitar", False))
                priors = _sanitize_neck_priors(parsed.get("neck_priors", []), duration) if is_live else []
                return {
                    "is_live_guitar": is_live,
                    "mode": "multimodal_video" if is_live else "theory_audio",
                    "reason": parsed.get("reason", f"Analyzed via {res.get('model_used', 'gemini-4-argon')}"),
                    "neck_region": parsed.get("neck_region"),
                    "neck_priors": priors,
                    "sample_frames": frame_bytes,
                }
            except Exception:
                pass

    return {
        "is_live_guitar": False,
        "mode": "theory_audio",
        "reason": f"Motion detected (variance {variance:.2f}); using audio + theory solver",
        "neck_region": None,
        "neck_priors": [],
        "sample_frames": frame_bytes,
    }
