"""Render per-track audio stems via FluidSynth.

The renderer drives ``pretty_midi.PrettyMIDI.fluidsynth()`` (which itself
wraps the ``pyfluidsynth`` bindings to the Homebrew-installed
``libfluidsynth``). For each track in a :class:`MidiExporter`, we build a
single-instrument PrettyMIDI and synthesize it against the chosen
soundfont — yielding one mono float32 buffer per track.

Why per-track stems instead of one render?

- Lets us apply per-instrument effect chains (HPF on bass, transient on
  drums, plate verb on melody) before summing.
- Lets us pan tracks independently in the mix.
- Lets us export stems for the user to drop into Logic / Ardour.
"""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import fluidsynth
import numpy as np

from src.daw_integration.generic.midi_export import MidiExporter

from .soundfont_resolver import resolve_soundfont

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 44100


@dataclass
class TrackStem:
    """One rendered stem.

    ``audio`` is mono float32 at ``sample_rate`` Hz.
    """
    name: str
    program: int
    is_drum: bool
    audio: np.ndarray
    sample_rate: int = DEFAULT_SAMPLE_RATE


@dataclass
class RenderedStems:
    """Result of a per-track render pass."""
    sample_rate: int
    soundfont: Path
    stems: list[TrackStem] = field(default_factory=list)

    def by_name(self) -> dict[str, TrackStem]:
        return {s.name: s for s in self.stems}


class FluidSynthRenderer:
    """Render a :class:`MidiExporter` to per-track stems via FluidSynth.

    Holds a single ``fluidsynth.Synth`` and one ``sfload`` for the whole
    lifetime of the renderer; ``render_stems`` reuses it via
    ``system_reset()`` between tracks and between calls. Each
    ``Synth()`` ctor + 40 MB soundfont load grows the libfluidsynth heap
    (the OS does not return those pages on ``delete()``), so creating a
    new Synth per render leaks ~6 MB per call. Reusing one Synth pins
    that cost at construction time and keeps every subsequent render
    flat. Call :meth:`close` (or use the renderer as a context manager)
    to release the underlying synth.
    """

    def __init__(
        self,
        soundfont: Optional[str | Path] = None,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ):
        self.soundfont = resolve_soundfont(soundfont)
        self.sample_rate = sample_rate
        self._synth: Optional[fluidsynth.Synth] = None
        self._sfid: Optional[int] = None

    def _ensure_synth(self) -> tuple[fluidsynth.Synth, int]:
        if self._synth is None:
            synth = fluidsynth.Synth(samplerate=float(self.sample_rate))
            self._sfid = synth.sfload(str(self.soundfont))
            self._synth = synth
        assert self._sfid is not None
        return self._synth, self._sfid

    def close(self) -> None:
        """Release the underlying ``fluidsynth.Synth``. Idempotent."""
        synth = self._synth
        if synth is None:
            return
        self._synth = None
        sfid = self._sfid
        self._sfid = None
        try:
            if sfid is not None:
                try:
                    synth.sfunload(sfid)
                except Exception:
                    logger.debug("close: sfunload failed (non-fatal)",
                                 exc_info=True)
        finally:
            try:
                synth.delete()
            finally:
                gc.collect()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> "FluidSynthRenderer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def render_stems(self, midi: MidiExporter) -> RenderedStems:
        """Synthesize one mono buffer per track in ``midi``.

        Reuses the renderer's persistent ``fluidsynth.Synth`` across every
        track and every call. Older code used ``pm.fluidsynth(sf2_path=...)``
        per track, which constructed a fresh ``Synth`` and re-loaded the
        soundfont every time — leaking ~6 MB per render in libfluidsynth's
        internal heap.
        """
        if not midi.tracks:
            raise ValueError("MidiExporter has no tracks to render.")

        synth, sfid = self._ensure_synth()
        # Reset state from any prior render before rendering the first track.
        synth.system_reset()

        stems: list[TrackStem] = []
        for track_name, pm in midi.iter_single_track_pms():
            if not pm.instruments or not pm.instruments[0].notes:
                logger.debug("render: skipping empty track %r", track_name)
                continue
            inst = pm.instruments[0]
            try:
                raw = inst.fluidsynth(synthesizer=synth, sfid=sfid)
            except Exception:
                logger.exception(
                    "render: fluidsynth failed for track %r (program=%d "
                    "is_drum=%s); skipping",
                    track_name, inst.program, inst.is_drum,
                )
                synth.system_reset()
                continue
            # Match the per-track normalization that the old
            # ``pm.fluidsynth()`` path produced (single-instrument PM →
            # peak normalized to 1.0). Without this, downstream gain
            # staging in the mixer would shift relative to before.
            audio = np.asarray(raw, dtype=np.float32)
            del raw
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            if peak > 0.0:
                audio /= peak
            # Flush hanging notes + reverb tail before the next track
            # reuses this synth.
            synth.system_reset()
            stems.append(TrackStem(
                name=track_name,
                program=inst.program,
                is_drum=inst.is_drum,
                audio=audio,
                sample_rate=self.sample_rate,
            ))
            logger.info(
                "render: %s (program=%d drum=%s) → %.1fs",
                track_name, inst.program, inst.is_drum,
                len(audio) / self.sample_rate,
            )

        if not stems:
            raise ValueError(
                "All tracks rendered empty audio. Check that tracks have "
                "notes and that the soundfont contains the requested "
                "GM programs."
            )

        gc.collect()
        return RenderedStems(
            sample_rate=self.sample_rate,
            soundfont=self.soundfont,
            stems=stems,
        )
