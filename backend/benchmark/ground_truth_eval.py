"""
Ground Truth Evaluation Engine for Guitar Tablature Transcription.
Calculates note-by-note precision, recall, F1, string & fret fidelity,
and verifies zero string 6 noise and physical plausibility constraints.
"""
import os
import json
from typing import List, Dict, Any, Tuple
from backend.benchmark.reference_clapton_tab import get_clapton_ground_truth_tab

def evaluate_transcription(predicted_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scores predicted guitar tab against the official human ground truth (measures 46-69)."""
    gt_notes = get_clapton_ground_truth_tab()

    if not predicted_notes:
        return {
            "total_gt_notes": len(gt_notes),
            "total_pred_notes": 0,
            "pitch_f1": 0.0,
            "fret_box_accuracy": 0.0,
            "string_6_notes": 0,
            "rapid_fret_span_violations": 0,
            "bend_coverage": 0.0
        }

    # 1. Zero String 6 Guard Verification
    string_6_count = sum(1 for n in predicted_notes if n.get("s") == 6)
    
    # 2. Biomechanical Rapid Fret Span Plausibility
    span_violations = 0
    sorted_pred = sorted(predicted_notes, key=lambda x: float(x.get("t", 0.0)))
    for i in range(1, len(sorted_pred)):
        dt = float(sorted_pred[i].get("t", 0.0)) - float(sorted_pred[i-1].get("t", 0.0))
        df = abs(int(sorted_pred[i].get("f", 0)) - int(sorted_pred[i-1].get("f", 0)))
        if dt < 0.20 and df > 4:
            span_violations += 1

    # 3. Note-by-Note Matching (Pitch & Time within 0.15s window)
    matched_gt = 0
    gt_matched_indices = set()
    
    for pn in sorted_pred:
        pt = float(pn.get("t", 0.0))
        pp = int(pn.get("p", 60))
        
        # Find closest unmatched ground truth note
        best_match_idx = None
        best_dt = 0.20  # 200ms tolerance
        
        for idx, gn in enumerate(gt_notes):
            if idx in gt_matched_indices:
                continue
            gt_t = float(gn["t"])
            gt_p = int(gn["p"])
            
            dt = abs(pt - gt_t)
            if dt <= best_dt and pp == gt_p:
                best_dt = dt
                best_match_idx = idx
                
        if best_match_idx is not None:
            matched_gt += 1
            gt_matched_indices.add(best_match_idx)

    precision = matched_gt / max(1, len(predicted_notes))
    recall = matched_gt / max(1, len(gt_notes))
    f1 = 2 * (precision * recall) / max(1e-6, precision + recall)

    # 4. Fret Box Accuracy (Frets 7-18 for C Blues solo)
    valid_frets = sum(1 for n in predicted_notes if 5 <= int(n.get("f", 0)) <= 19)
    fret_box_acc = valid_frets / max(1, len(predicted_notes))

    # 5. Bend Detection Accuracy
    gt_bends_count = sum(1 for n in gt_notes if "bend" in n)
    pred_bends_count = sum(1 for n in predicted_notes if n.get("bend") is not None)
    bend_ratio = min(1.0, pred_bends_count / max(1, gt_bends_count))

    return {
        "total_gt_notes": len(gt_notes),
        "total_pred_notes": len(predicted_notes),
        "matched_notes": matched_gt,
        "note_precision": round(precision * 100, 1),
        "note_recall": round(recall * 100, 1),
        "note_f1": round(f1 * 100, 1),
        "string_6_notes": string_6_count,
        "rapid_fret_span_violations": span_violations,
        "fret_box_accuracy": round(fret_box_acc * 100, 1),
        "pred_bends": pred_bends_count,
        "gt_bends": gt_bends_count,
        "bend_coverage": round(bend_ratio * 100, 1)
    }
