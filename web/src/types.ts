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

// Consolidated genre catalog for the radial genre wheel.
export interface GenreItem {
  id: string;          // song preset id (what /generate's `genre` receives)
  name: string;        // display name
  section: string;     // per-section "feel" preset id
  sections: SectionAvail[];
}
export interface GenreFamily {
  family: string;
  color: string;
  angle: number;       // wheel position, 12 o'clock = 0
  genres: GenreItem[];
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
  vocal?: string | null;
}

export interface SectionInfo {
  label: string;
  role: string;
  bars: number;
}

export interface SectionVoice {
  label: string;
  role: string;
  start_bar: number;
  end_bar: number;
  n_notes: number;
  dense: boolean;
  suggested: string; // "studio" | "rough"
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

export interface BlockSpec {
  genre: string;
  key?: string;
  scale?: string;
  tempo?: number;
  time_signature?: number[];
  seed?: number;
  swing?: number | null;
  instruments?: string[];
  section_presets?: Record<string, string>;
  section_overrides?: Record<string, SectionOverride>;
  sections?: { start_bar: number; end_bar: number; label: string; role: string; preset_id?: string }[];
  section?: { start_bar: number; end_bar: number } | null;
  inferred?: boolean;
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
  tags?: string[];
  spec?: BlockSpec | null;
  lyrics?: string;
  vocal_takes?: number;
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

// Result of POST /api/parse-prompt — a natural-language description parsed
// into Generate-form fields, plus a transparency report.
export interface SongPlan {
  genre: string;
  key: string | null;
  scale: string | null;
  tempo: number | null;
  swing: number | null;
  sections: string[];
  section_presets: Record<string, string>;
  section_overrides: Record<string, SectionOverride>;
  instruments: string[];
  understood: string[];
  notes: string[];
}

export interface SectionOverride {
  knobs?: Record<string, number>;
  energy?: number;
  feature_lead?: boolean;
  key?: string;
  scale?: string;
  tempo?: number;
  bars?: number;
}

export interface GenerateBody {
  genre: string;
  key?: string | null;
  scale?: string | null;
  tempo?: number | null;
  progression?: string[];
  seed?: number | null;
  swing?: number | null;
  instruments: string[];
  sections: string[];
  section_presets?: Record<string, string>;   // role → preset id (multi-preset songs)
  section_overrides?: Record<string, SectionOverride>;  // role → playing-style
  with_pdf: boolean;
  with_stems: boolean;
  master_preset: string;
  save_as_block?: boolean;
  block_name?: string | null;
}
