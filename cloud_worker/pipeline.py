import os
import io
import glob
import shutil
import uuid
import base64
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import soundfile as sf
import librosa
import torch
from scipy.signal import medfilt

MODEL_DIR = os.environ.get("AUDIO_SEPARATOR_MODEL_DIR", "/opt/models")
SEP_TMP_DIR = "/tmp/sep_out"
TUNING_OFFSETS = [64, 59, 55, 50, 45, 40]  # Strings 1..6: E4, B3, G3, D3, A2, E2
MAX_BEND_SEMITONES = 4.0

_BEAT_MODEL = None
_MT3_MODEL = None
_SEPARATOR = None


def get_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def warmup_models() -> Dict[str, Any]:
    """Lazily loads models into GPU memory once per container instance."""
    global _BEAT_MODEL, _MT3_MODEL, _SEPARATOR
    device = get_device()

    if _BEAT_MODEL is None:
        from beat_this.inference import File2Beats
        _BEAT_MODEL = File2Beats(checkpoint_path="final0", device=device, dbn=False)

    if _SEPARATOR is None:
        from audio_separator.separator import Separator
        os.makedirs(MODEL_DIR, exist_ok=True)
        os.makedirs(SEP_TMP_DIR, exist_ok=True)
        _SEPARATOR = Separator(
            model_file_dir=MODEL_DIR,
            output_dir=SEP_TMP_DIR,
            output_format="WAV",
            sample_rate=44100,
        )
        _SEPARATOR.load_model(model_filename="BS-Roformer-SW.ckpt")

    if _MT3_MODEL is None:
        from mt3_infer import load_model
        for m_name in ("yourmt3", "mr_mt3", "mt3_pytorch"):
            try:
                _MT3_MODEL = (m_name, load_model(m_name, device=device))
                break
            except Exception as e:
                print(f"Warning loading {m_name} with device={device}: {e}")
                try:
                    _MT3_MODEL = (m_name, load_model(m_name))
                    break
                except Exception as e2:
                    print(f"Warning loading {m_name} fallback: {e2}")

    return {
        "device": device,
        "beat_model_loaded": _BEAT_MODEL is not None,
        "separator_loaded": _SEPARATOR is not None,
        "mt3_model": _MT3_MODEL[0] if _MT3_MODEL else None,
    }


def _classify_upward_bend(rise: float, base_pitch: int) -> Optional[Dict[str, Any]]:
    if rise < 0.38 or rise > MAX_BEND_SEMITONES + 0.45:
        return None
    clamped = min(MAX_BEND_SEMITONES, rise)
    if clamped < 0.75:
        bend_type, semis = "quarter", 0.5
    elif clamped < 1.45:
        bend_type, semis = "half", 1.0
    elif clamped < 2.45:
        bend_type, semis = "full", 2.0
    elif clamped < 3.45:
        bend_type, semis = "1.5", 3.0
    else:
        bend_type, semis = "2.0", 4.0
    return {
        "type": bend_type,
        "semitones": float(semis),
        "target_pitch": int(round(base_pitch + semis)),
    }


