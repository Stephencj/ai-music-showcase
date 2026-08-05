// ai-music `Member`  ⇄  canonical refined-character (v1)  — TypeScript port
//
// The dress-up creator stores a band as Member[] in localStorage (key
// "dressup.lineup"). This module maps that shape to/from the shared, engine-
// agnostic schema (refined-characters/schema/character.v1.schema.json) so band
// members can flow into the wider character universe — different games/domains
// can't share localStorage, so they exchange canonical JSON instead.
//
// Field names line up almost 1:1 with the reference converter
// (refined-characters/convert/aimusic-member.mjs); the differences here:
//   • `build` maps to the Member's `model` (a body-model id like "boy_slim",
//     which matches the schema's build enum) — not `body` (girl/boy), which is
//     re-derived from the model's gender on import.
//   • ai-music tints facial hair with the hair colour, so facialHair.color is
//     written from / read back into hairColor.
//   • the schema's per-character eyes.color is honoured (Member.eyeColor).
//
// Usage:
//   import { exportBand, importBand } from "./canonical";
//   const json = exportBand(members);           // → clipboard / file / URL
//   const added = importBand(pastedJson);        // → append to the band

import { MODELS, MODEL_IDS, type Gender } from "./models";
import { type Member, type Part, normalizeMember, newId } from "./wardrobe";

// ── Canonical schema (character.v1.schema.json) ─────────────────────────────
export interface Styled {
  style: string;      // catalog style id, or "none"
  color?: string;     // palette token or #RRGGBB hex
}
export interface RefinedCharacter {
  format: "refined-character";
  version: 1;
  id?: string;
  name?: string;
  build: string;      // body model id (see anchors.v1.json / models.ts)
  skin: string;       // palette token (sk1..sk6) or #hex
  eyes?: { color?: string; style?: string };
  hair?: Styled;
  facialHair?: Styled;
  hat?: Styled;
  glasses?: Styled;
  top?: Styled;
  bottom?: Styled;
  shoes?: Styled;
  accessory?: Styled;
  tags?: string[];
  meta?: Record<string, unknown>;
}

// A styled slot: "none"/empty → { style: "none" }; a real style keeps its colour
// when one is given (glasses carry no colour).
const styled = (style: string | undefined, color?: string): Styled =>
  !style || style === "none" ? { style: "none" } : color ? { style, color } : { style };

// ── Member → canonical ──────────────────────────────────────────────────────
export function toCanonical(m: Member): RefinedCharacter {
  return {
    format: "refined-character",
    version: 1,
    ...(m.id ? { id: m.id } : {}),
    ...(m.name ? { name: m.name } : {}),
    build: m.model || (m.body === "boy" ? "boy_slim" : "girl_slim"),
    skin: m.skin,
    eyes: { color: m.eyeColor || "#4a3524", style: "round" },
    hair: styled(m.hair, m.hairColor),
    facialHair: styled(m.facialHair, m.hairColor), // ai-music tints facial hair to hair
    hat: styled(m.hat, m.hatColor),
    glasses: styled(m.glasses),
    top: styled(m.top, m.topColor),
    bottom: styled(m.bottom, m.bottomColor),
    shoes: styled(m.shoes, m.shoesColor),
    accessory: styled(m.accessory, m.accessoryColor),
    tags: m.part ? [`role:${m.part}`] : [],
  };
}

// ── canonical → Member ──────────────────────────────────────────────────────
export function fromCanonical(c: RefinedCharacter): Member {
  const col = (s?: Styled) => (s && s.color) || undefined;
  const sid = (s?: Styled) => (s && s.style) || "none";
  // build is a body-model id; re-derive the girl/boy body from its gender.
  const model = c.build && MODEL_IDS.includes(c.build) ? c.build : undefined;
  const gender: Gender = model ? MODELS[model].gender
    : (typeof c.build === "string" && c.build.startsWith("boy") ? "boy" : "girl");
  const role = (c.tags || []).find((t) => t.startsWith("role:"))?.slice(5);
  return {
    id: c.id || newId(),
    name: c.name || "Member",
    part: (role as Part) || "Vocals",
    body: gender,
    model,
    skin: c.skin,
    eyeColor: c.eyes?.color,
    hair: sid(c.hair), hairColor: col(c.hair) || "h-brown",
    hat: sid(c.hat), hatColor: col(c.hat) || "pink",
    glasses: sid(c.glasses),
    facialHair: sid(c.facialHair),
    top: sid(c.top), topColor: col(c.top) || "sky",
    bottom: sid(c.bottom), bottomColor: col(c.bottom) || "indigo",
    shoes: sid(c.shoes), shoesColor: col(c.shoes) || "red",
    accessory: sid(c.accessory), accessoryColor: col(c.accessory) || "pink",
    makeup: "none",
  };
}

// ── Band-level export / import ──────────────────────────────────────────────

/** Serialise a band as a pretty JSON array of canonical characters. */
export function exportBand(members: Member[]): string {
  return JSON.stringify(members.map(toCanonical), null, 2);
}

/** A one-click link that opens a game with the band pre-loaded via ?band=.
 *  Compact (no pretty-print) to keep the URL short. */
export function exportBandUrl(
  members: Member[],
  base = "https://play.example.com/",
): string {
  const compact = JSON.stringify(members.map(toCanonical));
  return base + "?band=" + encodeURIComponent(compact);
}

/** Parse canonical JSON (an array OR a single object), map each back to a
 *  Member, and run it through normalizeMember so unknown styles/colours fall
 *  back safely to this app's catalog. Throws on invalid JSON. */
export function importBand(json: string): Member[] {
  const parsed = JSON.parse(json);
  const list: unknown[] = Array.isArray(parsed) ? parsed : [parsed];
  return list.map((c) => {
    const member = fromCanonical((c || {}) as RefinedCharacter);
    // normalizeMember validates every slot; keep the raw eyeColor + part it can't
    // vouch for, then let it re-derive a fresh id so imports never collide.
    return normalizeMember({ ...member, id: newId() });
  });
}
