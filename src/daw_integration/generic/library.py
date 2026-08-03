"""
Sheet-music library — a curated set of saved pieces.

Each entry references an existing block by ``block_name`` (the block store
stays the source of truth for the audio / MIDI / notation / PDF assets)
and adds library-only metadata. Saved at ``data/library/<id>.yaml``:

    id: frijole_blues
    block_name: Frijole_Blues
    title: Frijole Blues
    favorite: true
    collection: blues
    note: ""
    added: 2026-08-02T21:15:00

The directory is the index (globbed on read), matching the songs/blocks
sidecar convention — no database, one file per entry, easy to sync with
the iOS on-device cache.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml


LIBRARY_DIR = Path("data/library")


def _safe_id(name: str) -> str:
    s = name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
    return s or "untitled"


def _path(entry_id: str) -> Path:
    return LIBRARY_DIR / f"{_safe_id(entry_id)}.yaml"


def _read(p: Path) -> dict:
    with open(p, "r") as f:
        return yaml.safe_load(f) or {}


def _write(p: Path, entry: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.safe_dump(entry, f, sort_keys=False, default_flow_style=False)


def list_entries() -> list[dict]:
    """All library entries, newest first (entries missing ``added`` sort last)."""
    if not LIBRARY_DIR.exists():
        return []
    entries: list[dict] = []
    for p in LIBRARY_DIR.glob("*.yaml"):
        try:
            entries.append(_read(p))
        except Exception:  # noqa: BLE001 — skip a corrupt sidecar, don't fail the list
            continue
    entries.sort(key=lambda e: e.get("added") or "", reverse=True)
    return entries


def get_entry(entry_id: str) -> dict:
    """Return one entry by id, or raise ``FileNotFoundError``."""
    p = _path(entry_id)
    if not p.exists():
        raise FileNotFoundError(f"No library entry {entry_id!r} ({p})")
    return _read(p)


def add_entry(block_name: str, *, title: str | None = None,
              collection: str = "", note: str = "") -> dict:
    """Add a block to the library. Idempotent per block: re-adding keeps the
    original ``added`` timestamp and ``favorite`` flag, but refreshes
    title / collection / note. The id is derived from ``block_name``."""
    if not block_name or not block_name.strip():
        raise ValueError("block_name is required.")
    entry_id = _safe_id(block_name)
    p = _path(entry_id)
    existing = _read(p) if p.exists() else {}
    entry = {
        "id": entry_id,
        "block_name": block_name.strip(),
        "title": (title or existing.get("title") or block_name).strip(),
        "favorite": bool(existing.get("favorite", False)),
        "collection": (collection or existing.get("collection") or "").strip(),
        "note": note if note else existing.get("note", ""),
        "added": existing.get("added")
        or datetime.now().isoformat(timespec="seconds"),
    }
    _write(p, entry)
    return entry


def set_favorite(entry_id: str, value: bool) -> dict:
    """Toggle an entry's favorite flag; raises ``FileNotFoundError`` if absent."""
    entry = get_entry(entry_id)
    entry["favorite"] = bool(value)
    _write(_path(entry_id), entry)
    return entry


def delete_entry(entry_id: str) -> bool:
    """Remove an entry. Returns True if it existed, False otherwise."""
    p = _path(entry_id)
    if p.exists():
        p.unlink()
        return True
    return False
