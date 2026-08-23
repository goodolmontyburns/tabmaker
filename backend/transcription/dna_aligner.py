import json
from typing import List, Dict, Any, Tuple, Optional

def event_token(n: Any) -> Tuple[Any, Any, int, str]:
    """
    Extracts (string_or_type, fret_or_dur, pitch, bend_flag) from event dict or object.
    Supports both Note events (string, fret, pitch, bend) and Rest events ('R', dur, 0, '').
    """
    if isinstance(n, dict):
        if n.get('is_rest') or n.get('type') == 'rest':
            dur = n.get('d', 0.25)
            return ('R', dur, 0, '')
        s = n.get('s', 1)
        f = n.get('f', 0)
        p = n.get('p', 60)
        b_val = n.get('bend')
        bend = 'b' if b_val else ''
        return (int(s), int(f), int(p), bend)
    else:
        if getattr(n, 'is_rest', False):
            dur = getattr(n, 'duration', 0.25)
            return ('R', dur, 0, '')
        s = getattr(n, 'string', 1)
        f = getattr(n, 'fret', 0)
        p = getattr(n, 'pitch', 60)
        b_val = getattr(n, 'bend', 0.0)
        bend = 'b' if b_val else ''
        return (int(s), int(f), int(p), bend)

def align_tab_sequences_dna(
    gt_events: List[Any], 
    pred_events: List[Any],
    match_reward: int = 2,
    pitch_match_reward: int = 1,
    gap_penalty: int = -1
) -> Dict[str, Any]:
    """
    Global sequence alignment (Needleman-Wunsch) treating guitar tab notes AND rests like DNA sequence.
    Penalizes intercalated notes during rest periods, missed notes, string errors, and pitch errors.
    """
    seqA = [event_token(n) for n in gt_events]
    seqB = [event_token(n) for n in pred_events]

    M, N = len(seqA), len(seqB)
    if M == 0 or N == 0:
        return {
            "gt_len": M,
            "pred_len": N,
            "exact_matches": 0,
            "exact_identity_pct": 0.0,
            "pitch_identity_pct": 0.0,
            "alignedA": [],
            "alignedB": []
        }

    dp = [[0] * (N + 1) for _ in range(M + 1)]
    backtrace = [[0] * (N + 1) for _ in range(M + 1)]

    for i in range(M + 1):
        dp[i][0] = i * gap_penalty
        backtrace[i][0] = 1 # up
    for j in range(N + 1):
        dp[0][j] = j * gap_penalty
        backtrace[0][j] = 2 # left
    backtrace[0][0] = 0

    for i in range(1, M + 1):
        for j in range(1, N + 1):
            tokA = seqA[i - 1]
            tokB = seqB[j - 1]

            # Case 1: Both are Rests
            if tokA[0] == 'R' and tokB[0] == 'R':
                score_match = match_reward
            # Case 2: One is Rest, other is Note (Intercalation / Omission)
            elif tokA[0] == 'R' or tokB[0] == 'R':
                score_match = gap_penalty * 2 # heavy penalty for intercalating note during rest
            # Case 3: Both are Notes - Exact match (String + Fret)
            elif tokA[0] == tokB[0] and tokA[1] == tokB[1]:
                score_match = match_reward
            # Case 4: Pitch match (Harmonic homology across strings)
            elif tokA[2] == tokB[2]:
                score_match = pitch_match_reward
            else:
                score_match = gap_penalty

            score_diag = dp[i - 1][j - 1] + score_match
            score_up   = dp[i - 1][j] + gap_penalty
            score_left = dp[i][j - 1] + gap_penalty

            best_score = max(score_diag, score_up, score_left)
            dp[i][j] = best_score

            if best_score == score_diag:
                backtrace[i][j] = 0
            elif best_score == score_up:
                backtrace[i][j] = 1
            else:
                backtrace[i][j] = 2

    # Traceback
    alignedA, alignedB = [], []
    i, j = M, N
    exact_matches = 0
    pitch_matches = 0

    while i > 0 or j > 0:
        if i > 0 and j > 0 and backtrace[i][j] == 0:
            tokA, tokB = seqA[i - 1], seqB[j - 1]
            alignedA.append(tokA)
            alignedB.append(tokB)
            if tokA[0] == tokB[0] and tokA[1] == tokB[1]:
                exact_matches += 1
                pitch_matches += 1
            elif tokA[0] != 'R' and tokB[0] != 'R' and tokA[2] == tokB[2]:
                pitch_matches += 1
            i -= 1
            j -= 1
        elif i > 0 and backtrace[i][j] == 1:
            alignedA.append(seqA[i - 1])
            alignedB.append(None)
            i -= 1
        else:
            alignedA.append(None)
            alignedB.append(seqB[j - 1])
            j -= 1

    alignedA.reverse()
    alignedB.reverse()

    exact_identity = (exact_matches / max(M, N)) * 100.0
    pitch_identity = (pitch_matches / max(M, N)) * 100.0

    return {
        "gt_len": M,
        "pred_len": N,
        "aligned_len": len(alignedA),
        "exact_matches": exact_matches,
        "pitch_matches": pitch_matches,
        "exact_identity_pct": round(exact_identity, 2),
        "pitch_identity_pct": round(pitch_identity, 2),
        "alignedA": alignedA,
        "alignedB": alignedB
    }
