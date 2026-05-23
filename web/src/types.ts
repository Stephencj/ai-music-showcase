export interface SectionAvail {
  role: string;
  native: boolean;
}

export interface Preset {
  id: string;
  name: string;
  tempo: number;
  key: string;
  scale: string;
  time_signature: number[];
  default_bars: number;
  default_instruments: string[];
  sections: SectionAvail[];
}

export interface Instrument {
  id: string;
  label: string;
  role: string;
  default: boolean;
}

export interface Family {
  family: string;
  label: string;
  instruments: Instrument[];
}

export interface JobUrls {
  midi: string | null;
  audio: string | null;
  audio_hifi: string | null;
  pdf: string | null;
}

export interface SectionInfo {
  label: string;
  role: string;
  bars: number;
}

export interface JobResult {
  seed: number;
  genre: string;
  bars: number;
  key: string;
  scale: string;
  tempo: number;
  time_signature: number[];
  summary: string;
  sections: SectionInfo[];
  saved_block: string | null;
  section_blocks: string[];
  urls: JobUrls;
}

export interface Job {
  id: string;
  status: "pending" | "running" | "done" | "error";
  progress: number;
  message: string;
  error: string | null;
  result?: JobResult;
}

export interface BlockInstrument {
  name: string;
  n_notes: number;
}

export interface Block {
  name: string;
  bars: number | null;
  tempo: number | null;
  time_signature: number[] | null;
  n_notes: number | null;
  duration_seconds: number | null;
  instruments?: BlockInstrument[];
  created?: string | null;
  has_preview: boolean;
  audio_url: string;
}

export interface TimelineEntry {
  block_name: string;
  repeat: number;
}

export interface SongInfo {
  duration_seconds: number;
  n_instruments: number;
  n_notes: number;
  summary: string;
}

export interface SongRenderResult {
  kind?: string;
  info: SongInfo;
  urls: JobUrls;
}

export interface GenerateBody {
  genre: string;
  key?: string | null;
  scale?: string | null;
  tempo?: number | null;
  seed?: number | null;
  instruments: string[];
  sections: string[];
  with_pdf: boolean;
  with_stems: boolean;
  master_preset: string;
}
