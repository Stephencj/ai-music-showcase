"""MCP server exposing the song-composition pipeline to LLMs.

Two transports ship side-by-side:

- **stdio** — the standard MCP pattern for local LLM clients. Launch
  with ``python scripts/run_mcp.py``; register with
  ``claude mcp add ai-music -- <venv>/bin/python <path>/scripts/run_mcp.py``.

- **SSE** — mounted at ``/mcp`` on the existing FastAPI launcher so a
  remote LLM (or a session on a different machine) can hit the same
  tools. Inherits ``IPAwareAuthMiddleware`` for off-LAN auth.

Tools wrap the bank + composer; they intentionally return plain JSON-
friendly dicts so any MCP client can introspect without needing custom
parsers.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from src.composition import BANK
from src.composition.song_composer import compose_song as _compose_song
from src.daw_integration.generic.styles import STYLES


logger = logging.getLogger(__name__)


mcp = FastMCP("ai-music-studio")


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------

@mcp.tool()
def list_styles() -> list[dict]:
    """All available genre presets with their default bar counts.

    Returns one dict per style: ``name``, ``label``, ``default_bars``,
    ``has_rhythm_variants`` (whether ``compose_song`` can fill section
    overrides automatically).
    """
    out: list[dict] = []
    for key, preset in STYLES.items():
        out.append({
            "name":               key,
            "label":              preset.name,
            "default_bars":       int(preset.default_bars),
            "key":                preset.key,
            "scale":              preset.scale,
            "tempo":              float(preset.tempo),
            "has_rhythm_variants": bool(preset.rhythm_variants),
            "rhythm_variants":    list((preset.rhythm_variants or {}).keys()),
        })
    return sorted(out, key=lambda d: d["name"])


@mcp.tool()
def list_techniques(
    instrument: str = "",
    role: str = "",
    tag: str = "",
) -> list[dict]:
    """Techniques registered in the bank.

    Filters (all optional): ``instrument`` ("chords" / "bass" /
    "melody" / "drums"), ``role`` ("intro" / "verse" / "chorus" /
    "bridge" / "outro"), ``tag`` (e.g. ``"funk_rock"``).
    """
    out = BANK.all_techniques()
    if instrument:
        out = [t for t in out if instrument in t.instruments]
    if role:
        out = [t for t in out if role in t.section_roles]
    if tag:
        out = [t for t in out if tag in t.tags]
    return [t.to_dict() for t in out]


@mcp.tool()
def inspect_technique(name: str) -> dict:
    """Full metadata for one technique by name."""
    t = BANK.get(name)
    if t is None:
        return {"error": f"unknown technique {name!r}"}
    return t.to_dict()


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

@mcp.tool()
def compose_song(
    genre: str = "pop",
    seed: int = 0,
    technique_overrides: Optional[dict[str, str]] = None,
    key: str = "",
    scale: str = "",
    tempo: float = 0.0,
    bars: int = 0,
    swing: float = -1.0,
) -> dict:
    """Generate a full song using the TechniqueBank.

    Same ``seed`` produces the same song; bump by 1 for variation.
    ``technique_overrides`` pins specific cells, keys shaped
    ``"{role}:{instrument}"`` (e.g. ``{"verse:bass": "funk_walk"}``).

    Returns ``midi_path`` + ``wav_path`` (paths Gradio's allowlist
    already exposes via ``/gradio_api/file=…``), ``summary`` (human-
    readable list of picks), ``selections`` (machine-readable
    per-cell choices).
    """
    kwargs: dict[str, Any] = {
        "genre": genre, "seed": int(seed),
        "technique_overrides": technique_overrides or None,
    }
    if key:
        kwargs["key"] = key
    if scale:
        kwargs["scale"] = scale
    if tempo and tempo > 0:
        kwargs["tempo"] = float(tempo)
    if bars and bars > 0:
        kwargs["bars"] = int(bars)
    if swing >= 0:
        kwargs["swing"] = float(swing)
    return _compose_song(**kwargs)


@mcp.tool()
def get_last_compose() -> dict:
    """Path + summary of the most recent compose. Empty when nothing
    has been composed yet this session.

    Reads directly from the conventional output directory rather than
    keeping in-memory state; an LLM that lost its conversation can
    still find the last file.
    """
    from pathlib import Path
    midi = Path("data/outputs/app/last_composition.mid")
    wav = Path("data/outputs/app/last_composition.wav")
    if not midi.exists():
        return {"midi_path": "", "wav_path": "", "exists": False}
    return {
        "midi_path": str(midi.resolve()),
        "wav_path": str(wav.resolve()) if wav.exists() else "",
        "exists": True,
        "size_bytes": midi.stat().st_size,
    }
