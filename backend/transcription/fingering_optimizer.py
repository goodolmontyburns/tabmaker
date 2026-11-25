"""
Full 6-String Key-Aware & Video-Prior Biomechanical Viterbi Fingering Optimizer.
Enforces physical hand-span constraints (<= 4 frets at speed), bend physics
(no bends on open strings; full bends prefer strings 1..3), legato same-string
continuity for slides/hammer-ons, and adherence to target_fret or video neck priors.
"""
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

# Standard 6-string Guitar Tuning Offsets (1: high e -> 6: low E)
STRING_OFFSETS: Dict[int, int] = {
    1: 64,  # e4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40,  # E2
}

PITCH_CLASS_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Scale templates (12 pitch classes relative to root)
MINOR_PENTATONIC = {0, 3, 5, 7, 10}
BLUES_SCALE = {0, 3, 5, 6, 7, 10}
MAJOR_PENTATONIC = {0, 2, 4, 7, 9}
NATURAL_MINOR = {0, 2, 3, 5, 7, 8, 10}
MAJOR_SCALE = {0, 2, 4, 5, 7, 9, 11}


def _get_note_field(n: Any, key: str, default: Any = None) -> Any:
    if isinstance(n, dict):
        return n.get(key, default)
    return getattr(n, key, default)


def estimate_key_and_box(notes: List[Any], user_target_fret: Optional[int] = None) -> Dict[str, Any]:
    """
    Duration- and cadence-weighted key/mode estimator across all 12 keys.
    Returns key label, tonic pitch class, and suggested primary fret box.
    """
    if not notes:
        return {"key": "C Blues / Pentatonic", "tonic_pc": 0, "mode": "minor_blues", "recommended_fret": user_target_fret or 8}

    pc_weights = np.zeros(12, dtype=np.float64)
    sorted_notes = sorted(notes, key=lambda n: float(_get_note_field(n, "t", 0.0)))
    for idx, n in enumerate(sorted_notes):
        p = int(_get_note_field(n, "p", 60))
        d = max(0.05, float(_get_note_field(n, "d", 0.15)))
        vel = float(_get_note_field(n, "velocity", 0.7))
        w = d * (0.6 + 0.6 * vel)
        # Weight final resolving notes higher (phrase cadences)
        if idx >= len(sorted_notes) - 3:
            w *= 1.5
        pc_weights[p % 12] += w

    total_w = float(np.sum(pc_weights)) or 1.0
    pc_norm = pc_weights / total_w

    best_score = -1e9
    best_tonic = 0
    best_mode = "Minor Blues"

    templates = [
        ("Minor Blues", BLUES_SCALE, 1.0),
        ("Minor Pentatonic", MINOR_PENTATONIC, 1.02),
        ("Major Pentatonic", MAJOR_PENTATONIC, 0.98),
        ("Natural Minor", NATURAL_MINOR, 0.92),
        ("Major", MAJOR_SCALE, 0.90),
    ]

    last_pc = int(_get_note_field(sorted_notes[-1], "p", 60)) % 12
    first_pc = int(_get_note_field(sorted_notes[0], "p", 60)) % 12

    for tonic in range(12):
        for mode_name, intervals, weight_bias in templates:
            in_scale = sum(pc_norm[(tonic + iv) % 12] for iv in intervals)
            out_scale = 1.0 - in_scale
            tonic_bonus = 0.18 * pc_norm[tonic] + 0.08 * pc_norm[(tonic + 7) % 12]
            cadence_bonus = (0.12 if last_pc == tonic else 0.0) + (0.05 if first_pc == tonic else 0.0)
            score = (in_scale - 0.65 * out_scale + tonic_bonus + cadence_bonus) * weight_bias
            if score > best_score:
                best_score = score
                best_tonic = tonic
                best_mode = mode_name

    # Compute standard Box-1 anchor fret on low E string (E2 = pc 4)
    # e.g., C (pc 0) -> fret 8; A (pc 9) -> fret 5; G (pc 7) -> fret 3 or 15; E (pc 4) -> fret 12
    box1_fret = (best_tonic - 4) % 12
    if box1_fret < 3:
        box1_fret += 12  # Prefer upper mid-neck over cramped frets 0-2 unless open soloing

    rec_fret = int(user_target_fret) if user_target_fret is not None else int(box1_fret)
    return {
        "key": f"{PITCH_CLASS_NAMES[best_tonic]} {best_mode}",
        "tonic_pc": best_tonic,
        "mode": best_mode,
        "recommended_fret": rec_fret,
        "box1_fret": int(box1_fret),
    }


