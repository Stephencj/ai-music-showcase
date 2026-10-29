"""Render tracks through sampled SFZ instruments, falling back to FluidSynth.

``sound="sampled"`` plays each track whose instrument has a sampled library
in ``data/instruments/`` (or ``$AI_MUSIC_INSTRUMENTS``) through
:mod:`.sfz`; every other track renders through the General MIDI soundfont as
before. Stems come back stereo and peak-normalised like FluidSynth's, so the
mixer's gain staging is unchanged.

The libraries are free downloads, not committed (see
``data/instruments/README.md``):

- Rhodes: jlearman jRhodes3c (1977 Rhodes Mark I; free to use in your music).
- Electric bass: Karoryfer Black And Blue Basses (CC0).
- Drums: Virtuosity Drums, a contemporary jazz kit (CC0).
- Alto sax: Karoryfer Weresax (CC0).
"""

from __future__ import annotations

import gc
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from src.daw_integration.generic.midi_export import MidiExporter

from .sfz import Note, SampleCache, SfzInstrument, SfzRenderer, load_sfz
from .synth import DEFAULT_SAMPLE_RATE, FluidSynthRenderer, RenderedStems, TrackStem

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INSTRUMENT_DIR = PROJECT_ROOT / "data" / "instruments"

SOUNDS = ("gm", "sampled")


@dataclass(frozen=True)
class SampledInstrument:
    """One sampled library and how to play GM tracks through it."""
    id: str
    sfz: str                      # path under the instruments dir
    programs: tuple[int, ...] = ()
    is_drum: bool = False
    # Libraries mapped at written pitch (bass guitar is notated an octave
    # above where it sounds) need the MIDI shifted to reach the right sample.
    key_offset: int = 0
    cc: dict[int, float] = field(default_factory=dict)
    # Tone voicing applied to the raw stem before the mixer's family chain:
    # (kind, frequency Hz, gain dB) with kind "low_shelf" / "high_shelf" / "peak".
    eq: tuple[tuple[str, float, float], ...] = ()


SAMPLED_INSTRUMENTS: tuple[SampledInstrument, ...] = (
    SampledInstrument(
        id="rhodes",
        sfz="jlearman.jRhodes3c/jRhodes3c-looped-flac-sfz/_jRhodes-stereo-looped.sfz",
        programs=(4, 5),                      # Electric Piano 1 / 2
        # A brighter, barkier tine like the fusion records.
        eq=(("high_shelf", 2500.0, 4.0), ("peak", 300.0, -2.0)),
    ),
    SampledInstrument(
        id="electric_bass",
        sfz="karoryfer.black-and-blue-basses/Programs/05-darkblack_pluck.sfz",
        programs=(32, 33, 34, 35, 36, 37),    # acoustic … slap basses (not synth bass)
        key_offset=12,
    ),
    SampledInstrument(
        id="drum_kit",
        sfz="virtuosity_drums/Programs/01-basic-kit.sfz",
        is_drum=True,
        # The close-miked kick swamps the overheads; lift the cymbals and
        # tighten the low end so the hats drive the groove.
        eq=(("low_shelf", 70.0, -4.0), ("peak", 400.0, -2.5), ("high_shelf", 5000.0, 6.0)),
    ),
    SampledInstrument(
        id="alto_sax",
        sfz="karoryfer.weresax/Programs/Sax.sfz",
        programs=(64, 65, 66, 67),            # soprano … baritone sax
        eq=(("peak", 250.0, -2.0), ("high_shelf", 7000.0, 2.0)),
    ),
)


def instrument_dir() -> Path:
    env = os.environ.get("AI_MUSIC_INSTRUMENTS")
    return Path(env) if env else DEFAULT_INSTRUMENT_DIR


def sampled_for(program: int, is_drum: bool, root: Optional[Path] = None) -> Optional[SampledInstrument]:
    """The sampled library for a track, when it's installed."""
    root = root or instrument_dir()
    for inst in SAMPLED_INSTRUMENTS:
        if inst.is_drum != is_drum:
            continue
        if not is_drum and program not in inst.programs:
            continue
        if (root / inst.sfz).exists():
            return inst
    return None


def available() -> list[str]:
    """Ids of the sampled instruments installed on this machine."""
    root = instrument_dir()
    return [i.id for i in SAMPLED_INSTRUMENTS if (root / i.sfz).exists()]


