"""Pydantic request models for the API. Responses are plain JSON dicts
(assembled in routes.py) so the engine's own return shapes pass through
without a second mapping layer to maintain."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """One-button song generation. Everything but ``genre`` is optional and
    falls back to the preset's defaults."""
    genre: str
    key: Optional[str] = None
    scale: Optional[str] = None
    tempo: Optional[float] = None
    # Roman-numeral chords/bar overriding the preset's progression — used by
    # "generate similar" to reproduce a progression detected from a sample.
    progression: list[str] = Field(default_factory=list)
    seed: Optional[int] = None            # 0/None → random (returned in result)
    swing: Optional[float] = None
    bars: Optional[int] = None
    instruments: list[str] = Field(default_factory=list)   # instrument ids
    sections: list[str] = Field(default_factory=list)      # roles to include
    # Multi-preset songs: role → preset id, e.g. {"chorus": "hip_hop"}. Each
    # mapped section renders in that preset's feel (progression/pacing/
    # techniques/reharm); key/scale/tempo stay global. Unmapped roles use genre.
    section_presets: dict[str, str] = Field(default_factory=dict)
    # Per-section playing-style overrides: role → {knobs?: {...}, energy?: float,
    # feature_lead?: bool}. `knobs` merge over the section's knobs (e.g.
    # drum_fill); `energy` sets that section's level directly (sparse/big);
    # `feature_lead` forces the lead/solo into that section.
    section_overrides: dict[str, dict] = Field(default_factory=dict)
    # Sections to leave out, as indices into the arranged section list (the
    # one ``sections`` builds, repeats included), e.g. [3] drops the bridge of
    # intro/verse/chorus/bridge/…; the rest close up (Create → Timeline).
    remove_sections: list[int] = Field(default_factory=list)
    # An explicit form, [{role, bars, label?}] in playing order (repeats
    # included), instead of the genre's template: a saved song re-made with
    # its own form (Library → Open in Timeline). Not for Christmas styles.
    section_layout: Optional[list[dict]] = None
    # Hit points, in seconds from the start of the song: the band lands an
    # accent there (snapped to the nearest 16th), e.g. a stab on each caption
    # of a video. Honoured by styles that support it (Funk Fusion).
    hits: list[float] = Field(default_factory=list)
    with_stems: bool = False
    with_pdf: bool = True
    master_preset: Optional[str] = "default"
    # "gm" (soundfont) or "sampled" (real-instrument SFZ libraries where
    # installed). None → the style's default.
    sound: Optional[str] = None
    # Lead voice for sampled renders (render/lead_voices.py): "punch"/"sonic"
    # (default synth), "ewi", "layered", "horns", "trumpet", "guitar". Also
    # sets where the lead plays (horns and guitar sit lower than a synth).
    lead_patch: Optional[str] = None
    # How hits land: "punch" (exact, the band breathes around them) or
    # "groove" (on the next beat, inside the groove).
    hit_style: Optional[str] = None
    # Arrangement variant: "" (normal) or "hits_only" (Funk Fusion: no lead or
    # riffs; the band lands the hits together, 70s-section horn punches).
    arrangement: Optional[str] = None
    # Loudness of the delivered mix (integrated LUFS). None = as mastered
    # (about −12); background beds under a video sit around −23 to −28.
    target_lufs: Optional[float] = None
    # Christmas styles: a public-domain carol id (src/composition/carols.py,
    # e.g. "silent_night") or "original" / None for an original tune.
    tune: Optional[str] = None
    # About how long the song should be, in seconds (sections are planned or
    # scaled to fit). None = the style's natural length.
    length_seconds: Optional[float] = None
    # Post-generation conveniences:
    save_as_block: bool = False
    block_name: Optional[str] = None
    split_into_blocks: bool = False        # one block per section (mix & match)


class BackingTracksRequest(BaseModel):
    """One carol rendered as a sing-along backing track in several keys
    (render/backing.py): an MP3 and a timing JSON per key."""
    tune: str                                           # carol id (src/composition/carols.py)
    genre: str = "christmas_orchestral_full"            # a christmas_* style id
    keys: list[str] = Field(default_factory=list)       # e.g. ["C", "G", "low"]; empty = C D F G Bb low high
    tempo: Optional[float] = None                       # BPM; None = the style's pick for the carol
    seed: int = 1
    guide_melody: bool = False                          # the melody kept very quiet as a guide
    both: bool = False                                  # render the plain AND the guide version
    length_seconds: Optional[float] = None              # None = one pass per verse (up to four)
    arrangement: str = ""                               # other Christmas variants, e.g. "less_busy,warmer"
    target_lufs: float = -16.0


