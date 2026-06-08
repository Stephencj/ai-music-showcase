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
    with_stems: bool = False
    with_pdf: bool = True
    master_preset: Optional[str] = "default"
    # Post-generation conveniences:
    save_as_block: bool = False
    block_name: Optional[str] = None
    split_into_blocks: bool = False        # one block per section (mix & match)


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
