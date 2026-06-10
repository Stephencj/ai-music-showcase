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

/**
 * Place notes on string/fret positions for tab.
 *
 * Notes that start together form a chord, and a string can only sound one note
 * at a time — so within each onset group we assign DISTINCT strings, giving the
 * highest note first pick (it "wins" its preferred string; lower tones move to
 * the next-best free string). Otherwise a note can usually be played in several
 * spots, so we pick the one that keeps the fretting hand near where it just was
 * (the line stays in position) while gently preferring lower frets. The melody
 * (top note of each group) anchors the hand for the next group. Notes that
 * can't be voiced on a free string in range are dropped.
 */
export function assignFrets(
  notes: [number, number, number][], // [pitch, start, dur]
  tuning: number[],
  maxFret = 19,
): TabNote[] {
  const EPS = 1e-3; // notes within this many beats count as one strum/chord
  const sorted = [...notes].sort((a, b) => a[1] - b[1]);
  const out: TabNote[] = [];
  let prevFret = 2; // anchor low on the neck at the start
  let i = 0;
  while (i < sorted.length) {
    // Gather the onset group, then voice it highest-pitch first.
    let j = i;
    const start0 = sorted[i][1];
    while (j < sorted.length && Math.abs(sorted[j][1] - start0) <= EPS) j++;
    const group = sorted.slice(i, j).sort((a, b) => b[0] - a[0]);
    const used = new Set<number>();
    let topFret: number | null = null;
    for (const [pitch, start, dur] of group) {
      let best: { string: number; fret: number } | null = null;
      let bestCost = Infinity;
      for (let s = 0; s < tuning.length; s++) {
        if (used.has(s)) continue;                 // string already taken this chord
        const fret = pitch - tuning[s];
        if (fret < 0 || fret > maxFret) continue;
        const cost = Math.abs(fret - prevFret) + fret * 0.1;
        if (cost < bestCost) { bestCost = cost; best = { string: s, fret }; }
      }
      if (!best) continue; // no free in-range string — can't voice this tone
      used.add(best.string);
      if (topFret === null) topFret = best.fret;   // highest note placed first
      out.push({ string: best.string, fret: best.fret, start, dur, pitch });
    }
    if (topFret !== null) prevFret = topFret;       // hand follows the top line
    i = j;
  }
  return out;
}
