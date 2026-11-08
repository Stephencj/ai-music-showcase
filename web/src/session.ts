// The Create session: a thread of messages (your description, feedback and
// section edits) and the song versions they produced (v1, v2, …). Kept
// client-side and persisted to localStorage — every version is a /generate
// job, and its plan (a GenerateRequest body) is all that's needed to make
// the next one.
import type { ArrangementOptions } from "./api";
import type { Family, JobResult, SectionOverride, SongPlan } from "./types";

export interface SVersion {
  n: number;
  plan: SongPlan;
  jobId: string | null;
  status: "running" | "done" | "error";
  progress: number;
  message: string;
  result?: JobResult;
  error?: string;
  savedAs?: string;            // block name once saved to the library
}

export interface SMsg {
  id: string;
  role: "user" | "app";
  kind?: "pending" | "describe" | "revise" | "section" | "error";
  text?: string;
  chips?: string[];            // "Here's what I understood"
  changes?: string[];          // "Changed N things"
  notes?: string[];
  interpreter?: string;
  version?: number;            // the version this message produced
}

export interface Session {
  title: string;
  interpreter?: string;
  msgs: SMsg[];
  versions: SVersion[];
}

export const EMPTY_SESSION: Session = { title: "", msgs: [], versions: [] };

const KEY = "aimusic.create.session";

export function loadSession(): Session {
  try {
    const v = localStorage.getItem(KEY);
    if (!v) return EMPTY_SESSION;
    const s = JSON.parse(v) as Session;
    return Array.isArray(s.msgs) && Array.isArray(s.versions) ? s : EMPTY_SESSION;
  } catch {
    return EMPTY_SESSION;
  }
}

export function saveSession(s: Session) {
  try { localStorage.setItem(KEY, JSON.stringify(s)); } catch { /* storage full / private mode */ }
}

export const INTERPRETER_NAME: Record<string, string> = {
  claude: "Claude", local: "local AI", rules: "rules",
};

/** A short song title from the first description. */
export function titleFrom(text: string): string {
  const first = text.trim().split(/(?<=[.!?])\s/)[0].replace(/[.!?]+$/, "");
  return first.length > 26 ? first.slice(0, 25).replace(/\s+\S*$/, "") + "…" : first;
}

