"""Built-in techniques for the song-composition bank.

~20 baseline techniques cover one entry per (instrument, role) cell so
any random pick produces something musical. The Funk Rock starter set
adds ~10 deliberately-tuned techniques tagged ``funk_rock`` that
``compose_song(genre="funk_rock")`` prefers.

Each technique is a thin wrapper that calls an existing MidiExporter
generator over ``[ctx.start_bar, ctx.end_bar]`` with curated kwargs.
No new low-level renderers — this layer composes existing ones.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.composition.techniques import BANK, Technique, TechniqueContext


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed(ctx: TechniqueContext) -> int:
    """A fresh int seed for the renderer, derived from the ctx rng."""
    return int(ctx.rng.integers(0, 1_000_000))


def _register(
    *,
    name: str,
    label: str,
    description: str,
    instruments: tuple[str, ...],
    roles: tuple[str, ...],
    apply,
    weight: int = 1,
    tags: tuple[str, ...] = (),
) -> None:
    BANK.register(Technique(
        name=name, label=label, description=description,
        instruments=instruments, section_roles=roles,
        weight=weight, tags=tags, apply=apply,
    ))


# ---------------------------------------------------------------------------
# CHORDS — one per role
# ---------------------------------------------------------------------------

def _chords_pad_swells(midi, ctx: TechniqueContext) -> None:
    """Sustained pad — sets up tension without committing to a rhythm."""
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pad",
        voicing="seventh", swing=ctx.swing,
    )


def _chords_funk_comp(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="funk_comp",
        voicing="ninth", swing=ctx.swing,
    )


def _chords_open_quarter(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pulse_quarter",
        voicing="seventh", swing=ctx.swing,
    )


def _chords_tresillo_clave(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="tresillo",
        voicing="ninth", swing=ctx.swing,
    )


def _chords_pedal_pad(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pad",
        voicing="triad", swing=ctx.swing,
    )


_register(name="pad_swells", label="Pad with swells",
          description="Sustained chord pad — establishes harmony with no rhythmic commitment.",
          instruments=("chords",), roles=("intro",), weight=2,
          apply=_chords_pad_swells)
_register(name="funk_comp_9th", label="Funk 9th comping",
          description="Classic 16th-note funk chord comping on 9th voicings.",
          instruments=("chords",), roles=("verse",), weight=2,
          apply=_chords_funk_comp)
_register(name="open_quarter_pulse", label="Open quarter pulse",
          description="Quarter-note chord pulse with seventh voicings — chorus lift.",
          instruments=("chords",), roles=("chorus",), weight=2,
          apply=_chords_open_quarter)
_register(name="tresillo_clave", label="Tresillo clave",
          description="3-3-2 Latin tresillo with ninth voicings — bridge contrast.",
          instruments=("chords",), roles=("bridge",), weight=2,
          apply=_chords_tresillo_clave)
_register(name="pedal_pad", label="Pedal pad",
          description="Sustained pad on the tonic for the outro tail.",
          instruments=("chords",), roles=("outro",), weight=2,
          apply=_chords_pedal_pad)


# ---------------------------------------------------------------------------
# BASS — one per role
# ---------------------------------------------------------------------------

def _bass_pedal_drone(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="root",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_funk_walk(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="funk_16ths",
        approach_tones=True, seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_octave_pump(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="disco_octave",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_funk_slap(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="flea_slap",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_fadeout_walk(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="root_fifth",
        seed=_seed(ctx), swing=ctx.swing,
    )


_register(name="pedal_drone", label="Pedal drone",
          description="Sustained root tone — opens space, suggests stillness.",
          instruments=("bass",), roles=("intro",), weight=2,
          apply=_bass_pedal_drone)
_register(name="funk_walk", label="Funk 16ths walking",
          description="16th-note funk groove with leading-tone approach into chord changes.",
          instruments=("bass",), roles=("verse",), weight=2,
          apply=_bass_funk_walk)
_register(name="octave_pump_chorus", label="Octave pump",
          description="Disco-style root/octave alternation — drives the chorus.",
          instruments=("bass",), roles=("chorus",), weight=2,
          apply=_bass_octave_pump)
_register(name="funk_riff_slap", label="Flea slap-style riff",
          description="Slap-funk bass with thumb/pop alternation — bridge funk.",
          instruments=("bass",), roles=("bridge",), weight=2,
          apply=_bass_funk_slap)
_register(name="fadeout_walk", label="Root-fifth fadeout",
          description="Sparse root-fifth walk — winds down energy through the outro.",
          instruments=("bass",), roles=("outro",), weight=2,
          apply=_bass_fadeout_walk)


# ---------------------------------------------------------------------------
# MELODY — one per role
# ---------------------------------------------------------------------------

def _melody_motif(midi, ctx: TechniqueContext) -> None:
    """Default motif-driven melody — reuses MidiExporter's melody engine."""
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _melody_tension_arc(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.45,
    )


