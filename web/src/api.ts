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
  clarity?: boolean;
  phonetic?: string;
  section_engines?: { start_bar: number; end_bar: number; engine: string }[];
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

// --- Practice mode: chord chart + bar timings (detected from the MIDI) ---
export interface ChordEntry {
  bar: number;
  start_time: number;
  end_time: number;
  root: string | null;
  quality: string | null;
  symbol: string;   // absolute, e.g. "Gmaj7" / "Em" / "N.C."
  roman: string;    // key-relative, e.g. "IV" / "vi"
  nashville: string; // e.g. "4" / "6m"
}
export interface ChordSpan {
  start_bar: number; end_bar: number;
  start_time: number; end_time: number;
  root: string | null;
  quality: string | null;
  symbol: string;
  roman: string;
  nashville: string;
}
export interface ScoreSection {
  label: string; role: string;
  start_bar: number; end_bar: number;
  start_time: number; end_time: number;
}
export interface ScoreData {
  key: string; scale: string; tempo: number;
  time_signature: number[]; bars: number; bar_seconds: number;
  beats_per_bar: number;
  sections: ScoreSection[];
  chords: ChordEntry[];       // one per bar
  chord_spans: ChordSpan[];   // consecutive identical chords merged
}
export const getScoreData = (name: string) =>
  jget<ScoreData>(`/api/blocks/${encodeURIComponent(name)}/score-data`);

// Per-track notes [pitch, startBeat, durBeat] (beats = quarter notes) for the
// notation roll + real-time piano/guitar. Same data the workstation loads.
export interface NoteTrack {
  track: string;
  is_drum: boolean;
  notes: [number, number, number][];
}
export interface BlockNotes {
  tempo: number;
  bars: number;
  time_signature: number[];
  key: string;
  scale: string;
  tracks: NoteTrack[];
}
export const getBlockNotes = (name: string) =>
  jget<BlockNotes>(`/api/blocks/${encodeURIComponent(name)}/notes`);
export const partAudioUrl = (name: string, idx: number) =>
  url(`/api/blocks/${encodeURIComponent(name)}/part-audio/${idx}`);

// Songs (timelines of blocks) practised like a block: derived chart + cached audio.
export const getSongScoreData = (title: string) =>
  jget<ScoreData>(`/api/songs/${encodeURIComponent(title)}/score-data`);
export const songAudioUrl = (title: string) =>
  url(`/api/songs/${encodeURIComponent(title)}/audio`);
export const songWavUrl = (title: string) =>
  url(`/api/songs/${encodeURIComponent(title)}/audio.wav`);

// Analyze an uploaded song → same score-data shape + a Roman-numeral
// progression for "generate similar".
export interface AudioAnalysis extends ScoreData {
  duration: number;
  progression: string[];
}
export async function analyzeAudio(file: File): Promise<AudioAnalysis> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(url("/api/analyze/audio"), { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json() as Promise<AudioAnalysis>;
}

// Scan a sheet-music image → MIDI block (slow OMR job; returns a job_id to poll).
export async function scanSheet(file: File): Promise<{ job_id: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(url("/api/scan/sheet"), { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json() as Promise<{ job_id: string }>;
}
// Lyric drafting is answered by a Claude Code watch-loop (no API key):
// enqueue a request, then poll until it's answered with fitted lyrics.
export const requestLyrics = (name: string, theme: string) =>
  jpost<{ request_id: string }>(`/api/blocks/${encodeURIComponent(name)}/lyrics/draft`, { theme });
export interface AiRequest {
  id: string;
  kind: string;
  status: "pending" | "answered" | "error";
  answer: string | null;
  error: string | null;
}
export const getAiRequest = (id: string) => jget<AiRequest>(`/api/ai/requests/${id}`);
export async function pollAiRequest(
  id: string,
  { timeoutMs = 180000, intervalMs = 1500 }: { timeoutMs?: number; intervalMs?: number } = {}
): Promise<AiRequest> {
  const start = Date.now();
  for (;;) {
    const r = await getAiRequest(id);
    if (r.status === "answered" || r.status === "error") return r;
    if (Date.now() - start > timeoutMs)
      throw new Error("Timed out waiting for Claude Code to answer — is an assistant loop running?");
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}
export const setLyrics = (name: string, lyrics: string) =>
  jpost<{ ok: boolean }>(`/api/blocks/${encodeURIComponent(name)}/lyrics`, { lyrics });
// Compose (or regenerate) the vocal melody+harmony from the lyrics, answered
// by the Claude Code watch-loop. Enqueue, then poll the request id.
export const composeMelody = (name: string, lyrics: string) =>
  jpost<{ request_id: string }>(`/api/blocks/${encodeURIComponent(name)}/melody/compose`, { lyrics });
export interface SectionEngine { start_bar: number; end_bar: number; engine: string }
export const renderVocals = (
  name: string,
  body: {
    lyrics: string; voice: string; engine: string; harmonies: boolean;
    clarity?: boolean; phonetic?: string; section_engines?: SectionEngine[];
  }
) => jpost<{ job_id: string }>(`/api/blocks/${encodeURIComponent(name)}/vocals`, body);
// Auto-generate the editable ARPABET ("phonetic version") of a lyric so the
// user can tweak per-word diction before re-singing.
export const getPhonetic = (lyrics: string) =>
  jpost<{ phonetic: string }>(`/api/phonetic`, { lyrics });
// Per-section voice info (density + suggested engine) for per-section switching.
export const getSectionVoices = (name: string) =>
  jget<{ sections: import("./types").SectionVoice[] }>(
    `/api/blocks/${encodeURIComponent(name)}/section-voices`);
// Download the composed vocal melody as a MIDI guide (for your DAW's Auto-Tune).
export const vocalGuideUrl = (name: string) =>
  url(`/api/blocks/${encodeURIComponent(name)}/vocal-guide.mid`);

// --- Karaoke (full-screen sing-along) ---
export interface KaraokeData {
  duration: number;
  tempo: number;
  key: string;
  scale: string;
  notes: [number, number, number][];                 // [pitch, startSec, endSec]
  words: { text: string; start: number; end: number }[];
  lyrics: string;
  has_lead: boolean;
}
export const getKaraoke = (name: string) =>
  jget<KaraokeData>(`/api/blocks/${encodeURIComponent(name)}/karaoke`);
/** The block's full preview audio (instrumental + synth guide vocal) — the backing to sing over. */
export const blockAudioUrl = (name: string) =>
  url(`/api/blocks/${encodeURIComponent(name)}/audio`);
/** The Lead Vocal track rendered alone — an audible guide of the melody to sing. */
export const vocalGuideAudioUrl = (name: string) =>
  url(`/api/blocks/${encodeURIComponent(name)}/vocal-guide-audio`);
// Pitch-correct a recorded/uploaded vocal onto the block's melody (or its key).
// Returns a job id; poll with pollVocal (same result shape as a vocal render).
export const autotuneBlock = async (
  name: string,
  file: Blob,
  opts: { mode?: string; strength?: number; toKey?: boolean } = {}
): Promise<{ job_id: string }> => {
  const fname = (file as File).name
    || (file.type.includes("webm") ? "take.webm" : file.type.includes("ogg") ? "take.ogg" : "take.wav");
  const fd = new FormData();
  fd.append("file", file, fname);
  fd.append("mode", opts.mode ?? "natural");
  fd.append("strength", String(opts.strength ?? 0.85));
  fd.append("to_key", String(opts.toKey ?? false));
  const r = await fetch(url(`/api/blocks/${encodeURIComponent(name)}/autotune`), { method: "POST", body: fd });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
};

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
