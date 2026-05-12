"""
Song timelines — saved arrangements of blocks.

A "song" in the new model is just a title + an ordered list of timeline
entries. Each entry references a block by name and adds a repeat count.
Saved at ``data/songs/<title>.yaml``:

    title: My Song
    timeline:
      - {block_name: verse_1, repeat: 2}
      - {block_name: chorus,  repeat: 1}
      - {block_name: bridge,  repeat: 1}
      - {block_name: verse_1, repeat: 1}
      - {block_name: chorus,  repeat: 2}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SONGS_DIR = Path("data/songs")


def _safe_name(name: str) -> str:
    s = name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
    return s or "untitled"


def _path(title: str) -> Path:
    return SONGS_DIR / f"{_safe_name(title)}.yaml"


def list_song_timelines() -> list[str]:
    if not SONGS_DIR.exists():
        return []
    return sorted(p.stem for p in SONGS_DIR.glob("*.yaml"))


def save_song_timeline(title: str,
                       timeline: list[dict[str, Any]],
                       overwrite: bool = False) -> Path:
    """Persist a song timeline. Refuses to overwrite by default."""
    if not title or not title.strip():
        raise ValueError("Song title is required.")
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(title)
    if p.exists() and not overwrite:
        raise FileExistsError(
            f"A song titled {title!r} already exists. "
            "Pick a different title or pass overwrite=True."
        )
    payload = {
        "title": title.strip(),
        "timeline": [
            {"block_name": str(t["block_name"]),
             "repeat": int(t.get("repeat") or 1)}
            for t in timeline
            if t.get("block_name")
        ],
    }
    with open(p, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
    return p


def load_song_timeline(title: str) -> dict:
    """Return ``{title, timeline}`` from disk."""
    p = _path(title)
    if not p.exists():
        raise FileNotFoundError(f"No saved song titled {title!r} ({p})")
    with open(p, "r") as f:
        data = yaml.safe_load(f) or {}
    return {
        "title": data.get("title", title),
        "timeline": list(data.get("timeline", [])),
    }


def delete_song_timeline(title: str) -> None:
    p = _path(title)
    if p.exists():
        p.unlink()
