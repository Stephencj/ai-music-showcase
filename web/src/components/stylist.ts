// Stylist track — data model for the band's lineup and wardrobe, plus the
// "image" multiplier a well-styled, on-brand band earns on gig payoffs (the
// visual sibling of the producer's production multiplier). Everything is a
// plain catalog of ids so member looks persist compactly in localStorage and
// render as layered SVG (see BandAvatar) — no assets, fully offline.

export type ThemeTag = "street" | "punk" | "glam" | "formal" | "retro";

export const THEME_LABEL: Record<ThemeTag, string> = {
  street: "Street", punk: "Punk", glam: "Glam", formal: "Formal", retro: "Retro",
};

export interface WardrobeItem { id: string; name: string; color?: string; theme?: ThemeTag; }

// Instrument roles a member can hold (drives the little instrument badge).
export const PARTS = ["Vocals", "Guitar", "Bass", "Keys", "Drums"] as const;
export type Part = (typeof PARTS)[number];
export const PART_ICON: Record<string, string> = {
  Vocals: "🎤", Guitar: "🎸", Bass: "🎻", Keys: "🎹", Drums: "🥁",
};

export const SKINS: WardrobeItem[] = [
  { id: "sk1", name: "Porcelain", color: "#f3d2b3" },
  { id: "sk2", name: "Warm", color: "#e0ac7e" },
  { id: "sk3", name: "Tan", color: "#c68642" },
  { id: "sk4", name: "Brown", color: "#8d5524" },
  { id: "sk5", name: "Deep", color: "#5a3620" },
];

// Hair styles map to path generators in BandAvatar (keyed by id).
export const HAIR_STYLES: WardrobeItem[] = [
  { id: "bald", name: "Shaved" },
  { id: "short", name: "Short" },
  { id: "mohawk", name: "Mohawk", theme: "punk" },
  { id: "long", name: "Long", theme: "glam" },
  { id: "bun", name: "Top knot", theme: "street" },
  { id: "afro", name: "Afro", theme: "retro" },
];
export const HAIR_COLORS: WardrobeItem[] = [
  { id: "h-black", name: "Black", color: "#1c1c22" },
  { id: "h-brown", name: "Brown", color: "#4a2c1a" },
  { id: "h-blond", name: "Blond", color: "#d9b06a" },
  { id: "h-red", name: "Auburn", color: "#7a2f1d" },
  { id: "h-pink", name: "Pink", color: "#e85b9c", theme: "punk" },
  { id: "h-blue", name: "Electric", color: "#3aa0ff", theme: "punk" },
  { id: "h-plat", name: "Platinum", color: "#e7e7ee", theme: "glam" },
];

export const TOPS: WardrobeItem[] = [
  { id: "tee", name: "Plain tee", color: "#6b7280" },
  { id: "band-tee", name: "Band tee", color: "#26262e", theme: "street" },
  { id: "leather", name: "Leather jacket", color: "#222026", theme: "punk" },
  { id: "sequin", name: "Sequin top", color: "#b65cff", theme: "glam" },
  { id: "blazer", name: "Blazer", color: "#2b3550", theme: "formal" },
  { id: "denim", name: "Denim jacket", color: "#3f6695", theme: "retro" },
  { id: "hoodie", name: "Hoodie", color: "#c2410c", theme: "street" },
];
export const BOTTOMS: WardrobeItem[] = [
  { id: "jeans", name: "Jeans", color: "#34507a" },
  { id: "ripped", name: "Ripped jeans", color: "#2a3a55", theme: "punk" },
  { id: "leather-pants", name: "Leather pants", color: "#1d1b20", theme: "glam" },
  { id: "slacks", name: "Slacks", color: "#23242b", theme: "formal" },
  { id: "cargos", name: "Cargos", color: "#4a5040", theme: "street" },
  { id: "flares", name: "Flares", color: "#6b3f8c", theme: "retro" },
];
export const SHADES: WardrobeItem[] = [
  { id: "none", name: "None" },
  { id: "round", name: "Round shades", color: "#222", theme: "retro" },
  { id: "wayfarer", name: "Wayfarers", color: "#111", theme: "street" },
  { id: "star", name: "Star shades", color: "#ff3d7f", theme: "glam" },
  { id: "visor", name: "Visor", color: "#10b981", theme: "punk" },
];
export const HATS: WardrobeItem[] = [
  { id: "none", name: "None" },
  { id: "beanie", name: "Beanie", color: "#3b3b46", theme: "street" },
  { id: "fedora", name: "Fedora", color: "#2a2620", theme: "formal" },
  { id: "cap", name: "Snapback", color: "#1f2937", theme: "street" },
  { id: "tophat", name: "Top hat", color: "#15151b", theme: "glam" },
];

