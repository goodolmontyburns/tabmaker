import os
os.environ["KERAS_HOME"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "temp_uploads", ".keras"))
os.makedirs(os.environ["KERAS_HOME"], exist_ok=True)
import uuid
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import librosa
from scipy.signal import medfilt

from backend.transcription.fingering_optimizer import (
    STRING_OFFSETS,
    estimate_key_and_box,
    optimize_tab_fingerings,
)

# Standard 6-String Guitar Tuning Offsets (Strings 1..6: high e -> low E)
TUNING_OFFSETS = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2
MAX_BEND_SEMITONES = 4.0


@dataclass
class BendInfo:
    type: str  # "quarter", "half", "full", "1.5", "2.0", "bend_release", "release"
    semitones: float
    target_pitch: int


@dataclass
class NoteEvent:
    id: str
    p: int          # MIDI pitch number (40..88)
    t: float        # Start time in seconds
    d: float        # Duration in seconds
    s: int = 1      # Guitar string (1..6)
    f: int = 0      # Fret number (0..24)
    velocity: float = 0.8
    bend: Optional[Dict[str, Any]] = None
    slide: Optional[str] = None      # "/", "\"
    vibrato: bool = False
    articulation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "id": self.id,
            "p": int(self.p),
            "t": float(round(self.t, 3)),
            "d": float(round(self.d, 3)),
            "s": int(self.s),
            "f": int(self.f),
            "velocity": float(round(self.velocity, 2)),
            "vibrato": bool(self.vibrato),
        }
        if self.bend:
            res["bend"] = self.bend
        if self.slide:
            res["slide"] = self.slide
        if self.articulation:
            res["articulation"] = self.articulation
        return res


def _classify_upward_bend(rise: float, base_pitch: int) -> Optional[Dict[str, Any]]:
    """Quantizes physically plausible upward bend intervals (capped at 4.0 semitones)."""
    if rise < 0.38 or rise > MAX_BEND_SEMITONES + 0.45:
        return None
    clamped = min(MAX_BEND_SEMITONES, rise)
    if clamped < 0.75:
        bend_type, semitones = "quarter", 0.5
    elif clamped < 1.45:
        bend_type, semitones = "half", 1.0
    elif clamped < 2.45:
        bend_type, semitones = "full", 2.0
    elif clamped < 3.45:
        bend_type, semitones = "1.5", 3.0
    else:
        bend_type, semitones = "2.0", 4.0
    return {
        "type": bend_type,
        "semitones": float(semitones),
        "target_pitch": int(round(base_pitch + semitones)),
    }


