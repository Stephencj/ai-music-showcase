// Shared band helpers: the Band game (BandScreen) and the main generator both
// use these so a saved band can drive song generation.
import { type Member, type Part, PART_INSTRUMENT, normalizeMember } from "./dressup/wardrobe";

export interface SavedBand {
  name: string;
  members: Member[];
}

// Which section roles each part "leads" — its genre colours these sections when
// blending. The vocalist has none: they set the song's OVERARCHING genre (the
// frontperson's sound), while the instrumentalists flavour their own sections
// (funk bassist grooves the verse, rock guitarist owns the chorus).
export const PART_LEAD_ROLES: Record<Part, string[]> = {
  Vocals: [],
  Bass: ["verse"],
  Guitar: ["chorus", "solo"],
  Keys: ["intro", "bridge", "outro"],
  Drums: ["drop", "breakdown", "prechorus"],
};

const BAND_KEY = "aimusic.band";

/** Load the band saved by the Band game (localStorage), normalized. Returns
 *  null if there's no band or it has no members. */
export function loadSavedBand(): SavedBand | null {
  try {
    const raw = localStorage.getItem(BAND_KEY);
    if (!raw) return null;
    const b = JSON.parse(raw) as { name?: string; members?: unknown[] };
    const members = (b.members || []).map((m) => normalizeMember(m as Record<string, unknown>));
    if (!members.length) return null;
    return { name: typeof b.name === "string" ? b.name : "My Band", members };
  } catch {
    return null;
  }
}

/** Roster → generation params.
 *  - `instruments`: one per member's part.
 *  - `genre` (overarching): the vocalist's genre if set, else the most-common
 *    member genre (null if none, so the caller keeps its own genre).
 *  - `section_presets` (only when `blendBySection`): each instrumentalist's
 *    genre applied to the sections their part leads, so verse/chorus/etc. take
 *    on the individual members' flavours. Roles equal to the base genre are
 *    omitted (the engine would treat them as no-op). */
export function bandGenerateParams(members: Member[], blendBySection = false): {
  instruments: string[];
  genre: string | null;
  section_presets: Record<string, string>;
} {
  const instruments = Array.from(
    new Set(members.map((m) => PART_INSTRUMENT[m.part]).filter(Boolean)));

  // Overarching genre: prefer the vocalist's, else the most common.
  const vocalGenre = members.find(
    (m) => m.part === "Vocals" && (m.genre || "").trim())?.genre?.trim();
  const counts = new Map<string, number>();
  for (const m of members) {
    const g = (m.genre || "").trim();
    if (g) counts.set(g, (counts.get(g) || 0) + 1);
  }
  let common: string | null = null;
  let best = 0;
  for (const [g, n] of counts) if (n > best) { best = n; common = g; }
  const genre = vocalGenre || common;

  const section_presets: Record<string, string> = {};
  if (blendBySection) {
    for (const m of members) {
      const g = (m.genre || "").trim();
      if (!g || g === genre) continue;             // no-op vs the base
      for (const role of PART_LEAD_ROLES[m.part] || []) {
        section_presets[role] = g;                 // later member wins a shared role
      }
    }
  }

  return { instruments, genre, section_presets };
}