def get_candidate_voicings(pitch: int, max_string: int = 6, max_fret: int = 24) -> List[Tuple[int, int]]:
    """Returns all valid (string, fret) pairs across strings 1..max_string."""
    candidates: List[Tuple[int, int]] = []
    for s in range(1, max_string + 1):
        fret = pitch - STRING_OFFSETS[s]
        if 0 <= fret <= max_fret:
            candidates.append((s, fret))
    if not candidates:
        # Clamp to closest reachable string if extreme outlier pitch occurs
        best_s = 1 if pitch > 64 else 6
        best_f = max(0, min(max_fret, pitch - STRING_OFFSETS[best_s]))
        candidates.append((best_s, best_f))
    return candidates


def _active_neck_window(t: float, neck_priors: Optional[List[Dict[str, Any]]]) -> Optional[Tuple[int, int]]:
    if not neck_priors:
        return None
    for win in neck_priors:
        if float(win.get("t_start", 0.0)) - 0.25 <= t <= float(win.get("t_end", 0.0)) + 0.25:
            return int(win.get("min_fret", 0)), int(win.get("max_fret", 24))
    return None


def state_cost(
    s: int,
    f: int,
    pitch: int,
    t: float,
    has_bend: bool = False,
    bend_semitones: float = 0.0,
    target_fret: Optional[int] = None,
    box1_fret: int = 8,
    neck_priors: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Biomechanical static preference cost for playing pitch at (string s, fret f)."""
    cost = 0.0

    # 1. Bend physics
    if has_bend:
        if f == 0:
            return 10000.0  # Physically impossible to bend an open string up on standard guitar
        if f <= 2:
            cost += 12.0  # Very stiff tension near nut
        if s == 6:
            cost += 15.0  # Rarely bend wound low E string in solos
        elif s in (1, 2, 3) and bend_semitones >= 1.5:
            cost -= 2.5  # Natural strings for full bends

    # 2. Open string slight penalty when target box is mid/high neck (harder to vibrato)
    anchor = target_fret if target_fret is not None else box1_fret
    if f == 0 and anchor >= 4:
        cost += 5.5

    # 3. Video neck-prior window (highest authority when fretboard is visible)
    win = _active_neck_window(t, neck_priors)
    if win is not None:
        min_f, max_f = win
        if min_f <= f <= max_f:
            cost -= 6.0
        else:
            dist = min_f - f if f < min_f else f - max_f
            cost += dist * 2.2
    else:
        # 4. Ergonomic box anchoring using user target_fret or key's box1 / octave box
        upper_box = box1_fret + 12 if box1_fret <= 10 else box1_fret
        if target_fret is not None:
            if target_fret <= f <= target_fret + 4:
                cost -= 3.5
            elif pitch >= 78 and upper_box <= f <= upper_box + 4:
                cost -= 3.0
            else:
                cost += min(abs(f - (target_fret + 1.5)), abs(f - (upper_box + 1.5)) + 3.0) * 0.65
        else:
            if box1_fret <= f <= box1_fret + 4:
                cost -= 3.0
            elif pitch >= 78 and upper_box <= f <= upper_box + 4:
                cost -= 3.0
            else:
                cost += min(abs(f - (box1_fret + 1.5)), abs(f - (upper_box + 1.5))) * 0.6

    # 5. Mild preference against playing very high frets (>17) on wound strings 5/6 (muddy timbre)
    if s in (5, 6) and f > 15:
        cost += 4.5 + (f - 15) * 0.8

    return cost


def transition_cost(
    s1: int,
    f1: int,
    t1: float,
    s2: int,
    f2: int,
    t2: float,
    is_simultaneous: bool = False,
    prev_slide: Optional[str] = None,
) -> float:
    """Calculates physical hand transition cost between consecutive notes."""
    dt = max(0.001, t2 - t1)
    df = abs(f2 - f1)
    ds = abs(s2 - s1)

    # Simultaneous notes (dyads / chords)
    if is_simultaneous or dt < 0.05:
        if s1 == s2:
            return 10000.0
        # Open strings can combine easily with fretted notes; otherwise cap stretch <= 4 frets
        if f1 > 0 and f2 > 0 and df > 4:
            return 600.0 * (df - 4)
        return ds * 1.4 + (0.0 if (f1 == 0 or f2 == 0) else df * 1.6)

    # Explicit slide continuity prefers staying on the same string
    if prev_slide and s1 != s2:
        return 40.0 + ds * 5.0

    # Rapid sequential notes (dt < 0.24s) -> Strict 4-fret hand-span guard
    if dt < 0.24:
        if f1 > 0 and f2 > 0 and df > 4:
            return 800.0 * (df - 4) + ds * 2.0
        return (0.0 if (f1 == 0 or f2 == 0) else df * 1.35) + ds * 1.1

    # Medium-speed shift (0.24s..0.60s)
    if dt < 0.60:
        return (0.0 if (f1 == 0 or f2 == 0) else df * 0.55) + ds * 0.7

    # Phrase gap (>= 0.60s): ample time to shift cleanly
    return df * 0.22 + ds * 0.35


def optimize_tab_fingerings(
    notes: List[Any],
    target_fret: Optional[int] = None,
    key_info: Optional[Dict[str, Any]] = None,
    neck_priors: Optional[List[Dict[str, Any]]] = None,
    default_box: Optional[int] = None,
) -> List[Any]:
    """
    Globally optimal 6-string (string, fret) assignment via Viterbi Dynamic Programming.
    Respects user target_fret, detected key boxes, bend physics, and optional video neck priors.
    """
    if not notes:
        return []

    resolved_target = target_fret if target_fret is not None else default_box
    resolved_key = key_info or estimate_key_and_box(notes, user_target_fret=resolved_target)
    box1_fret = int(resolved_key.get("box1_fret", 8))

    sorted_notes = sorted(notes, key=lambda n: float(_get_note_field(n, "t", 0.0)))
    N = len(sorted_notes)

    states_per_note: List[List[Tuple[int, int]]] = []
    for n in sorted_notes:
        p = int(_get_note_field(n, "p", 60))
        states_per_note.append(get_candidate_voicings(p, max_string=6, max_fret=24))

    V: List[List[float]] = []
    backpointer: List[List[int]] = []

    n0 = sorted_notes[0]
    b0 = _get_note_field(n0, "bend")
    V0 = [
        state_cost(
            s,
            f,
            int(_get_note_field(n0, "p", 60)),
            float(_get_note_field(n0, "t", 0.0)),
            has_bend=bool(b0),
            bend_semitones=float(b0.get("semitones", 0.0)) if isinstance(b0, dict) else 0.0,
            target_fret=resolved_target,
            box1_fret=box1_fret,
            neck_priors=neck_priors,
        )
        for (s, f) in states_per_note[0]
    ]
    V.append(V0)
    backpointer.append([0] * len(states_per_note[0]))

    for i in range(1, N):
        prev_note = sorted_notes[i - 1]
        curr_note = sorted_notes[i]
        prev_states = states_per_note[i - 1]
        curr_states = states_per_note[i]

        prev_t = float(_get_note_field(prev_note, "t", 0.0))
        curr_t = float(_get_note_field(curr_note, "t", 0.0))
        curr_p = int(_get_note_field(curr_note, "p", 60))
        curr_bend = _get_note_field(curr_note, "bend")
        prev_slide = _get_note_field(prev_note, "slide")

        is_simul = (curr_t - prev_t) < 0.05
        Vi: List[float] = []
        bpi: List[int] = []

        for cs, cf in curr_states:
            sc = state_cost(
                cs,
                cf,
                curr_p,
                curr_t,
                has_bend=bool(curr_bend),
                bend_semitones=float(curr_bend.get("semitones", 0.0)) if isinstance(curr_bend, dict) else 0.0,
                target_fret=resolved_target,
                box1_fret=box1_fret,
                neck_priors=neck_priors,
            )
            best_cost = float("inf")
            best_prev = 0
            for p_idx, (ps, pf) in enumerate(prev_states):
                tc = transition_cost(
                    ps, pf, prev_t, cs, cf, curr_t, is_simultaneous=is_simul, prev_slide=prev_slide
                )
                total = V[i - 1][p_idx] + tc + sc
                if total < best_cost:
                    best_cost = total
                    best_prev = p_idx
            Vi.append(best_cost)
            bpi.append(best_prev)

        V.append(Vi)
        backpointer.append(bpi)

    best_last_idx = int(np.argmin(V[-1]))
    path = [best_last_idx]
    for i in range(N - 1, 0, -1):
        path.append(backpointer[i][path[-1]])
    path.reverse()

    optimized: List[Any] = []
    for i, n in enumerate(sorted_notes):
        s, f = states_per_note[i][path[i]]
        if isinstance(n, dict):
            note_copy = dict(n)
            note_copy["s"] = int(s)
            note_copy["f"] = int(f)
            optimized.append(note_copy)
        else:
            n.s = int(s)
            n.f = int(f)
            optimized.append(n)

    return optimized
