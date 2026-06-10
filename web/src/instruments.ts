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

// ── Aperture / harmonics ─────────────────────────────────────────────────────
// A valve combo (or slide position) only sets the tube LENGTH; which note you
// get is the harmonic (partial) you lock in with the lip aperture — tighter
// aperture + faster air = higher partial. So the real fingering depends on the
// note's octave, not just its pitch class. We pick, for the actual written
// note, the combo whose harmonic series lands closest to it on a low partial.
const VALVES_BY_DROP = [[], [2], [1], [1, 2], [2, 3], [1, 3], [1, 2, 3]]; // semitone drop → valves
const TRUMPET_F0 = 48;   // written open fundamental ≈ C3 (Bb trumpet)
const TROMBONE_F0 = 34;  // 1st-position fundamental ≈ Bb1 (concert)

function bestHarmonic(note: number, fundamentals: number[]): { idx: number; partial: number } {
  // A combo only "plays" the note if one of its harmonics is within ~a
  // quartertone (the 7th partial is the most off, ~0.35 semitone). Among those,
  // prefer the lowest partial, then the most open combo.
  let best: { idx: number; partial: number; score: number } | null = null;
  let fallback: { idx: number; partial: number; err: number } | null = null;
  for (let idx = 0; idx < fundamentals.length; idx++) {
    const f0 = fundamentals[idx];
    const p = Math.max(2, Math.min(9, Math.round(2 ** ((note - f0) / 12))));
    const err = Math.abs(note - (f0 + 12 * Math.log2(p)));
    if (!fallback || err < fallback.err) fallback = { idx, partial: p, err };
    if (err > 0.5) continue;
    const score = p + idx * 0.1;
    if (!best || score < best.score) best = { idx, partial: p, score };
  }
  const r = best ?? fallback;
  return r ? { idx: r.idx, partial: r.partial } : { idx: 0, partial: 0 };
}

export function trumpetFingering(written: number): { valves: number[]; partial: number } {
  const { idx, partial } = bestHarmonic(written, VALVES_BY_DROP.map((_, d) => TRUMPET_F0 - d));
  return { valves: VALVES_BY_DROP[idx], partial };
}

export function trombonePosition(concert: number): { pos: number; partial: number } {
  const { idx, partial } = bestHarmonic(concert, [0, 1, 2, 3, 4, 5, 6].map((d) => TROMBONE_F0 - d));
  return { pos: idx + 1, partial };
}

/** Lip-opening size + label for a harmonic — tighter (smaller) for higher partials. */
export function apertureFor(partial: number): { ry: number; word: string } {
  if (!partial) return { ry: 6, word: "" };
  return {
    ry: Math.max(1.5, Math.min(7.5, 8 - (partial - 2) * 0.8)),
    word: partial <= 3 ? "open" : partial <= 6 ? "medium" : "tight",
  };
}

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

// ── Section members / voices ─────────────────────────────────────────────────
// A "section" is an ensemble: each chord voice is played by a different member
// instrument, each with its OWN fingering kind + transposition. A solo wind is
// a single monophonic voice. `voiceSpecsFor` returns the per-voice plan,
// ordered top → bottom (highest register first), used to render one fingering
// figure per voice.
export type FingerKind = "valves" | "slide" | "keys";
export interface VoiceSpec { label: string; kind: FingerKind; transpose: number }

export function memberKind(name: string): FingerKind {
  const n = name.toLowerCase();
  if (/trombone/.test(n)) return "slide";
  if (/trumpet|cornet|flugel|tuba|euphonium|\bhorn\b/.test(n)) return "valves";
  return "keys"; // sax, flute, clarinet, oboe, bassoon, etc.
}
function memberSpec(name: string): VoiceSpec {
  return { label: name, kind: memberKind(name), transpose: transposeWritten(name) };
}

// Section → member instruments, top (highest) → bottom.
const SECTIONS: Record<string, string[]> = {
  "brass section": ["Alto Sax", "Trumpet", "Tenor Sax", "Trombone"],
  "woodwind section": ["Flute", "Oboe", "Clarinet", "Bassoon"],
};

/** Per-voice fingering plan for a track: a section's members, or the solo
 *  instrument as a single voice. */
export function voiceSpecsFor(trackName: string): VoiceSpec[] {
  const key = trackName.toLowerCase().trim();
  for (const sec of Object.keys(SECTIONS)) {
    if (key.includes(sec)) return SECTIONS[sec].map(memberSpec);
  }
  return [memberSpec(trackName)];
}

// ── shared ──────────────────────────────────────────────────────────────────
/** Notes (in seconds) sounding at time t — already converted to seconds. */
export function notesAt<T extends { start: number; dur: number }>(notes: T[], t: number): T[] {
  return notes.filter((n) => t >= n.start && t < n.start + n.dur);
}

/** Pull a single member's monophonic line out of a section's voiced chords.
 *  Notes that start together (within ~60ms) form one chord; its distinct
 *  pitches are ranked high→low and voice `voiceIdx` (0 = top of the section)
 *  takes the matching pitch — mirroring how the live diagrams assign voices to
 *  members. Lets an ensemble part be tabbed one instrument at a time. */
export function voiceLine<T extends { pitch: number; start: number; dur: number }>(
  notes: T[], voiceIdx: number, _nVoices: number,
): { pitch: number; start: number; dur: number }[] {
  const sorted = [...notes].sort((a, b) => a.start - b.start);
  const groups: { start: number; notes: T[] }[] = [];
  for (const n of sorted) {
    const g = groups[groups.length - 1];
    if (g && Math.abs(n.start - g.start) <= 0.06) g.notes.push(n);
    else groups.push({ start: n.start, notes: [n] });
  }
  const out: { pitch: number; start: number; dur: number }[] = [];
  for (const g of groups) {
    const seen = new Set<number>();
    const distinct = g.notes.slice().sort((a, b) => b.pitch - a.pitch)
      .filter((n) => (seen.has(n.pitch) ? false : (seen.add(n.pitch), true)));
    const pick = distinct[voiceIdx];
    if (pick) out.push({ pitch: pick.pitch, start: g.start, dur: pick.dur });
  }
  return out;
}
