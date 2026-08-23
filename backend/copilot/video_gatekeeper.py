import os
import subprocess
import shutil
import json
from typing import List, Dict, Any, Optional
import numpy as np
from PIL import Image
from backend.copilot.gemini_client import GeminiClient

def extract_video_frames(video_path: str, duration: float, num_frames: int = 4) -> List[bytes]:
    """Extracts sample JPEG frames evenly spaced across video duration using ffmpeg."""
    if not os.path.exists(video_path) or duration <= 0:
        return []

    ffmpeg_bin = shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"
    timestamps = np.linspace(duration * 0.15, duration * 0.85, num_frames)
    frame_bytes_list: List[bytes] = []

    for idx, t in enumerate(timestamps):
        tmp_img = f"/tmp/tabmaker_frame_{idx}_{os.getpid()}.jpg"
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(round(t, 2)),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "3",
            tmp_img
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if os.path.exists(tmp_img):
                with open(tmp_img, "rb") as f:
                    frame_bytes_list.append(f.read())
                os.remove(tmp_img)
        except Exception:
            if os.path.exists(tmp_img):
                os.remove(tmp_img)

    return frame_bytes_list

def compute_frame_variance(frame_bytes_list: List[bytes]) -> float:
    """Computes normalized mean absolute pixel difference across sample frames."""
    if len(frame_bytes_list) < 2:
        return 0.0

    images = []
    for b in frame_bytes_list:
        try:
            import io
            img = Image.open(io.BytesIO(b)).convert('L').resize((128, 128))
            images.append(np.array(img, dtype=np.float32))
        except Exception:
            continue

    if len(images) < 2:
        return 0.0

    diffs = []
    for i in range(len(images) - 1):
        diff = np.mean(np.abs(images[i+1] - images[i]))
        diffs.append(diff)

    return float(np.mean(diffs))

def analyze_video_feasibility(
    video_path: Optional[str],
    duration: float,
    gemini_client: Optional[GeminiClient] = None
) -> Dict[str, Any]:
    """Determines whether video shows an active guitarist with visible fretboard."""
    if not video_path or not os.path.exists(video_path):
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "No video stream provided (audio-only mode)",
            "neck_region": None,
            "sample_frames": []
        }

    frames = extract_video_frames(video_path, duration=duration, num_frames=4)
    if not frames:
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "Could not extract video frames from stream",
            "neck_region": None,
            "sample_frames": []
        }

    variance = compute_frame_variance(frames)
    
    # If frames have less than 2.0 mean pixel difference, it's a static image or album cover
    if variance < 2.0:
        return {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": f"Static video track / album artwork (motion variance {variance:.2f})",
            "neck_region": None,
            "sample_frames": frames
        }

    # If motion detected and Gemini client has a key, query Gemini to confirm fretboard visibility
    if gemini_client and gemini_client.has_valid_key():
        prompt = """Analyze these video frames from a music video/track.
Does this video clearly show a guitarist's fretting hand and guitar neck being played?
Return JSON strictly in this format:
{
  "is_live_guitar": true,
  "neck_region": "frets 8-15",
  "reason": "Close-up shot of guitarist fretting hand"
}
If it is a music video with fast cuts, animations, singer closeups, or no clear fretboard, return:
{
  "is_live_guitar": false,
  "neck_region": null,
  "reason": "No clear view of guitarist fretboard/hands"
}"""
        res = gemini_client.generate_content(
            prompt=prompt,
            image_bytes_list=frames,
            temperature=0.1
        )
        if res.get("success"):
            try:
                parsed = json.loads(res.get("raw_text", "{}"))
                is_live = bool(parsed.get("is_live_guitar", False))
                return {
                    "is_live_guitar": is_live,
                    "mode": "multimodal_video" if is_live else "theory_audio",
                    "reason": parsed.get("reason", "Analyzed via Gemini Vision"),
                    "neck_region": parsed.get("neck_region"),
                    "sample_frames": frames
                }
            except Exception:
                pass

    return {
        "is_live_guitar": True,
        "mode": "multimodal_video",
        "reason": f"Active video motion detected (variance {variance:.2f})",
        "neck_region": None,
        "sample_frames": frames
    }
