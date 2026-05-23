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
