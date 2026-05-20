import type {
  Block,
  Family,
  GenerateBody,
  Job,
  Preset,
  SongRenderResult,
  TimelineEntry,
} from "./types";

// API base. Same-origin by default (FastAPI serves the bundle + /api). A
// packaged Capacitor/Tauri client can override it to point at the Mac via
// localStorage; Phase 4 wires Bonjour/Tailscale discovery into this.
const KEY = "aimusic.apiBase";
export const apiBase = () => localStorage.getItem(KEY) || "";
export const setApiBase = (v: string) =>
  v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY);

const url = (p: string) => apiBase() + p;

async function jget<T>(p: string): Promise<T> {
  const r = await fetch(url(p));
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json() as Promise<T>;
}
async function jpost<T>(p: string, body?: unknown): Promise<T> {
  const r = await fetch(url(p), {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json() as Promise<T>;
}

export const getPresets = () => jget<Preset[]>("/api/presets");
export const getInstruments = () => jget<Family[]>("/api/instruments");
export const getMasterPresets = () => jget<string[]>("/api/master-presets");

export const generate = (body: GenerateBody) =>
  jpost<{ job_id: string }>("/api/generate", body);
export const getJob = (id: string) => jget<Job>(`/api/jobs/${id}`);
export const saveBlockFromJob = (job_id: string, name: string) =>
  jpost<{ name: string }>("/api/blocks/from-job", { job_id, name });
export const splitJob = (id: string) =>
  jpost<{ section_blocks: string[] }>(`/api/jobs/${id}/split`);

// --- Blocks & songs (Compose screen) ---
export const getBlocks = () => jget<Block[]>("/api/blocks");
export async function deleteBlock(name: string): Promise<void> {
  const r = await fetch(url(`/api/blocks/${encodeURIComponent(name)}`), { method: "DELETE" });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
}
export const renderSong = (timeline: TimelineEntry[]) =>
  jpost<SongRenderResult>("/api/songs/render", { timeline });
export const saveSong = (title: string, timeline: TimelineEntry[], overwrite = true) =>
  jpost<{ saved: string }>("/api/songs", { title, timeline, overwrite });
export const listSongs = () => jget<{ songs: string[] }>("/api/songs");
export const loadSong = (title: string) =>
  jget<{ title: string; timeline: TimelineEntry[] }>(`/api/songs/${encodeURIComponent(title)}`);

/** Absolute URL for an artifact path (for <audio src> / download links). */
export const mediaUrl = (path: string) => url(path);

/** Poll a job to completion, reporting each status to `onProgress`. */
export async function pollJob(
  id: string,
  onProgress: (j: Job) => void,
  intervalMs = 400
): Promise<Job> {
  for (;;) {
    const job = await getJob(id);
    onProgress(job);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