def detect_bends_in_contour(
    time_frames: np.ndarray,
    pitch_contour: np.ndarray,
    base_pitch: int,
    confidence: Optional[np.ndarray] = None,
) -> Optional[Dict[str, Any]]:
    """
    Analyzes continuous pitch trajectory with confidence gating and strict physical caps
    (<= 4.0 semitones) to detect quarter/half/full bends, bend-releases, and pre-bend releases.
    """
    if len(pitch_contour) < 5 or np.all(np.isnan(pitch_contour)):
        return None

    valid_mask = ~np.isnan(pitch_contour)
    if confidence is not None and len(confidence) == len(pitch_contour):
        valid_mask = valid_mask & (confidence >= 0.45)

    if np.sum(valid_mask) < 4:
        return None

    pitches = pitch_contour[valid_mask]
    if len(pitches) >= 5:
        pitches = medfilt(pitches, kernel_size=5)

    # Reject contours with > 5 semitone excursions from base_pitch (octave-jump or wide slide, not a bend)
    if np.max(pitches) - base_pitch > MAX_BEND_SEMITONES + 0.8:
        return None

    clean_pitches = np.array([p for p in pitches if abs(p - base_pitch) <= 5.0])
    if len(clean_pitches) < 4:
        return None

    q_len = max(1, len(clean_pitches) // 4)
    start_p = float(np.median(clean_pitches[:q_len]))
    end_p = float(np.median(clean_pitches[-q_len:]))
    max_p = float(np.max(clean_pitches))
    rise_peak = max_p - start_p
    delta_end = end_p - start_p

    # 1. Bend + Release (rises >= 0.85 semitones mid-note, returns near start)
    if rise_peak >= 0.85 and rise_peak <= MAX_BEND_SEMITONES + 0.45 and abs(delta_end) < 0.45:
        bend = _classify_upward_bend(rise_peak, base_pitch)
        if bend:
            bend["type"] = "bend_release"
            return bend

    # 2. Standard Upward Bend
    if delta_end >= 0.65 or (rise_peak >= 0.85 and end_p >= start_p + 0.45):
        return _classify_upward_bend(rise_peak, base_pitch)

    # 3. Pre-bend Release (starts high, drops 0.75..3.5 semitones down to base pitch)
    if delta_end <= -0.75 and abs(delta_end) <= 3.5:
        drop = min(3.0, round(abs(delta_end) * 2.0) / 2.0)
        return {
            "type": "release",
            "semitones": float(drop),
            "target_pitch": int(round(base_pitch)),
        }

    return None


def detect_vibrato_in_contour(
    time_frames: np.ndarray,
    pitch_contour: np.ndarray,
    confidence: Optional[np.ndarray] = None,
) -> bool:
    """Detects periodic blues/rock vibrato (4..8.5 Hz pitch modulation of 0.16..1.1 semitones)."""
    if len(pitch_contour) < 12:
        return False
    valid = ~np.isnan(pitch_contour)
    if confidence is not None and len(confidence) == len(pitch_contour):
        valid = valid & (confidence >= 0.45)
    if np.sum(valid) < 10:
        return False

    t_v = time_frames[valid]
    dur = float(t_v[-1] - t_v[0])
    if dur < 0.22:
        return False

    p_v = pitch_contour[valid]
    # Detrend slow bend slope with linear fit
    coef = np.polyfit(t_v - t_v[0], p_v, 1)
    resid = p_v - np.polyval(coef, t_v - t_v[0])
    std_dev = float(np.std(resid))
    if not (0.12 <= std_dev <= 0.55):
        return False

    # Count zero-crossings to verify periodic oscillation (~4 to 9 Hz -> 8..18 crossings/sec)
    crossings = int(np.sum(np.diff(np.signbit(resid))))
    rate_hz = (crossings / 2.0) / dur
    return 3.5 <= rate_hz <= 9.5


def fuse_bend_note_pairs(
    notes: List[NoteEvent],
    onset_times: Optional[np.ndarray] = None,
    onset_env: Optional[np.ndarray] = None,
    pitch_times: Optional[np.ndarray] = None,
    pitch_midi: Optional[np.ndarray] = None,
    pitch_conf: Optional[np.ndarray] = None,
) -> List[NoteEvent]:
    """
    Fuses stair-stepped note detections created when a note bends upward +1..+3 semitones
    without a second pick attack into a single fretted note with a bend annotation.
    """
    if len(notes) < 2:
        return notes

    notes.sort(key=lambda x: x.t)
    fused: List[NoteEvent] = []
    i = 0

    def _onset_peak_near(t_val: float) -> float:
        if onset_times is None or onset_env is None or len(onset_times) == 0:
            return 1.0
        mask = (onset_times >= t_val - 0.04) & (onset_times <= t_val + 0.04)
        if not np.any(mask):
            return 0.0
        return float(np.max(onset_env[mask]))

    while i < len(notes):
        curr = notes[i]
        if i + 1 < len(notes):
            nxt = notes[i + 1]
            gap = nxt.t - (curr.t + curr.d)
            pitch_jump = nxt.p - curr.p

            if -0.05 <= gap <= 0.08 and 1 <= pitch_jump <= 3:
                o1 = _onset_peak_near(curr.t)
                o2 = _onset_peak_near(nxt.t)
                weak_reattack = o1 > 0 and o2 < 0.45 * o1

                # Also verify continuous pitch trajectory across boundary if contour provided
                continuous_glide = True
                if pitch_times is not None and pitch_midi is not None and len(pitch_times) > 0:
                    span_mask = (pitch_times >= curr.t) & (pitch_times <= nxt.t + nxt.d)
                    if pitch_conf is not None and len(pitch_conf) == len(pitch_midi):
                        span_mask = span_mask & (pitch_conf >= 0.4)
                    vals = pitch_midi[span_mask]
                    vals = vals[~np.isnan(vals)]
                    if len(vals) >= 4:
                        continuous_glide = float(np.max(vals) - np.min(vals)) >= (pitch_jump - 0.4)

                if weak_reattack and continuous_glide:
                    curr.d = max(curr.d, (nxt.t + nxt.d) - curr.t)
                    curr.bend = _classify_upward_bend(float(pitch_jump), curr.p)
                    if nxt.vibrato:
                        curr.vibrato = True
                    fused.append(curr)
                    i += 2
                    continue

        fused.append(curr)
        i += 1

    return fused


def quantize_notes_to_grid(
    notes: List[NoteEvent],
    bpm: float = 120.0,
    time_sig: Tuple[int, int] = (4, 4),
) -> List[NoteEvent]:
    """Quantizes note timings to a 16th-note grid when close while preserving swing feel."""
    if not notes:
        return []
    beat_dur = 60.0 / max(40.0, min(240.0, bpm))
    grid_unit = beat_dur / 4.0

    for n in notes:
        quantized_t = round(n.t / grid_unit) * grid_unit
        if abs(quantized_t - n.t) <= 0.035:
            n.t = max(0.0, quantized_t)
        quantized_d = round(n.d / grid_unit) * grid_unit
        if quantized_d >= 0.05 and abs(quantized_d - n.d) <= 0.04:
            n.d = quantized_d
        elif n.d < 0.05:
            n.d = 0.08

    notes.sort(key=lambda x: x.t)
    return notes


def deduplicate_same_pitch_notes(notes: List[NoteEvent], onset_tol: float = 0.065) -> List[NoteEvent]:
    """
    Merges duplicate detections of the exact same MIDI pitch emitted across multiple
    MT3 instrument channels (e.g. Clean Guitar + Overdriven Guitar) within onset_tol or overlapping.
    """
    if not notes:
        return []
    notes.sort(key=lambda x: (x.t, -x.velocity))
    deduped: List[NoteEvent] = []
    for n in notes:
        merged = False
        for existing in reversed(deduped):
            if n.t - existing.t > 0.5 and existing.t + existing.d < n.t:
                continue
            if existing.p == n.p and (abs(n.t - existing.t) <= onset_tol or n.t < existing.t + existing.d - 0.01):
                existing.d = max(existing.d, (n.t + n.d) - existing.t)
                existing.velocity = max(existing.velocity, n.velocity)
                if n.bend and not existing.bend:
                    existing.bend = n.bend
                if n.vibrato:
                    existing.vibrato = True
                merged = True
                break
        if not merged:
            deduped.append(n)
    return deduped


def suppress_harmonic_overtones(notes: List[NoteEvent]) -> List[NoteEvent]:
    """Removes weaker 2nd (+12) and 3rd (+19) harmonic ghost notes co-occurring with fundamentals."""
    if not notes:
        return []
    notes.sort(key=lambda x: x.t)
    to_remove = set()

    for i, a in enumerate(notes):
        if id(a) in to_remove:
            continue
        for j in range(i + 1, len(notes)):
            b = notes[j]
            if b.t - a.t > 0.05:
                break
            if (b.p == a.p + 12 or b.p == a.p + 19) and b.velocity <= a.velocity * 1.15:
                to_remove.add(id(b))
            elif (a.p == b.p + 12 or a.p == b.p + 19) and a.velocity < b.velocity * 0.85:
                to_remove.add(id(a))

    return [n for n in notes if id(n) not in to_remove]


def filter_lead_solo_polyphony(notes: List[NoteEvent], max_concurrent: int = 2) -> List[NoteEvent]:
    """
    Prunes sub-guitar rumble (< E2 MIDI 40) and limits simultaneous voices to max_concurrent
    while preserving full 6-string guitar range (40..88).
    """
    if not notes:
        return []
    clean = [n for n in notes if 40 <= n.p <= 88]
    clean.sort(key=lambda x: x.t)

    pruned: List[NoteEvent] = []
    for n in clean:
        overlapping = [active for active in pruned if active.t + active.d > n.t + 0.025]
        if len(overlapping) < max_concurrent:
            pruned.append(n)
        else:
            all_candidates = overlapping + [n]
            scored = []
            for c in all_candidates:
                score = c.velocity * 2.5
                if 48 <= c.p <= 84:
                    score += 1.5
                if c.bend:
                    score += 2.0
                if c.d >= 0.14:
                    score += 1.0
                scored.append((score, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            keep_ids = {id(x[1]) for x in scored[:max_concurrent]}
            if id(n) in keep_ids:
                drop_target = scored[-1][1]
                pruned = [x for x in pruned if id(x) != id(drop_target)]
                pruned.append(n)

    pruned.sort(key=lambda x: x.t)
    return pruned


def consolidate_vibrato_fragments(notes: List[NoteEvent], max_gap: float = 0.075) -> List[NoteEvent]:
    """Merges adjacent notes of the same pitch fractured by vibrato."""
    if not notes:
        return []
    notes.sort(key=lambda x: x.t)
    merged: List[NoteEvent] = []
    for n in notes:
        if not merged:
            merged.append(n)
            continue
        prev = merged[-1]
        gap = n.t - (prev.t + prev.d)
        if prev.p == n.p and 0.0 <= gap <= max_gap:
            prev.d = (n.t + n.d) - prev.t
            if n.bend and not prev.bend:
                prev.bend = n.bend
            if n.vibrato:
                prev.vibrato = True
        else:
            merged.append(n)
    return merged


def postprocess_note_events(
    raw_notes: List[Dict[str, Any]],
    target_fret: Optional[int] = None,
    bpm: float = 120.0,
    neck_priors: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Shared 6-string cleaning, bend clamping, slide detection, key detection, and Viterbi fingering solver
    used on both Cloud Worker output and local fallback detections.
    """
    events: List[NoteEvent] = []
    for n in raw_notes:
        p = int(n.get("p", 60))
        if not (40 <= p <= 88):
            continue
        bend = n.get("bend")
        if isinstance(bend, dict):
            semis = float(bend.get("semitones", 0.0))
            if semis > MAX_BEND_SEMITONES or semis < 0.35:
                bend = None
        events.append(
            NoteEvent(
                id=str(n.get("id") or uuid.uuid4().hex[:8]),
                p=p,
                t=float(n.get("t", 0.0)),
                d=max(0.05, float(n.get("d", 0.1))),
                s=max(1, min(6, int(n.get("s", 1)))),
                f=max(0, min(24, int(n.get("f", 0)))),
                velocity=float(n.get("velocity", 0.8)),
                bend=bend,
                slide=n.get("slide"),
                vibrato=bool(n.get("vibrato", False)),
                articulation=n.get("articulation"),
            )
        )

    clean = deduplicate_same_pitch_notes(events)
    clean = suppress_harmonic_overtones(clean)
    clean = filter_lead_solo_polyphony(clean, max_concurrent=2)
    clean = consolidate_vibrato_fragments(clean, max_gap=0.075)
    clean = quantize_notes_to_grid(clean, bpm=bpm)

    key_info = estimate_key_and_box(clean, user_target_fret=target_fret)
    optimized = optimize_tab_fingerings(
        clean,
        target_fret=target_fret,
        key_info=key_info,
        neck_priors=neck_priors,
    )

    # Detect slides along the solved strings
    for i in range(len(optimized) - 1):
        curr_n = optimized[i]
        next_n = optimized[i + 1]
        gap = next_n.t - (curr_n.t + curr_n.d)
        if not curr_n.bend and -0.02 <= gap <= 0.05 and curr_n.s == next_n.s and 1 <= abs(curr_n.f - next_n.f) <= 5:
            curr_n.slide = "/" if next_n.f > curr_n.f else "\\"

    return [n.to_dict() for n in optimized], key_info


def extract_notes_and_bends(
    audio_path: str,
    target_fret: Optional[int] = None,
    prefer_open: bool = False,
    bpm: float = 120.0,
) -> List[NoteEvent]:
    """Local CPU fallback extractor (used only when Cloud GPU Worker is unavailable)."""
    if not os.path.exists(audio_path):
        return []

    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
        _, midi_data, _ = predict(
            audio_path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=0.58,
            frame_threshold=0.38,
            minimum_note_length=55.0,
            minimum_frequency=librosa.note_to_hz("E2"),
            maximum_frequency=librosa.note_to_hz("E6"),
        )
    except Exception as e:
        print(f"Local fallback prediction failed: {e}")
        return []

    if not midi_data or not midi_data.instruments:
        return []

    raw_midi_notes = sorted(midi_data.instruments[0].notes, key=lambda x: x.start)

    try:
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        hop = 256
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y,
            fmin=librosa.note_to_hz("E2"),
            fmax=librosa.note_to_hz("E6"),
            sr=sr,
            hop_length=hop,
            frame_length=2048,
        )
        times = librosa.times_like(f0, sr=sr, hop_length=hop)
        global_midi = librosa.hz_to_midi(f0)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
        onset_times = librosa.times_like(onset_env, sr=sr, hop_length=hop)
    except Exception:
        times = np.array([])
        global_midi = np.array([])
        voiced_probs = np.array([])
        onset_env = np.array([])
        onset_times = np.array([])

    note_objects: List[NoteEvent] = []
    for mn in raw_midi_notes:
        p = int(mn.pitch)
        t_start = float(mn.start)
        t_end = float(mn.end)
        dur = t_end - t_start
        if dur < 0.045 or not (40 <= p <= 88):
            continue

        bend_data = None
        vibrato = False
        if len(times) > 0:
            mask = (times >= t_start) & (times <= t_end)
            if np.sum(mask) >= 4:
                sub_t = times[mask]
                sub_p = global_midi[mask]
                sub_c = voiced_probs[mask] if len(voiced_probs) == len(times) else None
                bend_data = detect_bends_in_contour(sub_t, sub_p, base_pitch=p, confidence=sub_c)
                vibrato = detect_vibrato_in_contour(sub_t, sub_p, confidence=sub_c)

        note_objects.append(
            NoteEvent(
                id=uuid.uuid4().hex[:8],
                p=p,
                t=t_start,
                d=dur,
                s=1,
                f=0,
                velocity=float(mn.velocity / 127.0 if hasattr(mn, "velocity") else 0.8),
                bend=bend_data,
                vibrato=vibrato,
            )
        )

    note_objects = fuse_bend_note_pairs(
        note_objects,
        onset_times=onset_times,
        onset_env=onset_env,
        pitch_times=times,
        pitch_midi=global_midi,
        pitch_conf=voiced_probs,
    )
    dicts, _ = postprocess_note_events([n.to_dict() for n in note_objects], target_fret=target_fret, bpm=bpm)
    return [
        NoteEvent(
            id=d["id"],
            p=d["p"],
            t=d["t"],
            d=d["d"],
            s=d["s"],
            f=d["f"],
            velocity=d.get("velocity", 0.8),
            bend=d.get("bend"),
            slide=d.get("slide"),
            vibrato=d.get("vibrato", False),
            articulation=d.get("articulation"),
        )
        for d in dicts
    ]
