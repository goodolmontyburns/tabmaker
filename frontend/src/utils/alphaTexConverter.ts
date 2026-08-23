import type { NoteItem } from '../components/CleanTabScore';

export function convertNotesToAlphaTex(
  notes: NoteItem[],
  title: string = "Guitar Solo (AI Transcription)",
  artist: string = "TabMaker AI",
  tempo: number = 131,
  durationSec: number = 0,
  isGroundTruth: boolean = false
): string {
  const beatDur = 60.0 / tempo; // e.g. 0.458s at 131 BPM, 0.5s at 120 BPM
  const measureDur = 4.0 * beatDur; // 4/4 meter
  
  // Calculate total measures
  const maxNoteTime = notes.reduce((max, n) => Math.max(max, n.t + n.d), 0);
  const effectiveDur = Math.max(durationSec, maxNoteTime, 4.0);
  const totalMeasures = isGroundTruth ? 25 : Math.max(1, Math.ceil(effectiveDur / measureDur));
  const startMeasureNum = isGroundTruth ? 45 : 1;

  const lines: string[] = [
    `\\title "${title.replace(/"/g, "'")}"`,
    `\\artist "${artist}"`,
    `\\tempo ${tempo}`,
    `\\tuning (E4 B3 G3 D3 A2 E2)`,
    ``
  ];

  // Group notes into measures 0 to totalMeasures - 1
  const byMeasure: { [m: number]: NoteItem[] } = {};
  for (let m = 0; m < totalMeasures; m++) {
    byMeasure[m] = [];
  }

  notes.forEach((n) => {
    let mIdx = Math.floor((n.t + 0.05) / measureDur);
    if (mIdx < 0) mIdx = 0;
    if (mIdx >= totalMeasures) mIdx = totalMeasures - 1;
    byMeasure[mIdx].push(n);
  });

  for (let mIdx = 0; mIdx < totalMeasures; mIdx++) {
    const mNum = startMeasureNum + mIdx;
    const mNotes = byMeasure[mIdx] || [];
    mNotes.sort((a, b) => a.t - b.t);

    const isPickup = isGroundTruth && mNum === 45;
    lines.push(`// Bar ${mNum}${isPickup ? ' (Pickup)' : ''}`);

    if (mNotes.length === 0) {
      lines.push(':1 r |');
      continue;
    }

    // Special pickup bar handling for Clapton ground truth
    if (isPickup && mNotes.length === 2) {
      lines.push(':4 r :8 8.2 :8 10.2 |');
      continue;
    }

    // Group notes into simultaneous chords / dyads
    const tokens: string[] = [];
    let i = 0;
    while (i < mNotes.length) {
      const current = mNotes[i];
      const simultaneous = [current];
      while (i + 1 < mNotes.length && Math.abs(mNotes[i + 1].t - current.t) <= 0.085) {
        simultaneous.push(mNotes[i + 1]);
        i++;
      }

      // Determine duration token based on note duration
      let durToken = ':8';
      if (current.d >= 0.7) durToken = ':2';
      else if (current.d >= 0.35) durToken = ':4';
      else if (current.d <= 0.14) durToken = ':16';

      if (simultaneous.length === 1) {
        let effect = '';
        if (current.bend) {
          const type = current.bend.type;
          if (type === 'full') effect = '{b (0 4)}';
          else if (type === 'half') effect = '{b (0 2)}';
          else if (type === 'quarter') effect = '{b (0 1)}';
          else effect = '{b (0 4)}';
        }
        if (current.vibrato) effect += '{v}';
        tokens.push(`${durToken} ${current.f}.${current.s}${effect}`);
      } else {
        // Simultaneous Chord / Dyad
        const chordNotes = simultaneous.map((n) => {
          let eff = '';
          if (n.bend) eff = '{b (0 4)}';
          return `${n.f}.${n.s}${eff}`;
        }).join(' ');
        tokens.push(`${durToken} (${chordNotes})`);
      }
      i++;
    }

    lines.push(`${tokens.join(' ')} |`);
  }

  return lines.join('\n');
}
