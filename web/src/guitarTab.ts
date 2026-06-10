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
 * Greedily place each note on a string/fret. A note can usually be played in
 * several spots; we pick the one that keeps the fretting hand near where it
 * just was (so the line stays in one position) while gently preferring lower
 * frets. Notes outside the instrument's range are dropped.
 */
export function assignFrets(
  notes: [number, number, number][], // [pitch, start, dur]
  tuning: number[],
  maxFret = 19,
): TabNote[] {
  const sorted = [...notes].sort((a, b) => a[1] - b[1]);
  let prevFret = 2; // anchor low on the neck at the start
  const out: TabNote[] = [];
  for (const [pitch, start, dur] of sorted) {
    let best: { string: number; fret: number } | null = null;
    let bestCost = Infinity;
    for (let s = 0; s < tuning.length; s++) {
      const fret = pitch - tuning[s];
      if (fret < 0 || fret > maxFret) continue;
      // Stay near the previous hand position; mildly favour lower frets.
      const cost = Math.abs(fret - prevFret) + fret * 0.1;
      if (cost < bestCost) { bestCost = cost; best = { string: s, fret }; }
    }
    if (!best) continue; // unreachable on this neck — skip rather than fake it
    prevFret = best.fret;
    out.push({ string: best.string, fret: best.fret, start, dur, pitch });
  }
  return out;
}
