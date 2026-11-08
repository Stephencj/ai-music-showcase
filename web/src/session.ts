// The Create session: a thread of messages (your description, feedback and
// section edits) and the song versions they produced (v1, v2, …). Kept on
// the server (/api/sessions) so "New song" archives it into the history
// instead of clearing it; every version is a /generate job, and its plan (a
// GenerateRequest body) is all that's needed to make the next one.
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
  from?: number;               // the version it was made from (Undo goes back to it)
  // Kept by the server:
  block?: string;              // the version's block (auto-saved: it's in Practice)
  audio?: "missing";           // its audio is gone: render it again from plan + seed
  seed?: number;
  changes?: string[];
  interpreter?: string;
}

export interface SMsg {
  id: string;
  role: "user" | "app";
  kind?: "pending" | "describe" | "revise" | "section" | "opened" | "error";
  text?: string;
  chips?: string[];            // "Here's what I understood"
  changes?: string[];          // "Changed N things"
  notes?: string[];
  interpreter?: string;
  version?: number;            // the version this message produced
}

export interface Session {
  id?: string;                 // the server's id (none until the first message)
  title: string;
  interpreter?: string;
  created?: string;
  updated?: string;
  msgs: SMsg[];
  versions: SVersion[];
}

export const EMPTY_SESSION: Session = { title: "", msgs: [], versions: [] };

const LEGACY_KEY = "aimusic.create.session";    // the old browser-only thread
const CURRENT_KEY = "aimusic.create.current";   // the open session's id

/** A thread saved in this browser before sessions moved to the server (to
 *  bring over once), or null. */
export function takeLegacySession(): Session | null {
  try {
    const v = localStorage.getItem(LEGACY_KEY);
    if (!v) return null;
    const s = JSON.parse(v) as Session;
    return Array.isArray(s.msgs) && Array.isArray(s.versions) && s.msgs.length ? s : null;
  } catch {
    return null;
  }
}
export function forgetLegacySession() {
  try { localStorage.removeItem(LEGACY_KEY); } catch { /* private mode */ }
}

export function loadCurrentId(): string | null {
  try { return localStorage.getItem(CURRENT_KEY); } catch { return null; }
}
export function saveCurrentId(id: string | null | undefined) {
  try {
    if (id) localStorage.setItem(CURRENT_KEY, id); else localStorage.removeItem(CURRENT_KEY);
  } catch { /* private mode */ }
}

// Version fields the server owns (its job outcome, block and library links).
const SERVER_OWNED = ["block", "savedAs", "audio", "seed", "changes", "interpreter"] as const;

/** The server's copy of the open session folded into ours: messages and
 *  versions it added (e.g. Claude continuing the thread), and what it knows
 *  about each version — its block, audio, and a job it started (a render). */
export function mergeServer(local: Session, server: Session): Session {
  if (local.id && server.id !== local.id) return local;
  const sv = new Map(server.versions.map((v) => [v.n, v]));
  const versions = local.versions.map((v) => {
    const o = sv.get(v.n);
    if (!o) return v;
    const next: SVersion = { ...v };
    for (const k of SERVER_OWNED) (next as unknown as Record<string, unknown>)[k] = o[k];
    if (o.jobId && o.jobId !== v.jobId) {
      // The server moved it to another job (rendered again, or re-registered).
      Object.assign(next, { jobId: o.jobId, status: o.status, progress: o.progress, message: o.message,
        result: o.result, error: o.error });
    } else if (o.status !== "running" && (o.status !== v.status || o.audio !== v.audio)) {
      Object.assign(next, { status: o.status, result: o.result ?? v.result, error: o.error });
    }
    return next;
  });
  const have = new Set(local.versions.map((v) => v.n));
  const mine = new Set(local.msgs.map((m) => m.id));
  return {
    ...local,
    id: server.id, created: server.created, updated: server.updated,
    msgs: [...local.msgs, ...server.msgs.filter((m) => !mine.has(m.id))],
    versions: [...versions, ...server.versions.filter((v) => !have.has(v.n))].sort((a, b) => a.n - b.n),
  };
}

export const INTERPRETER_NAME: Record<string, string> = {
  claude: "Claude", local: "local AI", rules: "rules",
};

