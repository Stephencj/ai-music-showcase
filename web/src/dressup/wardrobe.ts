// Dress-up wardrobe — the data model for a band member's look and the full
// catalog of customizable items. SELF-CONTAINED & OFFLINE: no backend, no
// assets — every item is a shape id rendered as layered SVG (see Figure.tsx)
// in a chosen colour, so it works fully client-side and is ready to spin off
// into a standalone app. A "look" is a shape id + colour id per body slot.

export type ThemeTag = "sweet" | "rock" | "sparkle" | "sporty" | "cozy" | "fancy";
export const THEME_LABEL: Record<ThemeTag, string> = {
  sweet: "Sweet", rock: "Rock", sparkle: "Sparkle", sporty: "Sporty", cozy: "Cozy", fancy: "Fancy",
};

export interface Swatch { id: string; name: string; hex: string; }
export interface Shape { id: string; name: string; emoji?: string; theme?: ThemeTag; }

// Bright, kid-friendly palette for clothes/hair/accessories.
export const COLORS: Swatch[] = [
  { id: "red", name: "Red", hex: "#ef4444" },
  { id: "coral", name: "Coral", hex: "#fb7185" },
  { id: "orange", name: "Orange", hex: "#fb923c" },
  { id: "yellow", name: "Yellow", hex: "#facc15" },
  { id: "lime", name: "Lime", hex: "#a3e635" },
  { id: "green", name: "Green", hex: "#34d399" },
  { id: "teal", name: "Teal", hex: "#2dd4bf" },
  { id: "sky", name: "Sky", hex: "#38bdf8" },
  { id: "blue", name: "Blue", hex: "#3b82f6" },
  { id: "indigo", name: "Indigo", hex: "#6366f1" },
  { id: "purple", name: "Purple", hex: "#a855f7" },
  { id: "pink", name: "Pink", hex: "#ec4899" },
  { id: "bubblegum", name: "Bubblegum", hex: "#f9a8d4" },
  { id: "white", name: "White", hex: "#f8fafc" },
  { id: "silver", name: "Silver", hex: "#cbd5e1" },
  { id: "gray", name: "Gray", hex: "#64748b" },
  { id: "black", name: "Black", hex: "#1f2937" },
  { id: "brown", name: "Brown", hex: "#92400e" },
];

export const SKINS: Swatch[] = [
  { id: "sk1", name: "Light", hex: "#ffe0bd" },
  { id: "sk2", name: "Fair", hex: "#f1c27d" },
  { id: "sk3", name: "Olive", hex: "#e0ac69" },
  { id: "sk4", name: "Tan", hex: "#c68642" },
  { id: "sk5", name: "Brown", hex: "#8d5524" },
  { id: "sk6", name: "Deep", hex: "#5a3620" },
];

export const HAIR_COLORS: Swatch[] = [
  { id: "h-black", name: "Black", hex: "#211f26" },
  { id: "h-brown", name: "Brown", hex: "#5a3318" },
  { id: "h-chestnut", name: "Chestnut", hex: "#8a4b2a" },
  { id: "h-blond", name: "Blond", hex: "#e3bd72" },
  { id: "h-ginger", name: "Ginger", hex: "#c2521f" },
  { id: "h-pink", name: "Pink", hex: "#f472b6" },
  { id: "h-purple", name: "Purple", hex: "#a855f7" },
  { id: "h-blue", name: "Blue", hex: "#38bdf8" },
  { id: "h-mint", name: "Mint", hex: "#5eead4" },
  { id: "h-white", name: "Platinum", hex: "#eef0f4" },
];

// Each slot's shapes. "none" entries let a slot be empty. theme tags drive the
// cohesion ("on-brand") bonus in imageBreakdown.
export const HAIR: Shape[] = [
  { id: "short", name: "Short" },
  { id: "buzz", name: "Buzz" },
  { id: "bob", name: "Bob", theme: "sweet" },
  { id: "long", name: "Long", theme: "sweet" },
  { id: "wavy", name: "Wavy", theme: "fancy" },
  { id: "curly", name: "Curly", theme: "sweet" },
  { id: "pony", name: "Ponytail", theme: "sporty" },
  { id: "pigtails", name: "Pigtails", theme: "sweet" },
  { id: "bun", name: "Top bun", theme: "fancy" },
  { id: "braids", name: "Braids", theme: "sweet" },
  { id: "afro", name: "Afro" },
  { id: "mohawk", name: "Mohawk", theme: "rock" },
  { id: "spiky", name: "Spiky", theme: "rock" },
];

