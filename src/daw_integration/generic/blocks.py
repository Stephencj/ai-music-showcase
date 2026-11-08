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
import json
import logging
import re
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
    spec: Optional[dict] = None,
) -> bool:
    """Render ``pm`` via the project's HQ pipeline (FluidSynthRenderer
    + Mixer) and write a stereo WAV to ``wav_path``. ``spec`` (the block's
    generation spec) renders it in its style: sampled instruments, lead
    voice, mix and loudness, like the generation itself.

    Returns True on success, False on any failure (missing soundfont,
    fluidsynth not installed, OOM mid-mix). The caller decides whether
    to fall back to a lower-quality path or just skip the preview —
    block save itself is never blocked by a preview failure.
    """
    try:
        # Lazy imports so blocks.py stays useful without dragging in
        # the audio_processing stack on import (keeps test load fast).
        from src.audio_processing.render.pipeline import (
            level_wav, render_to_audio, style_lufs, style_render_args,
        )
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
                **style_render_args(spec),
            )
            if style_lufs(spec) is not None:
                level_wav(result.mix_path, style_lufs(spec))
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
    spec: Optional[dict] = None,
) -> bool:
    """Best-effort preview WAV: try HQ first, fall back to the
    pretty_midi path on any failure. Returns True if SOME audio
    landed at ``wav_path``."""
    if _write_block_wav_hq(pm, wav_path, sample_rate=sample_rate, spec=spec):
        return True
    return _write_block_wav_fallback(pm, wav_path, sample_rate=22050)


def _adopt_audio(src: "Path | str", wav_path: Path) -> bool:
    """Make ``wav_path`` a WAV copy of an already-rendered mix (WAV or MP3).
    False when the source is missing or can't be converted."""
    src = Path(src)
    if not src.exists() or src.stat().st_size == 0:
        return False
    try:
        if src.suffix.lower() == ".wav":
            shutil.copyfile(src, wav_path)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), str(wav_path)],
                           check=True, timeout=300)
        return wav_path.exists() and wav_path.stat().st_size > 0
    except Exception:  # noqa: BLE001
        return False


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
               wav_sample_rate: int = _DEFAULT_PREVIEW_SR,
               spec: Optional[dict] = None,
               tags: Optional[list[str]] = None,
               audio_source: "Optional[Path | str]" = None) -> Path:
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
    if spec is not None:
        metadata["spec"] = spec       # generation provenance (regenerate / edit-in-generate)
    if tags:
        metadata["tags"] = [str(t) for t in tags]
    with open(yaml_path, "w") as f:
        yaml.safe_dump(metadata, f, sort_keys=False, default_flow_style=False)

    if write_wav and audio_source and _adopt_audio(audio_source, wav_path):
        # The generation's own final mix (its sampled instruments, mix and
        # loudness): keep that rather than re-rendering the MIDI on the
        # General MIDI soundfont, which sounds nothing like what was made.
        write_preview_mp3(wav_path, _preview_path(name))
    elif write_wav:
        # HQ first (44.1 kHz stereo via FluidSynthRenderer + Mixer);
        # graceful fallback to pretty_midi.synthesize on failure.
        if _write_block_wav(pm, wav_path, sample_rate=wav_sample_rate, spec=spec):
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
            vdir = BLOCKS_DIR / f"{yaml_file.stem}.vocals"
            meta["_vocal_takes"] = (
                sum(1 for d in vdir.iterdir() if d.is_dir() and (d / "meta.json").exists())
                if vdir.exists() else 0
            )
            meta.setdefault("tags", [])
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


def block_spec(name: str) -> Optional[dict]:
    """The block's generation spec (its genre, lead voice, …), if it has one."""
    try:
        with open(_yaml_path(name), "r") as f:
            return (yaml.safe_load(f) or {}).get("spec") or None
    except Exception:
        return None


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
    if _write_block_wav(pm, wav_path, sample_rate=sample_rate, spec=block_spec(name)):
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
    if _write_block_wav(pm, wav_path, sample_rate=sample_rate, spec=block_spec(name)):
        # Refresh the compact MP3 the UI streams alongside the HQ WAV.
        write_preview_mp3(wav_path, _preview_path(name))
        return wav_path
    return None


