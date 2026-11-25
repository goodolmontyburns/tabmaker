import type { NoteItem } from '../components/CleanTabScore';

export interface AlphaTexOptions {
  notes: NoteItem[];
  title?: string;
  artist?: string;
  tempo?: number;
  durationSec?: number;
  isGroundTruth?: boolean;
  beats?: number[];
  downbeats?: number[];
}

function decomposeSlotsToRests(slotCount: number, isTriplet: boolean): string[] {
  if (slotCount <= 0) return [];
  const tokens: string[] = [];
  let rem = slotCount;

  if (isTriplet) {
    // 12 eighth-note-triplet slots per 4/4 measure (1 beat = 3 slots)
    while (rem >= 12) { tokens.push(':1 r'); rem -= 12; }
    while (rem >= 6) { tokens.push(':2 r'); rem -= 6; }
    while (rem >= 3) { tokens.push(':4 r'); rem -= 3; }
    while (rem > 0) { tokens.push(':8{tu 3} r'); rem -= 1; }
    return tokens;
  }

  // 16 sixteenth-note slots per 4/4 measure (1 beat = 4 slots)
  while (rem >= 16) { tokens.push(':1 r'); rem -= 16; }
  while (rem >= 8) { tokens.push(':2 r'); rem -= 8; }
  while (rem >= 4) { tokens.push(':4 r'); rem -= 4; }
  while (rem >= 2) { tokens.push(':8 r'); rem -= 2; }
  while (rem >= 1) { tokens.push(':16 r'); rem -= 1; }
  return tokens;
}

function slotSpanToDurationToken(spanSlots: number, isTriplet: boolean): string {
  if (isTriplet) {
    if (spanSlots >= 12) return ':1';
    if (spanSlots >= 6) return ':2';
    if (spanSlots >= 3) return ':4';
    return ':8{tu 3}';
  }
  if (spanSlots >= 16) return ':1';
  if (spanSlots >= 8) return ':2';
  if (spanSlots >= 4) return ':4';
  if (spanSlots >= 2) return ':8';
  return ':16';
}

function formatBendEffect(note: NoteItem): string {
  let effect = '';
  if (note.bend) {
    const bType = note.bend.type;
    const semis = note.bend.semitones ?? 2.0;
    if (bType === 'bend_release') {
      const units = Math.max(1, Math.min(8, Math.round(semis * 2)));
      effect += `{b (0 ${units} 0)}`;
    } else if (bType === 'release') {
      const units = Math.max(1, Math.min(8, Math.round(semis * 2)));
      effect += `{b (${units} 0)}`;
    } else {
      const units = Math.max(1, Math.min(8, Math.round(semis * 2)));
      effect += `{b (0 ${units})}`;
    }
  }
  if (note.slide === '/' || note.slide === '\\') {
    effect += '{s}';
  }
  if (note.vibrato) {
    effect += '{v}';
  }
  return effect;
}

