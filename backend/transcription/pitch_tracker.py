from backend.transcription.fingering_optimizer import optimize_tab_fingerings
import os
os.environ["KERAS_HOME"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "temp_uploads", ".keras"))
os.makedirs(os.environ["KERAS_HOME"], exist_ok=True)
import sys
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import librosa
# Standard Guitar Tuning Offsets (Strings 1..6: high E -> low E)
TUNING_OFFSETS = [64, 59, 55, 50, 45]  # E4, B3, G3, D3, A2, E2

@dataclass
class BendInfo:
    type: str  # "full", "half", "bend", "release", "none"
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
        res = {
            "id": self.id,
            "p": int(self.p),
            "t": float(round(self.t, 3)),
            "d": float(round(self.d, 3)),
            "s": int(self.s),
            "f": int(self.f),
            "velocity": float(round(self.velocity, 2)),
            "vibrato": bool(self.vibrato)
        }
        if self.bend:
            res["bend"] = self.bend
        if self.slide:
            res["slide"] = self.slide
        if self.articulation:
            res["articulation"] = self.articulation
        return res

def get_initial_fingering(pitch: int, target_fret: int = 8, prefer_open: bool = False) -> Tuple[int, int]:
    """Computes string and fret for a pitch with target fret proximity bias (favoring blues boxes at frets 8 & 15)."""
    candidates = []
    for s_idx, offset in enumerate(TUNING_OFFSETS):
        fret = pitch - offset
        if 0 <= fret <= 24:
            score = 0
            if prefer_open and fret == 0:
                score += 40
            # Proximity to target fret (favor 8th fret box and 15th fret box)
            if pitch >= 72:
                score -= min(abs(fret - 8), abs(fret - 15)) * 3
            else:
                score -= abs(fret - target_fret) * 2
            # Strongly prefer strings 1, 2, 3 for soloing
            if pitch >= 55 and s_idx in [0, 1, 2]:
                score += 30
            # Strongly disfavor string 5 and 6 for lead solo
            if s_idx in [4, 5]:
                score -= 50
            candidates.append((score, s_idx + 1, fret))
    if not candidates:
        return 1, max(0, min(24, pitch - 64))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return int(candidates[0][1]), int(candidates[0][2])

