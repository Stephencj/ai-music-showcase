// Registries for the non-string Live diagrams: drum-kit layout, brass valve /
// trombone slide tables, a simplified woodwind key chart, and instrument
// transposition (our MIDI is concert pitch; transposing instruments read in a
// written key, so the fingering follows written = concert + offset).

export type Family = "drums" | "brass" | "woodwind";

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export function noteName(pitch: number): string {
  return NOTE_NAMES[((pitch % 12) + 12) % 12] + (Math.floor(pitch / 12) - 1);
}

/** Family for a track, or null if it isn't one of these. Drums use the flag. */
export function familyFor(name: string, isDrum: boolean): Family | null {
  if (isDrum) return "drums";
  const n = name.toLowerCase();
  if (/trumpet|cornet|flugel|trombone|tuba|euphonium|\bhorn\b|brass/.test(n)) return "brass";
  if (/flute|piccolo|clarinet|oboe|bassoon|\bsax\b|saxophone|recorder|woodwind/.test(n)) return "woodwind";
  return null;
}

/** Semitones to add to a CONCERT MIDI pitch to get the WRITTEN pitch. */
export function transposeWritten(name: string): number {
  const n = name.toLowerCase();
  if (/bari(tone)?\s*sax/.test(n)) return 21;   // Eb, down a 6th + octave
  if (/tenor\s*sax/.test(n)) return 14;         // Bb, down a 9th
  if (/alto\s*sax/.test(n)) return 9;           // Eb, down a 6th
  if (/sopran(o|ino)\s*sax/.test(n)) return 2;  // Bb
  if (/clarinet/.test(n) && !/bass\s*clarinet/.test(n)) return 2; // Bb
  if (/trumpet|cornet|flugel/.test(n)) return 2; // Bb
  if (/\bhorn\b|french\s*horn/.test(n)) return 7; // F
  return 0; // flute, oboe, bassoon, trombone, tuba, piccolo, sections
}

// ── Drums ──────────────────────────────────────────────────────────────────
// Mirror of GM_DRUMS (src/daw_integration/generic/midi_export.py). x/y are in a
// 0..100 box; the kit reads like a seated kit, hand percussion in a lower row.
export interface DrumPad { note: number; label: string; x: number; y: number; r: number; group: "kit" | "perc" }
export const DRUM_LAYOUT: DrumPad[] = [
  // cymbals (top)
  { note: 49, label: "Crash", x: 16, y: 14, r: 11, group: "kit" },
  { note: 51, label: "Ride", x: 82, y: 14, r: 11, group: "kit" },
  { note: 53, label: "Bell", x: 92, y: 26, r: 6, group: "kit" },
  { note: 46, label: "HH open", x: 8, y: 34, r: 8, group: "kit" },
  { note: 42, label: "HH", x: 22, y: 36, r: 8, group: "kit" },
  // toms
  { note: 50, label: "Hi tom", x: 40, y: 24, r: 9, group: "kit" },
  { note: 47, label: "Mid tom", x: 56, y: 24, r: 9, group: "kit" },
  { note: 45, label: "Lo tom", x: 70, y: 40, r: 10, group: "kit" },
  // snare + kick + rim/clap
  { note: 38, label: "Snare", x: 34, y: 52, r: 11, group: "kit" },
  { note: 37, label: "Rim", x: 22, y: 58, r: 5, group: "kit" },
  { note: 39, label: "Clap", x: 48, y: 58, r: 7, group: "kit" },
  { note: 36, label: "Kick", x: 50, y: 78, r: 14, group: "kit" },
  // hand / Latin percussion (lower labelled row)
  { note: 54, label: "Tamb", x: 6, y: 95, r: 6, group: "perc" },
  { note: 56, label: "Cowbl", x: 17, y: 95, r: 6, group: "perc" },
  { note: 60, label: "Bongo H", x: 28, y: 95, r: 6, group: "perc" },
  { note: 61, label: "Bongo L", x: 39, y: 95, r: 6, group: "perc" },
  { note: 63, label: "Conga", x: 50, y: 95, r: 6, group: "perc" },
  { note: 62, label: "C.mute", x: 61, y: 95, r: 6, group: "perc" },
  { note: 64, label: "Conga L", x: 72, y: 95, r: 6, group: "perc" },
  { note: 65, label: "Timb H", x: 83, y: 95, r: 6, group: "perc" },
  { note: 66, label: "Timb L", x: 94, y: 95, r: 6, group: "perc" },
  { note: 75, label: "Clave", x: 6, y: 86, r: 5, group: "perc" },
  { note: 67, label: "Agogo H", x: 16, y: 86, r: 5, group: "perc" },
  { note: 68, label: "Agogo L", x: 26, y: 86, r: 5, group: "perc" },
  { note: 69, label: "Cabasa", x: 36, y: 86, r: 5, group: "perc" },
  { note: 70, label: "Maraca", x: 46, y: 86, r: 5, group: "perc" },
  { note: 73, label: "Guiro S", x: 56, y: 86, r: 5, group: "perc" },
  { note: 74, label: "Guiro L", x: 66, y: 86, r: 5, group: "perc" },
  { note: 76, label: "Wood H", x: 76, y: 86, r: 5, group: "perc" },
  { note: 77, label: "Wood L", x: 86, y: 86, r: 5, group: "perc" },
];

