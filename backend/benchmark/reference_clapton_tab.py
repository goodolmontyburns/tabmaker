"""
Reference Ground Truth Tablature for Eric Clapton - I'm Tore Down Solo (1:19 - 2:03).
Parsed directly from the official Guitar Pro 3 file:
'/Users/gbaird/Downloads/Eric Clapton - Im Tore Down (ver 2).gp3'
Solo begins at the pickup notes at the end of Measure 45 and continues through the end of Measure 69.
"""
import os
import uuid
from typing import List, Dict, Any
from backend.benchmark.gp3_parser import parse_gp3_solo

def get_clapton_ground_truth_tab(gp3_path: str = None) -> List[Dict[str, Any]]:
    """
    Returns the complete list of ground truth note events parsed directly from
    the standard Guitar Pro 3 (GP3) file, starting at the pickup notes at the end
    of measure 45 and concluding at measure 69.
    """
    note_events = parse_gp3_solo(
        gp3_path=gp3_path,
        track_idx=1,
        start_measure=45,
        end_measure=69,
        pickup_notes_count=2
    )
    
    notes_dict = []
    for i, e in enumerate(note_events):
        nd = e.to_dict()
        nd["id"] = f"gt_{i+1:03d}"
        notes_dict.append(nd)
        
    return notes_dict

if __name__ == "__main__":
    gt = get_clapton_ground_truth_tab()
    print(f"Loaded {len(gt)} Ground Truth notes from GP3.")
    print("First 5:", gt[:5])
    print("Last 5:", gt[-5:])
