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

Preview WAVs render at 44.1 kHz stereo via FluidSynthRenderer + the
project's Mixer (same path Compose Song's "Render HQ" uses), with a
graceful fallback to ``pretty_midi.synthesize`` (22 kHz mono) when
FluidSynth isn't available — block save shouldn't fail just because
the soundfont is missing in some constrained environment.
"""

from __future__ import annotations

import datetime as _dt
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pretty_midi
import soundfile as sf
import yaml


logger = logging.getLogger("ai_music_studio.blocks")


BLOCKS_DIR = Path("data/blocks")

_DEFAULT_PREVIEW_SR = 44100  # 44.1 kHz stereo, matches Compose Song HQ render


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


def _preview_path(name: str) -> Path:
    """The small, browser/iOS-friendly preview that the UI actually
    streams. MP3 (not OGG/Vorbis) on purpose: Safari/iOS — the priority
    target — only gained Ogg Vorbis support in 17.4, while MP3 plays on
    every iOS version and every browser."""
    return BLOCKS_DIR / f"{_safe_name(name)}.mp3"


_PREVIEW_BITRATE = "128k"  # ~2.5 MB/min stereo — a 4½-min song lands ~4 MB


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


def _write_block_wav_hq(
    pm: pretty_midi.PrettyMIDI, wav_path: Path,
    sample_rate: int = _DEFAULT_PREVIEW_SR,
) -> bool:
    """Render ``pm`` via the project's HQ pipeline (FluidSynthRenderer
    + Mixer) and write a stereo WAV to ``wav_path``.

    Returns True on success, False on any failure (missing soundfont,
    fluidsynth not installed, OOM mid-mix). The caller decides whether
    to fall back to a lower-quality path or just skip the preview —
    block save itself is never blocked by a preview failure.
    """
    try:
        # Lazy imports so blocks.py stays useful without dragging in
        # the audio_processing stack on import (keeps test load fast).
        from src.audio_processing.render.pipeline import render_to_audio
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            midi_tmp = tmp_dir / "block.mid"
            pm.write(str(midi_tmp))
            result = render_to_audio(
                midi=midi_tmp,
                output_dir=tmp_dir / "render",
                sample_rate=sample_rate,
                with_stems=False,
                master_preset="default",
            )
            # Move the rendered mix.wav onto the block's expected path.
            wav_path.parent.mkdir(parents=True, exist_ok=True)
            # shutil.move is safe across same-filesystem temp dirs.
            import shutil
            shutil.move(str(result.mix_path), str(wav_path))
        return True
    except Exception as e:
        logger.warning("HQ block render failed for %s: %s", wav_path, e)
        return False


def _write_block_wav_fallback(
    pm: pretty_midi.PrettyMIDI, wav_path: Path, sample_rate: int = 22050,
) -> bool:
    """Last-resort preview render via pretty_midi.synthesize (mono,
    sine-y). Used when the HQ pipeline can't fire in the current
    environment (no soundfont, no fluidsynth, etc.)."""
    try:
        audio = pm.synthesize(fs=sample_rate)
        sf.write(str(wav_path), audio, sample_rate)
        return True
    except Exception as e:
        logger.warning("Fallback block render failed for %s: %s", wav_path, e)
        return False


def _write_block_wav(
    pm: pretty_midi.PrettyMIDI, wav_path: Path,
    sample_rate: int = _DEFAULT_PREVIEW_SR,
) -> bool:
    """Best-effort preview WAV: try HQ first, fall back to the
    pretty_midi path on any failure. Returns True if SOME audio
    landed at ``wav_path``."""
    if _write_block_wav_hq(pm, wav_path, sample_rate=sample_rate):
        return True
    return _write_block_wav_fallback(pm, wav_path, sample_rate=22050)


def write_preview_mp3(wav_path: "Path | str", mp3_path: "Path | str",
                      bitrate: str = _PREVIEW_BITRATE) -> bool:
    """Transcode an existing WAV into a small, universally-playable MP3.

    The 30–47 MB multi-minute WAVs that full-song blocks produce render
    as a *blank* player in the Gradio audio widget (worst on the iPhone
    WKWebView). A ~3–4 MB MP3 streams instantly instead. Encoding runs
    straight off the on-disk WAV — no 250-second buffer is ever held in
    RAM — so memory stays flat and we dodge the encoder segfault seen
    when feeding long buffers to libsndfile directly.

    Tries ffmpeg first (robust streaming encoder), then libsndfile's MP3
    writer. Returns True iff a non-empty MP3 landed at ``mp3_path``.
    """
    wav_path = Path(wav_path)
    mp3_path = Path(mp3_path)
    if not wav_path.exists():
        return False
    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        try:
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path),
                 "-c:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)],
                check=True, capture_output=True,
            )
            if mp3_path.exists() and mp3_path.stat().st_size > 0:
                return True
        except Exception as e:
            logger.warning("ffmpeg mp3 encode failed for %s: %s", mp3_path, e)

    # Fallback: libsndfile MP3 (build here reports MP3 write support).
    try:
        data, sr = sf.read(str(wav_path))
        sf.write(str(mp3_path), data, sr, format="MP3")
        if mp3_path.exists() and mp3_path.stat().st_size > 0:
            return True
    except Exception as e:
        logger.warning("soundfile mp3 encode failed for %s: %s", mp3_path, e)
    return False


def ensure_preview_audio(name: str,
                         sample_rate: int = _DEFAULT_PREVIEW_SR) -> Optional[Path]:
    """Return the small streaming preview the UI should play (MP3), making
    sure both the source WAV and the MP3 exist first. Falls back to the
    WAV path if MP3 encoding isn't available in this environment."""
    wav = ensure_preview_wav(name, sample_rate=sample_rate)
    if wav is None:
        return None
    mp3 = _preview_path(name)
    if not mp3.exists():
        write_preview_mp3(wav, mp3)
    return mp3 if mp3.exists() else wav


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
        # HQ first (44.1 kHz stereo via FluidSynthRenderer + Mixer);
        # graceful fallback to pretty_midi.synthesize on failure.
        if _write_block_wav(pm, wav_path, sample_rate=wav_sample_rate):
            # Compact MP3 the UI actually streams (the raw WAV is too big
            # to load in the player for full-length songs).
            write_preview_mp3(wav_path, _preview_path(name))

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
            mp3 = yaml_file.with_suffix(".mp3")
            meta["_preview_path"] = str(mp3) if mp3.exists() else None
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
    """Lazy-synth a .wav preview if it's missing. Returns the path or None on failure.

    Uses the same HQ-first dispatch as :func:`save_block` so lazy
    previews match the eager ones at 44.1 kHz stereo.
    """
    wav_path = _wav_path(name)
    if wav_path.exists():
        return wav_path
    midi_path = _midi_path(name)
    if not midi_path.exists():
        return None
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception:
        return None
    if _write_block_wav(pm, wav_path, sample_rate=sample_rate):
        return wav_path
    return None


def rerender_block_wav(name: str, sample_rate: int = _DEFAULT_PREVIEW_SR) -> Optional[Path]:
    """Force-re-render a block's preview WAV to HQ regardless of
    whether a cached one exists. Used by the Library's
    'Re-render all blocks at HQ' batch operation."""
    midi_path = _midi_path(name)
    if not midi_path.exists():
        return None
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception:
        return None
    wav_path = _wav_path(name)
    if _write_block_wav(pm, wav_path, sample_rate=sample_rate):
        # Refresh the compact MP3 the UI streams alongside the HQ WAV.
        write_preview_mp3(wav_path, _preview_path(name))
        return wav_path
    return None


def delete_block(name: str) -> None:
    """Remove the .mid, .yaml, .wav, .mp3, and Melody Studio sidecar for
    a block. Silently ignores missing files."""
    safe = _safe_name(name)
    sidecar = BLOCKS_DIR / f"{safe}_melody.yaml"
    for p in (_midi_path(name), _yaml_path(name), _wav_path(name),
              _preview_path(name), sidecar):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