class ChristmasMixRequest(BaseModel):
    """A seamless playlist of generated Christmas songs (render/playlist.py)."""
    total_minutes: float = 0.0                  # mix length; or give count
    count: int = 0                              # number of songs (0 = from total_minutes)
    styles: list[str] = Field(default_factory=list)    # christmas_* style ids (empty = all six)
    tunes: list[str] = Field(default_factory=list)     # carol ids (empty = every carol)
    originals: float = 0.4                      # share of original tunes
    min_track_seconds: float = 150.0
    max_track_seconds: float = 240.0
    crossfade: float = 4.0                      # seconds
    target_lufs: float = -16.0                  # YouTube normalises to about -14
    arrangement: str = ""                       # Christmas variants for every song
    seed: int = 1
    name: str = "christmas-mix"
    formats: list[str] = Field(default_factory=lambda: ["mp3"])   # "mp3" and/or "wav"


class VideoChapter(BaseModel):
    """One chapter of a video to score (see src/api/video_score.py)."""
    start: float                                   # seconds into the video
    card: float = 0.0                              # title card length at its start
    roles: list[str] = Field(default_factory=lambda: ["verse"])
    key: Optional[str] = None
    lead: str = "synth_lead"                       # or "lead_guitar"
    label: str = ""
    intro: Optional[bool] = None                   # None = only the first chapter
    sections: Optional[list[dict]] = None          # explicit form (single-chapter scores)
    arrangement: Optional[str] = None              # this chapter's arrangement (overrides the score's)


class VideoScoreRequest(BaseModel):
    """Score a whole video: one chapter per section of the video, each landing
    on a downbeat, hits on captions/cards, rendered as one continuous mix."""
    duration: float
    chapters: list[VideoChapter]
    hits: list[float] = Field(default_factory=list)   # seconds into the video
    genre: str = "funk_fusion_full"
    seed: int = 52
    base_tempo: float = 158.0
    lead_patch: Optional[str] = None
    with_stems: bool = False
    hit_style: str = "groove"                         # or "punch"
    curate_hits: bool = True                          # thin hits musically (see video_score)
    min_hit_gap: float = 3.0
    offset: float = 0.0                               # video time of music time 0 (negative = pickup)
    arrangement: str = ""                             # e.g. "hits_only"
    # Loudness of the delivered score (integrated LUFS). None = as mastered
    # (about −12); background music under a video sits around −23 to −28.
    target_lufs: Optional[float] = None
    # Instruments added to the style's band (e.g. string_section, french_horn).
    extra_instruments: list[str] = Field(default_factory=list)
    stops: list[list[float]] = Field(default_factory=list)   # band stops [start, end] in video seconds


class ParsePromptRequest(BaseModel):
    """Natural-language song description → a SongPlan that pre-fills the
    Generate form (rule-based, deterministic)."""
    prompt: str = ""


class DescribeRequest(BaseModel):
    """Plain-English song description → a song plan (src/api/describe.py).
    ``wait=False`` runs it as a job (poll ``/jobs/{id}``) for clients that
    can't hold a request open while the interpreter thinks."""
    text: str = ""
    wait: bool = True


class ReviseRequest(BaseModel):
    """The current song plan + plain-English feedback → a revised plan."""
    plan: dict = Field(default_factory=dict)
    feedback: str = ""
    wait: bool = True


class GeneratePartRequest(BaseModel):
    """DAW-channel part generation (VST/host bridge). Given musical context,
    generate ONE part that fits — MIDI note-list (+ optional rendered WAV)."""
    target: str = "melody"          # chords | bass | melody | lead | drums
    key: str = "C"
    scale: str = "major"
    tempo: float = 120.0
    time_signature: list[int] = Field(default_factory=lambda: [4, 4])
    bars: int = 4
    progression: list[str] = Field(default_factory=list)   # roman chords/bar; [] → default for key
    genre: Optional[str] = None     # pulls style defaults (melody_style/drum/bass/voicing)
    # Per-part modifiers (override the genre/preset default for that part).
    # Valid values come from GET /api/part-options.
    voicing: Optional[str] = None        # chords
    chord_rhythm: Optional[str] = None   # chords
    bass_pattern: Optional[str] = None   # bass
    drum_pattern: Optional[str] = None   # drums
    melody_style: Optional[str] = None   # melody / lead
    phrase_shape: Optional[str] = None   # melody / lead
    octave: Optional[int] = None         # chords / bass / melody / lead
    note_density: Optional[float] = None # bass / melody / lead / drums (0–1)
    parts: list[str] = Field(default_factory=list)  # /generate-arrangement: which
                                  # parts (default drums+bass+chords+melody)
    output: str = "both"            # midi | wav | both
    seed: Optional[int] = None
    # The other channels' parts (role + note-list), so generation can fit what's
    # already there. v1 records them for context; complement logic builds on it.
    existing_parts: list[dict] = Field(default_factory=list)


class SaveBlockFromJobRequest(BaseModel):
    job_id: str
    name: str
    overwrite: bool = False


class SongSaveRequest(BaseModel):
    title: str
    timeline: list[dict]                   # [{block_name, repeat}, ...]
    overwrite: bool = False


class SongRenderRequest(BaseModel):
    timeline: list[dict]
    with_pdf: bool = True