# --------------------------------------------------------------------------
# Vocal takes — persisted sung renders per block, so the user can keep,
# re-select, or delete previous generations. Each take lives at:
#     data/blocks/<name>.vocals/<take_id>/{mix.mp3, vocal.mp3, score.zip,
#                                          meta.json}
# (gitignored audio; meta.json holds the lyrics + engine/voice used).
# --------------------------------------------------------------------------
def _vocals_dir(name: str) -> Path:
    return BLOCKS_DIR / f"{_safe_name(name)}.vocals"


def _safe_take_id(take_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", take_id or "")


def save_vocal_take(name: str, *, mix: "Path | str | None" = None,
                    vocal: "Path | str | None" = None,
                    score: "Path | str | None" = None,
                    lyrics: str = "", engine: str = "", voice: str = "",
                    harmonies: bool = True, clarity: bool = False,
                    phonetic: str = "", section_engines: "list | None" = None) -> dict:
    """Persist one sung render as a dated take under the block. Copies the
    given mix / vocal-stem / score files in and writes a ``meta.json``.
    Returns the take's metadata dict (with a unique, sortable ``id``)."""
    take_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    take_dir = _vocals_dir(name) / take_id
    take_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}
    for src, role, default_ext in ((mix, "mix", ".mp3"),
                                   (vocal, "vocal", ".mp3"),
                                   (score, "score", ".zip")):
        if not src:
            continue
        sp = Path(src)
        if not sp.exists():
            continue
        dst = take_dir / f"{role}{sp.suffix or default_ext}"
        try:
            shutil.copy2(sp, dst)
            files[role] = dst.name
        except OSError:
            logger.warning("could not copy %s into vocal take %s", sp, take_id)

    meta = {
        "id": take_id,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "engine": engine, "voice": voice, "harmonies": bool(harmonies),
        "clarity": bool(clarity), "phonetic": phonetic or "",
        "section_engines": section_engines or [],
        "lyrics": lyrics, "files": files,
    }
    (take_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def list_vocal_takes(name: str) -> list[dict]:
    """All persisted takes for a block, newest first."""
    base = _vocals_dir(name)
    if not base.exists():
        return []
    takes: list[dict] = []
    for d in base.iterdir():
        meta_path = d / "meta.json"
        if not d.is_dir() or not meta_path.exists():
            continue
        try:
            takes.append(json.loads(meta_path.read_text()))
        except (OSError, ValueError):
            continue
    takes.sort(key=lambda t: str(t.get("created", "")), reverse=True)
    return takes


def vocal_take_file(name: str, take_id: str, role: str) -> Optional[Path]:
    """Path to a take's ``mix`` / ``vocal`` / ``score`` artifact, or None."""
    take_dir = _vocals_dir(name) / _safe_take_id(take_id)
    meta_path = take_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        files = json.loads(meta_path.read_text()).get("files", {})
    except (OSError, ValueError):
        return None
    fn = files.get(role)
    if not fn:
        return None
    p = take_dir / fn
    return p if p.exists() else None


def delete_vocal_take(name: str, take_id: str) -> bool:
    """Remove one take. Returns True if it existed."""
    d = _vocals_dir(name) / _safe_take_id(take_id)
    if d.exists() and d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def set_preview_take(name: str, take_id: "str | None") -> None:
    """Point the block's play/preview audio at a saved vocal take's mix, or
    clear it (``take_id=None``) to revert to the instrumental preview. Stored
    as ``preview_take`` in the block yaml — non-destructive: the instrumental
    ``.mp3`` / ``.wav`` are untouched, so this is fully reversible."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    if take_id:
        tid = _safe_take_id(take_id)
        if not vocal_take_file(name, tid, "mix"):
            raise FileNotFoundError(f"No mix for take {take_id!r}")
        meta["preview_take"] = tid
    else:
        meta.pop("preview_take", None)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def active_preview_audio(name: str,
                         sample_rate: int = _DEFAULT_PREVIEW_SR) -> Optional[Path]:
    """The audio the block's play button should stream: a chosen vocal take's
    mix when ``preview_take`` is set (and still present), otherwise the
    instrumental preview."""
    yaml_path = _yaml_path(name)
    if yaml_path.exists():
        try:
            with open(yaml_path, "r") as f:
                tid = (yaml.safe_load(f) or {}).get("preview_take")
        except Exception:  # noqa: BLE001
            tid = None
        if tid:
            p = vocal_take_file(name, tid, "mix")
            if p:
                return p
    return ensure_preview_audio(name, sample_rate=sample_rate)


def delete_block(name: str) -> None:
    """Remove the .mid, .yaml, .wav, .mp3, .peaks.json, cached .musicxml,
    Melody Studio sidecar, and saved vocal takes for a block. Silently ignores missing
    files."""
    safe = _safe_name(name)
    sidecar = BLOCKS_DIR / f"{safe}_melody.yaml"
    for p in (_midi_path(name), _yaml_path(name), _wav_path(name),
              _preview_path(name), _peaks_path(name), sidecar,
              BLOCKS_DIR / f"{safe}.musicxml"):          # the cached score (block_musicxml)
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
    shutil.rmtree(_vocals_dir(name), ignore_errors=True)
    shutil.rmtree(BLOCKS_DIR / f"{safe}.versions", ignore_errors=True)


def _peaks_path(name: str) -> Path:
    return BLOCKS_DIR / f"{_safe_name(name)}.peaks.json"


def block_peaks(name: str, buckets: int = 64) -> Optional[list[float]]:
    """Return a small normalized waveform-peak array (0..1) for a sleek
    thumbnail, computed once from the block WAV and cached as a sidecar."""
    import json
    pp = _peaks_path(name)
    if pp.exists():
        try:
            return json.loads(pp.read_text())
        except Exception:
            pass
    peaks = wav_peaks(_wav_path(name), buckets)
    if peaks is None:
        return None
    try:
        pp.write_text(json.dumps(peaks))
    except OSError:
        pass
    return peaks


def wav_peaks(wav: Path, buckets: int = 64) -> Optional[list[float]]:
    """``buckets`` normalized (0..1) absolute peaks of an audio file, evenly
    spaced in time; None when it can't be read."""
    if not Path(wav).exists():
        return None
    try:
        data, _ = sf.read(str(wav), dtype="float32")
    except Exception:
        return None
    if getattr(data, "ndim", 1) == 2:
        data = data.mean(axis=1)
    n = len(data)
    if n == 0:
        return None
    edges = np.linspace(0, n, buckets + 1).astype(int)
    peaks = [
        float(np.abs(data[edges[i]:edges[i + 1]]).max()) if edges[i + 1] > edges[i] else 0.0
        for i in range(buckets)
    ]
    peak_max = max(peaks) or 1.0
    return [round(p / peak_max, 3) for p in peaks]


def set_tags(name: str, tags: list[str]) -> list[str]:
    """Replace a block's tag list (used for collections / grouping)."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    clean = sorted({str(t).strip() for t in tags if str(t).strip()})
    meta["tags"] = clean
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)
    return clean


def set_lyrics(name: str, lyrics: str) -> None:
    """Store lyrics on a block (they travel with it; vocals re-render on demand)."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    meta["lyrics"] = str(lyrics)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def set_spec(name: str, spec: dict) -> None:
    """Attach/replace a block's generation spec (provenance)."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    meta["spec"] = spec
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def set_session(name: str, session: Optional[dict]) -> None:
    """Link a block to the Create session it came from (``{id, version}``),
    or unlink it (``None``): Library → Open in Timeline reopens that session."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    if session:
        meta["session"] = dict(session)
    else:
        meta.pop("session", None)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def read_meta(name: str) -> Optional[dict]:
    """A block's metadata (its .yaml), or None when there's no such block."""
    yaml_path = _yaml_path(name)
    if not yaml_path.exists():
        return None
    with open(yaml_path, "r") as f:
        return yaml.safe_load(f) or {}


def _estimate_key(midi_path: Path) -> tuple[str, str]:
    """Best-effort key/mode from the MIDI via music21. Falls back to C major."""
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    try:
        from music21 import converter
        analyzed = converter.parse(str(midi_path)).analyze("key")
        tonic = names[analyzed.tonic.pitchClass]
        mode = "minor" if analyzed.mode == "minor" else "major"
        return tonic, mode
    except Exception:
        return "C", "major"


def infer_spec(name: str, default_genre: str = "pop") -> Optional[dict]:
    """Build a *best-effort* generation spec for a block that predates
    provenance. Instruments come from the track names; key/mode are
    estimated from the MIDI; tempo/meter from metadata. Genre can't be
    recovered, so it defaults (caller marks ``inferred=True``). Good enough
    to seed "Edit in Generate"; NOT a basis for per-instrument regenerate
    (the guessed genre's progression would clash)."""
    midi_path = _midi_path(name)
    if not midi_path.exists():
        return None
    try:
        pm = pretty_midi.PrettyMIDI(str(midi_path))
        with open(_yaml_path(name), "r") as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        return None

    from src.composition.instruments import INSTRUMENT_REGISTRY
    by_label: dict[str, str] = {}
    for iid, inst in INSTRUMENT_REGISTRY.items():
        by_label[(inst.label or "").lower()] = iid
        tn = getattr(inst, "track_name", None)
        if tn:
            by_label[tn.lower()] = iid
    inst_ids: list[str] = []
    for i in pm.instruments:
        iid = by_label.get((i.name or "").lower())
        if iid and iid not in inst_ids:
            inst_ids.append(iid)

    key, scale = _estimate_key(midi_path)
    ts = meta.get("time_signature") or [4, 4]
    bars = int(meta.get("bars") or 0)
    sections = (
        [{"start_bar": 0, "end_bar": max(0, bars - 1), "label": "Section", "role": "verse"}]
        if bars else []
    )
    return {
        "genre": default_genre,
        "key": key, "scale": scale,
        "tempo": float(meta.get("tempo") or 120.0),
        "time_signature": [int(ts[0]), int(ts[1])],
        "seed": None, "swing": None,
        "instruments": inst_ids,
        "sections": sections,
        "section": None,
        "inferred": True,
    }


def rename_block(old: str, new: str) -> str:
    """Rename a block (and all its sidecars). Returns the new safe name.
    Raises FileExistsError on collision, FileNotFoundError if missing."""
    if not new or not new.strip():
        raise ValueError("New name is empty.")
    old_safe, new_safe = _safe_name(old), _safe_name(new)
    if new_safe == old_safe:
        return new_safe
    if _yaml_path(new).exists() or _midi_path(new).exists():
        raise FileExistsError(f"A block named {new_safe!r} already exists.")
    if not _yaml_path(old).exists():
        raise FileNotFoundError(f"Block not found: {old}")
    pairs = [
        (_midi_path(old), _midi_path(new)),
        (_yaml_path(old), _yaml_path(new)),
        (_wav_path(old), _wav_path(new)),
        (_preview_path(old), _preview_path(new)),
        (_peaks_path(old), _peaks_path(new)),
        (BLOCKS_DIR / f"{old_safe}_melody.yaml", BLOCKS_DIR / f"{new_safe}_melody.yaml"),
    ]
    for src, dst in pairs:
        if src.exists():
            src.rename(dst)
    # Move the per-block directories too (saved vocal takes + versions), so a
    # rename doesn't orphan them under the old name.
    for suffix in (".vocals", ".versions"):
        src_dir = BLOCKS_DIR / f"{old_safe}{suffix}"
        if src_dir.exists():
            src_dir.rename(BLOCKS_DIR / f"{new_safe}{suffix}")
    yaml_path = _yaml_path(new)
    with open(yaml_path, "r") as f:
        meta = yaml.safe_load(f) or {}
    meta["name"] = new_safe
    with open(yaml_path, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)
    return new_safe