def resolve_sound(sound: Optional[str], style_name: Optional[str] = None) -> str:
    """Explicit choice, then $AI_MUSIC_SOUND, then the style's default."""
    for choice in (sound, os.environ.get("AI_MUSIC_SOUND")):
        if choice in SOUNDS:
            return choice
    if style_name:
        try:
            from src.daw_integration.generic.styles import STYLES
            preset = STYLES.get(style_name)
            if preset is not None and getattr(preset, "sound", "gm") in SOUNDS:
                return preset.sound
        except Exception:
            logger.debug("resolve_sound: style lookup failed", exc_info=True)
    return "gm"


def _voice_eq(audio: np.ndarray, eq, sample_rate: int) -> np.ndarray:
    import pedalboard as pdb
    plugins = []
    for kind, freq, gain in eq:
        if kind == "low_shelf":
            plugins.append(pdb.LowShelfFilter(cutoff_frequency_hz=freq, gain_db=gain))
        elif kind == "high_shelf":
            plugins.append(pdb.HighShelfFilter(cutoff_frequency_hz=freq, gain_db=gain))
        else:
            plugins.append(pdb.PeakFilter(cutoff_frequency_hz=freq, gain_db=gain, q=0.8))
    out = pdb.Pedalboard(plugins)(audio.T.copy(), sample_rate=sample_rate)
    return np.ascontiguousarray(np.asarray(out, dtype=np.float32).T)


class SampledRenderer:
    """Per-track stems: SFZ where a library exists, FluidSynth elsewhere."""

    def __init__(self, soundfont: Optional[str | Path] = None, *,
                 sample_rate: int = DEFAULT_SAMPLE_RATE,
                 root: Optional[Path] = None, seed: int = 1) -> None:
        self.soundfont = soundfont
        self.sample_rate = sample_rate
        self.root = root or instrument_dir()
        self.seed = seed
        self._fluid: Optional[FluidSynthRenderer] = None
        self._loaded: dict[str, SfzInstrument] = {}

    def __enter__(self) -> "SampledRenderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._fluid is not None:
            self._fluid.close()
            self._fluid = None
        self._loaded.clear()
        gc.collect()

    def _fluid_renderer(self) -> FluidSynthRenderer:
        if self._fluid is None:
            self._fluid = FluidSynthRenderer(soundfont=self.soundfont, sample_rate=self.sample_rate)
        return self._fluid

    def _instrument(self, inst: SampledInstrument) -> SfzInstrument:
        if inst.id not in self._loaded:
            self._loaded[inst.id] = load_sfz(self.root / inst.sfz, cc_overrides=inst.cc or None)
        return self._loaded[inst.id]

    def render_stems(self, midi: MidiExporter) -> RenderedStems:
        if not midi.tracks:
            raise ValueError("MidiExporter has no tracks to render.")
        fluid_tracks: list = []
        stems: list[TrackStem] = []
        order: list[str] = []
        for index, track in enumerate(midi.tracks):
            if not track.notes:
                continue
            order.append(track.name)
            inst = sampled_for(track.program, track.is_drum, self.root)
            if inst is None:
                fluid_tracks.append(track)
                continue
            sfz = self._instrument(inst)
            for region in sfz.regions:
                region.seq_counter = 0
            notes = [Note(pitch=int(n.pitch) + inst.key_offset, start=float(n.start),
                          end=float(n.end), velocity=int(n.velocity)) for n in track.notes]
            audio = SfzRenderer(sfz, self.sample_rate, cache=SampleCache(),
                                seed=self.seed + index).render(notes)
            if inst.eq and audio.size:
                audio = _voice_eq(audio, inst.eq, self.sample_rate)
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            if peak <= 0.0:
                logger.warning("sampled: %s rendered silent, using FluidSynth", track.name)
                fluid_tracks.append(track)
                continue
            audio /= peak
            stems.append(TrackStem(name=track.name, program=track.program, is_drum=track.is_drum,
                                   audio=audio, sample_rate=self.sample_rate))
            logger.info("sampled: %s → %s (%.1fs)", track.name, inst.id, audio.shape[1] / self.sample_rate)
            gc.collect()

        if fluid_tracks:
            sub = MidiExporter(tempo=midi.tempo, time_signature=midi.time_signature)
            sub.tracks = fluid_tracks
            stems.extend(self._fluid_renderer().render_stems(sub).stems)

        if not stems:
            raise ValueError("All tracks rendered empty audio.")
        stems.sort(key=lambda s: order.index(s.name) if s.name in order else len(order))
        return RenderedStems(sample_rate=self.sample_rate,
                             soundfont=Path(self.root),
                             stems=stems)