class BlockVersionRequest(BaseModel):
    """Snapshot the block's current state as a named version."""
    label: str = ""
    note: str = ""


class PreviewTakeRequest(BaseModel):
    """Point the block's play/preview at a vocal take's mix, or clear it
    (``take_id: null``) to revert to the instrumental preview."""
    take_id: Optional[str] = None


class LibrarySaveRequest(BaseModel):
    """Add a block to the sheet-music library. Only ``block_name`` is
    required; the rest is library-only metadata."""
    block_name: str
    title: Optional[str] = None
    collection: str = ""
    note: str = ""
    folder: str = ""                 # folder id/path to file it into ('' = none)


class FolderCreateRequest(BaseModel):
    name: str
    parent: str = ""                 # a top-level folder's id/path → subfolder
    description: str = ""


class FolderUpdateRequest(BaseModel):
    """Only the fields given change; ``parent: ""`` moves it to the top level."""
    name: Optional[str] = None
    description: Optional[str] = None
    parent: Optional[str] = None


class FolderItemsRequest(BaseModel):
    """Add library entries (by id) and/or blocks (by name; added to the
    library first if needed) to a folder, at ``position`` (default: end)."""
    entry_ids: list[str] = Field(default_factory=list)
    block_names: list[str] = Field(default_factory=list)
    position: Optional[int] = None


class FolderReorderRequest(BaseModel):
    entry_ids: list[str]


class FolderMoveRequest(BaseModel):
    entry_id: str
    to_folder: str                   # id/path, or "unfiled"
    from_folder: str = ""            # '' = out of every other folder
    position: Optional[int] = None


class SplitRequest(BaseModel):
    tag: Optional[str] = None        # collection tag for the split sections


class RenameRequest(BaseModel):
    new_name: str


class TagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class EditBlockRequest(BaseModel):
    mute: list[str] = Field(default_factory=list)          # track names to drop
    regenerate: list[str] = Field(default_factory=list)    # track names to re-roll
    save_as: Optional[str] = None                          # None → overwrite in place


class ProduceBlockRequest(BaseModel):
    """Producer-role move: arrange (mute/regenerate) + mix + master a block.
    ``track_mix`` is ``{track_name: {mute, gain_db, pan, eq:{low_db,mid_db,
    high_db}, comp:{threshold_db,ratio}, fx:{reverb,delay,chorus,distortion}}}``,
    each setting relative to the family baseline."""
    mute: list[str] = Field(default_factory=list)
    regenerate: list[str] = Field(default_factory=list)
    master_preset: str = "default"                         # default|loud|cinematic|transparent
    track_mix: dict[str, Any] = Field(default_factory=dict)
    save_as: Optional[str] = None


class MixPreviewRequest(BaseModel):
    """Render a block with a per-track mix + master to a throwaway preview
    (A/B mixing, ear-training) — does not modify the saved block."""
    track_mix: dict[str, Any] = Field(default_factory=dict)
    master_preset: str = "default"


class LyricsDraftRequest(BaseModel):
    theme: Optional[str] = None


class SetLyricsRequest(BaseModel):
    lyrics: str = ""


class SectionEngine(BaseModel):
    """A song section sung by a specific engine (per-section voice switching)."""
    start_bar: int                # inclusive bar range, as in BlockSpec.sections
    end_bar: int
    engine: str                   # "studio" (sung) | "rough" (rap/TTS)


class VocalsRequest(BaseModel):
    lyrics: str
    voice: str = ""               # "" = system default say voice
    engine: str = "rough"         # "rough" now; "studio" when available
    harmonies: bool = True        # stack the block's harmony/backing lines
    clarity: bool = False         # intelligibility transform: cap register,
                                  # gap words, de-melisma (trades a little
                                  # melody for clearer diction)
    phonetic: str = ""            # optional edited ARPABET version (one
                                  # bracketed group per word) — sing these
                                  # phonemes instead of g2p on the spelling
    section_engines: list[SectionEngine] = []  # per-section voice map; empty =
                                  # use `engine` for the whole song


class PhoneticRequest(BaseModel):
    lyrics: str                   # → auto-generated, editable ARPABET version


class AiAnswerRequest(BaseModel):
    """A Claude Code watch-loop's answer to a queued AI request. ``answer``
    is the content (lyrics string, or a melody plan dict for later kinds)."""
    answer: Any = None
    error: Optional[str] = None


class SessionBody(BaseModel):
    """A Create session (or the parts of one to merge): its title, the
    thread's messages and its versions, as the Create screen holds them."""
    title: Optional[str] = None
    interpreter: Optional[str] = None
    msgs: Optional[list[dict]] = None
    versions: Optional[list[dict]] = None


class SessionRenameRequest(BaseModel):
    title: str


class SessionFromBlockRequest(BaseModel):
    block: str


class SessionReviseRequest(BaseModel):
    feedback: str
    wait: bool = False
