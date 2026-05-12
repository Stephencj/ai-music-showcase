"""
User-defined presets: track / section / song.

Three layers of YAML-backed presets the Compose-Song UI saves to. Built-in
``STYLES`` in ``styles.py`` are never modified — user saves go to a parallel
filesystem store under ``data/presets/`` and ``data/song_specs/user/``.

By default, ``save_*`` refuses to overwrite an existing file (the user
explicitly said "do not override existing"). Pass ``overwrite=True`` if a
caller really wants to clobber.
"""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .song_spec import Section, SongSpec


PRESETS_BASE = Path("data/presets")
TRACKS_DIR = PRESETS_BASE / "tracks"
SECTIONS_DIR = PRESETS_BASE / "sections"
SONGS_DIR = Path("data/song_specs/user")


def _safe_name(name: str) -> str:
    """Filesystem-safe slug. Keeps spaces as underscores; strips path separators."""
    s = name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
    return s or "untitled"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _list_yaml_basenames(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(p.stem for p in path.glob("*.yaml"))


def _write_yaml(path: Path, data: Any, overwrite: bool) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"{path} already exists. Pick a different name or pass overwrite=True."
        )
    _ensure_dir(path.parent)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    return path


def _read_yaml(path: Path) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Track presets — single freeform-track config
# ---------------------------------------------------------------------------
# Stored shape: a single dict matching one entry of Section.custom_tracks
# (without the track_name — the user supplies that when applying).

def list_track_presets() -> list[str]:
    return _list_yaml_basenames(TRACKS_DIR)


def load_track_preset(name: str) -> dict:
    path = TRACKS_DIR / f"{_safe_name(name)}.yaml"
    return _read_yaml(path)


def save_track_preset(name: str, config: dict, overwrite: bool = False) -> Path:
    if not isinstance(config, dict) or "type" not in config:
        raise ValueError("Track preset must be a dict with a 'type' field.")
    payload = {k: v for k, v in config.items() if k != "track_name"}
    return _write_yaml(TRACKS_DIR / f"{_safe_name(name)}.yaml", payload, overwrite)


# ---------------------------------------------------------------------------
# Section presets — single Section snapshot
# ---------------------------------------------------------------------------

def list_section_presets() -> list[str]:
    return _list_yaml_basenames(SECTIONS_DIR)


def load_section_preset(name: str) -> Section:
    payload = _read_yaml(SECTIONS_DIR / f"{_safe_name(name)}.yaml")
    return Section(**payload)


def save_section_preset(name: str, section: Section, overwrite: bool = False) -> Path:
    payload = _dataclass_to_clean_dict(section)
    return _write_yaml(SECTIONS_DIR / f"{_safe_name(name)}.yaml", payload, overwrite)


# ---------------------------------------------------------------------------
# Song presets — full SongSpec (mirrors data/song_specs/*.yaml shape)
# ---------------------------------------------------------------------------

def list_song_presets() -> list[str]:
    return _list_yaml_basenames(SONGS_DIR)


def load_song_preset(name: str) -> SongSpec:
    payload = _read_yaml(SONGS_DIR / f"{_safe_name(name)}.yaml")
    sections_data = payload.pop("sections", []) or []
    sections = [Section(**s) for s in sections_data]
    return SongSpec(sections=sections, **payload)


def save_song_preset(name: str, spec: SongSpec, overwrite: bool = False) -> Path:
    payload = _dataclass_to_clean_dict(spec)
    payload["sections"] = [_dataclass_to_clean_dict(s) for s in spec.sections]
    return _write_yaml(SONGS_DIR / f"{_safe_name(name)}.yaml", payload, overwrite)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dataclass_to_clean_dict(obj: Any) -> dict:
    """asdict(obj) but drop keys whose value is None.

    Empty lists are preserved — Section.tracks=[] is a meaningful sentinel
    ("no primary tracks, freeform-only") and must survive save/load round-trip.
    """
    if hasattr(obj, "__dataclass_fields__"):
        raw = asdict(obj)
    elif isinstance(obj, dict):
        raw = obj
    else:
        raise TypeError(f"Cannot serialize {type(obj).__name__}")
    return {k: v for k, v in raw.items() if v is not None}