def _melody_anthemic(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.75,
    )


def _melody_blues_lick_chain(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.7,
    )


def _melody_recap_fade(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.35,
    )


_register(name="tension_arc_chromatic", label="Chromatic tension arc",
          description="Sparse melody hinting at chromatic neighbours — sets unresolved tension.",
          instruments=("melody",), roles=("intro",), weight=2,
          apply=_melody_tension_arc)
_register(name="chord_tone_motif", label="Chord-tone motif",
          description="Default motif engine over the verse chords.",
          instruments=("melody",), roles=("verse",), weight=2,
          apply=_melody_motif)
_register(name="anthemic_arc", label="Anthemic arc",
          description="Higher-density melodic arc — chorus payoff.",
          instruments=("melody",), roles=("chorus",), weight=2,
          apply=_melody_anthemic)
_register(name="blues_lick_chain", label="Blues lick chain",
          description="Bluesy phrase chain over the bridge changes.",
          instruments=("melody",), roles=("bridge",), weight=2,
          apply=_melody_blues_lick_chain)
_register(name="motif_recap_fade", label="Motif recap, fading",
          description="Light recap of the main motif at low density — outro tail.",
          instruments=("melody",), roles=("outro",), weight=2,
          apply=_melody_recap_fade)


# ---------------------------------------------------------------------------
# DRUMS — one per role
# ---------------------------------------------------------------------------

