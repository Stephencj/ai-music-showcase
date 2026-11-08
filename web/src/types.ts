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
  progression?: string[];   // genre's chord loop as roman numerals (core unit)
  progressions?: PresetProgressions;   // per-role pools + variants for the builder
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

// "Explain this song" — the teaching breakdown.
export interface ExplainChord {
  name: string; roman: string; nashville: string; function: string;
}
export interface ExplainSection {
  label: string; role: string | null; bars: number; feel: string;
  key_relation: string; tempo: number | null;
  chords: ExplainChord[];
  progression_name: string | null;
  devices: string[];
  arrangement: string;
}
export interface ExplainData {
  key: string; tempo: number | null; genre: string;
  form: string[]; sections: ExplainSection[];
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
  plays?: string[];             // instrument ids that played in it (the rest of the band rests)
  melody?: string | null;       // planned tunes (Christmas): who has the melody
  melody_default?: string | null; // … who the arrangement gave it to (before a moved tune)
  melody_options?: string[];    // … and who in the band could carry it
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
  timeline?: TimelineStatus;
}

/** Whether a block opens in Create's Timeline, and if not, why. */
export interface TimelineStatus { ok: boolean; reason?: string; session_id?: string }

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
// A song plan: a /generate body as the Describe interpreters produce it
// (src/composition/song_plan.py). The Funk Fusion options (arrangement, lead
// voice, hits, loudness) have no form controls; they ride along with the plan.
export interface SongPlan {
  genre: string;
  key?: string;
  scale?: string;
  tempo?: number;
  swing?: number;
  seed?: number;
  sections?: string[];
  section_presets?: Record<string, string>;
  section_overrides?: Record<string, SectionOverride>;
  instruments?: string[];
  arrangement?: string;
  lead_patch?: string;
  hits?: number[];
  hit_style?: string;
  target_lufs?: number;
  remove_sections?: number[];   // arranged-section indices left out (Timeline → Remove section)
  tune?: string;             // Christmas styles: a public-domain carol id or "original"
  length_seconds?: number;
  section_layout?: { role: string; bars: number; label?: string }[];   // a saved song's own form
}

// POST /api/describe and /api/revise.
export interface DescribeResult {
  plan: SongPlan;
  summary: string;
  understood: string[];
  notes: string[];
  interpreter: "claude" | "local" | "rules";
  engine: string;
  changes?: string[];
}

export interface SectionOverride {
  knobs?: Record<string, number>;
  energy?: number;
  feature_lead?: boolean;
  key?: string;
  scale?: string;
  tempo?: number;
  bars?: number;
  progression?: string[];    // per-section chord progression (roman numerals)
  instruments?: string[];    // per-section instrument subset (ids); empty = all
  arrangement?: string;      // per-section arrangement variant (Funk Fusion)
  lead?: string;             // Christmas: the instrument that carries the tune here
}

// Progression choices for the section builder (from GET /presets).
export interface ProgressionOption { index: number; symbols: string[]; }
export interface PresetProgressions {
  sections: Record<string, ProgressionOption[]>;   // role → pool
  variants: { name: string; symbols: string[] }[]; // song-level forms
  default: string[];
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
  // Engine options a described plan carries (no form controls).
  arrangement?: string;
  lead_patch?: string;
  hits?: number[];
  hit_style?: string;
  target_lufs?: number;
  remove_sections?: number[];
  tune?: string;
  length_seconds?: number;
  section_layout?: { role: string; bars: number; label?: string }[];
}
