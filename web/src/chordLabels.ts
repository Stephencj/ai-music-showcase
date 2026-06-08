// Re-number chords (Roman / Nashville) against any tonic + mode, client-side.
// The detected notes never change — only the degree they're labelled as — so
// the practice chart can show the same progression in any modal context.
// Mirrors the backend conventions in chord_analysis.py for parity.

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const FLAT_TO_SHARP: Record<string, string> = {
  Db: "C#", Eb: "D#", Gb: "F#", Ab: "G#", Bb: "A#", Cb: "B", Fb: "E",
};

export function rootPc(name: string): number {
  const n = FLAT_TO_SHARP[name] ?? name;
  const i = NOTE_NAMES.indexOf(n);
  return i < 0 ? 0 : i;
}

// The seven church modes (semitone sets from the tonic), full modal range.
export const MODES: { id: string; label: string; intervals: number[] }[] = [
  { id: "major", label: "Major (Ionian)", intervals: [0, 2, 4, 5, 7, 9, 11] },
  { id: "dorian", label: "Dorian", intervals: [0, 2, 3, 5, 7, 9, 10] },
  { id: "phrygian", label: "Phrygian", intervals: [0, 1, 3, 5, 7, 8, 10] },
  { id: "lydian", label: "Lydian", intervals: [0, 2, 4, 6, 7, 9, 11] },
  { id: "mixolydian", label: "Mixolydian", intervals: [0, 2, 4, 5, 7, 9, 10] },
  { id: "minor", label: "Minor (Aeolian)", intervals: [0, 2, 3, 5, 7, 8, 10] },
  { id: "locrian", label: "Locrian", intervals: [0, 1, 3, 5, 6, 8, 10] },
];

export const ALL_ROOTS = NOTE_NAMES;

// Map a backend scale name to one of our mode ids (best-effort).
export function scaleToModeId(scale: string): string {
  const s = (scale || "").toLowerCase();
  const hit = MODES.find((m) => m.id === s);
  if (hit) return hit.id;
  if (s.includes("dorian")) return "dorian";
  if (s.includes("phrygian")) return "phrygian";
  if (s.includes("lydian")) return "lydian";
  if (s.includes("mixo")) return "mixolydian";
  if (s.includes("locrian")) return "locrian";
  if (s.includes("min") || s.includes("aeolian")) return "minor";
  return "major";
}

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII"];
const MINOR_QUALITIES = new Set(["min", "min6", "min7", "dim", "dim7", "m7b5"]);
const ROMAN_SUFFIX: Record<string, string> = {
  maj: "", min: "", dim: "°", aug: "+", sus2: "sus2", sus4: "sus4",
  "6": "6", min6: "6", "7": "7", maj7: "maj7", min7: "7", dim7: "°7", m7b5: "ø7",
};

// Scale degree (1-7) + accidental for a semitone offset, within a mode.
// Diatonic notes are plain; chromatic notes spell as a flat of the next degree
// (matching the backend's all-flat convention), except the leading tone below
// the tonic, which reads as a raised 7th.
function degreeOf(rel: number, intervals: number[]): { num: number; acc: string } {
  rel = ((rel % 12) + 12) % 12;
  const idx = intervals.indexOf(rel);
  if (idx >= 0) return { num: idx + 1, acc: "" };
  let lowerIdx = 0;
  for (let i = 0; i < intervals.length; i++) if (intervals[i] < rel) lowerIdx = i;
  const upperIdx = (lowerIdx + 1) % 7;
  if (upperIdx === 0) return { num: lowerIdx + 1, acc: "#" }; // raised 7th
  return { num: upperIdx + 1, acc: "b" };
}

export function romanFor(root: string, quality: string, tonic: string, intervals: number[]): string {
  const rel = (rootPc(root) - rootPc(tonic) + 12) % 12;
  const { num, acc } = degreeOf(rel, intervals);
  const base = ROMAN[num - 1];
  const cased = MINOR_QUALITIES.has(quality) ? base.toLowerCase() : base;
  return acc + cased + (ROMAN_SUFFIX[quality] ?? "");
}

export function nashvilleFor(root: string, quality: string, tonic: string, intervals: number[]): string {
  const rel = (rootPc(root) - rootPc(tonic) + 12) % 12;
  const { num, acc } = degreeOf(rel, intervals);
  let q = "";
  if (MINOR_QUALITIES.has(quality) && !["dim", "dim7", "m7b5"].includes(quality)) q = "m";
  else if (["dim", "dim7", "m7b5"].includes(quality)) q = "°";
  else if (quality === "aug") q = "+";
  let colour = "";
  if (["7", "maj7", "min7"].includes(quality)) colour = "7";
  else if (["6", "min6"].includes(quality)) colour = "6";
  else if (["sus2", "sus4"].includes(quality)) colour = quality;
  return acc + String(num) + q + colour;
}
