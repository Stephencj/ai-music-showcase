"""
Block storage — pre-rendered MIDI snippets with sidecar metadata + audio
preview.

A "block" is one rendered piece of music (typically a verse / chorus / bridge
worth of bars). Each block lives at:

    data/blocks/<name>.mid    — the pretty_midi-written MIDI file
    data/blocks/<name>.yaml   — metadata for the library view
    data/blocks/<name>.wav    — synthesized preview for instant playback
                                (lazily generated if missing)

The Compose Song tab arranges blocks on a timeline and concatenates them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pretty_midi
import soundfile as sf
import yaml


BLOCKS_DIR = Path("data/blocks")

_DEFAULT_PREVIEW_SR = 22050  # sample rate for the preview WAV (smaller than 44.1k to save disk)


def _safe_name(name: str) -> str:
    s = name.strip().replace("/", "_").replace("\\", "_").replace(" ", "_")
    return s or "untitled"


def _ensure_dir() -> None:
    BLOCKS_DIR.mkdir(parents=True, exist_ok=True)


def _yaml_path(name: str) -> Path:
    return BLOCKS_DIR / f"{_safe_name(name)}.yaml"


def _midi_path(name: str) -> Path:
    return BLOCKS_DIR / f"{_safe_name(name)}.mid"


def _wav_path(name: str) -> Path:
    return BLOCKS_DIR / f"{_safe_name(name)}.wav"


def _instrument_summary(pm: pretty_midi.PrettyMIDI) -> list[dict]:
    """Compact per-instrument descriptor for the library card."""
    out: list[dict] = []
    for inst in pm.instruments:
        out.append({
            "name": inst.name or "unnamed",
            "program": int(inst.program),
            "is_drum": bool(inst.is_drum),
            "n_notes": len(inst.notes),
        })
    return out


def _total_notes(pm: pretty_midi.PrettyMIDI) -> int:
    return sum(len(i.notes) for i in pm.instruments)


def save_block(name: str,
               pm: pretty_midi.PrettyMIDI,
               *,
               tempo: float,
               time_signature: tuple[int, int],
               bars: int,
               overwrite: bool = False,
               write_wav: bool = True,
               wav_sample_rate: int = _DEFAULT_PREVIEW_SR) -> Path:
    """Persist a block. Writes .mid + .yaml (and .wav unless ``write_wav=False``).

    Returns the .yaml path. Raises FileExistsError on collision unless
    ``overwrite=True``. Raises ValueError if the MIDI has zero notes (would
    produce a zero-duration entry on the timeline).
    """
    if _total_notes(pm) == 0:
        raise ValueError(
            f"Block {name!r} has no notes — refusing to save. "
            "Render something first."
        )
    _ensure_dir()
    yaml_path = _yaml_path(name)
    midi_path = _midi_path(name)
    wav_path = _wav_path(name)
    if not overwrite and (yaml_path.exists() or midi_path.exists()):
        raise FileExistsError(
            f"A block named {name!r} already exists. "
            "Pick a different name or pass overwrite=True."
        )

    pm.write(str(midi_path))

    metadata = {
        "name": _safe_name(name),
        "tempo": float(tempo),
        "time_signature": [int(time_signature[0]), int(time_signature[1])],
        "bars": int(bars),
        "duration_seconds": float(pm.get_end_time()),
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "instruments": _instrument_summary(pm),
        "n_notes": _total_notes(pm),
    }
    with open(yaml_path, "w") as f:
        yaml.safe_dump(metadata, f, sort_keys=False, default_flow_style=False)

    if write_wav:
        try:
            audio = pm.synthesize(fs=wav_sample_rate)
            sf.write(str(wav_path), audio, wav_sample_rate)
        except Exception:
            # Preview is nice-to-have; don't block save if synth fails.
            pass

    return yaml_path


def list_blocks() -> list[dict]:
    """Return metadata for every block in BLOCKS_DIR, sorted by name.

    Filters out two YAML-file categories that share the directory but
    aren't blocks:

      - ``*_melody.yaml`` — Melody Studio plan sidecars (no ``.mid``,
        no ``name`` field; they attach edits to a sibling block).
      - Files whose metadata lacks a ``name`` field, indicating a
        malformed or non-block YAML that would only confuse the UI.
    """
    if not BLOCKS_DIR.exists():
        return []
    out: list[dict] = []
    for yaml_file in sorted(BLOCKS_DIR.glob("*.yaml")):
        if yaml_file.stem.endswith("_melody"):
            continue
        try:
            with open(yaml_file, "r") as f:
                meta = yaml.safe_load(f) or {}
            if not meta.get("name"):
                continue
            meta["_yaml_path"] = str(yaml_file)
            meta["_midi_path"] = str(yaml_file.with_suffix(".mid"))
            wav = yaml_file.with_suffix(".wav")
            meta["_wav_path"] = str(wav) if wav.exists() else None
            out.append(meta)
        except Exception:
            continue
    return out


def load_block(name: str) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Return (PrettyMIDI, metadata dict). Raises FileNotFoundError if missing."""
    midi_path = _midi_path(name)
    yaml_path = _yaml_path(name)
    if not midi_path.exists():
        raise FileNotFoundError(f"Block MIDI not found: {midi_path}")
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    meta: dict = {}
    if yaml_path.exists():
        with open(yaml_path, "r") as f:
            meta = yaml.safe_load(f) or {}
    return pm, meta


def ensure_preview_wav(name: str, sample_rate: int = _DEFAULT_PREVIEW_SR) -> Optional[Path]:
    """Lazy-synth a .wav preview if it's missing. Returns the path or None on failure."""
    wav_path = _wav_path(name)
    if wav_path.exists():
        return wav_path
    midi_path = _midi_path(name)
    if not midi_path.exists():
        return None
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        audio = pm.synthesize(fs=sample_rate)
        sf.write(str(wav_path), audio, sample_rate)
        return wav_path
    except Exception:
        return None


def delete_block(name: str) -> None:
    """Remove the .mid, .yaml, .wav, and Melody Studio sidecar for a
    block. Silently ignores missing files."""
    safe = _safe_name(name)
    sidecar = BLOCKS_DIR / f"{safe}_melody.yaml"
    for p in (_midi_path(name), _yaml_path(name), _wav_path(name), sidecar):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