export const HATS: Shape[] = [
  { id: "none", name: "None", emoji: "🚫" },
  { id: "beanie", name: "Beanie", emoji: "🧢", theme: "cozy" },
  { id: "cap", name: "Cap", emoji: "🧢", theme: "sporty" },
  { id: "party", name: "Party hat", emoji: "🥳", theme: "sparkle" },
  { id: "crown", name: "Crown", emoji: "👑", theme: "fancy" },
  { id: "flower", name: "Flower", emoji: "🌸", theme: "sweet" },
  { id: "bow", name: "Big bow", emoji: "🎀", theme: "sweet" },
  { id: "tophat", name: "Top hat", emoji: "🎩", theme: "fancy" },
  { id: "cowboy", name: "Cowboy", emoji: "🤠", theme: "rock" },
  { id: "ears", name: "Cat ears", emoji: "🐱", theme: "sweet" },
];

export const GLASSES: Shape[] = [
  { id: "none", name: "None", emoji: "🚫" },
  { id: "round", name: "Round", emoji: "👓" },
  { id: "square", name: "Square", emoji: "🤓" },
  { id: "heart", name: "Hearts", emoji: "😍", theme: "sweet" },
  { id: "star", name: "Stars", emoji: "🤩", theme: "sparkle" },
  { id: "sun", name: "Sunglasses", emoji: "😎", theme: "rock" },
];

export const TOPS: Shape[] = [
  { id: "tee", name: "T-shirt", emoji: "👕" },
  { id: "long", name: "Long sleeve", emoji: "👚", theme: "cozy" },
  { id: "tank", name: "Tank top", emoji: "🎽", theme: "sporty" },
  { id: "hoodie", name: "Hoodie", emoji: "🧥", theme: "cozy" },
  { id: "dress", name: "Dress", emoji: "👗", theme: "sweet" },
  { id: "gown", name: "Sparkle gown", emoji: "✨", theme: "sparkle" },
  { id: "tutu-top", name: "Leotard", emoji: "🩰", theme: "fancy" },
  { id: "jacket", name: "Leather jacket", emoji: "🧥", theme: "rock" },
  { id: "stripes", name: "Striped tee", emoji: "👕", theme: "sweet" },
  { id: "jersey", name: "Sports jersey", emoji: "🏀", theme: "sporty" },
];

export const BOTTOMS: Shape[] = [
  { id: "pants", name: "Pants", emoji: "👖" },
  { id: "jeans", name: "Jeans", emoji: "👖", theme: "rock" },
  { id: "shorts", name: "Shorts", emoji: "🩳", theme: "sporty" },
  { id: "skirt", name: "Skirt", emoji: "👗", theme: "sweet" },
  { id: "tutu", name: "Tutu", emoji: "🩰", theme: "fancy" },
  { id: "leggings", name: "Leggings", emoji: "🦵", theme: "sporty" },
  { id: "none", name: "(dress only)", emoji: "🚫" },
];

export const SHOES: Shape[] = [
  { id: "sneakers", name: "Sneakers", emoji: "👟", theme: "sporty" },
  { id: "boots", name: "Boots", emoji: "🥾", theme: "rock" },
  { id: "sandals", name: "Sandals", emoji: "🩴", theme: "cozy" },
  { id: "flats", name: "Flats", emoji: "🥿", theme: "sweet" },
  { id: "heels", name: "Heels", emoji: "👠", theme: "fancy" },
  { id: "barefoot", name: "Barefoot", emoji: "🦶" },
];

// Boy-only (girls never get facial hair). Coloured with the hair colour.
export const FACIAL_HAIR: Shape[] = [
  { id: "none", name: "None", emoji: "🚫" },
  { id: "stubble", name: "Stubble", theme: "rock" },
  { id: "mustache", name: "Mustache", theme: "rock" },
  { id: "goatee", name: "Goatee", theme: "rock" },
  { id: "beard", name: "Beard", theme: "cozy" },
];

