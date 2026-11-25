import os
import sys
import shutil
import subprocess
from typing import Tuple, Optional
from pydub import AudioSegment


def resolve_ytdlp_bin() -> str:
    candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    if os.path.exists(candidate):
        return candidate
    return shutil.which("yt-dlp") or "yt-dlp"


def resolve_ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/usr/local/bin/ffmpeg"


def fetch_youtube_title(youtube_url: str, ytdlp_bin: Optional[str] = None) -> str:
    ytdlp = ytdlp_bin or resolve_ytdlp_bin()
    for extra in (["--extractor-args", "youtube:player_client=android"], []):
        try:
            cmd = [ytdlp] + extra + ["-e", "--no-playlist", youtube_url]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
            if res.returncode == 0:
                title = res.stdout.decode("utf-8", errors="ignore").strip()
                if title:
                    return title
        except Exception:
            continue
    return "YouTube Guitar Solo"


def _normalize_to_44k_wav(src_path: str, dst_path: str, ffmpeg_bin: str) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        src_path,
        "-acodec",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        dst_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)


def _slice_media(src_path: str, dst_path: str, start_time: float, end_time: float, ffmpeg_bin: str, is_video: bool = False) -> None:
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{max(0.0, start_time):.3f}",
        "-to",
        f"{max(start_time + 0.5, end_time):.3f}",
        "-i",
        src_path,
    ]
    if is_video:
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-an", dst_path])
    else:
        cmd.extend(["-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", dst_path])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)


def ingest_youtube_slice(
    youtube_url: str,
    session_dir: str,
    start_time: float,
    end_time: float,
) -> Tuple[str, Optional[str], float, str]:
    """
    Downloads high-quality audio and cropped solo video strictly for [start_time, end_time].
    Returns (cropped_wav_path, cropped_video_path_or_None, actual_duration, video_title).
    """
    ytdlp_bin = resolve_ytdlp_bin()
    ffmpeg_bin = resolve_ffmpeg_bin()
    video_title = fetch_youtube_title(youtube_url, ytdlp_bin=ytdlp_bin)

    crop_start = max(0.0, float(start_time))
    crop_end = float(end_time) if float(end_time) > crop_start else crop_start + 30.0
    cropped_wav = os.path.join(session_dir, "cropped.wav")

    # 1. Try targeted section download at highest audio quality first
    section_spec = f"*{crop_start:.2f}-{crop_end:.2f}"
    section_audio_tmpl = os.path.join(session_dir, "section_audio.%(ext)s")
    section_strategies = [
        ["--extractor-args", "youtube:player_client=android", "-f", "bestaudio/best"],
        ["-f", "bestaudio/best"],
    ]

    audio_ready = False
    for strat in section_strategies:
        try:
            cmd = [
                ytdlp_bin,
                "--no-playlist",
                "--download-sections",
                section_spec,
                "--force-keyframes-at-cuts",
                "-x",
                "--audio-format",
                "wav",
                "--ffmpeg-location",
                ffmpeg_bin,
                "-o",
                section_audio_tmpl,
            ] + strat + [youtube_url]
            subprocess.run(cmd, check=True, timeout=75, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            candidate = os.path.join(session_dir, "section_audio.wav")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 8000:
                _normalize_to_44k_wav(candidate, cropped_wav, ffmpeg_bin)
                audio_ready = True
                break
        except Exception as e:
            print(f"Section audio download fallback ({strat}): {e}")
            continue

    # 2. Fallback: download bestaudio and slice locally with ffmpeg
    if not audio_ready:
        full_audio_tmpl = os.path.join(session_dir, "input_audio.%(ext)s")
        for strat in section_strategies + [["-f", "18/bestaudio/best"]]:
            try:
                cmd = [
                    ytdlp_bin,
                    "--no-playlist",
                    "-x",
                    "--audio-format",
                    "wav",
                    "--ffmpeg-location",
                    ffmpeg_bin,
                    "-o",
                    full_audio_tmpl,
                ] + strat + [youtube_url]
                subprocess.run(cmd, check=True, timeout=90, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                candidate = os.path.join(session_dir, "input_audio.wav")
                if os.path.exists(candidate) and os.path.getsize(candidate) > 8000:
                    _slice_media(candidate, cropped_wav, crop_start, crop_end, ffmpeg_bin, is_video=False)
                    audio_ready = True
                    break
            except Exception as e:
                print(f"Full audio download fallback ({strat}): {e}")
                continue

    if not audio_ready or not os.path.exists(cropped_wav):
        raise RuntimeError("Could not download audio from YouTube. Check the URL or upload a WAV/MP3 file directly.")

    seg = AudioSegment.from_file(cropped_wav)
    duration = round(len(seg) / 1000.0, 3)

    # 3. Download cropped solo video slice so t=0 of solo.mp4 matches t=0 of cropped.wav
    cropped_video: Optional[str] = None
    section_vid_path = os.path.join(session_dir, "solo.mp4")
    for v_extra in (["--extractor-args", "youtube:player_client=android"], []):
        try:
            v_cmd = [
                ytdlp_bin,
                "--no-playlist",
            ] + v_extra + [
                "--download-sections",
                section_spec,
                "--force-keyframes-at-cuts",
                "-f",
                "18/best[height<=480][ext=mp4]/worst[ext=mp4]",
                "--ffmpeg-location",
                ffmpeg_bin,
                "-o",
                section_vid_path,
                youtube_url,
            ]
            subprocess.run(v_cmd, check=True, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(section_vid_path) and os.path.getsize(section_vid_path) > 10000:
                cropped_video = section_vid_path
                break
        except Exception:
            continue

    if not cropped_video:
        raw_vid_path = os.path.join(session_dir, "raw_video.mp4")
        try:
            v_cmd2 = [
                ytdlp_bin,
                "--no-playlist",
                "--extractor-args",
                "youtube:player_client=android",
                "-f",
                "18/worst[ext=mp4]/best[ext=mp4]",
                "-o",
                raw_vid_path,
                youtube_url,
            ]
            subprocess.run(v_cmd2, check=True, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_vid_path) and os.path.getsize(raw_vid_path) > 10000:
                _slice_media(raw_vid_path, section_vid_path, crop_start, crop_end, ffmpeg_bin, is_video=True)
                if os.path.exists(section_vid_path) and os.path.getsize(section_vid_path) > 10000:
                    cropped_video = section_vid_path
                os.remove(raw_vid_path)
        except Exception:
            cropped_video = None

    return cropped_wav, cropped_video, duration, video_title
