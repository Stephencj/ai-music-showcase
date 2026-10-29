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

from .sfz import Note, SampleCache, SfzInstrument, SfzRenderer, Vibrato, load_sfz
from .lead_voices import LeadLayer, voice
from .synth_lead import LEAD_PATCHES, render_lead
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
    # Measure each sample's real pitch and correct it (render/autotune.py).
    auto_tune: bool = False
    # "sfz" plays the library at ``sfz``; "synth" renders a lead voice
    # (render/lead_voices.py: the built-in synth and/or sampled layers).
    engine: str = "sfz"
    # For "synth" tracks: a fixed lead voice; empty = the render's lead_patch.
    voice: str = ""


SAMPLED_INSTRUMENTS: tuple[SampledInstrument, ...] = (
    # Strings and French horn: VSCO 2 CE sustains (scripts/setup/make_vsco_sfz.py).
    SampledInstrument(
        id="string_section",
        sfz="vsco2-ce-strings/strings_section_sus.sfz",
        programs=(48, 49, 50, 51),            # string ensembles
        auto_tune=True,
    ),
    SampledInstrument(
        id="string_spiccato",
        sfz="vsco2-ce-strings/strings_section_spic.sfz",
        programs=(45,),                       # short bowed strings (GM pizzicato as the fallback)
        auto_tune=True,
    ),
    SampledInstrument(
        id="french_horn",
        sfz="vsco2-ce-strings/french_horn_sus.sfz",
        programs=(60,),
        auto_tune=True,
    ),
    # A lead guitar track (GM overdrive/distortion guitar) plays as the
    # stacked overdriven guitar voice, so a song can trade leads with the
    # main lead track.
    SampledInstrument(
        id="lead_guitar",
        sfz="",
        programs=(29, 30),
        engine="synth",
        voice="guitar_stack",
    ),
    # Lead-voice layers only (render/lead_voices.py): no GM program maps here.
    SampledInstrument(
        id="trumpet_sus",
        auto_tune=True,
        sfz="vsco2-ce/trumpet_sus.sfz",
    ),
    SampledInstrument(
        id="guitar_twang",
        auto_tune=True,
        sfz="karoryfer.black-and-green-guitars/Programs/04-green_twang.sfz",
    ),
    SampledInstrument(
        id="guitar_staccato",
        auto_tune=True,
        sfz="karoryfer.black-and-green-guitars/Programs/05-green_staccato.sfz",
    ),
    SampledInstrument(
        id="synth_lead",
        sfz="",
        programs=tuple(range(80, 88)),        # GM synth leads
        engine="synth",
        eq=(("peak", 2500.0, 1.5),),
    ),
    # Horns: VSCO 2 CE (CC0) staccato samples, mapped by
    # scripts/setup/make_brass_sfz.py.
    SampledInstrument(
        id="horn_section",
        auto_tune=True,
        sfz="vsco2-ce/horns_stac.sfz",
        programs=(61,),                       # Brass Section
        eq=(("peak", 300.0, -2.0), ("high_shelf", 4000.0, 2.5)),
    ),
    SampledInstrument(
        id="trumpet",
        auto_tune=True,
        sfz="vsco2-ce/trumpet_stac.sfz",
        programs=(56, 59),                    # Trumpet, Muted Trumpet
    ),
    SampledInstrument(
        id="trombone",
        auto_tune=True,
        sfz="vsco2-ce/trombone_stac.sfz",
        programs=(57,),
    ),
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


# GM drum kit 40: the General MIDI soundfont's recorded brush kit (taps on
# the snare keys). Drum tracks on this program render through FluidSynth.
BRUSH_KIT = 40


def instrument_dir() -> Path:
    env = os.environ.get("AI_MUSIC_INSTRUMENTS")
    return Path(env) if env else DEFAULT_INSTRUMENT_DIR


def sampled_for(program: int, is_drum: bool, root: Optional[Path] = None) -> Optional[SampledInstrument]:
    """The sampled library for a track, when it's installed."""
    root = root or instrument_dir()
    if is_drum and program == BRUSH_KIT:
        return None                           # the soundfont's recorded brush kit
    for inst in SAMPLED_INSTRUMENTS:
        if inst.is_drum != is_drum:
            continue
        if not is_drum and program not in inst.programs:
            continue
        if inst.engine != "sfz" or (root / inst.sfz).exists():
            return inst
    return None


def available() -> list[str]:
    """Ids of the sampled instruments installed on this machine."""
    root = instrument_dir()
    return [i.id for i in SAMPLED_INSTRUMENTS if i.engine != "sfz" or (root / i.sfz).exists()]


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


def _amp(audio: np.ndarray, drive_db: float, sample_rate: int) -> np.ndarray:
    """A smooth fusion overdrive, not a rock fuzz: the guitar is brought up to
    full level first (the samples are quiet, so the drive would barely bite),
    a mid hump and low cut go in before the clipping (the classic
    overdrive-pedal voicing that keeps it vocal and tight), a compressor adds
    sustain, then a speaker roll-off and a touch of chorus."""
    import pedalboard as pdb
    peak = float(np.abs(audio).max())
    if peak > 0:
        audio = audio / peak
    board = pdb.Pedalboard([
        pdb.HighpassFilter(cutoff_frequency_hz=140.0),
        pdb.PeakFilter(cutoff_frequency_hz=850.0, gain_db=6.0, q=0.7),
        pdb.Compressor(threshold_db=-18.0, ratio=4.0, attack_ms=5.0, release_ms=120.0),
        pdb.Gain(gain_db=6.0),
        pdb.Distortion(drive_db=drive_db),
        pdb.PeakFilter(cutoff_frequency_hz=300.0, gain_db=-2.0, q=0.8),
        pdb.PeakFilter(cutoff_frequency_hz=2400.0, gain_db=2.0, q=1.0),
        pdb.LowpassFilter(cutoff_frequency_hz=4600.0),
        pdb.Chorus(rate_hz=0.8, depth=0.12, centre_delay_ms=7.0, feedback=0.0, mix=0.18),
    ])
    out = board(audio.T.copy(), sample_rate=sample_rate)
    return np.ascontiguousarray(np.asarray(out, dtype=np.float32).T)


def _space(audio: np.ndarray, amount: float, sample_rate: int) -> np.ndarray:
    """A lead-guitar space: a dotted-ish delay and a big, wide reverb, with
    room for the tail."""
    import pedalboard as pdb
    tail = np.zeros((2, int(2.5 * sample_rate)), dtype=np.float32)
    audio = np.concatenate([audio, tail], axis=1)
    board = pdb.Pedalboard([
        pdb.Delay(delay_seconds=0.29, feedback=0.3 * amount, mix=0.2 * amount),
        pdb.Reverb(room_size=0.75, damping=0.4, wet_level=0.34 * amount,
                   dry_level=1.0 - 0.25 * amount, width=1.0),
    ])
    out = board(audio.T.copy(), sample_rate=sample_rate)
    return np.ascontiguousarray(np.asarray(out, dtype=np.float32).T)


class SampledRenderer:
    """Per-track stems: SFZ where a library exists, FluidSynth elsewhere."""

    def __init__(self, soundfont: Optional[str | Path] = None, *,
                 sample_rate: int = DEFAULT_SAMPLE_RATE,
                 root: Optional[Path] = None, seed: int = 1,
                 lead_patch: Optional[str] = None) -> None:
        self.soundfont = soundfont
        self.sample_rate = sample_rate
        self.root = root or instrument_dir()
        self.seed = seed
        self.lead_patch = lead_patch
        self._sample_tuner = None
        self._fluid: Optional[FluidSynthRenderer] = None
        self._loaded: dict[str, SfzInstrument] = {}

    def __enter__(self) -> "SampledRenderer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._sample_tuner is not None:
            self._sample_tuner.save()
        if self._fluid is not None:
            self._fluid.close()
            self._fluid = None
        self._loaded.clear()
        gc.collect()

    def _tuner(self, inst: Optional[SampledInstrument]):
        if inst is None or not inst.auto_tune:
            return None
        if self._sample_tuner is None:
            from .autotune import SampleTuner
            self._sample_tuner = SampleTuner(self.root / ".tuning.json")
        return self._sample_tuner.cents

    def _fluid_renderer(self) -> FluidSynthRenderer:
        if self._fluid is None:
            self._fluid = FluidSynthRenderer(soundfont=self.soundfont, sample_rate=self.sample_rate)
        return self._fluid

    def _instrument(self, inst: SampledInstrument) -> SfzInstrument:
        if inst.id not in self._loaded:
            self._loaded[inst.id] = load_sfz(self.root / inst.sfz, cc_overrides=inst.cc or None)
        return self._loaded[inst.id]

    def _sfz_by_id(self, inst_id: str) -> Optional[SfzInstrument]:
        inst = next((i for i in SAMPLED_INSTRUMENTS if i.id == inst_id and i.engine == "sfz"), None)
        if inst is None or not (self.root / inst.sfz).exists():
            return None
        return self._instrument(inst)

    def _lead_layer(self, layer: LeadLayer, notes: list[Note], index: int) -> Optional[np.ndarray]:
        shifted = [Note(n.pitch + 12 * layer.octave, n.start, n.end, n.velocity) for n in notes]
        if layer.kind == "synth":
            return render_lead(shifted, self.sample_rate,
                               patch=LEAD_PATCHES.get(layer.patch, LEAD_PATCHES["punch"]))
        long_inst = self._sfz_by_id(layer.sfz)
        short_inst = self._sfz_by_id(layer.sfz_short) if layer.sfz_short else None
        if long_inst is None and short_inst is None:
            return None
        # Notes an octave shift pushes past the instrument's top fold back
        # down an octave rather than going silent.
        top = max((r.hikey for i in (long_inst, short_inst) if i for r in i.regions), default=127)
        bottom = min((r.lokey for i in (long_inst, short_inst) if i for r in i.regions), default=0)
        folded = []
        for n in shifted:
            p = n.pitch
            while p > top and p - 12 >= bottom:
                p -= 12
            folded.append(Note(p, n.start, n.end, n.velocity))
        shifted = folded
        parts = []
        for inst, chosen in (
            (short_inst, [n for n in shifted if short_inst is not None and n.end - n.start < layer.short_below]),
            (long_inst or short_inst, [n for n in shifted if short_inst is None or n.end - n.start >= layer.short_below]),
        ):
            if inst is None or not chosen:
                continue
            for region in inst.regions:
                region.seq_counter = 0
            spec = next((i for i in SAMPLED_INSTRUMENTS if i.engine == "sfz" and self._loaded.get(i.id) is inst), None)
            vib = Vibrato(cents=layer.vibrato) if layer.vibrato else None
            parts.append(SfzRenderer(inst, self.sample_rate, cache=SampleCache(), seed=self.seed + index,
                                     sample_tune=self._tuner(spec), vibrato=vib).render(chosen))
        if not parts:
            return None
        n = max(p.shape[1] for p in parts)
        audio = np.zeros((2, n), dtype=np.float32)
        for p in parts:
            audio[:, :p.shape[1]] += p
        if layer.drive_db:
            audio = _amp(audio, layer.drive_db, self.sample_rate)
        if layer.chorus:
            import pedalboard as pdb
            board = pdb.Pedalboard([pdb.Chorus(rate_hz=0.6, depth=0.2 * layer.chorus, centre_delay_ms=8.0,
                                               feedback=0.0, mix=0.3 * layer.chorus)])
            audio = np.ascontiguousarray(np.asarray(board(audio.T.copy(), sample_rate=self.sample_rate),
                                                    dtype=np.float32).T)
        if layer.space:
            audio = _space(audio, layer.space, self.sample_rate)
        return audio

    def _lead(self, notes: list[Note], index: int, voice_name: Optional[str] = None) -> np.ndarray:
        """A lead track in its named voice (render/lead_voices.py)."""
        lead_voice = voice(voice_name if voice_name is not None else self.lead_patch)
        layers = []
        for layer in lead_voice.layers:
            audio = self._lead_layer(layer, notes, index)
            if audio is not None and audio.size and float(np.abs(audio).max()) > 0:
                layers.append((audio / float(np.abs(audio).max()), 10 ** (layer.db / 20.0)))
        if not layers:                       # e.g. a sampled voice whose libraries aren't installed
            return render_lead(notes, self.sample_rate)
        n = max(a.shape[1] for a, _ in layers)
        mix = np.zeros((2, n), dtype=np.float32)
        for audio, gain in layers:
            mix[:, :audio.shape[1]] += audio * gain
        return mix

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
            notes = [Note(pitch=int(n.pitch) + inst.key_offset, start=float(n.start),
                          end=float(n.end), velocity=int(n.velocity)) for n in track.notes]
            if inst.engine == "synth":
                audio = self._lead(notes, index, inst.voice or self.lead_patch)
            else:
                sfz = self._instrument(inst)
                for region in sfz.regions:
                    region.seq_counter = 0
                audio = SfzRenderer(sfz, self.sample_rate, cache=SampleCache(), seed=self.seed + index,
                                    sample_tune=self._tuner(inst)).render(notes)
            if inst.eq and audio.size:
                audio = _voice_eq(audio, inst.eq, self.sample_rate)
            peak = float(np.abs(audio).max()) if audio.size else 0.0
            if peak <= 0.0:
                logger.warning("sampled: %s rendered silent, using FluidSynth", track.name)
                fluid_tracks.append(track)
                continue
            audio /= peak
            if inst.engine == "synth":
                # Level-match lead voices after normalising (sampled voices are
                # peakier, so equal peaks would leave them quieter).
                audio *= 10 ** (voice(inst.voice or self.lead_patch).gain_db / 20.0)
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
