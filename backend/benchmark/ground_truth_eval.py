"""
Ground Truth Evaluation Engine for Guitar Tablature Transcription.
Calculates raw and time-offset-aligned note precision, recall, F1,
DNA sequence pitch/exact identity, bend coverage, impossible-bend checks,
and physical hand-span plausibility constraints.
"""
from typing import List, Dict, Any
from backend.benchmark.reference_clapton_tab import get_clapton_ground_truth_tab
from backend.transcription.dna_aligner import align_tab_sequences_dna


def _match_notes_with_offset(
    gt_notes: List[Dict[str, Any]],
    sorted_pred: List[Dict[str, Any]],
    time_offset: float = 0.0,
    tol: float = 0.20,
) -> int:
    matched_gt = 0
    gt_matched_indices = set()
    for pn in sorted_pred:
        pt = float(pn.get("t", 0.0)) + time_offset
        pp = int(pn.get("p", 60))
        best_match_idx = None
        best_dt = tol
        for idx, gn in enumerate(gt_notes):
            if idx in gt_matched_indices:
                continue
            dt = abs(pt - float(gn["t"]))
            if dt <= best_dt and pp == int(gn["p"]):
                best_dt = dt
                best_match_idx = idx
        if best_match_idx is not None:
            matched_gt += 1
            gt_matched_indices.add(best_match_idx)
    return matched_gt


def evaluate_transcription(predicted_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Scores predicted guitar tab against the official human ground truth (measures 46-69)."""
    gt_notes = get_clapton_ground_truth_tab()

    if not predicted_notes:
        return {
            "total_gt_notes": len(gt_notes),
            "total_pred_notes": 0,
            "matched_notes": 0,
            "note_precision": 0.0,
            "note_recall": 0.0,
            "note_f1": 0.0,
            "aligned_offset_sec": 0.0,
            "aligned_matched_notes": 0,
            "aligned_note_f1": 0.0,
            "dna_pitch_identity_pct": 0.0,
            "dna_exact_identity_pct": 0.0,
            "fret_box_accuracy": 0.0,
            "string_6_notes": 0,
            "rapid_fret_span_violations": 0,
            "impossible_bends": 0,
            "pred_bends": 0,
            "gt_bends": sum(1 for n in gt_notes if "bend" in n),
            "bend_coverage": 0.0,
        }

    string_6_count = sum(1 for n in predicted_notes if n.get("s") == 6)

    span_violations = 0
    sorted_pred = sorted(predicted_notes, key=lambda x: float(x.get("t", 0.0)))
    for i in range(1, len(sorted_pred)):
        dt = float(sorted_pred[i].get("t", 0.0)) - float(sorted_pred[i - 1].get("t", 0.0))
        f1 = int(sorted_pred[i - 1].get("f", 0))
        f2 = int(sorted_pred[i].get("f", 0))
        df = abs(f2 - f1)
        if dt < 0.20 and f1 > 0 and f2 > 0 and df > 4:
            span_violations += 1

    impossible_bends = sum(
        1
        for n in predicted_notes
        if isinstance(n.get("bend"), dict) and float(n["bend"].get("semitones", 0.0)) > 4.0
    )

    matched_raw = _match_notes_with_offset(gt_notes, sorted_pred, time_offset=0.0, tol=0.20)
    precision = matched_raw / max(1, len(predicted_notes))
    recall = matched_raw / max(1, len(gt_notes))
    f1 = 2 * (precision * recall) / max(1e-6, precision + recall)

    # Global slice-offset alignment (-1.0s to +1.0s in 25ms steps)
    best_offset = 0.0
    best_matched = matched_raw
    for step in range(-40, 41):
        off = step * 0.025
        m = _match_notes_with_offset(gt_notes, sorted_pred, time_offset=off, tol=0.20)
        if m > best_matched:
            best_matched = m
            best_offset = off

    a_prec = best_matched / max(1, len(predicted_notes))
    a_rec = best_matched / max(1, len(gt_notes))
    a_f1 = 2 * (a_prec * a_rec) / max(1e-6, a_prec + a_rec)

    dna = align_tab_sequences_dna(gt_notes, sorted_pred)

    valid_frets = sum(1 for n in predicted_notes if 5 <= int(n.get("f", 0)) <= 19)
    fret_box_acc = valid_frets / max(1, len(predicted_notes))

    gt_bends_count = sum(1 for n in gt_notes if "bend" in n)
    pred_bends_count = sum(1 for n in predicted_notes if n.get("bend") is not None)
    bend_ratio = min(1.0, pred_bends_count / max(1, gt_bends_count))

    return {
        "total_gt_notes": len(gt_notes),
        "total_pred_notes": len(predicted_notes),
        "matched_notes": matched_raw,
        "note_precision": round(precision * 100, 1),
        "note_recall": round(recall * 100, 1),
        "note_f1": round(f1 * 100, 1),
        "aligned_offset_sec": round(best_offset, 3),
        "aligned_matched_notes": best_matched,
        "aligned_note_f1": round(a_f1 * 100, 1),
        "dna_pitch_identity_pct": dna["pitch_identity_pct"],
        "dna_exact_identity_pct": dna["exact_identity_pct"],
        "string_6_notes": string_6_count,
        "rapid_fret_span_violations": span_violations,
        "impossible_bends": impossible_bends,
        "fret_box_accuracy": round(fret_box_acc * 100, 1),
        "pred_bends": pred_bends_count,
        "gt_bends": gt_bends_count,
        "bend_coverage": round(bend_ratio * 100, 1),
    }
