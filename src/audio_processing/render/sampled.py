"""Render tracks through sampled SFZ instruments, falling back to FluidSynth.

``sound="sampled"`` plays each track whose instrument has a sampled library
in ``data/instruments/`` (or ``$AI_MUSIC_INSTRUMENTS``) through
:mod:`.sfz`; every other track renders through the General MIDI soundfont as
before. Stems come back stereo and peak-normalised like FluidSynth's, so the
mixer's gain staging is unchanged.

The libraries are free downloads, not committed (see
``data/instruments/README.md``):

- Electric pianos: Greg Sullivan's Wurlitzer EP200 (CC BY 3.0) and the VCSL
  TX81Z FM piano (CC0).
- Electric bass: Karoryfer Black And Blue Basses (CC0).
- Drums: Virtuosity Drums, a contemporary jazz kit (CC0).
- Alto sax: Karoryfer Weresax (CC0).
- Christmas: VCSL grand piano / harp / glockenspiel / sleigh bells / shaker,
  VSCO 2 CE woodwinds / organ / muted trumpet, Karoryfer Sneakybass (all CC0).
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
    # Only tracks whose name contains one of these (lowercase) take this
    # library; empty = any track on ``programs``. Lets one GM program pick
    # different libraries by role (the organ's pedal bass, a sax melody).
    names: tuple[str, ...] = ()


# GM drum kit 40, the brush kit.
BRUSH_KIT_PROGRAM = 40

SAMPLED_INSTRUMENTS: tuple[SampledInstrument, ...] = (
    # Christmas instruments (all CC0; maps by scripts/setup/make_christmas_sfz.py):
    # VCSL Kawai grand, harp, glockenspiel, sleigh bells and shaker; VSCO 2 CE
    # flute / clarinet / oboe, quiet pipe organ and straight-mute trumpet;
    # Karoryfer Sneakybass (a quiet pizzicato double bass, mapped at written
    # pitch like the bass guitars).
    # Grand piano: Salamander (Yamaha C5, 16 velocity layers, release
    # samples; CC BY 3.0, credited in CREDITS.md), else the VCSL Kawai.
    SampledInstrument(
        id="grand_piano",
        sfz="salamander-grand/Salamander Grand Piano V3.sfz",
        programs=(0, 1),                      # Acoustic Grand / Bright Piano
        eq=(("peak", 250.0, -1.5), ("high_shelf", 6000.0, -1.0)),
    ),
    SampledInstrument(
        id="grand_piano_kawai",
        sfz="vcsl/piano_kawai.sfz",
        programs=(0, 1),
        eq=(("peak", 250.0, -1.5), ("high_shelf", 6000.0, -1.0)),
    ),
    # Orchestral double bass, bowed (Karoryfer Meatbass, CC0; sounding pitch).
    SampledInstrument(id="contrabass", sfz="karoryfer.meatbass/Meatbass/Programs/03_arco_5vel.sfz",
                      programs=(43,)),
    SampledInstrument(
        id="upright_bass",
        sfz="karoryfer.sneakybass/Sneakybass/Programs/02-sneakybass_pluck.sfz",
        programs=(32,),                       # Acoustic Bass
        key_offset=12,
        # The close, quiet pizzicato is boomy below 100 Hz; lift the note's
        # body and finger so it walks clearly under a trio.
        eq=(("low_shelf", 90.0, -4.0), ("peak", 220.0, 1.5), ("peak", 1200.0, 2.0)),
    ),
    SampledInstrument(id="harp", sfz="vcsl/harp.sfz", programs=(46,), auto_tune=True),
    SampledInstrument(id="glockenspiel", sfz="vcsl/glockenspiel.sfz", programs=(9,),
                      eq=(("high_shelf", 6000.0, -3.0),)),
    SampledInstrument(id="sleigh_bells", sfz="vcsl/sleigh_bells.sfz", programs=(112,),
                      eq=(("high_shelf", 7000.0, -3.0),)),
    SampledInstrument(id="shaker", sfz="vcsl/shaker.sfz", programs=(113,)),
    SampledInstrument(id="flute", sfz="vsco2-ce-xmas/flute_sus.sfz", programs=(73,), auto_tune=True),
    SampledInstrument(id="clarinet", sfz="vsco2-ce-xmas/clarinet_sus.sfz", programs=(71,), auto_tune=True),
    SampledInstrument(id="oboe", sfz="vsco2-ce-xmas/oboe_sus.sfz", programs=(68,), auto_tune=True),
    # Acoustic guitars (FreePats): a Spanish classical guitar (CC0) and the
    # FSS steel-string (GPL with FreePats' exception: music made with it
    # isn't covered). Both mapped at sounding pitch.
    SampledInstrument(id="nylon_guitar",
                      sfz="freepats-nylon/SpanishClassicalGuitar-SFZ-20190618/SpanishClassicalGuitar-20190618.sfz",
                      programs=(24,), auto_tune=True),
    SampledInstrument(id="steel_guitar",
                      sfz="freepats-steel/FSS-SteelStringGuitar-SFZ-20200521/FSS-SteelStringGuitar-20200521.sfz",
                      programs=(25,), auto_tune=True,
                      eq=(("high_shelf", 6000.0, -2.5),)),   # bright strums, kept under the tune
    # The pedal bass plays the same quiet organ's own pedal rank (VCSL).
    SampledInstrument(id="organ_pedal", sfz="vcsl-extra/organ_pedal_quiet.sfz", programs=(19,), names=("pedal",)),
    SampledInstrument(id="church_organ", sfz="vsco2-ce-xmas/organ_quiet.sfz", programs=(19,)),
    SampledInstrument(id="cello", sfz="vsco2-ce-strings/cellos_sus.sfz", programs=(42,), auto_tune=True),
    SampledInstrument(id="muted_trumpet", sfz="vsco2-ce/trumpet_muted_sus.sfz", programs=(59,), auto_tune=True,
                      eq=(("high_shelf", 5000.0, -2.0),)),
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
    # The clean lead guitar (voice "guitar_clean"): FreePats FSBS Fender
    # through a clean amp (CC0).
    SampledInstrument(
        id="guitar_fsbs_clean",
        auto_tune=True,
        sfz="freepats-fsbs-clean/EGuitarFSBS-clean SFZ+FLAC-20260807/EGuitarFSBS-clean bridge 20260807.sfz",
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
        programs=(56, 59),                    # Trumpet (Muted Trumpet: the straight-mute sustains above)
    ),
    SampledInstrument(
        id="trombone",
        auto_tune=True,
        sfz="vsco2-ce/trombone_stac.sfz",
        programs=(57,),
    ),
    # Electric pianos. Only samples whose licence allows commercial music
    # (tests/unit/test_instrument_licenses.py): Greg Sullivan's Wurlitzer
    # EP200 (CC BY 3.0, credit him) for electric piano 1, the VCSL Yamaha
    # TX81Z FM piano (CC0) for electric piano 2 and as the fallback.
    SampledInstrument(
        id="electric_piano",
        sfz="gregsullivan.e-pianos/Wurlitzer EP200/Wurlitzer EP200.sfz",
        programs=(4,),                        # Electric Piano 1
        # A brighter, barkier voicing like the fusion records.
        eq=(("high_shelf", 2500.0, 4.0), ("peak", 300.0, -2.0)),
    ),
    SampledInstrument(
        id="fm_piano",
        sfz="vcsl-fm/fm_piano.sfz",
        programs=(4, 5),                      # Electric Piano 2 (and 1 without the Wurlitzer)
        auto_tune=True,
        eq=(("high_shelf", 5000.0, -4.0),),   # the FM tine is far brighter than a Rhodes
    ),
    SampledInstrument(
        id="electric_bass",
        sfz="karoryfer.black-and-blue-basses/Programs/05-darkblack_pluck.sfz",
        programs=(32, 33, 34, 35, 36, 37),    # finger … slap basses (acoustic: the upright above)
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
    # The brush kit (GM drum program 40): Karoryfer Swirly Drums (CC0), every
    # hit played with brushes, on the GM keys the brush parts write.
    SampledInstrument(
        id="brush_kit",
        sfz="karoryfer.swirly-drums/Programs/Basic_kit.sfz",
        is_drum=True,
        programs=(BRUSH_KIT_PROGRAM,),
    ),
    # Tenor sax (VCSL, CC0): the vibrato takes for a melody, the straight
    # two-layer sustains for section parts. Without it the tenor plays the
    # alto samples below.
    SampledInstrument(id="tenor_sax_melody", sfz="vcsl-extra/tenor_sax_vib.sfz", programs=(66,),
                      names=("melody",), eq=(("peak", 250.0, -1.5),)),
    SampledInstrument(id="tenor_sax", sfz="vcsl-extra/tenor_sax_nv.sfz", programs=(66,),
                      eq=(("peak", 250.0, -1.5),)),
    SampledInstrument(
        id="alto_sax",
        sfz="karoryfer.weresax/Programs/Sax.sfz",
        programs=(64, 65, 66, 67),            # soprano … baritone sax
        eq=(("peak", 250.0, -2.0), ("high_shelf", 7000.0, 2.0)),
    ),
)


# GM drum kit 40: Swirly Drums when installed, else the soundfont's
# recorded brush kit (FluidSynth).
BRUSH_KIT = BRUSH_KIT_PROGRAM


def instrument_dir() -> Path:
    env = os.environ.get("AI_MUSIC_INSTRUMENTS")
    return Path(env) if env else DEFAULT_INSTRUMENT_DIR


def sampled_for(program: int, is_drum: bool, root: Optional[Path] = None,
                name: str = "") -> Optional[SampledInstrument]:
    """The sampled library for a track, when it's installed."""
    root = root or instrument_dir()
    for inst in SAMPLED_INSTRUMENTS:
        if inst.is_drum != is_drum:
            continue
        if is_drum:
            # A kit with programs plays only those (the brush kit); the
            # standard kit plays every other drum program. Without Swirly
            # Drums the brush kit falls back to the soundfont's.
            if inst.programs and program not in inst.programs:
                continue
            if not inst.programs and program == BRUSH_KIT:
                continue
        elif program not in inst.programs:
            continue
        if inst.names and not any(n in name.lower() for n in inst.names):
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