export interface Member {
  id: string;
  name: string;
  part: Part;
  skin: string;        // SKINS id
  hair: string;        // HAIR_STYLES id
  hairColor: string;   // HAIR_COLORS id
  top: string;         // TOPS id
  bottom: string;      // BOTTOMS id
  shades: string;      // SHADES id ("none" = bare)
  hat: string;         // HATS id ("none" = none)
}

// A sensible default look (used as the "is this styled?" baseline).
export function defaultMember(part: Part, name: string, seed = 0): Member {
  const pick = <T,>(arr: T[], k: number) => arr[(seed + k) % arr.length];
  return {
    id: `m_${part}_${seed}_${name.replace(/\s+/g, "")}`,
    name, part,
    skin: pick(SKINS, 0).id,
    hair: "short", hairColor: "h-black",
    top: "tee", bottom: "jeans", shades: "none", hat: "none",
  };
}

const find = (arr: WardrobeItem[], id: string) => arr.find((x) => x.id === id);
export const skinOf = (m: Member) => find(SKINS, m.skin)?.color || SKINS[0].color!;
export const hairColorOf = (m: Member) => find(HAIR_COLORS, m.hairColor)?.color || HAIR_COLORS[0].color!;
export const topOf = (m: Member) => find(TOPS, m.top) || TOPS[0];
export const bottomOf = (m: Member) => find(BOTTOMS, m.bottom) || BOTTOMS[0];
export const shadesOf = (m: Member) => find(SHADES, m.shades) || SHADES[0];
export const hatOf = (m: Member) => find(HATS, m.hat) || HATS[0];

// Has the member been dressed beyond the plain default look?
export function isStyled(m: Member): boolean {
  return m.top !== "tee" || m.bottom !== "jeans" || m.shades !== "none"
    || m.hat !== "none" || m.hair !== "short" || m.hairColor !== "h-black";
}

// The theme a member reads as: the most-represented theme tag across worn
// items (null when the look is themeless/plain).
export function dominantTheme(m: Member): ThemeTag | null {
  const tags = [
    find(HAIR_STYLES, m.hair)?.theme, find(HAIR_COLORS, m.hairColor)?.theme,
    topOf(m).theme, bottomOf(m).theme, shadesOf(m).theme, hatOf(m).theme,
  ].filter(Boolean) as ThemeTag[];
  if (!tags.length) return null;
  const count = new Map<ThemeTag, number>();
  for (const t of tags) count.set(t, (count.get(t) || 0) + 1);
  return [...count.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

export interface ImageBreakdown {
  image: number; lineup: number; styled: number; cohesion: number;
  theme: ThemeTag | null; themeShare: number;
}

// The image multiplier (1.0–1.6) a styled lineup earns on gig payoffs:
//   • lineup    — distinct instrument roles covered (a real band, up to 4)
//   • styled    — members dressed beyond the plain default
//   • cohesion  — a shared visual theme across the lineup (on-brand)
export function imageBreakdown(members: Member[]): ImageBreakdown {
  if (!members.length)
    return { image: 1, lineup: 0, styled: 0, cohesion: 0, theme: null, themeShare: 0 };

  const roles = new Set(members.map((m) => m.part));
  const lineup = 0.04 * Math.min(4, roles.size);

  const styledCount = members.filter(isStyled).length;
  const styled = 0.03 * Math.min(4, styledCount);

  const themes = members.map(dominantTheme).filter(Boolean) as ThemeTag[];
  let theme: ThemeTag | null = null, themeShare = 0, cohesion = 0;
  if (themes.length) {
    const count = new Map<ThemeTag, number>();
    for (const t of themes) count.set(t, (count.get(t) || 0) + 1);
    const [top, n] = [...count.entries()].sort((a, b) => b[1] - a[1])[0];
    theme = top; themeShare = n / members.length;
    // Up to +0.25 when the whole (styled) lineup is on one theme.
    cohesion = themeShare >= 0.5 ? 0.25 * themeShare : 0;
  }

  const image = Math.max(1, Math.min(1.6, 1 + lineup + styled + cohesion));
  return { image: Math.round(image * 100) / 100, lineup, styled, cohesion, theme, themeShare };
}
