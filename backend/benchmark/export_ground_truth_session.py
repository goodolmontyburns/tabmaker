"""
Exports the ground truth Eric Clapton "I'm Tore Down" solo (measures 46-69)
from the official PDF into a valid TabMaker session format.
"""
import os
import json
from typing import Dict, Any
from backend.benchmark.reference_clapton_tab import get_clapton_ground_truth_tab

def save_notes_to_midi(notes: list, midi_path: str):
    try:
        import pretty_midi
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(program=27)  # Electric Guitar (clean)
        for n in notes:
            p = int(n.get("p", 60))
            t_start = float(n.get("t", 0.0))
            t_dur = float(n.get("d", 0.1))
            note = pretty_midi.Note(
                velocity=100,
                pitch=p,
                start=t_start,
                end=t_start + t_dur
            )
            instrument.notes.append(note)
        midi.instruments.append(instrument)
        midi.write(midi_path)
    except Exception as e:
        print(f"MIDI export warning: {e}")

def generate_ground_truth_session(output_dir: str = "temp_uploads/ground_truth") -> Dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    notes = get_clapton_ground_truth_tab()
    
    # Solo duration is 44 seconds (1:19 to 2:03)
    duration = 44.0
    
    midi_path = os.path.join(output_dir, "solo.mid")
    save_notes_to_midi(notes, midi_path)
    
    session_data = {
        "session_id": "ground_truth_clapton",
        "title": "Eric Clapton - I'm Tore Down (Guitar Pro 3 Solo, Measures 45-69)",
        "notes": notes,
        "duration": duration,
        "stems": {},
        "video_analysis": {
            "is_live_guitar": False,
            "mode": "theory_audio",
            "reason": "Ground Truth Human Transcription from Guitar Pro 3 File"
        },
        "original": "/output/benchmark/cropped.wav",
        "guitar_stem": "/output/benchmark/cropped.wav",
        "midi": "/output/ground_truth/solo.mid",
        "key": "C Blues",
        "is_ground_truth": True
    }
    
    json_path = os.path.join(output_dir, "session.json")
    with open(json_path, "w") as f:
        json.dump(session_data, f, indent=2)
        
    return session_data

if __name__ == "__main__":
    session = generate_ground_truth_session()
    print(f"Generated ground truth session with {len(session['notes'])} notes in temp_uploads/ground_truth/session.json")