def _drums_hat_eighths_only(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="basic_rock", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.3,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_funk_basic(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="funk", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=1.0,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_open_hat_drive(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="four_on_floor", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=1.0,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_halftime_break(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="halftime", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.8,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_fade_hat_only(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="basic_rock", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.25,
        seed=_seed(ctx), swing=ctx.swing,
    )


_register(name="hat_eighths_only", label="Hat eighths only",
          description="Just the hi-hat pulse — leaves space for the intro.",
          instruments=("drums",), roles=("intro",), weight=2,
          apply=_drums_hat_eighths_only)
_register(name="funk_basic_kit", label="Funk kit (full)",
          description="Standard funk pattern at full density — verse groove.",
          instruments=("drums",), roles=("verse",), weight=2,
          apply=_drums_funk_basic)
_register(name="open_hat_drive", label="Four-on-floor drive",
          description="Four-on-floor kick + open hi-hat — chorus power.",
          instruments=("drums",), roles=("chorus",), weight=2,
          apply=_drums_open_hat_drive)
_register(name="half_time_breakbeat", label="Halftime breakbeat",
          description="Halftime feel — bridge dynamic shift.",
          instruments=("drums",), roles=("bridge",), weight=2,
          apply=_drums_halftime_break)
_register(name="fade_hat_only", label="Hat-only fade",
          description="Stripped to hat ticks — outro fade.",
          instruments=("drums",), roles=("outro",), weight=2,
          apply=_drums_fade_hat_only)


# ---------------------------------------------------------------------------
# FUNK ROCK STARTER SET
# ---------------------------------------------------------------------------
# Tuned bundles that nail the conversation brief. Tagged "funk_rock"
# so compose_song(genre="funk_rock") doubles their pick weight.

def _fr_nebulous_intro_chords(midi, ctx: TechniqueContext) -> None:
    """Pad with a stab on h2 of each bar — 'something is about to drop'."""
    # Render pad over the whole range, then layer stabs at the second
    # half of each bar via a second add_chord_progression pass with a
    # tight rhythm restricted by smaller velocity.
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pad",
        voicing="ninth", velocity=55, swing=ctx.swing,
    )
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="stabs_8th",
        voicing="ninth", velocity=70, swing=ctx.swing,
        track_name="Chords Stab",
    )


def _fr_nebulous_intro_bass(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="root",
        velocity=70, seed=_seed(ctx), swing=ctx.swing,
    )


def _fr_verse_chords(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="funk_comp",
        voicing="ninth", velocity=80, swing=ctx.swing,
    )


def _fr_verse_bass(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="funk_16ths",
        approach_tones=True, velocity=88,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _fr_chorus_chords(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="charleston",
        voicing="ninth", velocity=90, swing=ctx.swing,
    )


def _fr_chorus_bass(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="disco_octave",
        approach_tones=True, velocity=92,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _fr_bridge_chords(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="stabs_8th",
        voicing="ninth", velocity=92, swing=ctx.swing,
    )


def _fr_bridge_bass(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="flea_slap",
        velocity=95, seed=_seed(ctx), swing=ctx.swing,
    )


def _fr_outro_riff_pass(midi, ctx: TechniqueContext) -> None:
    """4-bar riff that alternates bass / lead.

    Splits the outro range in half: bass plays the riff for the first
    half, the riff "passes" to a lead-guitar track for the second half.
    """
    half = max(1, ctx.bar_count // 2)
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression[:half] if isinstance(ctx.progression, list)
        else ctx.progression,
        bars=half, bar_offset=ctx.start_bar,
        pattern="flea_slap", velocity=92,
        seed=_seed(ctx), swing=ctx.swing,
    )
    midi.add_lead_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression[half:] if isinstance(ctx.progression, list)
        else ctx.progression,
        bars=max(1, ctx.bar_count - half),
        bar_offset=ctx.start_bar + half,
        seed=_seed(ctx),
        track_name="Lead", program=26,
    ) if hasattr(midi, "add_lead_line") else None


def _fr_outro_drums_fade(midi, ctx: TechniqueContext) -> None:
    """Drums thin out across the outro: split the range in two and
    render the second half at lower density."""
    half = max(1, ctx.bar_count // 2)
    midi.add_drum_pattern(
        pattern="funk", bars=half,
        bar_offset=ctx.start_bar, density=0.7,
        seed=_seed(ctx), swing=ctx.swing,
    )
    if ctx.bar_count > half:
        midi.add_drum_pattern(
            pattern="basic_rock", bars=ctx.bar_count - half,
            bar_offset=ctx.start_bar + half, density=0.25,
            seed=_seed(ctx), swing=ctx.swing,
        )


_register(name="nebulous_intro_chords", label="Nebulous intro chords",
          description="Pad + stab-on-h2 — tense, holding for the verse drop.",
          instruments=("chords",), roles=("intro",),
          weight=3, tags=("funk_rock",),
          apply=_fr_nebulous_intro_chords)
_register(name="nebulous_intro_bass", label="Pedal-root intro bass",
          description="Single root tone — leaves space for the chord stabs.",
          instruments=("bass",), roles=("intro",),
          weight=3, tags=("funk_rock",),
          apply=_fr_nebulous_intro_bass)
_register(name="funk_rock_verse_chords", label="Funk Rock verse comping",
          description="9th-chord funk comping at a verse-friendly velocity.",
          instruments=("chords",), roles=("verse",),
          weight=3, tags=("funk_rock",),
          apply=_fr_verse_chords)
_register(name="funk_rock_verse_bass", label="Funk Rock verse bass",
          description="16ths walking with leading-tone approach into changes.",
          instruments=("bass",), roles=("verse",),
          weight=3, tags=("funk_rock",),
          apply=_fr_verse_bass)
_register(name="funk_rock_chorus_chords", label="Funk Rock chorus chords",
          description="Charleston rhythm on 9th voicings — opens the chorus.",
          instruments=("chords",), roles=("chorus",),
          weight=3, tags=("funk_rock",),
          apply=_fr_chorus_chords)
_register(name="funk_rock_chorus_bass", label="Funk Rock chorus bass",
          description="Disco-octave drive with chord-change approach tones.",
          instruments=("bass",), roles=("chorus",),
          weight=3, tags=("funk_rock",),
          apply=_fr_chorus_bass)
_register(name="funk_rock_bridge_chords", label="Funk Rock bridge stabs",
          description="8th-note stab figures on 9th voicings.",
          instruments=("chords",), roles=("bridge",),
          weight=3, tags=("funk_rock",),
          apply=_fr_bridge_chords)
_register(name="funk_rock_bridge_bass", label="Funk Rock bridge slap",
          description="Flea-style slap funk for the bridge.",
          instruments=("bass",), roles=("bridge",),
          weight=3, tags=("funk_rock",),
          apply=_fr_bridge_bass)
_register(name="funk_rock_outro_riff_pass", label="Outro riff passing",
          description="Riff passes from bass to lead across the outro range.",
          instruments=("bass",), roles=("outro",),
          weight=3, tags=("funk_rock",),
          apply=_fr_outro_riff_pass)
_register(name="funk_rock_outro_drums_fade", label="Drum fade-out",
          description="Drums thin from full funk to hat-only across the outro.",
          instruments=("drums",), roles=("outro",),
          weight=3, tags=("funk_rock",),
          apply=_fr_outro_drums_fade)


logger.info(
    "Registered %d techniques in the bank.", len(BANK.all_techniques()),
)