// Reads feminine but available to all (it's a band) — except it pairs with the
// girl body by default.
export const MAKEUP: Shape[] = [
  { id: "none", name: "None", emoji: "🚫" },
  { id: "lips", name: "Lipstick", theme: "fancy" },
  { id: "eyeshadow", name: "Eyeshadow", theme: "sparkle" },
  { id: "glam", name: "Full glam", theme: "sparkle" },
];

export const ACCESSORIES: Shape[] = [
  { id: "none", name: "None", emoji: "🚫" },
  { id: "necklace", name: "Necklace", emoji: "📿", theme: "fancy" },
  { id: "scarf", name: "Scarf", emoji: "🧣", theme: "cozy" },
  { id: "bowtie", name: "Bow tie", emoji: "🎀", theme: "fancy" },
  { id: "wings", name: "Fairy wings", emoji: "🧚", theme: "sparkle" },
  { id: "cape", name: "Cape", emoji: "🦸", theme: "rock" },
  { id: "backpack", name: "Backpack", emoji: "🎒", theme: "sporty" },
  { id: "headphones", name: "Headphones", emoji: "🎧", theme: "rock" },
];

export const PARTS = ["Vocals", "Guitar", "Bass", "Keys", "Drums"] as const;
export type Part = (typeof PARTS)[number];
export const PART_ICON: Record<string, string> = {
  Vocals: "🎤", Guitar: "🎸", Bass: "🎸", Keys: "🎹", Drums: "🥁",
};
// A member's part → the INSTRUMENT_REGISTRY id it contributes to a generated
// song's roster. Keeps the band lineup mapping onto real tracks.
export const PART_INSTRUMENT: Record<Part, string> = {
  Vocals: "vocal_lead",
  Guitar: "electric_guitar_clean",
  Bass: "electric_bass",
  Keys: "piano",
  Drums: "drum_kit",
};

export type BodyType = "girl" | "boy";

export interface Member {
  id: string; name: string; part: Part;
  genre?: string;        // preferred genre preset id (drives band-aware generation)
  body: BodyType;
  skin: string;
  hair: string; hairColor: string;
  hat: string; hatColor: string;
  glasses: string;
  top: string; topColor: string;
  bottom: string; bottomColor: string;
  shoes: string; shoesColor: string;
  accessory: string; accessoryColor: string;
  facialHair: string;    // boy-only; "none" for girls
  makeup: string;
  shirtPhoto?: string;   // data URL printed on the shirt
}

let _seq = 0;
export function newId(): string { return `m${Date.now().toString(36)}${(_seq++).toString(36)}`; }

export function defaultMember(part: Part, name: string, body: BodyType = "girl"): Member {
  return {
    id: newId(), name, part, body,
    skin: "sk2",
    hair: "short", hairColor: "h-brown",
    hat: "none", hatColor: "pink",
    glasses: "none",
    top: "tee", topColor: "sky",
    bottom: "pants", bottomColor: "indigo",
    shoes: "sneakers", shoesColor: "red",
    accessory: "none", accessoryColor: "pink",
    facialHair: "none", makeup: "none",
  };
}

