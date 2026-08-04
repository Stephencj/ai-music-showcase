// Shared band helpers: the Band game (BandScreen) and the main generator both
// use these so a saved band can drive song generation.
import { type Member, PART_INSTRUMENT, normalizeMember } from "./dressup/wardrobe";

export interface SavedBand {
  name: string;
  members: Member[];
}

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

/** Roster → generation params (simple "roster + blended vibe" version):
 *  instruments come from each member's part; the overarching genre is the most
 *  common member genre (null if none set, so the caller keeps its own genre). */
export function bandGenerateParams(members: Member[]): {
  instruments: string[];
  genre: string | null;
} {
  const instruments = Array.from(
    new Set(members.map((m) => PART_INSTRUMENT[m.part]).filter(Boolean)));

  const counts = new Map<string, number>();
  for (const m of members) {
    const g = (m.genre || "").trim();
    if (g) counts.set(g, (counts.get(g) || 0) + 1);
  }
  let genre: string | null = null;
  let best = 0;
  for (const [g, n] of counts) if (n > best) { best = n; genre = g; }

  return { instruments, genre };
}