/** A short song title from the first description: cut at a word, no "…"
 *  (it names the version's blocks: "<title> v2"). */
export function titleFrom(text: string): string {
  const first = text.trim().split(/(?<=[.!?])\s/)[0].replace(/[.!?]+$/, "").replace(/…|\.{3,}/g, " ").trim();
  if (first.length <= 32) return first;
  const cut = first.slice(0, 33);
  return (cut.includes(" ") ? cut.replace(/\s+\S*$/, "") : first.slice(0, 32)).replace(/[\s.,;:–—-]+$/, "");
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
export type LaneId = "drums" | "bass" | "keys" | "lead" | "strings" | "horns" | "choir" | "vocals";

export const LANES: { id: LaneId; name: string; hue: string; hueOn: string }[] = [
  { id: "drums", name: "Drums", hue: "#3b3570", hueOn: "#4a3f8c" },
  { id: "bass", name: "Bass", hue: "#1f4a5e", hueOn: "#1f5a73" },
  { id: "keys", name: "Keys", hue: "#4a2f4f", hueOn: "#5a3560" },
  { id: "lead", name: "Lead", hue: "#2f4a3f", hueOn: "#365a4b" },
  { id: "strings", name: "Strings", hue: "#3f4a2a", hueOn: "#4f5e2f" },
  { id: "horns", name: "Horns", hue: "#5e3f1f", hueOn: "#6e4a24" },
  { id: "choir", name: "Choir", hue: "#2f3f5e", hueOn: "#374a70" },
  { id: "vocals", name: "Vocals", hue: "#4f2f3a", hueOn: "#603846" },
];

// Instruments with a lane of their own, whatever their family (the choir
// "aah" pad is a chord_lead instrument, but it's a part of its own).
const OWN_LANE: Record<string, LaneId> = { synth_lead: "lead", lead_guitar: "lead", choir: "choir" };
const FAMILY_LANE: Record<string, LaneId> = {
  rhythm: "drums", bass: "bass", chord_lead: "keys", brass: "horns",
  woodwind: "horns", strings: "strings", vocal: "vocals",
};

/** Instrument id → lane. */
export function laneMap(families: Family[]): Record<string, LaneId> {
  const m: Record<string, LaneId> = {};
  for (const f of families) {
    for (const i of f.instruments) m[i.id] = OWN_LANE[i.id] ?? FAMILY_LANE[f.family] ?? "keys";
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
  falloff: { label: "Trumpet fall-off", lane: "horns" },
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

// ---------------------------------------------------------------------------
// Timeline edits that silence things: a part everywhere, a part in one
// section (a per-section instrument mask) or a whole section.
// ---------------------------------------------------------------------------
export const bandOf = (plan: SongPlan, defaultBand: string[]) =>
  plan.instruments?.length ? plan.instruments : defaultBand;

/** The plan without a part's instruments. Variants that need them go too
 *  (else they'd bring them back), and section masks drop them. */
export function withoutInstruments(plan: SongPlan, ids: string[], opts: ArrangementOptions | null,
  defaultBand: string[]): { plan: SongPlan; dropped: string[] } {
  const gone = new Set(ids);
  const needy = new Set((opts?.variants ?? []).filter((v) => v.needs_instruments.some((i) => gone.has(i))).map((v) => v.name));
  const dropped = new Set<string>();
  const keep = (a: string | undefined) => {
    const vs = splitVariants(a);
    vs.filter((v) => needy.has(v)).forEach((v) => dropped.add(v));
    return vs.filter((v) => !needy.has(v)).join(",");
  };
  const next: SongPlan = { ...plan, instruments: bandOf(plan, defaultBand).filter((i) => !gone.has(i)) };
  if (plan.arrangement != null) next.arrangement = keep(plan.arrangement);
  const so: Record<string, SectionOverride> = {};
  for (const [role, o] of Object.entries(plan.section_overrides || {})) {
    const c: SectionOverride = { ...o };
    if (c.arrangement != null) c.arrangement = keep(c.arrangement);
    if (c.instruments?.length) {
      c.instruments = c.instruments.filter((i) => !gone.has(i));
      if (!c.instruments.length) delete c.instruments;
    }
    if (c.lead && gone.has(c.lead)) delete c.lead;
    if (Object.keys(c).length) so[role] = c;
  }
  next.section_overrides = so;
  return { plan: next, dropped: [...dropped] };
}

/** The plan with instruments (back) in the band. */
export function withInstruments(plan: SongPlan, ids: string[], defaultBand: string[]): SongPlan {
  const band = bandOf(plan, defaultBand);
  return { ...plan, instruments: [...band, ...ids.filter((i) => !band.includes(i))] };
}

/** Silence (or bring back) some instruments in every section of a role: the
 *  section's instrument mask (empty = the whole band plays). */
export function withSectionSilence(plan: SongPlan, role: string, ids: string[], silent: boolean,
  defaultBand: string[]): SongPlan {
  const band = bandOf(plan, defaultBand);
  const cur = plan.section_overrides?.[role]?.instruments;
  const mask = cur?.length ? cur.filter((i) => band.includes(i)) : band;
  const nextMask = silent ? mask.filter((i) => !ids.includes(i))
    : [...mask, ...ids.filter((i) => band.includes(i) && !mask.includes(i))];
  const o: SectionOverride = { ...(plan.section_overrides?.[role] || {}) };
  if (band.every((i) => nextMask.includes(i))) delete o.instruments; else o.instruments = nextMask;
  const so = { ...(plan.section_overrides || {}) };
  if (Object.keys(o).length) so[role] = o; else delete so[role];
  return { ...plan, section_overrides: so };
}

/** Hand a role's tune to another instrument (null: back to the
 *  arrangement's own choice). Christmas styles honour it. */
export function withSectionLead(plan: SongPlan, role: string, lead: string | null): SongPlan {
  const o: SectionOverride = { ...(plan.section_overrides?.[role] || {}) };
  if (lead) o.lead = lead; else delete o.lead;
  const so = { ...(plan.section_overrides || {}) };
  if (Object.keys(o).length) so[role] = o; else delete so[role];
  return { ...plan, section_overrides: so };
}

/** The plan with no section handing its tune to another instrument. */
export function withoutLeads(plan: SongPlan): SongPlan {
  let next = plan;
  for (const role of Object.keys(plan.section_overrides || {})) next = withSectionLead(next, role, null);
  return next;
}

/** The plan with one more section removed. ``shown`` is its index in the
 *  version's section list, which already leaves out earlier removals. */
export function withoutSection(plan: SongPlan, shown: number): SongPlan {
  const gone = [...(plan.remove_sections ?? [])].sort((a, b) => a - b);
  let k = 0;
  for (let seen = -1; ; k++) {
    if (gone.includes(k)) continue;
    if (++seen === shown) break;
  }
  return { ...plan, remove_sections: [...gone, k].sort((a, b) => a - b) };
}

/** Where each section starts, in seconds: from the rendered MIDI when the
 *  server has it, else from the tempo and bar lengths. */
export function sectionStarts(bars: number[], tempo: number, timeSig: number[] | undefined,
  fromServer?: number[]): number[] {
  if (fromServer && fromServer.length === bars.length) return fromServer;
  const [n, d] = timeSig?.length === 2 ? timeSig : [4, 4];
  const barSec = (n * (4 / d) * 60) / (tempo || 120);
  return bars.reduce<number[]>((acc, _b, i) => [...acc, i ? acc[i - 1] + bars[i - 1] * barSec : 0], []);
}

/** Styles whose cells name their parts in Funk Fusion's words (groove,
 *  slap, chops, riffs…). Others (Christmas too) just say "on". */
export const funkWords = (genre: string) => genre === "funk_fusion_full";

/** What a part plays in a section, as a short cell label ("" = sits out). */
export function cellLabel(lane: LaneId, role: string, vs: string[], plan: SongPlan,
  laneHas: (lane: LaneId) => boolean, funk: boolean): string {
  if (!laneHas(lane)) return "";
  const ov = plan.section_overrides?.[role];
  if (!funk || !funkWords(plan.genre)) {
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
      if (role === "outro") return has("falloff") && !has("no_falloff") ? "fall-off" : "held";
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