// Coerce any saved/old-shape member into the current model (unknown ids → the
// default for that slot; old "shades" field → glasses). Keeps old localStorage
// looks renderable across model changes.
export function normalizeMember(m: Record<string, unknown> | null | undefined): Member {
  const o = (m || {}) as Record<string, unknown>;
  const part = (PARTS as readonly string[]).includes(o.part as string) ? (o.part as Part) : "Vocals";
  const d = defaultMember(part, typeof o.name === "string" ? o.name : "Member", o.body === "boy" ? "boy" : "girl");
  const ok = (arr: { id: string }[], id: unknown, fb: string) => arr.some((x) => x.id === id) ? (id as string) : fb;
  return {
    ...d,
    id: typeof o.id === "string" ? o.id : d.id,
    genre: typeof o.genre === "string" ? o.genre : undefined,
    skin: ok(SKINS, o.skin, d.skin),
    hair: ok(HAIR, o.hair, d.hair), hairColor: ok(HAIR_COLORS, o.hairColor, d.hairColor),
    hat: ok(HATS, o.hat, d.hat), hatColor: ok(COLORS, o.hatColor, d.hatColor),
    glasses: ok(GLASSES, o.glasses ?? o.shades, d.glasses),
    top: ok(TOPS, o.top, d.top), topColor: ok(COLORS, o.topColor, d.topColor),
    bottom: ok(BOTTOMS, o.bottom, d.bottom), bottomColor: ok(COLORS, o.bottomColor, d.bottomColor),
    shoes: ok(SHOES, o.shoes, d.shoes), shoesColor: ok(COLORS, o.shoesColor, d.shoesColor),
    accessory: ok(ACCESSORIES, o.accessory, d.accessory), accessoryColor: ok(COLORS, o.accessoryColor, d.accessoryColor),
    facialHair: o.body === "boy" ? ok(FACIAL_HAIR, o.facialHair, "none") : "none",
    makeup: ok(MAKEUP, o.makeup, "none"),
    shirtPhoto: typeof o.shirtPhoto === "string" ? o.shirtPhoto : undefined,
  };
}

// ── lookups ─────────────────────────────────────────────────────────────────
const swatch = (arr: Swatch[], id: string) => arr.find((s) => s.id === id);
export const colorHex = (id: string) => swatch(COLORS, id)?.hex || swatch(SKINS, id)?.hex || swatch(HAIR_COLORS, id)?.hex || "#888";
export const skinHex = (m: Member) => swatch(SKINS, m.skin)?.hex || SKINS[0].hex;
export const hairHex = (m: Member) => swatch(HAIR_COLORS, m.hairColor)?.hex || HAIR_COLORS[0].hex;
const shape = (arr: Shape[], id: string) => arr.find((s) => s.id === id);
export const themeOf = (arr: Shape[], id: string) => shape(arr, id)?.theme;

// ── image multiplier (the Stylist's payoff on gig earnings) ──────────────────
export function isStyled(m: Member): boolean {
  const d = defaultMember(m.part, m.name);
  return (["hair", "hat", "glasses", "top", "bottom", "shoes", "accessory",
    "hairColor", "topColor", "bottomColor", "shoesColor", "facialHair", "makeup"] as (keyof Member)[])
    .some((k) => m[k] !== d[k]) || !!m.shirtPhoto;
}

export function dominantTheme(m: Member): ThemeTag | null {
  const tags = [
    themeOf(HAIR, m.hair), themeOf(HATS, m.hat), themeOf(GLASSES, m.glasses),
    themeOf(TOPS, m.top), themeOf(BOTTOMS, m.bottom), themeOf(SHOES, m.shoes),
    themeOf(ACCESSORIES, m.accessory),
  ].filter(Boolean) as ThemeTag[];
  if (!tags.length) return null;
  const c = new Map<ThemeTag, number>();
  for (const t of tags) c.set(t, (c.get(t) || 0) + 1);
  return [...c.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

export interface ImageBreakdown {
  image: number; lineup: number; styled: number; cohesion: number;
  theme: ThemeTag | null; themeShare: number;
}
export function imageBreakdown(members: Member[]): ImageBreakdown {
  if (!members.length) return { image: 1, lineup: 0, styled: 0, cohesion: 0, theme: null, themeShare: 0 };
  const roles = new Set(members.map((m) => m.part));
  const lineup = 0.04 * Math.min(4, roles.size);
  const styled = 0.03 * Math.min(4, members.filter(isStyled).length);
  const themes = members.map(dominantTheme).filter(Boolean) as ThemeTag[];
  let theme: ThemeTag | null = null, themeShare = 0, cohesion = 0;
  if (themes.length) {
    const c = new Map<ThemeTag, number>();
    for (const t of themes) c.set(t, (c.get(t) || 0) + 1);
    const [top, n] = [...c.entries()].sort((a, b) => b[1] - a[1])[0];
    theme = top; themeShare = n / members.length;
    cohesion = themeShare >= 0.5 ? 0.25 * themeShare : 0;
  }
  const image = Math.max(1, Math.min(1.6, 1 + lineup + styled + cohesion));
  return { image: Math.round(image * 100) / 100, lineup, styled, cohesion, theme, themeShare };
}