/** describe_changes lines, a little friendlier to read. */
export function prettyChange(c: string): string {
  return c
    .replace(/^target_lufs: .* → (-?[\d.]+)$/, (_m, v) => `Loudness → ${v} LUFS${Number(v) <= -20 ? " (background)" : ""}`)
    .replace(/^tempo: /, "Tempo: ")
    .replace(/^key: /, "Key: ").replace(/^scale: /, "Scale: ").replace(/^genre: /, "Genre: ")
    .replace(/^lead_patch: /, "Lead voice: ")
    .replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Timeline lanes: the band grouped into parts, and what each part plays in a
// section (from the plan's arrangement variants and section_overrides).
// ---------------------------------------------------------------------------
export type LaneId = "drums" | "bass" | "keys" | "lead" | "strings" | "horns" | "vocals";

export const LANES: { id: LaneId; name: string; hue: string; hueOn: string }[] = [
  { id: "drums", name: "Drums", hue: "#3b3570", hueOn: "#4a3f8c" },
  { id: "bass", name: "Bass", hue: "#1f4a5e", hueOn: "#1f5a73" },
  { id: "keys", name: "Keys", hue: "#4a2f4f", hueOn: "#5a3560" },
  { id: "lead", name: "Lead", hue: "#2f4a3f", hueOn: "#365a4b" },
  { id: "strings", name: "Strings", hue: "#3f4a2a", hueOn: "#4f5e2f" },
  { id: "horns", name: "Horns", hue: "#5e3f1f", hueOn: "#6e4a24" },
  { id: "vocals", name: "Vocals", hue: "#4f2f3a", hueOn: "#603846" },
];

const LEAD_IDS = new Set(["synth_lead", "lead_guitar"]);
const FAMILY_LANE: Record<string, LaneId> = {
  rhythm: "drums", bass: "bass", chord_lead: "keys", brass: "horns",
  woodwind: "horns", strings: "strings", vocal: "vocals",
};

/** Instrument id → lane. */
export function laneMap(families: Family[]): Record<string, LaneId> {
  const m: Record<string, LaneId> = {};
  for (const f of families) {
    for (const i of f.instruments) m[i.id] = LEAD_IDS.has(i.id) ? "lead" : (FAMILY_LANE[f.family] ?? "keys");
  }
  return m;
}

// The arrangement variants, as option chips: a short label and the part they
// change. Variants the server adds later still show (by name) under "+ more".
export const VARIANT_UI: Record<string, { label: string; lane: LaneId }> = {
  soar: { label: "Soar", lane: "strings" },
  pocket_drums: { label: "Pocket drums", lane: "drums" },
  hits_only: { label: "Horn hits", lane: "horns" },
  brushes: { label: "Brushes", lane: "drums" },
  simple_bass: { label: "Simple bass", lane: "bass" },
  calm_keys: { label: "Calm keys", lane: "keys" },
  calm_drums: { label: "Calm drums", lane: "drums" },
  calm_bass: { label: "Calm bass", lane: "bass" },
  pocket_bass: { label: "Pocket bass", lane: "bass" },
  bass_flare: { label: "Bass flare", lane: "bass" },
  horn_bed: { label: "Horn bed", lane: "horns" },
  no_falloff: { label: "Held ending", lane: "horns" },
  string_intro: { label: "String intro", lane: "strings" },
};

export const variantLabel = (v: string) => VARIANT_UI[v]?.label ?? v.replace(/_/g, " ");

export function splitVariants(a: string | undefined | null): string[] {
  return (a || "").replace(/\+/g, ",").split(",").map((x) => x.trim()).filter(Boolean);
}

/** Variants in effect for a section: its own override, else the song's;
 *  shorthand ("calm") expanded into its parts. */
export function sectionVariants(plan: SongPlan, role: string, opts?: ArrangementOptions | null): string[] {
  const ov = plan.section_overrides?.[role];
  const raw = splitVariants(ov?.arrangement != null ? ov.arrangement : plan.arrangement);
  const out: string[] = [];
  for (const v of raw) {
    for (const p of opts?.expands?.[v] ?? [v]) if (!out.includes(p)) out.push(p);
  }
  return out;
}

/** Toggle a variant, keeping one per exclusive group (one per part). */
export function toggleVariant(vs: string[], v: string, opts?: ArrangementOptions | null): string[] {
  if (vs.includes(v)) return vs.filter((x) => x !== v);
  const group = opts?.exclusive?.find((g) => g.includes(v)) ?? [];
  return [...vs.filter((x) => !group.includes(x)), v];
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/** An edit to one section: its arrangement (comma-separated variants), its
 *  energy (null = back to the default) and whether the lead solos. */
export interface SectionEdit { arrangement?: string; energy?: number | null; feature_lead?: boolean }

/** The plan with one section's arrangement / energy / lead changed. An
 *  arrangement equal to the song's drops back to inheriting it. Instruments a
 *  variant needs join the band (as normalize_plan does server-side). */
export function withSectionEdit(plan: SongPlan, role: string, edit: SectionEdit,
  opts: ArrangementOptions | null, defaultBand: string[]): SongPlan {
  const so = { ...(plan.section_overrides || {}) };
  const cur: SectionOverride = { ...(so[role] || {}) };
  if (edit.arrangement !== undefined) {
    const songVs = sectionVariants({ ...plan, section_overrides: {} }, role, opts);
    if (sameSet(splitVariants(edit.arrangement), songVs)) delete cur.arrangement;
    else cur.arrangement = edit.arrangement;
  }
  if ("energy" in edit) { if (edit.energy == null) delete cur.energy; else cur.energy = edit.energy; }
  if ("feature_lead" in edit) { if (!edit.feature_lead) delete cur.feature_lead; else cur.feature_lead = true; }
  if (Object.keys(cur).length) so[role] = cur; else delete so[role];
  const next: SongPlan = { ...plan, section_overrides: so };
  const used = new Set([...splitVariants(next.arrangement),
    ...Object.values(so).flatMap((o) => splitVariants(o.arrangement))]);
  const needs = (opts?.variants ?? []).filter((v) => used.has(v.name)).flatMap((v) => v.needs_instruments);
  if (needs.length) {
    const band = next.instruments?.length ? next.instruments : defaultBand;
    const add = needs.filter((i, k) => !band.includes(i) && needs.indexOf(i) === k);
    if (add.length) next.instruments = [...band, ...add];
  }
  return next;
}

/** What a part plays in a section, as a short cell label ("" = sits out). */
export function cellLabel(lane: LaneId, role: string, vs: string[], plan: SongPlan,
  laneHas: (lane: LaneId) => boolean, funk: boolean): string {
  if (!laneHas(lane)) return "";
  const ov = plan.section_overrides?.[role];
  if (!funk) {
    if (lane === "lead" && ov?.feature_lead) return "solo";
    if (ov?.energy != null) return ov.energy < 0.85 ? "sparse" : ov.energy > 1.1 ? "big" : "on";
    return "on";
  }
  const has = (v: string) => vs.includes(v);
  switch (lane) {
    case "drums": return has("brushes") ? "brushes" : has("pocket_drums") ? "pocket" : has("calm_drums") ? "calm" : "groove";
    case "bass": {
      const b = has("calm_bass") ? "calm" : has("simple_bass") ? "simple" : has("pocket_bass") ? "pocket" : "slap";
      return has("bass_flare") ? b + " +flare" : b;
    }
    case "keys": return has("calm_keys") ? "calm" : "chops";
    case "lead": return has("hits_only") ? "" : ov?.feature_lead ? "solo" : "lead";
    case "horns":
      if (role === "outro") return has("no_falloff") ? "held" : "fall-off";
      if (has("hits_only")) return has("horn_bed") ? "bed" : plan.hits && plan.hits.length === 0 ? "" : "hits";
      return "riffs";
    case "strings":
      if (role === "intro" && has("string_intro")) return "intro run";
      if (!has("soar")) return "pad";
      return ({ intro: "swell", chorus: "soar", outro: "end" } as Record<string, string>)[role] ?? "pad";
    default: return "on";
  }
}

export const SECTION_SHORT: Record<string, string> = {
  intro: "Intro", buildup: "Build", verse: "Verse", prechorus: "Pre", chorus: "Chorus",
  drop: "Drop", bridge: "Brdg", breakdown: "Break", solo: "Solo", outro: "End",
};
export const SECTION_NAME: Record<string, string> = {
  intro: "Intro", buildup: "Buildup", verse: "Verse", prechorus: "Pre-chorus", chorus: "Chorus",
  drop: "Drop", bridge: "Bridge", breakdown: "Breakdown", solo: "Solo", outro: "Outro",
};

export function fmtTime(s: number): string {
  if (!isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}
