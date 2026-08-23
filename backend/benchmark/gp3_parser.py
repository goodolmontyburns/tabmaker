import os
import guitarpro
from typing import List, Tuple, Dict, Any
from backend.transcription.pitch_tracker import NoteEvent

STRING_OFFSETS = {
    1: 64,  # e4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40   # E2
}

def parse_gp3_solo(
    gp3_path: str = None,
    track_idx: int = 1,
    start_measure: int = 45,
    end_measure: int = 69,
    pickup_notes_count: int = 2
) -> List[NoteEvent]:
    """
    Parses guitar solo notes from Guitar Pro 3 file with tick-accurate timestamps and durations.
    Measures 45 (pickup) through 69.
    """
    if gp3_path is None:
        gp3_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "reference.gp3"))
    if not os.path.exists(gp3_path):
        alt_path = "/Users/gbaird/Downloads/Eric Clapton - Im Tore Down (ver 2).gp3"
        if os.path.exists(alt_path):
            gp3_path = alt_path
        else:
            raise FileNotFoundError(f"GP3 file not found at {gp3_path}")

    gp_file = guitarpro.parse(gp3_path)
    track = gp_file.tracks[track_idx]
    tempo = gp_file.tempo if gp_file.tempo else 131
    sec_per_tick = (60.0 / tempo) / 960.0

    m45_start_tick = track.measures[start_measure - 1].header.start
    
    note_events: List[NoteEvent] = []
    
    for m_idx in range(start_measure - 1, end_measure):
        m = track.measures[m_idx]
        m_num = m_idx + 1
        
        for voice in m.voices:
            for beat in voice.beats:
                if not beat.notes:
                    continue
                
                # In measure 45 (pickup bar), only take the 2 pickup notes at the end (ticks >= 2400 in measure)
                tick_in_m = beat.start - m.header.start
                if m_num == start_measure and tick_in_m < 2400:
                    continue
                
                # Absolute seconds from start of solo (Measure 45 header start)
                t = max(0.0, (beat.start - m45_start_tick) * sec_per_tick)
                
                dur_ticks = 3840.0 / beat.duration.value
                if beat.duration.isDotted:
                    dur_ticks *= 1.5
                dur_sec = dur_ticks * sec_per_tick
                
                for note in beat.notes:
                    # Check if tie
                    is_tie = hasattr(note.type, "name") and note.type.name == "tie"
                    if is_tie:
                        # Find matching string note to extend duration
                        for prev in reversed(note_events):
                            if prev.s == note.string:
                                prev.d = round(prev.d + dur_sec, 3)
                                break
                        continue
                    
                    s = note.string
                    f = note.value
                    p = STRING_OFFSETS.get(s, 64) + f
                    
                    bend_dict = None
                    if note.effect.bend:
                        # Check bend points
                        bend_points = getattr(note.effect.bend, 'points', [])
                        max_val = max([pt.value for pt in bend_points]) if bend_points else 2
                        semitones = max_val / 2.0  # In GP, 2 = 1 semitone, 4 = 2 semitones (full bend)
                        b_type = "full" if semitones >= 1.5 else "half" if semitones >= 0.75 else "quarter"
                        bend_dict = {
                            "type": b_type,
                            "semitones": round(semitones, 1),
                            "target_pitch": p + int(round(semitones))
                        }
                    
                    note_id = f"gp3_{m_num}_{s}_{f}_{int(t * 1000)}"
                    note_events.append(NoteEvent(
                        id=note_id,
                        p=p,
                        t=round(float(t), 3),
                        d=round(float(max(0.08, dur_sec)), 3),
                        s=s,
                        f=f,
                        vibrato=bool(note.effect.vibrato),
                        bend=bend_dict
                    ))
                    
    return note_events

def parse_gp3_solo_events_with_rests(
    gp3_path: str = None,
    track_idx: int = 1,
    start_measure: int = 45,
    end_measure: int = 69
) -> List[Dict[str, Any]]:
    """
    Extracts the comprehensive musical sequence including both Note events and explicit Rest events.
    """
    if gp3_path is None:
        gp3_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "reference.gp3"))
    if not os.path.exists(gp3_path):
        alt_path = "/Users/gbaird/Downloads/Eric Clapton - Im Tore Down (ver 2).gp3"
        if os.path.exists(alt_path):
            gp3_path = alt_path

    gp_file = guitarpro.parse(gp3_path)
    track = gp_file.tracks[track_idx]
    tempo = gp_file.tempo if gp_file.tempo else 131
    sec_per_tick = (60.0 / tempo) / 960.0
    m45_start_tick = track.measures[start_measure - 1].header.start
    
    events: List[Dict[str, Any]] = []
    
    for m_idx in range(start_measure - 1, end_measure):
        m = track.measures[m_idx]
        m_num = m_idx + 1
        for voice in m.voices:
            for beat in voice.beats:
                tick_in_m = beat.start - m.header.start
                if m_num == start_measure and tick_in_m < 2400:
                    continue
                
                t = max(0.0, (beat.start - m45_start_tick) * sec_per_tick)
                dur_ticks = 3840.0 / beat.duration.value
                if beat.duration.isDotted:
                    dur_ticks *= 1.5
                dur_sec = dur_ticks * sec_per_tick
                
                if beat.notes:
                    for note in beat.notes:
                        is_tie = hasattr(note.type, "name") and note.type.name == "tie"
                        if is_tie:
                            continue
                        s = note.string
                        f = note.value
                        p = STRING_OFFSETS.get(s, 64) + f
                        b = 0.5 if note.effect.bend else 0.0
                        events.append({
                            "type": "note",
                            "measure": m_num,
                            "s": s,
                            "f": f,
                            "p": p,
                            "t": round(float(t), 3),
                            "d": round(float(dur_sec), 3),
                            "bend": {"type": "quarter" if b < 0.75 else "full", "semitones": b, "target_pitch": p + int(b*2)} if b > 0 else None
                        })
                elif hasattr(beat.status, "name") and beat.status.name == "rest":
                    events.append({
                        "type": "rest",
                        "measure": m_num,
                        "token": f"R.{beat.duration.value}",
                        "t": round(float(t), 3),
                        "d": round(float(dur_sec), 3)
                    })
                    
    return events