def fold_into_range(notes: list[Note], *instruments: SfzInstrument) -> list[Note]:
    """Move notes outside the instruments' sampled range by octaves until
    they're inside, rather than letting them go silent (an SFZ plays nothing
    where no region is mapped: a melody written above the alto sax's top
    lost every high note)."""
    keys = [(r.lokey, r.hikey) for i in instruments for r in i.regions
            if r.trigger not in ("release", "release_key") and r.sample_path is not None]
    if not keys:
        return notes
    bottom, top = min(k[0] for k in keys), max(k[1] for k in keys)
    out = []
    for n in notes:
        p = n.pitch
        while p > top and p - 12 >= bottom:
            p -= 12
        while p < bottom and p + 12 <= top:
            p += 12
        out.append(n if p == n.pitch else Note(p, n.start, n.end, n.velocity))
    return out


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
        shifted = fold_into_range(shifted, *(i for i in (long_inst, short_inst) if i))
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
            inst = sampled_for(track.program, track.is_drum, self.root, track.name)
            if inst is None:
                fluid_tracks.append(track)
                continue
            notes = [Note(pitch=int(n.pitch) + inst.key_offset, start=float(n.start),
                          end=float(n.end), velocity=int(n.velocity)) for n in track.notes]
            if inst.engine == "synth":
                audio = self._lead(notes, index, inst.voice or self.lead_patch)
            else:
                sfz = self._instrument(inst)
                if not inst.is_drum:
                    notes = fold_into_range(notes, sfz)
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
