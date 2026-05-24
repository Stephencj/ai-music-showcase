import type {
  Block,
  Family,
  GenerateBody,
  Job,
  JobUrls,
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
export const splitJob = (id: string, tag?: string) =>
  jpost<{ section_blocks: string[]; tag: string | null }>(`/api/jobs/${id}/split`, tag ? { tag } : {});

// --- Blocks & songs (Compose screen) ---
export const getBlocks = () => jget<Block[]>("/api/blocks");
export async function deleteBlock(name: string): Promise<void> {
  const r = await fetch(url(`/api/blocks/${encodeURIComponent(name)}`), { method: "DELETE" });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
}
export const renderSong = (timeline: TimelineEntry[]) =>
  jpost<{ job_id: string }>("/api/songs/render", { timeline });

interface SongJob {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  message: string;
  error: string | null;
  result?: SongRenderResult;
}

/** Poll a song-render job (full HQ+MIDI+PDF, same job pipeline as generate). */
export async function pollSongRender(
  id: string,
  onProgress: (progress: number, message: string) => void,
  intervalMs = 400
): Promise<SongJob> {
  for (;;) {
    const job = await jget<SongJob>(`/api/jobs/${id}`);
    onProgress(job.progress, job.message);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
export const saveSong = (title: string, timeline: TimelineEntry[], overwrite = true) =>
  jpost<{ saved: string }>("/api/songs", { title, timeline, overwrite });
export const listSongs = () => jget<{ songs: string[] }>("/api/songs");
export const loadSong = (title: string) =>
  jget<{ title: string; timeline: TimelineEntry[] }>(`/api/songs/${encodeURIComponent(title)}`);

/** Absolute URL for an artifact path (for <audio src> / download links). */
export const mediaUrl = (path: string) => url(path);

/** Download URL for a block artifact (midi/wav/pdf/stems). */
export const blockFileUrl = (name: string, kind: "midi" | "wav" | "pdf" | "stems") =>
  url(`/api/blocks/${encodeURIComponent(name)}/${kind}`);

// --- Saved vocal takes (persisted sung renders per block) ---
export interface VocalTake {
  id: string;
  created: string;
  engine: string;
  voice: string;
  harmonies: boolean;
  lyrics: string;
  files: Record<string, string>; // role ("mix"|"vocal"|"score") -> filename
}
export const listVocalTakes = (name: string) =>
  jget<{ takes: VocalTake[] }>(`/api/blocks/${encodeURIComponent(name)}/vocals`);
export const vocalTakeUrl = (name: string, takeId: string, role: "mix" | "vocal" | "score") =>
  url(`/api/blocks/${encodeURIComponent(name)}/vocals/${takeId}/${role}`);
export async function deleteVocalTake(name: string, takeId: string): Promise<void> {
  const r = await fetch(url(`/api/blocks/${encodeURIComponent(name)}/vocals/${takeId}`), { method: "DELETE" });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
}

// --- Vocals ---
export const getVoices = () =>
  jget<{ voices: string[]; engines: string[]; studio_voices?: string[] }>("/api/voices");
export const getMelodyInfo = (name: string) =>
  jget<{ total_notes: number; phrase_syllables: number[]; has_lead: boolean }>(
    `/api/blocks/${encodeURIComponent(name)}/melody`);
export const draftLyrics = (name: string, theme: string) =>
  jpost<{ lyrics: string }>(`/api/blocks/${encodeURIComponent(name)}/lyrics/draft`, { theme });
export const setLyrics = (name: string, lyrics: string) =>
  jpost<{ ok: boolean }>(`/api/blocks/${encodeURIComponent(name)}/lyrics`, { lyrics });
export const renderVocals = (
  name: string,
  body: { lyrics: string; voice: string; engine: string; harmonies: boolean }
) => jpost<{ job_id: string }>(`/api/blocks/${encodeURIComponent(name)}/vocals`, body);

interface VocalJob {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  message: string;
  error: string | null;
  result?: { urls: JobUrls };
}
export async function pollVocal(
  id: string,
  onProgress: (progress: number, message: string) => void,
  intervalMs = 500
): Promise<VocalJob> {
  for (;;) {
    const job = await jget<VocalJob>(`/api/jobs/${id}`);
    onProgress(job.progress, job.message);
    if (job.status === "done" || job.status === "error") return job;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

export const getPeaks = (name: string) =>
  jget<{ peaks: number[] }>(`/api/blocks/${encodeURIComponent(name)}/peaks`).then((r) => r.peaks);
export const renameBlock = (name: string, new_name: string) =>
  jpost<{ name: string }>(`/api/blocks/${encodeURIComponent(name)}/rename`, { new_name });
export const setTags = (name: string, tags: string[]) =>
  jpost<{ tags: string[] }>(`/api/blocks/${encodeURIComponent(name)}/tags`, { tags });
export const editBlock = (
  name: string,
  body: { mute: string[]; regenerate: string[]; save_as?: string | null }
) => jpost<{ name: string }>(`/api/blocks/${encodeURIComponent(name)}/edit`, body);

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
