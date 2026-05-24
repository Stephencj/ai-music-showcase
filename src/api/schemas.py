"""Pydantic request models for the API. Responses are plain JSON dicts
(assembled in routes.py) so the engine's own return shapes pass through
without a second mapping layer to maintain."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    """One-button song generation. Everything but ``genre`` is optional and
    falls back to the preset's defaults."""
    genre: str
    key: Optional[str] = None
    scale: Optional[str] = None
    tempo: Optional[float] = None
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


class VocalsRequest(BaseModel):
    lyrics: str
    voice: str = ""               # "" = system default say voice
    engine: str = "rough"         # "rough" now; "studio" when available
    harmonies: bool = True        # stack the block's harmony/backing lines