// ── Brass ───────────────────────────────────────────────────────────────────
export function brassKind(name: string): "valves" | "slide" {
  return /trombone/i.test(name) ? "slide" : "valves";
}
// Pressed valves [1..3] per WRITTEN pitch class (standard Bb-trumpet chart).
export const TRUMPET_VALVES: Record<number, number[]> = {
  0: [], 1: [1, 2, 3], 2: [1, 3], 3: [2, 3], 4: [1, 2], 5: [1],
  6: [2], 7: [], 8: [2, 3], 9: [1, 2], 10: [1], 11: [2],
};
// Primary slide position 1..7 per concert pitch class.
export const TROMBONE_SLIDE: Record<number, number> = {
  0: 6, 1: 5, 2: 4, 3: 3, 4: 2, 5: 1, 6: 5, 7: 4, 8: 3, 9: 2, 10: 1, 11: 7,
};

// ── Woodwind (simplified, sax/flute-style) ──────────────────────────────────
// A column of keys top→bottom: octave key, then 6 main tone holes (L1-3, R1-3).
// `closed` lists which hole indices (0..5) are covered for the WRITTEN pitch
// class, and `oct` whether the octave key is added (upper register).
export const WW_KEY_LABELS = ["8va", "L1", "L2", "L3", "R1", "R2", "R3"];
// holes closed for the basic descending scale (C major-ish), pc → hole indices.
const WW_HOLES: Record<number, number[]> = {
  0: [],                    // C  (all open)
  2: [0],                   // D
  4: [0, 1],                // E
  5: [0, 1, 2],             // F
  7: [0, 1, 2, 3],          // G
  9: [0, 1, 2, 3, 4],       // A
  11: [0, 1, 2, 3, 4, 5],   // B
  // accidentals — approximate (nearest natural + a half-hole feel)
  1: [0, 1, 2, 3, 4, 5],    // C#
  3: [0, 1],                // D#/Eb
  6: [0, 1, 2, 3],          // F#
  8: [0, 1, 2, 3, 4],       // G#
  10: [0, 1, 2, 3, 4, 5],   // A#/Bb
};
/** Closed main holes + octave-key flag for a written pitch. */
export function woodwindKeys(written: number): { holes: number[]; oct: boolean } {
  return { holes: WW_HOLES[((written % 12) + 12) % 12] ?? [], oct: written >= 74 };
}

// ── shared ──────────────────────────────────────────────────────────────────
/** Notes (in seconds) sounding at time t — already converted to seconds. */
export function notesAt<T extends { start: number; dur: number }>(notes: T[], t: number): T[] {
  return notes.filter((n) => t >= n.start && t < n.start + n.dur);
}