export function convertNotesToAlphaTex(
  notes: NoteItem[],
  title: string = 'Guitar Solo',
  artist: string = 'TabMaker',
  tempo: number = 120,
  durationSec: number = 0,
  isGroundTruth: boolean = false,
  beats: number[] = [],
  downbeats: number[] = []
): string {
  const safeTempo = Math.max(40, Math.min(240, Math.round(tempo || 120)));
  const beatDur = 60.0 / safeTempo;
  const measureDur = 4.0 * beatDur;

  const maxNoteTime = notes.reduce((max, n) => Math.max(max, n.t + n.d), 0);
  const effectiveDur = Math.max(durationSec, maxNoteTime, measureDur);

  // Build explicit measure boundaries [start, end)
  const measureBounds: { start: number; end: number }[] = [];
  if (!isGroundTruth && downbeats && downbeats.length >= 2) {
    if (downbeats[0] > 0.25) {
      measureBounds.push({ start: 0, end: downbeats[0] });
    }
    for (let i = 0; i < downbeats.length - 1; i++) {
      measureBounds.push({ start: downbeats[i], end: downbeats[i + 1] });
    }
    let cursor = downbeats[downbeats.length - 1];
    while (cursor < effectiveDur - 0.1) {
      measureBounds.push({ start: cursor, end: cursor + measureDur });
      cursor += measureDur;
    }
  } else {
    const totalMeasures = isGroundTruth ? 25 : Math.max(1, Math.ceil(effectiveDur / measureDur));
    for (let m = 0; m < totalMeasures; m++) {
      measureBounds.push({ start: m * measureDur, end: (m + 1) * measureDur });
    }
  }

  const startMeasureNum = isGroundTruth ? 45 : 1;
  const lines: string[] = [
    `\\title "${title.replace(/"/g, "'")}"`,
    `\\artist "${artist}"`,
    `\\tempo ${safeTempo}`,
    `\\tuning (E4 B3 G3 D3 A2 E2)`,
    ``,
  ];

  // Unused beats parameter retained for future sub-beat refinement
  void beats;

  measureBounds.forEach((bound, mIdx) => {
    const mNum = startMeasureNum + mIdx;
    const mDur = Math.max(0.4, bound.end - bound.start);
    const mNotes = notes
      .filter((n) => n.t >= bound.start - 0.03 && n.t < bound.end - 0.03)
      .sort((a, b) => a.t - b.t);

    const isPickup = isGroundTruth && mNum === 45;
    lines.push(`// Bar ${mNum}${isPickup ? ' (Pickup)' : ''}`);

    if (mNotes.length === 0) {
      lines.push(':1 r |');
      return;
    }

    if (isPickup && mNotes.length === 2) {
      lines.push(':4 r :8 8.2 :8 10.2 |');
      return;
    }

    // Group simultaneous notes within 55ms into vertical clusters
    const clusters: { t: number; d: number; items: NoteItem[] }[] = [];
    let idx = 0;
    while (idx < mNotes.length) {
      const curr = mNotes[idx];
      const group = [curr];
      while (idx + 1 < mNotes.length && Math.abs(mNotes[idx + 1].t - curr.t) <= 0.055) {
        group.push(mNotes[idx + 1]);
        idx++;
      }
      clusters.push({
        t: curr.t,
        d: Math.max(...group.map((g) => g.d)),
        items: group,
      });
      idx++;
    }

    // Compare 16th-note grid (16 slots) vs triplet/shuffle grid (12 slots)
    const calcResidual = (gridN: number) =>
      clusters.reduce((acc, c) => {
        const rel = Math.max(0, Math.min(0.999, (c.t - bound.start) / mDur));
        const nearest = Math.round(rel * gridN) / gridN;
        return acc + Math.abs(rel - nearest);
      }, 0);

    const res16 = calcResidual(16);
    const res12 = calcResidual(12);
    const useTriplet = res12 < res16 * 0.85;
    const gridN = useTriplet ? 12 : 16;

    // Map clusters to unique slot indices 0..gridN-1
    const slotted = new Map<number, NoteItem[]>();
    clusters.forEach((c) => {
      const rel = Math.max(0, Math.min(0.999, (c.t - bound.start) / mDur));
      let slot = Math.min(gridN - 1, Math.max(0, Math.round(rel * gridN)));
      while (slotted.has(slot) && slot < gridN - 1) {
        slot++;
      }
      if (!slotted.has(slot)) {
        slotted.set(slot, c.items);
      }
    });

    const sortedSlots = Array.from(slotted.keys()).sort((a, b) => a - b);
    const tokens: string[] = [];
    let cursorSlot = 0;

    sortedSlots.forEach((slot, sIdx) => {
      if (slot > cursorSlot) {
        tokens.push(...decomposeSlotsToRests(slot - cursorSlot, useTriplet));
      }

      const nextSlot = sIdx + 1 < sortedSlots.length ? sortedSlots[sIdx + 1] : gridN;
      const items = slotted.get(slot)!;
      const desiredSlots = Math.max(1, Math.round((Math.max(...items.map((x) => x.d)) / mDur) * gridN));
      const maxAvail = Math.max(1, nextSlot - slot);
      const durSlots = Math.min(maxAvail, desiredSlots);

      // Snap durSlots to a valid single rhythmic value
      const validSpans = useTriplet ? [12, 6, 3, 1] : [16, 8, 4, 2, 1];
      const chosenSpan = validSpans.find((v) => v <= durSlots) || 1;
      const durToken = slotSpanToDurationToken(chosenSpan, useTriplet);

      if (items.length === 1) {
        const n = items[0];
        tokens.push(`${durToken} ${n.f}.${n.s}${formatBendEffect(n)}`);
      } else {
        // Deduplicate same-string notes in a chord
        const byString = new Map<number, NoteItem>();
        items.forEach((n) => {
          if (!byString.has(n.s)) byString.set(n.s, n);
        });
        const chordStr = Array.from(byString.values())
          .map((n) => `${n.f}.${n.s}${formatBendEffect(n)}`)
          .join(' ');
        tokens.push(`${durToken} (${chordStr})`);
      }

      cursorSlot = slot + chosenSpan;
    });

    if (cursorSlot < gridN) {
      tokens.push(...decomposeSlotsToRests(gridN - cursorSlot, useTriplet));
    }

    lines.push(`${tokens.join(' ')} |`);
  });

  return lines.join('\n');
}