def detect_bends_in_contour(time_frames: np.ndarray, pitch_contour: np.ndarray, base_pitch: int) -> Optional[Dict[str, Any]]:
    """Analyzes continuous pitch trajectory to detect guitar bends, releases, and vibrato."""
    if len(pitch_contour) < 5 or np.all(np.isnan(pitch_contour)):
        return None
    
    valid_mask = ~np.isnan(pitch_contour)
    if np.sum(valid_mask) < 4:
        return None
        
    times = time_frames[valid_mask]
    pitches = pitch_contour[valid_mask]
    
    if len(pitches) < 4:
        return None

    # Filter extreme outliers
    median_p = np.median(pitches)
    clean_pitches = np.array([p for p in pitches if abs(p - median_p) < 4.0])
    if len(clean_pitches) < 4:
        clean_pitches = pitches

    start_p = np.mean(clean_pitches[:max(1, len(clean_pitches)//4)])
    end_p = np.mean(clean_pitches[-max(1, len(clean_pitches)//4):])
    max_p = np.max(clean_pitches)
    min_p = np.min(clean_pitches)
    
    delta = end_p - start_p
    total_span = max_p - min_p

    # Standard upward bend
    if delta >= 0.75 or (max_p - start_p >= 0.85 and end_p >= start_p + 0.5):
        rise = max_p - start_p
        if 1.6 <= rise <= 2.5:
            bend_type = "full"
            semitones = 2.0
        elif 0.75 <= rise < 1.6:
            bend_type = "half"
            semitones = 1.0
        elif rise > 2.5:
            bend_type = "bend"
            semitones = float(round(rise, 1))
        else:
            bend_type = "bend"
            semitones = float(round(rise, 1))
            
        target_pitch = int(round(base_pitch + semitones))
        return {
            "type": bend_type,
            "semitones": float(semitones),
            "target_pitch": target_pitch
        }

    # Release bend (starts high, drops to base note)
    elif delta <= -0.75:
        drop = abs(delta)
        return {
            "type": "release",
            "semitones": float(round(drop, 1)),
            "target_pitch": int(round(base_pitch))
        }
        
    return None

def quantize_notes_to_grid(notes: List[NoteEvent], bpm: float = 120.0, time_sig: Tuple[int, int] = (4, 4)) -> List[NoteEvent]:
    """Quantizes note timings to 16th note musical grid while preserving expressive nuances."""
    beat_dur = 60.0 / bpm
    grid_unit = beat_dur / 4.0  # 16th note grid
    
    for n in notes:
        quantized_t = round(n.t / grid_unit) * grid_unit
        # Only snap if within 40ms to avoid ruining swing/blues groove
        if abs(quantized_t - n.t) <= 0.045:
            n.t = max(0.0, quantized_t)
        
        quantized_d = round(n.d / grid_unit) * grid_unit
        if quantized_d > 0 and abs(quantized_d - n.d) <= 0.045:
            n.d = quantized_d
        elif n.d < 0.05:
            n.d = 0.1
            
    notes.sort(key=lambda x: x.t)
    return notes

def filter_lead_solo_polyphony(notes: List[NoteEvent], max_concurrent: int = 2) -> List[NoteEvent]:
    """Strictly limits simultaneous voices to max_concurrent (blues lead solo constraint) and prunes bass bleed."""
    if not notes:
        return []
    
    # 1. Prune sub-register bass bleed (notes below E3 / MIDI 52 in a lead guitar solo)
    clean = [n for n in notes if n.p >= 52]
    clean.sort(key=lambda x: x.t)
    
    # 2. Sweep-line concurrent voice limiter
    pruned = []
    for n in clean:
        # Find already added notes that overlap with n
        overlapping = [active for active in pruned if active.t + active.d > n.t + 0.02]
        if len(overlapping) < max_concurrent:
            pruned.append(n)
        else:
            # Rank notes: solo lead range (55..84, strings 1..3), bends, and higher velocity take precedence
            all_candidates = overlapping + [n]
            scored = []
            for c in all_candidates:
                score = c.velocity * 2.0
                if 55 <= c.p <= 84:  # Core guitar solo register (G3 to C6)
                    score += 2.0
                if c.bend:
                    score += 2.5
                if c.d >= 0.15:
                    score += 1.0
                scored.append((score, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            keep_set = set(id(x[1]) for x in scored[:max_concurrent])
            if id(n) in keep_set:
                # Remove the lowest scored active note from pruned
                drop_target = scored[-1][1]
                pruned = [x for x in pruned if id(x) != id(drop_target)]
                pruned.append(n)
                
    pruned.sort(key=lambda x: x.t)
    return pruned

def suppress_harmonic_overtones(notes: List[NoteEvent]) -> List[NoteEvent]:
    """Removes 2nd (octave +12) and 3rd (octave+5th +19) harmonic ghost notes caused by guitar overdrive."""
    if not notes:
        return []
    
    notes.sort(key=lambda x: x.t)
    to_remove = set()
    
    for i, a in enumerate(notes):
        if id(a) in to_remove:
            continue
        for j in range(i + 1, len(notes)):
            b = notes[j]
            if b.t - a.t > 0.06:
                break
            # Check octave overtone (+12) or octave+fifth (+19)
            if (b.p == a.p + 12 or b.p == a.p + 19) and id(b) not in to_remove:
                # b is an overtone of fundamental a
                to_remove.add(id(b))
            elif (a.p == b.p + 12 or a.p == b.p + 19) and id(a) not in to_remove:
                to_remove.add(id(a))
                
    return [n for n in notes if id(n) not in to_remove]

def consolidate_vibrato_fragments(notes: List[NoteEvent], max_gap: float = 0.075) -> List[NoteEvent]:
    """Merges adjacent notes of the same pitch that were fractured by vibrato or wide bends."""
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
        
        # If same pitch (or within bend target) and starting right after prev
        if prev.p == n.p and 0 <= gap <= max_gap:
            # Extend duration of prev
            prev.d = (n.t + n.d) - prev.t
            if n.bend and not prev.bend:
                prev.bend = n.bend
            if n.vibrato:
                prev.vibrato = True
        else:
            merged.append(n)
            
    return merged

def extract_notes_and_bends(audio_path: str, target_fret: int = 8, prefer_open: bool = False, bpm: float = 120.0) -> List[NoteEvent]:
    """High-accuracy extraction of notes, continuous pitch contours, and guitar articulations."""
    if not os.path.exists(audio_path):
        return []

    # 1. Base note detection via Basic Pitch with tuned lead thresholds
    try:
        from basic_pitch.inference import predict
        from basic_pitch import ICASSP_2022_MODEL_PATH
        model_output, midi_data, note_events = predict(
            audio_path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=0.62,
            frame_threshold=0.42,
            minimum_note_length=65.0,
            minimum_frequency=librosa.note_to_hz('C3'),
            maximum_frequency=librosa.note_to_hz('E6')
        )
    except Exception as e:
        print(f"Prediction failed: {e}")
        return []

    if not midi_data or not midi_data.instruments:
        return []

    raw_midi_notes = midi_data.instruments[0].notes
    raw_midi_notes.sort(key=lambda x: x.start)

    # 2. Extract continuous pitch and bends using single vectorized YIN
    note_objects: List[NoteEvent] = []
    try:
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        hop = 256
        f0 = librosa.yin(
            y,
            fmin=librosa.note_to_hz('C3'),
            fmax=librosa.note_to_hz('E6'),
            sr=sr,
            hop_length=hop,
            frame_length=1024
        )
        times = librosa.times_like(f0, sr=sr, hop_length=hop)
        global_midi = librosa.hz_to_midi(f0)
    except Exception as e:
        times = np.array([])
        global_midi = np.array([])

    for idx, mn in enumerate(raw_midi_notes):
        p = int(mn.pitch)
        t_start = float(mn.start)
        t_end = float(mn.end)
        dur = t_end - t_start
        if dur < 0.045:
            continue

        bend_data = None
        vibrato = False

        if len(times) > 0:
            mask = (times >= t_start) & (times <= t_end)
            if np.sum(mask) >= 3:
                sub_times = times[mask]
                sub_pitches = global_midi[mask]
                bend_data = detect_bends_in_contour(sub_times, sub_pitches, base_pitch=p)

                # Check vibrato
                valid_p = sub_pitches[~np.isnan(sub_pitches)]
                if len(valid_p) >= 8:
                    std_dev = np.std(valid_p)
                    if 0.15 <= std_dev <= 0.45:
                        vibrato = True

        s, f = get_initial_fingering(p, target_fret=target_fret, prefer_open=prefer_open)
        
        note_objects.append(NoteEvent(
            id=str(uuid.uuid4())[:8],
            p=p,
            t=t_start,
            d=dur,
            s=s,
            f=f,
            velocity=float(mn.velocity / 127.0 if hasattr(mn, 'velocity') else 0.8),
            bend=bend_data,
            vibrato=vibrato
        ))

    # 3. Clean up lead solo: suppress sub-bass noise (< 52), overtones, limit polyphony, consolidate vibrato
    clean_notes = [n for n in note_objects if n.p >= 52]
    clean_notes = suppress_harmonic_overtones(clean_notes)
    clean_notes = filter_lead_solo_polyphony(clean_notes, max_concurrent=2)
    clean_notes = consolidate_vibrato_fragments(clean_notes, max_gap=0.075)

    # 4. Prune isolated accompaniment notes on strings 4 and 5
    valid_lead = []
    for idx, n in enumerate(clean_notes):
        if n.s in (4, 5):
            has_context = False
            if idx > 0:
                prev_n = clean_notes[idx - 1]
                if abs(n.t - prev_n.t) < 0.40 and prev_n.s in (3, 4, 5):
                    has_context = True
            if idx + 1 < len(clean_notes):
                next_n = clean_notes[idx + 1]
                if abs(next_n.t - n.t) < 0.40 and next_n.s in (3, 4, 5):
                    has_context = True
            if has_context:
                valid_lead.append(n)
        else:
            valid_lead.append(n)
    clean_notes = valid_lead

    # 5. Detect slides between adjacent notes
    for i in range(len(clean_notes) - 1):
        curr_n = clean_notes[i]
        next_n = clean_notes[i+1]
        time_gap = next_n.t - (curr_n.t + curr_n.d)
        if time_gap <= 0.05 and curr_n.s == next_n.s and abs(curr_n.f - next_n.f) in [1, 2, 3, 4]:
            if next_n.f > curr_n.f:
                curr_n.slide = "/"
            else:
                curr_n.slide = "\\"

    clean_notes = quantize_notes_to_grid(clean_notes, bpm=bpm)
    
    # Run Biomechanical Viterbi Optimizer to ensure zero string 6 notes and strict hand-span <= 4
    dict_notes = [n.to_dict() for n in clean_notes]
    optimized_dicts = optimize_tab_fingerings(dict_notes)
    
    final_notes = []
    for i, d in enumerate(optimized_dicts):
        orig_n = clean_notes[i]
        orig_n.s = d['s']
        orig_n.f = d['f']
        final_notes.append(orig_n)
        
    return final_notes
