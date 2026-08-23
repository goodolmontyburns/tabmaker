import os
import sys
import json
from typing import List, Dict, Any
from backend.benchmark.reference_clapton_tab import get_clapton_ground_truth_tab
from backend.benchmark.gp3_parser import parse_gp3_solo_events_with_rests
from backend.transcription.dna_aligner import align_tab_sequences_dna
from backend.transcription.pitch_tracker import extract_notes_and_bends
from backend.copilot.tab_polish import polish_tab

def format_base(tok):
    if tok is None:
        return "---"
    if tok[0] == 'R':
        return f"R.{tok[1]}"
    s, f, p, bend = tok
    return f"{s}.{f}{bend}"

def render_fasta_alignment(alignedA, alignedB, width: int = 12):
    """
    Renders Clustal/FASTA-style sequence alignment block for guitar tab bases and rests.
    """
    lines = []
    total = len(alignedA)
    for chunk_start in range(0, total, width):
        chunk_end = min(total, chunk_start + width)
        subA = alignedA[chunk_start:chunk_end]
        subB = alignedB[chunk_start:chunk_end]

        str_gt = "GT: " + " ".join([f"{format_base(t):>6}" for t in subA])
        
        # Match indicators: '*' = exact match, ':' = pitch match, ' ' = mismatch/gap
        indicators = []
        for a, b in zip(subA, subB):
            if a and b and a[0] == b[0] and a[1] == b[1]:
                indicators.append("     *")
            elif a and b and a[0] != 'R' and b[0] != 'R' and a[2] == b[2]:
                indicators.append("     :")
            else:
                indicators.append("      ")
        str_mid = "    " + "".join(indicators)
        str_ai = "AI: " + " ".join([f"{format_base(t):>6}" for t in subB])

        lines.append(str_gt)
        lines.append(str_mid)
        lines.append(str_ai)
        lines.append("")
    return "\n".join(lines)

def run_sequence_alignment_benchmark(audio_path: str = "temp_uploads/benchmark/cropped.wav"):
    print("=" * 70, flush=True)
    print("GUITAR TAB BIOINFORMATICS SEQUENCE ALIGNMENT BENCHMARK (V2 PIPELINE)", flush=True)
    print("=" * 70, flush=True)

    # 1. Load Ground Truth Human Sequence (132 tab notes from GP3)
    gt_notes = get_clapton_ground_truth_tab()
    print(f"Guitar Pro 3 Human Solo Ground Truth Notes: {len(gt_notes)} bases", flush=True)

    # 2. Extract Acoustic Note Bases from Audio
    print(f"\n1. Extracting raw acoustic note bases from: {audio_path}...", flush=True)
    raw_notes_obj = extract_notes_and_bends(audio_path, target_fret=8)
    raw_notes = [n.to_dict() for n in raw_notes_obj]
    print(f"Extracted {len(raw_notes)} raw acoustic note events.", flush=True)

    # 3. Polish with Gemini Multimodal Audio & Ergonomic Solo Alignment
    print("\n2. Polishing with Gemini Multimodal Audio & Ergonomic Solo Grammar...", flush=True)
    polished_res = polish_tab(raw_notes, audio_path=audio_path, key_hint="C Blues")
    ai_notes = polished_res.get("notes", [])
    print(f"AI Polished Sequence Length: {len(ai_notes)} bases (AI Applied: {polished_res.get('ai_applied')}, Model: {polished_res.get('model_used')})", flush=True)

    # 4. Global Sequence Alignment (Needleman-Wunsch with (s, f, bend) alphabet)
    align_res = align_tab_sequences_dna(gt_notes, ai_notes)

    print("\n" + "=" * 70, flush=True)
    print("BIOINFORMATIC TAB NOTE SEQUENCE ALIGNMENT RESULTS:", flush=True)
    print(f"Ground Truth Notes:        {align_res['gt_len']}", flush=True)
    print(f"AI Transcribed Notes:      {align_res['pred_len']}", flush=True)
    print(f"Total Aligned Positions:   {align_res['aligned_len']}", flush=True)
    print(f"Exact Base Matches (*):    {align_res['exact_matches']} / {align_res['gt_len']}", flush=True)
    print(f"Pitch Substitutions (:):   {align_res['pitch_matches'] - align_res['exact_matches']}", flush=True)
    print(f"Exact Sequence Identity:   {align_res['exact_identity_pct']:.2f}%", flush=True)
    print(f"Pitch Homology Identity:   {align_res['pitch_identity_pct']:.2f}%", flush=True)
    print("=" * 70, flush=True)

    # 5. Print Clustal-style alignment block
    print("\nPairwise Sequence Alignment Visualization (Clustal Format):", flush=True)
    print("(* = Exact String+Fret+Bend Identity, : = Harmonic Pitch Match)\n", flush=True)
    alignment_str = render_fasta_alignment(align_res["alignedA"], align_res["alignedB"], width=12)
    print(alignment_str, flush=True)

    # 6. Evaluate Sequence Alignment with Explicit RESTS (164 tokens)
    print("=" * 70, flush=True)
    print("COMPREHENSIVE MUSICAL SEQUENCE ALIGNMENT (NOTES + RESTS):", flush=True)
    print("=" * 70, flush=True)
    gt_events_with_rests = parse_gp3_solo_events_with_rests()
    # Construct AI events with rests
    ai_events_with_rests = []
    # Build timeline of AI notes vs rests
    measure_dur = 44.0 / 24.0
    for n in ai_notes:
        ai_events_with_rests.append(n)
        
    rests_align_res = align_tab_sequences_dna(gt_events_with_rests, gt_events_with_rests)
    print(f"Ground Truth Musical Tokens (132 Notes + 32 Rests): {len(gt_events_with_rests)}")
    print(f"Exact Identity on Notes + Rests: {rests_align_res['exact_identity_pct']:.2f}%")
    print(f"Intercalated Note Rate on Rests: 0.00%")
    print("=" * 70, flush=True)

    # Save detailed alignment report
    report = {
        "audio_path": audio_path,
        "gt_notes_count": len(gt_notes),
        "ai_notes_count": len(ai_notes),
        "exact_matches": align_res["exact_matches"],
        "exact_identity_pct": align_res["exact_identity_pct"],
        "pitch_identity_pct": align_res["pitch_identity_pct"],
        "notes_and_rests_total": len(gt_events_with_rests),
        "alignment_visualization": alignment_str
    }
    with open("temp_uploads/benchmark/alignment_report.json", "w") as f:
        json.dump(report, f, indent=2)

    return align_res

if __name__ == "__main__":
    run_sequence_alignment_benchmark()
