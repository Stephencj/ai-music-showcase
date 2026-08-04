// The 4-song set list (+ encore). Each slot is a MOOD the band plays: the same
// lineup and genres, shaped by tempo + section energy for its moment in the set.
import type { GenerateBody } from "./types";
import type { Member } from "./dressup/wardrobe";
import { bandGenerateParams } from "./band";

export type SlotId = "opener" | "energy" | "ballad" | "finale" | "encore";
export interface SetSlot { slot: SlotId; blockName?: string; }

export interface SlotDef {
  id: SlotId; label: string; icon: string; blurb: string;
  tempoMult: number; energy: number; resolve: boolean; encore?: boolean;
}

// The four main-set slots, in order.
export const SET_SLOTS: SlotDef[] = [
  { id: "opener", label: "Opener",   icon: "🎬", blurb: "Set the tone",              tempoMult: 1.00, energy: 0.95, resolve: false },
  { id: "energy", label: "Keep it up", icon: "🔥", blurb: "Ride the momentum",       tempoMult: 1.12, energy: 1.10, resolve: false },
  { id: "ballad", label: "Ballad",   icon: "🕯️", blurb: "Slow it down",             tempoMult: 0.66, energy: 0.72, resolve: false },
  { id: "finale", label: "Finale",   icon: "🎆", blurb: "Big finish, sweet resolve", tempoMult: 1.18, energy: 1.18, resolve: true },
];
// The encore — a fifth song the band earns by playing enough gigs.
export const ENCORE: SlotDef =
  { id: "encore", label: "Encore", icon: "⭐", blurb: "Earned by a great career", tempoMult: 1.08, energy: 1.15, resolve: true, encore: true };
export const ENCORE_GIGS = 10;   // gigs before the encore unlocks

// Section roles we shape the energy of; roles absent from a song are ignored.
const ENERGY_ROLES = ["intro", "verse", "prechorus", "chorus", "drop", "bridge", "solo", "breakdown", "outro"];
const LIFT_ROLES = new Set(["chorus", "drop"]);

export interface BaseFeel { genre: string; key: string; scale: string; tempo: number; }

/** Build the generation request for one set slot: the band's roster + genre
 *  blend, with the slot's mood applied as tempo + per-section energy (and a
 *  gentle, low-energy outro for the "sweet resolve" slots). */
export function slotGenerateBody(
  slot: SlotDef, members: Member[], base: BaseFeel,
): GenerateBody {
  const bp = bandGenerateParams(members, true);
  const tempo = Math.round(Math.max(50, Math.min(210, base.tempo * slot.tempoMult)));

  const section_overrides: Record<string, { energy: number }> = {};
  for (const role of ENERGY_ROLES) {
    const e = LIFT_ROLES.has(role) ? Math.min(1.5, slot.energy + 0.1) : slot.energy;
    section_overrides[role] = { energy: Number(e.toFixed(2)) };
  }
  if (slot.resolve) section_overrides["outro"] = { energy: 0.6 };   // sweet resolve

  return {
    genre: bp.genre || base.genre,
    key: base.key, scale: base.scale, tempo,
    seed: null, swing: null,
    instruments: bp.instruments, sections: [],
    section_presets: bp.section_presets,
    section_overrides,
    with_pdf: false, with_stems: false, master_preset: "default",
  };
}

/** Upsert a slot's saved song into the set list. */
export function upsertSlot(list: SetSlot[] | undefined, slot: SlotId, blockName: string): SetSlot[] {
  return [...(list || []).filter((s) => s.slot !== slot), { slot, blockName }];
}