def _detect_bends_and_vibrato(
    sub_times: np.ndarray,
    sub_midi: np.ndarray,
    sub_conf: np.ndarray,
    base_pitch: int,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    valid = (~np.isnan(sub_midi)) & (sub_conf >= 0.45)
    if np.sum(valid) < 5:
        return None, False

    pitches = sub_midi[valid]
    times = sub_times[valid]
    if len(pitches) >= 5:
        pitches = medfilt(pitches, kernel_size=5)
    if np.max(pitches) - base_pitch > MAX_BEND_SEMITONES + 0.8:
        return None, False
    clean = np.array([p for p in pitches if abs(p - base_pitch) <= 5.0])
    if len(clean) < 5:
        return None, False

    q_len = max(1, len(clean) // 4)
    start_p = float(np.median(clean[:q_len]))
    end_p = float(np.median(clean[-q_len:]))
    max_p = float(np.max(clean))
    rise_peak = max_p - start_p
    delta_end = end_p - start_p

    bend = None
    if 0.85 <= rise_peak <= MAX_BEND_SEMITONES + 0.45 and abs(delta_end) < 0.45:
        bend = _classify_upward_bend(rise_peak, base_pitch)
        if bend:
            bend["type"] = "bend_release"
    elif delta_end >= 0.65 or (rise_peak >= 0.85 and end_p >= start_p + 0.45):
        bend = _classify_upward_bend(rise_peak, base_pitch)
    elif -3.5 <= delta_end <= -0.75:
        drop = min(3.0, round(abs(delta_end) * 2.0) / 2.0)
        bend = {"type": "release", "semitones": float(drop), "target_pitch": int(base_pitch)}

    vibrato = False
    dur = float(times[-1] - times[0])
    if dur >= 0.22 and len(pitches) >= 12:
        coef = np.polyfit(times - times[0], pitches, 1)
        resid = pitches - np.polyval(coef, times - times[0])
        std_dev = float(np.std(resid))
        crossings = int(np.sum(np.diff(np.signbit(resid))))
        rate_hz = (crossings / 2.0) / dur
        if 0.12 <= std_dev <= 0.55 and 3.5 <= rate_hz <= 9.5:
            vibrato = True

    return bend, vibrato


def _build_backing_wav(mix_path: str, guitar_path: str, out_backing_path: str) -> None:
    mix_y, sr_m = sf.read(mix_path, always_2d=True)
    gtr_y, sr_g = sf.read(guitar_path, always_2d=True)
    if sr_g != sr_m:
        gtr_y = librosa.resample(gtr_y.T, orig_sr=sr_g, target_sr=sr_m).T
    n = min(len(mix_y), len(gtr_y))
    ch = min(mix_y.shape[1], gtr_y.shape[1])
    backing = np.clip(mix_y[:n, :ch] - gtr_y[:n, :ch], -1.0, 1.0)
    sf.write(out_backing_path, backing, sr_m, subtype="PCM_16")


def _encode_wav_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _deduplicate_same_pitch(notes: List[Dict[str, Any]], onset_tol: float = 0.065) -> List[Dict[str, Any]]:
    if not notes:
        return []
    notes.sort(key=lambda x: (x["t"], -x.get("velocity", 0.7)))
    deduped: List[Dict[str, Any]] = []
    for n in notes:
        merged = False
        for existing in reversed(deduped):
            if n["t"] - existing["t"] > 0.5 and existing["t"] + existing["d"] < n["t"]:
                continue
            if existing["p"] == n["p"] and (abs(n["t"] - existing["t"]) <= onset_tol or n["t"] < existing["t"] + existing["d"] - 0.01):
                existing["d"] = max(existing["d"], (n["t"] + n["d"]) - existing["t"])
                existing["velocity"] = max(existing.get("velocity", 0.7), n.get("velocity", 0.7))
                merged = True
                break
        if not merged:
            deduped.append(n)
    return deduped


def _extract_notes_mt3(guitar_path: str) -> List[Dict[str, Any]]:
    import io
    import pretty_midi
    from mt3_infer.utils.audio import load_audio

    audio, sr = load_audio(guitar_path)
    if _MT3_MODEL is not None:
        _, model = _MT3_MODEL
        midi_obj = model.transcribe(audio, sr=sr)
    else:
        from mt3_infer import transcribe
        midi_obj = transcribe(audio, model="yourmt3", sr=sr)

    if hasattr(midi_obj, "instruments"):
        pm = midi_obj
    else:
        buf = io.BytesIO()
        midi_obj.save(file=buf)
        buf.seek(0)
        pm = pretty_midi.PrettyMIDI(buf)

    raw: List[Dict[str, Any]] = []
    for inst in getattr(pm, "instruments", []):
        if getattr(inst, "is_drum", False):
            continue
        prog = int(getattr(inst, "program", 27))
        if 32 <= prog <= 39:  # Skip bass guitar channels
            continue
        is_guitar_prog = 24 <= prog <= 31
        for note in inst.notes:
            p = int(note.pitch)
            if not (40 <= p <= 88):
                continue
            dur = float(note.end - note.start)
            if dur < 0.045:
                continue
            vel = float(getattr(note, "velocity", 96)) / 127.0
            if not is_guitar_prog and vel < 0.40:
                continue
            raw.append({
                "id": uuid.uuid4().hex[:8],
                "p": p,
                "t": float(note.start),
                "d": dur,
                "velocity": vel if is_guitar_prog else vel * 0.9,
                "program": prog,
                "source": "yourmt3",
            })
    return _deduplicate_same_pitch(raw)


def _extract_notes_basic_pitch(guitar_path: str) -> List[Dict[str, Any]]:
    import basic_pitch
    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    onnx_candidate = os.path.join(os.path.dirname(basic_pitch.__file__), "saved_models", "icassp_2022", "nmp.onnx")
    model_path = onnx_candidate if os.path.exists(onnx_candidate) else ICASSP_2022_MODEL_PATH

    _, midi_data, _ = predict(
        guitar_path,
        model_or_model_path=model_path,
        onset_threshold=0.55,
        frame_threshold=0.36,
        minimum_note_length=50.0,
        minimum_frequency=80.0,
        maximum_frequency=1350.0,
    )
    if not midi_data or not midi_data.instruments:
        return []

    raw: List[Dict[str, Any]] = []
    for mn in midi_data.instruments[0].notes:
        p = int(mn.pitch)
        if not (40 <= p <= 88):
            continue
        dur = float(mn.end - mn.start)
        if dur < 0.045:
            continue
        raw.append({
            "id": uuid.uuid4().hex[:8],
            "p": p,
            "t": float(mn.start),
            "d": dur,
            "velocity": float(mn.velocity / 127.0 if hasattr(mn, "velocity") else 0.8),
            "program": 27,
            "source": "basic_pitch",
        })
    return _deduplicate_same_pitch(raw)


def _run_torchcrepe_contour(guitar_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    import torchcrepe
    audio, sr = torchcrepe.load.audio(guitar_path)
    if audio.dim() == 2 and audio.shape[0] > 1:
        audio = audio.mean(dim=0, keepdim=True)
    elif audio.dim() == 1:
        audio = audio.unsqueeze(0)

    hop_length = max(64, int(sr / 200.0))  # 5ms resolution
    device = get_device()
    pitch_hz, periodicity = torchcrepe.predict(
        audio,
        sr,
        hop_length,
        75.0,
        1400.0,
        "full",
        batch_size=1024,
        device=device,
        return_periodicity=True,
    )
    pitch_np = pitch_hz.reshape(-1).detach().cpu().numpy()
    conf_np = periodicity.reshape(-1).detach().cpu().numpy()
    times = np.arange(len(pitch_np)) * (hop_length / float(sr))
    with np.errstate(divide="ignore", invalid="ignore"):
        midi_vals = np.where(pitch_np > 0, 69.0 + 12.0 * np.log2(pitch_np / 440.0), np.nan)
    return times, midi_vals, conf_np


def _median_conf(c_times: np.ndarray, c_conf: np.ndarray, t_start: float, dur: float) -> float:
    if len(c_times) == 0:
        return 0.5
    mask = (c_times >= t_start) & (c_times <= t_start + dur)
    if not np.any(mask):
        return 0.0
    return float(np.median(c_conf[mask]))


def _combine_hybrid_notes(
    bp_notes: List[Dict[str, Any]],
    mt3_notes: List[Dict[str, Any]],
    c_times: np.ndarray,
    c_conf: np.ndarray,
) -> List[Dict[str, Any]]:
    combined: List[Dict[str, Any]] = []

    def _has_mt3_support(bp_n: Dict[str, Any]) -> bool:
        for m in mt3_notes:
            if abs(m["t"] - bp_n["t"]) <= 0.11 and abs(m["p"] - bp_n["p"]) <= 2:
                return True
        return False

    for bp_n in bp_notes:
        conf = _median_conf(c_times, c_conf, bp_n["t"], bp_n["d"])
        vel = float(bp_n.get("velocity", 0.7))
        if (_has_mt3_support(bp_n) and conf >= 0.30) or (vel >= 0.56 and conf >= 0.50 and bp_n["d"] >= 0.075):
            combined.append(bp_n)

    # Recover high-confidence YourMT3 guitar-program notes missed by Basic Pitch
    for m in mt3_notes:
        if not (24 <= int(m.get("program", 0)) <= 31):
            continue
        conf = _median_conf(c_times, c_conf, m["t"], m["d"])
        if float(m.get("velocity", 0.0)) >= 0.50 and conf >= 0.48:
            covered = any(abs(c["t"] - m["t"]) <= 0.10 and abs(c["p"] - m["p"]) <= 1 for c in combined)
            if not covered:
                combined.append(m)

    return _deduplicate_same_pitch(combined)


def _fuse_bends_and_articulations(
    raw_notes: List[Dict[str, Any]],
    guitar_path: str,
    c_times: np.ndarray,
    c_midi: np.ndarray,
    c_conf: np.ndarray,
) -> List[Dict[str, Any]]:
    if not raw_notes:
        return []

    y, sr = librosa.load(guitar_path, sr=22050, mono=True)
    hop = 256
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    onset_times = librosa.times_like(onset_env, sr=sr, hop_length=hop)

    for n in raw_notes:
        n["bend"] = None
        n["vibrato"] = False
        n["slide"] = None
        if len(c_times) > 0:
            mask = (c_times >= n["t"]) & (c_times <= n["t"] + n["d"])
            if np.sum(mask) >= 5:
                bend, vib = _detect_bends_and_vibrato(
                    c_times[mask], c_midi[mask], c_conf[mask], base_pitch=n["p"]
                )
                n["bend"] = bend
                n["vibrato"] = vib

    def _onset_peak(t_val: float) -> float:
        m = (onset_times >= t_val - 0.04) & (onset_times <= t_val + 0.04)
        return float(np.max(onset_env[m])) if np.any(m) else 0.0

    raw_notes.sort(key=lambda x: x["t"])
    fused: List[Dict[str, Any]] = []
    i = 0
    while i < len(raw_notes):
        curr = raw_notes[i]
        if i + 1 < len(raw_notes):
            nxt = raw_notes[i + 1]
            gap = nxt["t"] - (curr["t"] + curr["d"])
            jump = nxt["p"] - curr["p"]
            if -0.05 <= gap <= 0.08 and 1 <= jump <= 3:
                o1 = _onset_peak(curr["t"])
                o2 = _onset_peak(nxt["t"])
                if o1 > 0 and o2 < 0.45 * o1:
                    curr["d"] = max(curr["d"], (nxt["t"] + nxt["d"]) - curr["t"])
                    curr["bend"] = _classify_upward_bend(float(jump), curr["p"])
                    if nxt.get("vibrato"):
                        curr["vibrato"] = True
                    fused.append(curr)
                    i += 2
                    continue
        fused.append(curr)
        i += 1

    return fused


def _resolve_guitar_stem(output_files: List[str], sep_out: str) -> Optional[str]:
    search_dirs = [sep_out, SEP_TMP_DIR, os.getcwd()]
    candidates: List[str] = []
    for fpath in output_files:
        candidates.append(fpath)
        base = os.path.basename(fpath)
        for d in search_dirs:
            candidates.append(os.path.join(d, base))

    for d in (sep_out, SEP_TMP_DIR):
        candidates.extend(glob.glob(os.path.join(d, "*guitar*.wav")))
        candidates.extend(glob.glob(os.path.join(d, "*(guitar)*.wav")))

    for cand in candidates:
        if os.path.exists(cand) and "(guitar)" in os.path.basename(cand).lower():
            return cand
    for cand in candidates:
        if os.path.exists(cand) and "guitar" in os.path.basename(cand).lower():
            return cand
    return None


def _clear_dir_files(path: str) -> None:
    if not os.path.exists(path):
        return
    for name in os.listdir(path):
        p = os.path.join(path, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        except Exception:
            pass


def analyze_audio_pipeline(
    cropped_wav_path: str,
    work_dir: str,
    solo_mode: bool = True,
    transcriber: str = "hybrid",
) -> Dict[str, Any]:
    state = warmup_models()

    # 1. Beat & downbeat tracking on full mix
    beats_arr, downbeats_arr = _BEAT_MODEL(cropped_wav_path)
    beats = [round(float(b), 4) for b in beats_arr]
    downbeats = [round(float(d), 4) for d in downbeats_arr]
    if len(beats) >= 2:
        ibis = np.diff(beats)
        valid_ibis = ibis[(ibis > 0.22) & (ibis < 1.5)]
        med_ibi = float(np.median(valid_ibis)) if len(valid_ibis) else 0.5
        bpm = round(60.0 / max(0.25, med_ibi), 1)
    else:
        bpm = 120.0

    # 2. BS-RoFormer-SW 6-stem separation with reliable output path resolution
    sep_out = os.path.join(work_dir, "stems")
    os.makedirs(sep_out, exist_ok=True)
    os.makedirs(SEP_TMP_DIR, exist_ok=True)
    _clear_dir_files(SEP_TMP_DIR)

    try:
        _SEPARATOR.output_dir = sep_out
        if getattr(_SEPARATOR, "model_instance", None) is not None:
            _SEPARATOR.model_instance.output_dir = sep_out
        output_files = _SEPARATOR.separate(cropped_wav_path)
        found_guitar = _resolve_guitar_stem(output_files, sep_out)
        guitar_stem_path = os.path.join(work_dir, "guitar.wav")
        if found_guitar and os.path.exists(found_guitar):
            shutil.copyfile(found_guitar, guitar_stem_path)
        else:
            guitar_stem_path = cropped_wav_path
    finally:
        _clear_dir_files(SEP_TMP_DIR)

    backing_stem_path = os.path.join(work_dir, "backing.wav")
    has_isolated_stem = guitar_stem_path != cropped_wav_path and os.path.exists(guitar_stem_path)
    if has_isolated_stem:
        _build_backing_wav(cropped_wav_path, guitar_stem_path, backing_stem_path)
    else:
        backing_stem_path = cropped_wav_path

    g_y, sr_g = sf.read(guitar_stem_path)
    m_y, _ = sf.read(cropped_wav_path)
    guitar_rms = float(np.sqrt(np.mean(np.square(g_y)))) if len(g_y) else 0.0
    mix_rms = float(np.sqrt(np.mean(np.square(m_y)))) if len(m_y) else 1.0

    # Peak-normalize a transcription copy so quiet vintage mixes don't under-trigger
    transcribe_wav_path = guitar_stem_path
    peak_g = float(np.max(np.abs(g_y))) if len(g_y) else 0.0
    if 0.002 < peak_g < 0.50:
        gain = min(12.0, 0.85 / peak_g)
        transcribe_wav_path = os.path.join(work_dir, "guitar_norm.wav")
        sf.write(transcribe_wav_path, np.clip(g_y * gain, -1.0, 1.0), sr_g, subtype="PCM_16")

    # 3. Continuous TorchCREPE pitch contour (5ms)
    try:
        c_times, c_midi, c_conf = _run_torchcrepe_contour(transcribe_wav_path)
    except Exception as e:
        print(f"TorchCREPE warning: {e}")
        c_times, c_midi, c_conf = np.array([]), np.array([]), np.array([])

    # 4. Guitar multi-pitch transcription (hybrid | basic_pitch | yourmt3)
    mode = (transcriber or "hybrid").lower()
    if mode == "basic_pitch":
        raw_notes = _extract_notes_basic_pitch(transcribe_wav_path)
    elif mode == "yourmt3":
        raw_notes = _extract_notes_mt3(transcribe_wav_path)
    else:
        bp_notes = _extract_notes_basic_pitch(transcribe_wav_path)
        mt3_notes = _extract_notes_mt3(transcribe_wav_path)
        raw_notes = _combine_hybrid_notes(bp_notes, mt3_notes, c_times, c_conf)

    fused_notes = _fuse_bends_and_articulations(raw_notes, transcribe_wav_path, c_times, c_midi, c_conf)

    return {
        "device": state["device"],
        "mt3_model": state["mt3_model"],
        "transcriber_mode": mode,
        "beats": beats,
        "downbeats": downbeats,
        "bpm": bpm,
        "raw_notes": fused_notes,
        "has_isolated_stem": has_isolated_stem,
        "stem_metrics": {
            "guitar_rms": round(guitar_rms, 5),
            "mix_rms": round(mix_rms, 5),
            "guitar_to_mix_ratio": round(guitar_rms / max(1e-6, mix_rms), 3),
        },
        "guitar_stem_b64": _encode_wav_to_b64(guitar_stem_path),
        "backing_stem_b64": _encode_wav_to_b64(backing_stem_path),
    }
