"""
Biomechanical Viterbi Dynamic Programming Fingering Optimizer for Guitar Tablature.
Enforces physical hand-span constraints (<= 4 frets), smooth string crossings,
stable position boxes (Box 1: frets 7-11, Box 2: frets 15-18), and forbids String 6 in lead soloing.
"""
import numpy as np

STRING_OFFSETS = {
    1: 64,  # e4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
}

def get_candidate_voicings(pitch, max_string=5, max_fret=22):
    """
    Returns all valid (string, fret) pairs for a given MIDI pitch.
    Restricted to strings 1..max_string (default 5, excluding Low E).
    """
    candidates = []
    for s in range(1, max_string + 1):
        offset = STRING_OFFSETS[s]
        fret = pitch - offset
        if 0 <= fret <= max_fret:
            candidates.append((s, fret))
    # Fallback if no voicing on strings 1..5: allow string 5 or 4 closest
    if not candidates:
        for s in range(1, 6):
            offset = STRING_OFFSETS[s]
            fret = pitch - offset
            if fret >= 0:
                candidates.append((s, fret))
                break
    return candidates

def state_cost(s, f, pitch):
    """
    Static preference cost for voicing (s, f).
    Prefers expressive frets (5-18) over open strings (fret 0) in lead solos.
    Anchors to C Blues boxes (frets 7-11 for mid register, frets 15-18 for high register).
    """
    cost = 0.0
    # Penalty for open strings in lead guitar solos (cannot vibrato or bend)
    if f == 0:
        cost += 8.0
    elif f < 5:
        cost += 4.0  # Slightly penalize low fret stretches in lead mode
        
    # Register-based box preferences
    if pitch >= 78:  # High register (G5 and above) -> Box 2 (frets 15-18)
        if 15 <= f <= 19:
            cost -= 4.0
        else:
            cost += abs(f - 17) * 0.8
    elif pitch >= 63:  # Mid lead register (Eb4 to F5) -> Box 1 (frets 7-11)
        if 7 <= f <= 12:
            cost -= 4.0
        else:
            cost += abs(f - 9) * 0.6
    else:  # Lower lead register (G3 to D4) -> frets 7-10 on D/A strings
        if 5 <= f <= 10:
            cost -= 2.0
            
    return cost

def transition_cost(s1, f1, t1, s2, f2, t2, is_simultaneous=False):
    """
    Calculates biomechanical physical transition cost between consecutive notes.
    """
    dt = max(0.001, t2 - t1)
    df = abs(f2 - f1)
    ds = abs(s2 - s1)
    
    cost = 0.0
    
    # 1. Simultaneous notes (Dyads / Chords)
    if is_simultaneous or dt < 0.05:
        if s1 == s2:
            return 10000.0  # Physically impossible to play two notes on the same string simultaneously
        if df > 3:
            return 500.0 * (df - 3)  # Severe penalty for wide finger splits in dyads
        return ds * 1.5 + df * 2.0
        
    # 2. Rapid sequential notes (dt < 0.25s) -> Strict Hand Span Guard
    if dt < 0.25:
        if df > 4:
            # Physically impossible to stretch > 4 frets at high speed without shifting
            cost += 1000.0 * (df - 4)
        else:
            cost += df * 1.5
        cost += ds * 1.0
    else:
        # 3. Ample time to shift position (dt >= 0.25s)
        # Moderate cost for position shift
        cost += df * 0.4 + ds * 0.5
        
    return cost

def _get_note_field(n, key, default=None):
    if isinstance(n, dict):
        return n.get(key, default)
    return getattr(n, key, default)

def optimize_tab_fingerings(notes, default_box=8):
    """
    Given a list of note events (dicts or NoteEvent objects), finds the globally optimal 
    (string, fret) assignment minimizing hand-span violations, string jumps, and box shifts.
    """
    if not notes:
        return []
        
    # Sort notes by start time
    sorted_notes = sorted(notes, key=lambda n: float(_get_note_field(n, 't', 0.0)))
    N = len(sorted_notes)
    
    # Candidate states for each note
    states_per_note = []
    for n in sorted_notes:
        p = int(_get_note_field(n, 'p', 60))
        candidates = get_candidate_voicings(p, max_string=5, max_fret=22)
        states_per_note.append(candidates)
        
    # Viterbi DP tables
    # V[i][state_idx] = minimum cumulative cost
    # backpointer[i][state_idx] = best prev_state_idx
    V = []
    backpointer = []
    
    # Initialize step 0
    V0 = []
    for (s, f) in states_per_note[0]:
        c = state_cost(s, f, _get_note_field(sorted_notes[0], 'p', 60))
        V0.append(c)
    V.append(V0)
    backpointer.append([0] * len(states_per_note[0]))
    
    # Forward Pass
    for i in range(1, N):
        prev_states = states_per_note[i - 1]
        curr_states = states_per_note[i]
        prev_t = float(_get_note_field(sorted_notes[i - 1], 't', 0.0))
        curr_t = float(_get_note_field(sorted_notes[i], 't', 0.0))
        curr_p = int(_get_note_field(sorted_notes[i], 'p', 60))
        
        is_simul = (curr_t - prev_t) < 0.05
        
        Vi = []
        bpi = []
        
        for c_idx, (cs, cf) in enumerate(curr_states):
            sc = state_cost(cs, cf, curr_p)
            best_cost = float('inf')
            best_prev = 0
            
            for p_idx, (ps, pf) in enumerate(prev_states):
                tc = transition_cost(ps, pf, prev_t, cs, cf, curr_t, is_simultaneous=is_simul)
                total_cost = V[i - 1][p_idx] + tc + sc
                if total_cost < best_cost:
                    best_cost = total_cost
                    best_prev = p_idx
                    
            Vi.append(best_cost)
            bpi.append(best_prev)
            
        V.append(Vi)
        backpointer.append(bpi)
        
    # Backward Pass (Traceback)
    best_last_idx = int(np.argmin(V[-1]))
    path = [best_last_idx]
    
    for i in range(N - 1, 0, -1):
        prev_idx = backpointer[i][path[-1]]
        path.append(prev_idx)
        
    path.reverse()
    
    # Assign optimal (string, fret) to notes
    optimized_notes = []
    for i, n in enumerate(sorted_notes):
        state_idx = path[i]
        s, f = states_per_note[i][state_idx]
        if isinstance(n, dict):
            note_copy = dict(n)
            note_copy['s'] = int(s)
            note_copy['f'] = int(f)
            optimized_notes.append(note_copy)
        else:
            # NoteEvent object or dataclass
            n.s = int(s)
            n.f = int(f)
            optimized_notes.append(n)
        
    return optimized_notes
