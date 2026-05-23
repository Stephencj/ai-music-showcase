"""Top-level orchestration: MIDI → stems → mix → master → disk.

Use :func:`render_to_audio`. It accepts either a ``MidiExporter``
instance or a path to a ``.mid`` file (which is loaded back into a
fresh ``MidiExporter`` via ``pretty_midi``).
"""

from __future__ import annotations

import gc
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import numpy as np
import soundfile as sf

from src.daw_integration.generic.midi_export import MidiExporter, NoteEvent

from .effects import EffectChainLibrary, classify_family
from .mix import Mixer, ProcessedStem, _FAMILY_MIX
from .profiles import (
    apply_profile_to_family_mix,
    MIX_PROFILES,
    resolve_profile,
)
from .synth import FluidSynthRenderer, RenderedStems

logger = logging.getLogger(__name__)

MidiSource = Union[MidiExporter, str, Path]


@dataclass
class RenderResult:
    """File paths + metadata for a finished render."""
    mix_path: Path
    stem_paths: dict[str, Path] = field(default_factory=dict)
    manifest_path: Optional[Path] = None
    sample_rate: int = 44100
    soundfont: Optional[Path] = None
    master_preset: str = "default"
    duration_seconds: float = 0.0


def _load_midi(source: MidiSource) -> MidiExporter:
    """Coerce a MidiExporter or path to a MidiExporter."""
    if isinstance(source, MidiExporter):
        return source
    import pretty_midi
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"MIDI file not found: {path}")
    pm = pretty_midi.PrettyMIDI(str(path))
    # estimate_tempo() raises on a near-empty MIDI (<2 notes), which sparse
    # generations can produce. Fall back to the file's written tempo.
    try:
        tempo = float(pm.estimate_tempo()) if pm.instruments else 120.0
    except (ValueError, IndexError):
        _, _tempi = pm.get_tempo_changes()
        tempo = float(_tempi[0]) if len(_tempi) else 120.0
    if pm.time_signature_changes:
        ts = pm.time_signature_changes[0]
        time_sig = (ts.numerator, ts.denominator)
    else:
        time_sig = (4, 4)
    midi = MidiExporter(tempo=tempo, time_signature=time_sig)
    for inst in pm.instruments:
        notes = [
            NoteEvent(
                pitch=int(n.pitch),
                start=float(n.start),
                end=float(n.end),
                velocity=int(n.velocity),
            )
            for n in inst.notes
        ]
        midi.add_notes(
            notes=notes,
            track_name=inst.name or f"Track_{inst.program}",
            program=int(inst.program),
            is_drum=bool(inst.is_drum),
        )
    return midi


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    """Write float32 audio to a 16-bit PCM WAV.

    ``audio`` may be mono ``(N,)`` or ``(2, N)`` / ``(N, 2)`` stereo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = audio
    if data.ndim == 2 and data.shape[0] == 2:
        data = data.T
    sf.write(str(path), data, sample_rate, subtype="PCM_16")


def _safe_filename(name: str) -> str:
    keep = "-_."
    return "".join(c if c.isalnum() or c in keep else "_" for c in name).strip("_")


def render_to_audio(
    midi: MidiSource,
    *,
    output_dir: str | Path,
    soundfont: Optional[str | Path] = None,
    sample_rate: int = 44100,
    with_stems: bool = True,
    master_preset: Optional[str] = None,
    library: Optional[EffectChainLibrary] = None,
    mix_filename: str = "mix.wav",
    mix_profile: Optional[str] = None,
    style_name: Optional[str] = None,
) -> RenderResult:
    """Render MIDI to a finished mixed WAV (and optional per-track stems).

    Args:
        midi: A :class:`MidiExporter` or path to a ``.mid`` file.
        output_dir: Directory to write ``mix.wav`` and ``stems/`` into.
            Created if missing.
        soundfont: Path to a ``.sf2``/``.sf3``. Falls back to
            ``data/soundfonts/`` then to the bundled TimGM6mb.
        sample_rate: Render sample rate. 44.1 kHz is the default.
        with_stems: If True, write per-track stems to ``output_dir/stems/``.
        master_preset: ``default`` / ``loud`` / ``cinematic`` /
            ``transparent``. See :data:`MASTER_PRESETS`.
        library: Optional preconfigured :class:`EffectChainLibrary` (lets
            the caller override per-family chains).
        mix_filename: File name (just the leaf) for the final mix.

    Returns:
        :class:`RenderResult` with paths and metadata.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    midi_obj = _load_midi(midi)
    with FluidSynthRenderer(
        soundfont=soundfont, sample_rate=sample_rate
    ) as renderer:
        rendered: RenderedStems = renderer.render_stems(midi_obj)

    # Resolve the genre-aware mix profile. Priority:
    #   1. Explicit ``mix_profile=`` kwarg (e.g. "rock").
    #   2. Auto-resolution from ``style_name=`` via _PRESET_TO_PROFILE.
    #   3. Default to "pop" (vocal-forward streaming).
    if mix_profile and mix_profile in MIX_PROFILES:
        profile = MIX_PROFILES[mix_profile]
    else:
        profile = resolve_profile(style_name)
    eff_master = master_preset or profile.master_preset
    family_mix = apply_profile_to_family_mix(profile, _FAMILY_MIX)
    library = library or EffectChainLibrary()
    mixer = Mixer(
        library=library,
        family_mix=family_mix,
        sidechain_kick_into=profile.sidechain_kick_into,
    )
    mix, processed = mixer.mix(rendered, master_preset=eff_master)

    mix_path = output_dir / mix_filename
    _write_wav(mix_path, mix, sample_rate)
    duration = mix.shape[-1] / sample_rate

    stem_paths: dict[str, Path] = {}
    if with_stems:
        stems_dir = output_dir / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)
        for proc in processed:
            fname = f"{_safe_filename(proc.name)}.wav"
            p = stems_dir / fname
            _write_wav(p, proc.audio, sample_rate)
            stem_paths[proc.name] = p

    manifest_path = _write_manifest(
        output_dir=output_dir,
        midi_obj=midi_obj,
        rendered=rendered,
        processed=processed,
        mix_path=mix_path,
        stem_paths=stem_paths,
        master_preset=eff_master,
        duration=duration,
    )

    logger.info(
        "render_to_audio: wrote %s (%.1fs, %d stems)",
        mix_path, duration, len(stem_paths),
    )

    soundfont_path = rendered.soundfont
    del rendered, processed, mix, mixer
    gc.collect()

    return RenderResult(
        mix_path=mix_path,
        stem_paths=stem_paths,
        manifest_path=manifest_path,
        sample_rate=sample_rate,
        soundfont=soundfont_path,
        master_preset=eff_master,
        duration_seconds=duration,
    )


def _write_manifest(
    *,
    output_dir: Path,
    midi_obj: MidiExporter,
    rendered: RenderedStems,
    processed: list[ProcessedStem],
    mix_path: Path,
    stem_paths: dict[str, Path],
    master_preset: str,
    duration: float,
) -> Path:
    manifest = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "tempo": float(midi_obj.tempo),
        "time_signature": list(midi_obj.time_signature),
        "sample_rate": rendered.sample_rate,
        "soundfont": str(rendered.soundfont),
        "master_preset": master_preset,
        "duration_seconds": round(duration, 3),
        "mix": str(mix_path.relative_to(output_dir)),
        "stems": [
            {
                "name": p.name,
                "family": p.family,
                "file": str(stem_paths[p.name].relative_to(output_dir))
                        if p.name in stem_paths else None,
            }
            for p in processed
        ],
        "tracks": [
            {
                "name": t.name,
                "program": t.program,
                "is_drum": t.is_drum,
                "family": classify_family(t.name, t.program, t.is_drum),
            }
            for t in midi_obj.tracks
        ],
    }
    manifest_path = output_dir / "render_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path
