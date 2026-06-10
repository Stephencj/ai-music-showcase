// Guitar/bass tablature helpers: identify fretted tracks, pick a tuning, and
// turn a MIDI melody into string+fret positions for the tab lane.
//
// Tunings are listed high-string → low-string (index 0 is the top tab line),
// as MIDI note numbers of each open string.

export const STANDARD_GUITAR = [64, 59, 55, 50, 45, 40]; // e B G D A E
export const STANDARD_BASS = [43, 38, 33, 28];           // G D A E

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

/** A track whose part reads naturally as tab (guitar or bass, not a bassoon). */
export function isFrettedTrack(name: string): boolean {
  return /guitar|\bbass\b/i.test(name) && !/bassoon/i.test(name);
}

export function isBassTrack(name: string): boolean {
  return /\bbass\b/i.test(name) && !/bassoon/i.test(name);
}

/** A guitar (not bass) — the part that reads on the 6-string neck diagram. */
export function isGuitarTrack(name: string): boolean {
  return /guitar/i.test(name);
}

/** A keyboard-family part — the natural default for the piano diagram. */
export function isKeysTrack(name: string): boolean {
  return /piano|keys|keyboard|rhodes|wurli|organ|clav|harpsichord|e\.?\s?piano/i.test(name);
}

export function tuningFor(name: string): number[] {
  return isBassTrack(name) ? STANDARD_BASS : STANDARD_GUITAR;
}

/** String labels top→bottom (the top/highest string lowercased, classic style). */
export function stringLabelsFor(tuning: number[]): string[] {
  return tuning.map((p, i) => {
    const nm = NOTE_NAMES[((p % 12) + 12) % 12];
    return i === 0 ? nm.toLowerCase() : nm;
  });
}

export interface TabNote {
  string: number; // 0 = top (highest) string
  fret: number;
  start: number;  // same unit as the input (beats in, seconds after scaling)
  dur: number;
  pitch: number;
}

interface Pos { string: number; fret: number; }

/** All in-range string/fret spots a pitch can be played on this tuning. */
function positionsFor(pitch: number, tuning: number[], maxFret: number): Pos[] {
  const out: Pos[] = [];
  for (let s = 0; s < tuning.length; s++) {
    const fret = pitch - tuning[s];
    if (fret >= 0 && fret <= maxFret) out.push({ string: s, fret });
  }
  return out;
}

/** Cost of moving the fretting hand between two positions. */
function moveCost(a: Pos, b: Pos): number {
  const df = Math.abs(a.fret - b.fret), ds = Math.abs(a.string - b.string);
  // Fret distance is the main cost (keeps a run in one box); crossing strings
  // is cheap (so the line prefers the next string over a big stretch); jumps
  // beyond a ~4-fret hand span are penalised hard so runs don't lurch around.
  return df + ds * 0.4 + (df > 4 ? (df - 4) * 2 : 0);
}

/**
 * Place notes on string/fret positions for tab — scale-shape aware.
 *
 * The lead line (the top note of each onset) is fretted with a Viterbi pass
 * that minimises total hand movement, so scale runs stay inside a position box
 * and don't make nonsensical stretches/jumps. Notes that start together form a
 * chord (a string sounds one note at a time), so each onset group is voiced
 * across DISTINCT strings around the lead note's chosen position, highest note
 * first. Notes that can't be voiced on a free string in range are dropped.
 */
export function assignFrets(
  notes: [number, number, number][], // [pitch, start, dur]
  tuning: number[],
  maxFret = 19,
): TabNote[] {
  const EPS = 1e-3; // notes within this many beats count as one strum/chord
  const sorted = [...notes].sort((a, b) => a[1] - b[1]);

  // Group simultaneous notes (highest pitch first within a group).
  const groups: [number, number, number][][] = [];
  for (let i = 0; i < sorted.length;) {
    let j = i; const start0 = sorted[i][1];
    while (j < sorted.length && Math.abs(sorted[j][1] - start0) <= EPS) j++;
    groups.push(sorted.slice(i, j).sort((a, b) => b[0] - a[0]));
    i = j;
  }

  // The "lead" of each group is its highest note that can be fretted at all.
  const leadCands = groups.map((g) => {
    for (const [p] of g) {
      const c = positionsFor(p, tuning, maxFret);
      if (c.length) return c;
    }
    return [] as Pos[];
  });

  // Viterbi over the groups that have a frettable lead: pick the lead position
  // path of least total movement (+ a mild pull toward lower frets).
  const order: number[] = [];
  for (let g = 0; g < groups.length; g++) if (leadCands[g].length) order.push(g);
  const dp: number[][] = [], bk: number[][] = [];
  for (let m = 0; m < order.length; m++) {
    const cands = leadCands[order[m]];
    dp[m] = cands.map(() => Infinity); bk[m] = cands.map(() => -1);
    for (let k = 0; k < cands.length; k++) {
      const emit = cands[k].fret * 0.1;
      if (m === 0) { dp[m][k] = emit; continue; }
      const prev = leadCands[order[m - 1]];
      let best = Infinity, bi = 0;
      for (let kp = 0; kp < prev.length; kp++) {
        const v = dp[m - 1][kp] + moveCost(prev[kp], cands[k]);
        if (v < best) { best = v; bi = kp; }
      }
      dp[m][k] = emit + best; bk[m][k] = bi;
    }
  }
  const leadPos: (Pos | null)[] = groups.map(() => null);
  if (order.length) {
    let k = 0, best = Infinity;
    for (let kk = 0; kk < dp[order.length - 1].length; kk++)
      if (dp[order.length - 1][kk] < best) { best = dp[order.length - 1][kk]; k = kk; }
    for (let m = order.length - 1; m >= 0; m--) { leadPos[order[m]] = leadCands[order[m]][k]; k = bk[m][k]; }
  }

  // Voice each group across distinct strings around its lead position.
  const out: TabNote[] = [];
  for (let g = 0; g < groups.length; g++) {
    const ref = leadPos[g] ? leadPos[g]!.fret : 2;
    const used = new Set<number>();
    for (const [pitch, start, dur] of groups[g]) {
      let best: Pos | null = null, bestCost = Infinity;
      for (const p of positionsFor(pitch, tuning, maxFret)) {
        if (used.has(p.string)) continue;          // string already taken this chord
        const cost = Math.abs(p.fret - ref) + p.fret * 0.05;
        if (cost < bestCost) { bestCost = cost; best = p; }
      }
      if (!best) continue;
      used.add(best.string);
      out.push({ string: best.string, fret: best.fret, start, dur, pitch });
    }
  }
  return out;
}
