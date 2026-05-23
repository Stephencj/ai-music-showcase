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


# ---------------------------------------------------------------------------
# Additional variety — second-pass techniques per cell so weighted-random
# picks feel genuinely random instead of selecting the same single option.
# Tagged sparsely so the genre-preferred pull from compose_song still
# prefers the funk_rock starter when applicable.
# ---------------------------------------------------------------------------

# ----- CHORDS extras --------------------------------------------------------

def _chords_arp_ringout(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="arpeggio_down",
        voicing="seventh", swing=ctx.swing,
    )


def _chords_sparse_quarter_outro(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pulse_quarter",
        voicing="triad", velocity=55, swing=ctx.swing,
    )


def _chords_dotted_eighths_verse(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="dotted_8ths",
        voicing="seventh", swing=ctx.swing,
    )


def _chords_off_skank_chorus(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="off_skank",
        voicing="seventh", swing=ctx.swing,
    )


def _chords_bossa_bridge(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="bossa_comp",
        voicing="ninth", swing=ctx.swing,
    )


def _chords_arp_up_intro(midi, ctx: TechniqueContext) -> None:
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="arpeggio_up",
        voicing="seventh", swing=ctx.swing,
    )


_register(name="arpeggio_ringout", label="Arpeggio ringout",
          description="Descending arpeggio over the outro — gentle landing.",
          instruments=("chords",), roles=("outro",), weight=2,
          apply=_chords_arp_ringout)
_register(name="sparse_quarter_outro", label="Sparse quarter outro",
          description="Soft quarter-note pulse — winds the song down quietly.",
          instruments=("chords",), roles=("outro",), weight=1,
          apply=_chords_sparse_quarter_outro)
_register(name="dotted_8ths_verse", label="Dotted 8ths verse",
          description="Dotted-eighth comping — classic rock guitar verse feel.",
          instruments=("chords",), roles=("verse",), weight=1,
          apply=_chords_dotted_eighths_verse)
_register(name="off_skank_chorus", label="Off-beat skank chorus",
          description="Reggae-style off-beat skank — opens the chorus with bounce.",
          instruments=("chords",), roles=("chorus",), weight=1,
          apply=_chords_off_skank_chorus)
_register(name="bossa_comp_bridge", label="Bossa comp bridge",
          description="Bossa-style comping for the bridge — Brazilian colour.",
          instruments=("chords",), roles=("bridge",), weight=1,
          apply=_chords_bossa_bridge)
_register(name="arpeggio_up_intro", label="Arpeggio up intro",
          description="Rising arpeggio — pulls the listener into the verse.",
          instruments=("chords",), roles=("intro",), weight=1,
          apply=_chords_arp_up_intro)


# ----- BASS extras ----------------------------------------------------------

def _bass_walking_verse(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="walking",
        approach_tones=True, seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_offbeat_chorus(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="offbeat",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_geddy_lee_bridge(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="geddy_lee",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_palm_mute_verse(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="palm_mute_8ths",
        seed=_seed(ctx), swing=ctx.swing,
    )


def _bass_walking_swing_chorus(midi, ctx: TechniqueContext) -> None:
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="walking_swing",
        approach_tones=True, seed=_seed(ctx), swing=max(ctx.swing, 0.18),
    )


_register(name="walking_bass_verse", label="Walking bass verse",
          description="Quarter-note walking with leading-tone approach.",
          instruments=("bass",), roles=("verse",), weight=1,
          apply=_bass_walking_verse)
_register(name="offbeat_pulse_chorus", label="Offbeat pulse chorus",
          description="Eighth-note offbeat bass — house / disco lift.",
          instruments=("bass",), roles=("chorus",), weight=1,
          apply=_bass_offbeat_chorus)
_register(name="geddy_lee_bridge", label="Geddy Lee-style bridge",
          description="Melodic chord-tone eighths + 16th-note runs.",
          instruments=("bass",), roles=("bridge",), weight=1,
          apply=_bass_geddy_lee_bridge)
_register(name="palm_mute_verse", label="Palm-mute verse bass",
          description="Short, choppy root 8ths — metal / hard-rock chug.",
          instruments=("bass",), roles=("verse",), weight=1,
          apply=_bass_palm_mute_verse)
_register(name="walking_swing_chorus", label="Walking-swing chorus",
          description="Swung walking quarters with approach tones — jazz lift.",
          instruments=("bass",), roles=("chorus",), weight=1,
          apply=_bass_walking_swing_chorus)


# ----- MELODY extras --------------------------------------------------------

def _melody_arp_chord_tones_intro(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.55, melody_style="chord_tone",
    )


def _melody_pentatonic_verse(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.65, melody_style="pentatonic",
    )


def _melody_hook_repeat_chorus(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.85, melody_style="riff",
    )


def _melody_chromatic_run_bridge(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.75, melody_style="blues",
    )


def _melody_long_held_outro(midi, ctx: TechniqueContext) -> None:
    midi.add_melody(
        key=ctx.key, scale_name=ctx.scale,
        bars=ctx.bar_count, bar_offset=ctx.start_bar,
        seed=_seed(ctx), swing=ctx.swing,
        note_density=0.25, melody_style="motif",
    )


_register(name="chord_tone_arp_intro", label="Chord-tone arpeggio intro",
          description="Slow chord-tone melody mapping the harmony for the intro.",
          instruments=("melody",), roles=("intro",), weight=1,
          apply=_melody_arp_chord_tones_intro)
_register(name="pentatonic_verse", label="Pentatonic verse melody",
          description="Pentatonic-flavoured verse line — pop/rock idiom.",
          instruments=("melody",), roles=("verse",), weight=1,
          apply=_melody_pentatonic_verse)
_register(name="hook_repeat_chorus", label="Hook-repeat chorus",
          description="Dense riff-style chorus melody — earworm potential.",
          instruments=("melody",), roles=("chorus",), weight=1,
          apply=_melody_hook_repeat_chorus)
_register(name="chromatic_bridge", label="Chromatic bridge melody",
          description="Bluesy chromatic phrases for the bridge.",
          instruments=("melody",), roles=("bridge",), weight=1,
          apply=_melody_chromatic_run_bridge)
_register(name="long_held_outro", label="Long-held outro melody",
          description="Spacious melody — fades the piece out gracefully.",
          instruments=("melody",), roles=("outro",), weight=1,
          apply=_melody_long_held_outro)


# ----- DRUMS extras ---------------------------------------------------------

def _drums_kick_pulse_intro(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="basic_rock", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.5,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_pop_16ths_verse(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="pop_16ths", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.9,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_disco_chorus(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="disco", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=1.0,
        seed=_seed(ctx), swing=ctx.swing,
    )


def _drums_jazz_swing_bridge(midi, ctx: TechniqueContext) -> None:
    midi.add_drum_pattern(
        pattern="jazz_swing", bars=ctx.bar_count,
        bar_offset=ctx.start_bar, density=0.85,
        seed=_seed(ctx), swing=max(ctx.swing, 0.25),
    )


_register(name="kick_pulse_intro", label="Kick-pulse intro",
          description="Kick on every beat, hat eighths — slow build into the verse.",
          instruments=("drums",), roles=("intro",), weight=1,
          apply=_drums_kick_pulse_intro)
_register(name="pop_16ths_verse", label="Pop 16ths verse",
          description="16th-note pop drum pattern at high density.",
          instruments=("drums",), roles=("verse",), weight=1,
          apply=_drums_pop_16ths_verse)
_register(name="disco_chorus", label="Disco chorus",
          description="Four-on-floor with clap on 2/4 and open hat on every 'and'.",
          instruments=("drums",), roles=("chorus",), weight=1,
          apply=_drums_disco_chorus)
_register(name="jazz_swing_bridge", label="Jazz swing bridge",
          description="Ride spang-a-lang with sparse ghost snare — jazz feel.",
          instruments=("drums",), roles=("bridge",), weight=1,
          apply=_drums_jazz_swing_bridge)


# ---------------------------------------------------------------------------
# Genre packs — compact factory-driven additions
# ---------------------------------------------------------------------------
# Each pack ships 4-6 genre-tagged techniques. ``compose_song`` boosts
# any technique whose tag matches the chosen preset's genre family, so
# picking ``pop_full_song`` pulls from the pop pack while
# ``rock_anthem_full`` pulls from the rock pack. Techniques without
# genre tags still compete and act as the cross-genre baseline.


def _route_kwargs(ctx, default_program=None, default_track=None):
    """Pick program + track_name for a renderer call.

    Priority: per-call default (the technique's own preference) →
    ``ctx.instrument_obj`` (the user-selected Instrument the composer
    is routing this cell to) → renderer's hard-coded default.
    """
    program = default_program
    track_name = default_track
    inst = getattr(ctx, "instrument_obj", None)
    if inst is not None:
        # Per-instrument routing overrides the technique's preference
        # so the same technique can fire on piano, organ, guitar, etc.
        program = inst.program
        track_name = inst.label
    return program, track_name


def _add_chord_tech(name, *, rhythm, roles, label, description,
                    tags=(), weight=1, voicing="seventh",
                    velocity=None, program=None, track_name=None,
                    instruments=("chords",)):
    """Register a chord-instrument technique.

    Per-call ``program`` / ``track_name`` are the technique's own
    preferences (e.g. ``program=25`` for an "acoustic strum"
    technique). When ``compose_song`` is routing the cell to a
    specific Instrument it overrides BOTH via ``ctx.instrument_obj``
    so the technique lands on the right per-instrument track.

    ``instruments`` defaults to the legacy role bucket ``("chords",)``
    so any chord-role instrument matches; pass a tuple of specific
    INSTRUMENT_REGISTRY ids (e.g. ``("trumpet",)``) for section-aware
    techniques that should ONLY fire for that instrument.
    """
    def _apply(midi, ctx):
        eff_program, eff_track = _route_kwargs(ctx, program, track_name)
        kwargs = dict(
            key=ctx.key, scale_name=ctx.scale,
            progression=ctx.progression, bars=ctx.bar_count,
            bar_offset=ctx.start_bar, rhythm=rhythm,
            voicing=voicing, swing=ctx.swing,
        )
        if velocity is not None:
            kwargs["velocity"] = velocity
        if eff_program is not None:
            kwargs["program"] = eff_program
        if eff_track is not None:
            kwargs["track_name"] = eff_track
        midi.add_chord_progression(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=instruments, roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_bass_tech(name, *, pattern, roles, label, description,
                   tags=(), weight=1, approach_tones=False,
                   velocity=None, swing_floor=None, program=None,
                   track_name=None, instruments=("bass",)):
    def _apply(midi, ctx):
        eff_program, eff_track = _route_kwargs(ctx, program, track_name)
        kwargs = dict(
            key=ctx.key, scale_name=ctx.scale,
            progression=ctx.progression, bars=ctx.bar_count,
            bar_offset=ctx.start_bar, pattern=pattern,
            approach_tones=approach_tones,
            seed=_seed(ctx),
            swing=max(ctx.swing, swing_floor or 0.0),
        )
        if velocity is not None:
            kwargs["velocity"] = velocity
        if eff_program is not None:
            kwargs["program"] = eff_program
        if eff_track is not None:
            kwargs["track_name"] = eff_track
        midi.add_bass_line(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=instruments, roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_drum_tech(name, *, pattern, roles, label, description,
                   tags=(), weight=1, density=1.0, swing_floor=None):
    def _apply(midi, ctx):
        kwargs = dict(
            pattern=pattern, bars=ctx.bar_count,
            bar_offset=ctx.start_bar, density=density,
            seed=_seed(ctx),
            swing=max(ctx.swing, swing_floor or 0.0),
        )
        # Drums use channel 10 — only track_name matters for routing.
        inst = getattr(ctx, "instrument_obj", None)
        if inst is not None:
            kwargs["track_name"] = inst.label
        # add_drum_pattern self-heals a meter-incompatible pattern by
        # falling back to a meter-appropriate default.
        midi.add_drum_pattern(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=("drums",), roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_melody_tech(name, *, roles, label, description,
                     tags=(), weight=1, note_density=0.6,
                     melody_style="motif", program=None, track_name=None,
                     instruments=("melody",),
                     phrase_shape=None, velocity_curve=None,
                     velocity_range=None, octave=None,
                     motif_development=None, rhythm_motif=None,
                     lick_pool=None):
    """Register a melody-instrument technique.

    The base factory (melody_style + note_density) is sufficient for
    generic patterns. Vocal-lead techniques additionally pin phrasing
    knobs: ``phrase_shape`` (arc/rise/fall/valley/plateau/call_response),
    ``velocity_curve`` (matches phrase_shape values; produces real
    dynamic shaping instead of jitter), explicit ``velocity_range``
    + ``octave`` for register, and ``motif_development`` /
    ``rhythm_motif`` / ``lick_pool`` for melisma-style ornamentation.
    Any kwarg left as None falls through to ``add_melody``'s default.
    """
    def _apply(midi, ctx):
        eff_program, eff_track = _route_kwargs(ctx, program, track_name)
        kwargs = dict(
            key=ctx.key, scale_name=ctx.scale,
            bars=ctx.bar_count, bar_offset=ctx.start_bar,
            seed=_seed(ctx), swing=ctx.swing,
            note_density=note_density, melody_style=melody_style,
        )
        if eff_program is not None:
            kwargs["program"] = eff_program
        if eff_track is not None:
            kwargs["track_name"] = eff_track
        if phrase_shape is not None:
            kwargs["phrase_shape"] = phrase_shape
        if velocity_curve is not None:
            kwargs["velocity_curve"] = velocity_curve
        if velocity_range is not None:
            kwargs["velocity_range"] = velocity_range
        if octave is not None:
            kwargs["octave"] = octave
        if motif_development is not None:
            kwargs["motif_development"] = motif_development
        if rhythm_motif is not None:
            kwargs["rhythm_motif"] = rhythm_motif
        if lick_pool is not None:
            kwargs["lick_pool"] = lick_pool
        midi.add_melody(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=instruments, roles=roles, tags=tags,
              weight=weight, apply=_apply)


# ----- POP ------------------------------------------------------------------
_add_chord_tech("pop_chord_pad_intro", rhythm="pad",
                roles=("intro",), tags=("pop",),
                label="Pop pad intro",
                description="Soft seventh-pad opening — pop ballad / build.")
_add_chord_tech("pop_pulse_verse", rhythm="pulse_quarter",
                roles=("verse",), tags=("pop",),
                label="Pop quarter pulse",
                description="Steady quarter-note pulse — classic pop verse.")
_add_chord_tech("pop_anthem_chorus", rhythm="stabs_8th",
                roles=("chorus",), tags=("pop",),
                label="Pop anthem chorus",
                description="Eighth-note chord stabs — radio-pop chorus lift.")
_add_bass_tech("pop_root_fifth_verse", pattern="root_fifth",
               roles=("verse",), tags=("pop",),
               label="Pop root-fifth verse",
               description="Bouncy root-fifth — pop verse staple.")
_add_drum_tech("pop_clap_chorus", pattern="pop_disco",
               roles=("chorus",), tags=("pop",), density=1.0,
               label="Pop clap chorus",
               description="Four-on-floor with clap on 2 & 4 — pop drive.")


# ----- ROCK -----------------------------------------------------------------
_add_chord_tech("rock_power_chug_verse", rhythm="van_halen_chug",
                voicing="power", roles=("verse",), tags=("rock",),
                label="Rock chug verse",
                description="Palm-muted 8th chug on power chords — verse drive.")
_add_chord_tech("rock_open_chorus", rhythm="pulse_quarter",
                voicing="power", roles=("chorus",), tags=("rock",),
                label="Rock open chorus",
                description="Open power chords on every beat — anthemic chorus.")
_add_chord_tech("rock_pad_break", rhythm="pad",
                voicing="seventh", roles=("bridge",), tags=("rock",),
                label="Rock breakdown",
                description="Held pad chords — bridge dynamic drop.")
_add_bass_tech("rock_root_eighths_verse", pattern="palm_mute_8ths",
               roles=("verse",), tags=("rock",),
               label="Rock root 8ths",
               description="Driving root 8ths — locks with the chug guitar.")
_add_bass_tech("rock_root_fifth_chorus", pattern="root_fifth",
               roles=("chorus",), tags=("rock",), approach_tones=True,
               label="Rock chorus bass",
               description="Root-fifth bass with leading tones into changes.")
_add_drum_tech("rock_anthem_chorus", pattern="basic_rock",
               roles=("chorus",), tags=("rock",), density=1.0,
               label="Rock anthem kit",
               description="Full basic-rock kit at high velocity.")


# ----- JAZZ -----------------------------------------------------------------
_add_chord_tech("jazz_charleston_comp", rhythm="charleston",
                voicing="seventh", roles=("verse",), tags=("jazz",),
                label="Jazz charleston comp",
                description="Charleston-rhythm comping — classic jazz verse.")
_add_chord_tech("jazz_dotted_chorus", rhythm="dotted_8ths",
                voicing="ninth", roles=("chorus",), tags=("jazz",),
                label="Jazz dotted-8ths chorus",
                description="Dotted-eighth chord stabs on 9th voicings.")
_add_bass_tech("jazz_walking_swing", pattern="walking_swing",
               roles=("verse", "chorus"), tags=("jazz",),
               approach_tones=True, swing_floor=0.25,
               label="Jazz walking swing",
               description="Swung walking quarters with leading tones.")
_add_melody_tech("jazz_blues_run", roles=("verse",), tags=("jazz",),
                 note_density=0.7, melody_style="blues",
                 label="Jazz blues run",
                 description="Bluesy phrasing over the verse changes.")
_add_drum_tech("jazz_swing_kit_verse", pattern="jazz_swing",
               roles=("verse",), tags=("jazz",), density=0.85,
               swing_floor=0.25,
               label="Jazz swing kit",
               description="Spang-a-lang ride with sparse ghost snare.")


# ----- BLUES ----------------------------------------------------------------
_add_chord_tech("blues_shuffle_quarter", rhythm="pulse_quarter",
                voicing="seventh", roles=("verse", "chorus"),
                tags=("blues",),
                label="Blues shuffle comp",
                description="Quarter-note dominant-7 comping for shuffle blues.")
_add_bass_tech("blues_walking_boogie", pattern="walking",
               roles=("verse", "chorus"), tags=("blues",),
               approach_tones=True, swing_floor=0.18,
               label="Blues walking boogie",
               description="Walking blues boogie line over I-IV-V changes.")
_add_melody_tech("blues_pent_riff", roles=("verse",), tags=("blues",),
                 note_density=0.75, melody_style="blues",
                 label="Blues pentatonic riff",
                 description="Pentatonic-flavoured blues riff with bends.")
_add_drum_tech("blues_shuffle_kit", pattern="basic_rock",
               roles=("verse",), tags=("blues",), density=0.8,
               swing_floor=0.18,
               label="Blues shuffle kit",
               description="Shuffled basic rock kit at medium density.")


# ----- BALLAD ---------------------------------------------------------------
_add_chord_tech("ballad_arp_intro", rhythm="arpeggio_up",
                voicing="seventh", roles=("intro",), tags=("ballad",),
                label="Ballad arpeggio intro",
                description="Rising arpeggio — emotive ballad opening.")
_add_chord_tech("ballad_sus_pad_verse", rhythm="pad",
                voicing="ninth", roles=("verse",), tags=("ballad",),
                label="Ballad sustained pad",
                description="Held 9th-chord pads under the verse melody.")
_add_chord_tech("ballad_open_chorus", rhythm="pulse_quarter",
                voicing="seventh", roles=("chorus",), tags=("ballad",),
                label="Ballad open chorus",
                description="Quarter-note seventh chords — chorus lift.")
_add_bass_tech("ballad_root_held", pattern="root",
               roles=("verse", "intro"), tags=("ballad",), velocity=68,
               label="Ballad sustained root",
               description="Single held root per bar — leaves space for melody.")
_add_drum_tech("ballad_brush_chorus", pattern="halftime",
               roles=("chorus",), tags=("ballad",), density=0.6,
               label="Ballad brush feel",
               description="Half-time pattern at low density — ballad chorus.")


# ----- EDM ------------------------------------------------------------------
_add_chord_tech("edm_pluck_drop", rhythm="stabs_8th",
                voicing="triad", roles=("chorus",), tags=("edm",),
                label="EDM pluck stab",
                description="Eighth-note stabs over the drop.")
_add_chord_tech("edm_pad_breakdown", rhythm="pad",
                voicing="seventh", roles=("bridge",), tags=("edm",),
                label="EDM breakdown pad",
                description="Long pad chords through the breakdown.")
_add_bass_tech("edm_pump_drop", pattern="disco_octave",
               roles=("chorus",), tags=("edm",),
               label="EDM octave pump",
               description="Sidechain-style octave pump for the drop.")
_add_bass_tech("edm_filter_buildup", pattern="offbeat",
               roles=("intro",), tags=("edm",),
               label="EDM offbeat buildup",
               description="Offbeat pulse — tension before the drop.")
_add_drum_tech("edm_four_on_floor_drop", pattern="dance_house",
               roles=("chorus",), tags=("edm",), density=1.0,
               label="EDM four-on-floor",
               description="House kick + offbeat hats — the drop.")


# ----- HIP-HOP / R&B --------------------------------------------------------
_add_chord_tech("hiphop_pad_loop", rhythm="pad",
                voicing="seventh", roles=("verse", "chorus"),
                tags=("hip_hop",),
                label="Hip-hop pad loop",
                description="Sustained pad loop — backbone of vocal hip-hop.")
_add_bass_tech("hiphop_sub_verse", pattern="root",
               roles=("verse",), tags=("hip_hop",), velocity=80,
               label="Hip-hop sub bass",
               description="Long sustained root — sub-bass weight.")
_add_bass_tech("hiphop_octave_hook", pattern="disco_octave",
               roles=("chorus",), tags=("hip_hop",),
               label="Hip-hop octave hook",
               description="Root/octave alternation — chorus hook.")
_add_drum_tech("hiphop_boom_bap", pattern="halftime",
               roles=("verse",), tags=("hip_hop",), density=0.7,
               label="Hip-hop boom-bap",
               description="Halftime kick/snare — boom-bap feel.")


# ----- METAL ----------------------------------------------------------------
_add_chord_tech("metal_palm_chug", rhythm="van_halen_chug",
                voicing="power", roles=("verse",), tags=("metal",),
                label="Metal palm-mute chug",
                description="Tight palm-muted 8th-note chugs.")
_add_chord_tech("metal_open_chorus", rhythm="stabs_8th",
                voicing="power", roles=("chorus",), tags=("metal",),
                label="Metal open chorus",
                description="Open power-chord stabs — chorus drive.")
_add_bass_tech("metal_gallop_verse", pattern="palm_mute_8ths",
               roles=("verse",), tags=("metal",),
               label="Metal gallop bass",
               description="Galloping palm-muted 8ths under the riff.")
_add_drum_tech("metal_double_kick", pattern="metal_gallop",
               roles=("chorus",), tags=("metal",), density=1.0,
               label="Metal gallop kit",
               description="Gallop kick + tight snare — metal chorus.")


# ----- COUNTRY --------------------------------------------------------------
_add_chord_tech("country_pulse_verse", rhythm="pulse_quarter",
                voicing="triad", roles=("verse",), tags=("country",),
                label="Country pulse verse",
                description="Open-chord quarter pulse — classic country verse.")
_add_chord_tech("country_dotted_chorus", rhythm="dotted_8ths",
                voicing="triad", roles=("chorus",), tags=("country",),
                label="Country dotted-8ths",
                description="Galloping dotted-8th strum — country chorus.")
_add_bass_tech("country_root_fifth_verse", pattern="root_fifth",
               roles=("verse", "chorus"), tags=("country",),
               approach_tones=True,
               label="Country root-fifth",
               description="Honky-tonk root-fifth with leading-tone walks.")
_add_drum_tech("country_train_beat", pattern="basic_rock",
               roles=("verse", "chorus"), tags=("country",), density=0.9,
               label="Country train beat",
               description="Steady train-beat kit feel.")
_add_melody_tech("country_pent_verse",
                 roles=("verse",), tags=("country",),
                 note_density=0.7, melody_style="pentatonic",
                 label="Country pentatonic verse",
                 description="Major-pentatonic verse line — country idiom.")


# ----- REGGAE ---------------------------------------------------------------
_add_chord_tech("reggae_skank_verse", rhythm="off_skank",
                voicing="seventh", roles=("verse",), tags=("reggae",),
                label="Reggae off-beat skank",
                description="Classic off-beat skank comp — reggae verse.")
_add_chord_tech("reggae_skank_chorus", rhythm="off_skank",
                voicing="ninth", roles=("chorus",), tags=("reggae",),
                label="Reggae chorus skank",
                description="Wider 9th voicings on the off-beat — chorus lift.")
_add_bass_tech("reggae_root_held", pattern="root",
               roles=("verse", "chorus"), tags=("reggae",),
               label="Reggae sustained root",
               description="Long sustained root tones under the skank.")
_add_drum_tech("reggae_one_drop", pattern="halftime",
               roles=("verse", "chorus"), tags=("reggae",), density=0.7,
               label="Reggae one-drop",
               description="Halftime kit feel — reggae one-drop approximation.")


# ----- LATIN / SALSA --------------------------------------------------------
_add_chord_tech("latin_montuno_verse", rhythm="montuno_2_3",
                voicing="seventh", roles=("verse",), tags=("latin",),
                label="Latin montuno",
                description="2-3 montuno piano comp — salsa verse.")
_add_chord_tech("latin_clave_chorus", rhythm="clave_son_3side",
                voicing="ninth", roles=("chorus",), tags=("latin",),
                label="Latin 3-side clave chorus",
                description="3-side clave-driven chord hits — chorus feel.")
_add_bass_tech("latin_tumbao_verse", pattern="tumbao",
               roles=("verse", "chorus"), tags=("latin",),
               label="Latin tumbao",
               description="Anticipated tumbao bass — Cuban son idiom.")
_add_drum_tech("latin_salsa_kit", pattern="salsa",
               roles=("verse", "chorus"), tags=("latin",), density=0.95,
               label="Latin salsa kit",
               description="Salsa drum / percussion pattern.")
_add_drum_tech("latin_bossa_intro", pattern="bossa_nova",
               roles=("intro",), tags=("latin",), density=0.7,
               label="Latin bossa intro",
               description="Bossa nova kit feel — light intro.")


# ----- DISCO ----------------------------------------------------------------
_add_chord_tech("disco_stabs_verse", rhythm="disco_stabs",
                voicing="seventh", roles=("verse",), tags=("disco",),
                label="Disco stabs",
                description="Disco-style chord stabs on every off-beat.")
_add_chord_tech("disco_4_on_floor_chorus", rhythm="pulse_quarter",
                voicing="seventh", roles=("chorus",), tags=("disco",),
                label="Disco quarter chorus",
                description="Quarter-note chords driving the chorus.")
_add_bass_tech("disco_octave_verse", pattern="disco_octave",
               roles=("verse", "chorus"), tags=("disco",),
               label="Disco octave bass",
               description="Pulsing root/octave alternation — classic disco.")
_add_drum_tech("disco_kit_chorus", pattern="disco",
               roles=("chorus",), tags=("disco",), density=1.0,
               label="Disco chorus kit",
               description="Four-on-floor with snare+clap and open hat on 'and'.")
_add_drum_tech("disco_kit_verse", pattern="dance_house",
               roles=("verse",), tags=("disco",), density=0.9,
               label="Disco verse kit",
               description="Lighter dance-house feel under the verse.")


# ----- SOUL / MOTOWN --------------------------------------------------------
_add_chord_tech("soul_pulse_verse", rhythm="pulse_quarter",
                voicing="seventh", roles=("verse",), tags=("soul",),
                label="Soul pulse verse",
                description="Even quarter-note 7th-chord comp — Motown verse.")
_add_chord_tech("soul_stabs_chorus", rhythm="stabs_8th",
                voicing="ninth", roles=("chorus",), tags=("soul",),
                label="Soul horn stabs",
                description="Eighth-note 9th-chord stabs — soul chorus.")
_add_bass_tech("soul_walking_verse", pattern="walking",
               roles=("verse",), tags=("soul",), approach_tones=True,
               label="Soul walking verse",
               description="Walking quarter-note bass with leading tones — Motown.")
_add_bass_tech("soul_root_fifth_chorus", pattern="root_fifth",
               roles=("chorus",), tags=("soul",),
               label="Soul root-fifth chorus",
               description="Pumping root-fifth chorus bass.")
_add_drum_tech("soul_kit_verse", pattern="halftime",
               roles=("verse",), tags=("soul",), density=0.8,
               label="Soul halftime verse",
               description="Halftime snare backbeat with hat eighths.")


# ----- PUNK -----------------------------------------------------------------
_add_chord_tech("punk_power_verse", rhythm="pulse_quarter",
                voicing="power", roles=("verse",), tags=("punk",),
                label="Punk power chords",
                description="Driving power-chord quarter pulse — punk verse.")
_add_chord_tech("punk_open_chorus", rhythm="stabs_8th",
                voicing="power", roles=("chorus",), tags=("punk",),
                label="Punk open chorus",
                description="Open power-chord 8ths — punk chorus.")
_add_bass_tech("punk_root_eighths", pattern="palm_mute_8ths",
               roles=("verse", "chorus"), tags=("punk",),
               label="Punk root 8ths",
               description="Aggressive root 8ths — locked with the guitar.")
_add_drum_tech("punk_kit_drive", pattern="basic_rock",
               roles=("verse", "chorus"), tags=("punk",), density=1.0,
               label="Punk drive kit",
               description="Full basic-rock kit at top velocity — punk drive.")


# ---------------------------------------------------------------------------
# JAZZ sub-styles — every technique tagged ``"jazz"`` AND its sub-style
# token so jazz-specific presets can pull idiomatically while generic
# `jazz_aaba_full` still wins on the broader pool.
# ---------------------------------------------------------------------------

# ----- BOSSA JAZZ -----------------------------------------------------------
_add_chord_tech("bossa_jazz_comp_verse", rhythm="bossa_comp",
                voicing="ninth", roles=("verse",),
                tags=("jazz", "bossa_jazz"),
                label="Bossa jazz comp",
                description="Brazilian 9th-chord bossa comp pattern.")
_add_chord_tech("bossa_jazz_partido_chorus", rhythm="bossa_partido",
                voicing="ninth", roles=("chorus",),
                tags=("jazz", "bossa_jazz"),
                label="Bossa partido chorus",
                description="Partido alto comp variation — chorus lift.")
_add_bass_tech("bossa_jazz_samba_bass", pattern="samba_partido_alto",
               roles=("verse", "chorus"),
               tags=("jazz", "bossa_jazz"), swing_floor=0.08,
               label="Bossa partido bass",
               description="Samba partido bass line — Brazilian bossa feel.")
_add_drum_tech("bossa_jazz_kit", pattern="bossa_nova",
               roles=("verse", "chorus"), tags=("jazz", "bossa_jazz"),
               density=0.9,
               label="Bossa nova kit",
               description="Classic bossa nova drum pattern.")


# ----- HARD BOP -------------------------------------------------------------
_add_chord_tech("hard_bop_charleston_verse", rhythm="charleston",
                voicing="seventh", roles=("verse",),
                tags=("jazz", "hard_bop"),
                label="Hard bop charleston",
                description="Tight charleston comping — hard bop verse.")
_add_chord_tech("hard_bop_dotted_chorus", rhythm="dotted_8ths",
                voicing="ninth", roles=("chorus",),
                tags=("jazz", "hard_bop"),
                label="Hard bop dotted-8ths",
                description="Dense dotted-eighth stabs over the changes.")
_add_bass_tech("hard_bop_walking_swing", pattern="walking_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "hard_bop"), approach_tones=True,
               swing_floor=0.3,
               label="Hard bop walking swing",
               description="Fast swung walking bass with strong leading tones.")
_add_drum_tech("hard_bop_kit", pattern="jazz_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "hard_bop"), density=1.0,
               swing_floor=0.3,
               label="Hard bop kit",
               description="Aggressive ride + snare comping — bop feel.")
_add_melody_tech("hard_bop_bebop_lines",
                 roles=("verse", "chorus"),
                 tags=("jazz", "hard_bop"),
                 note_density=0.85, melody_style="blues",
                 label="Bebop-style melodic lines",
                 description="High-density chromatic bop lines.")


# ----- MODAL JAZZ -----------------------------------------------------------
_add_chord_tech("modal_jazz_pad_verse", rhythm="pad",
                voicing="quartal" if False else "ninth",  # quartal voicing absent
                roles=("verse",), tags=("jazz", "modal_jazz"),
                label="Modal jazz pad",
                description="Sustained 9th-chord pad — modal verse texture.")
_add_chord_tech("modal_jazz_sparse_chorus", rhythm="pulse_quarter",
                voicing="ninth", roles=("chorus",),
                tags=("jazz", "modal_jazz"),
                label="Modal sparse chorus",
                description="Sparse quarter-note chord punctuation — modal lift.")
_add_bass_tech("modal_jazz_root_held", pattern="root",
               roles=("verse",), tags=("jazz", "modal_jazz"),
               label="Modal root held",
               description="Pedal-root bass under modal harmony.")
_add_bass_tech("modal_jazz_walking", pattern="walking_swing",
               roles=("chorus", "bridge"),
               tags=("jazz", "modal_jazz"),
               approach_tones=False, swing_floor=0.18,
               label="Modal walking",
               description="Walking bass without aggressive chromatic approach.")
_add_drum_tech("modal_jazz_kit", pattern="jazz_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "modal_jazz"), density=0.7,
               swing_floor=0.2,
               label="Modal jazz kit",
               description="Lighter ride/brush feel under the modal pad.")


# ----- BALLAD JAZZ ----------------------------------------------------------
_add_chord_tech("ballad_jazz_pad_verse", rhythm="pad",
                voicing="ninth", roles=("verse",),
                tags=("jazz", "ballad_jazz"),
                label="Ballad jazz pad",
                description="Slow 9th-chord pads — ballad verse mood.")
_add_chord_tech("ballad_jazz_arp_intro", rhythm="arpeggio_up",
                voicing="ninth", roles=("intro",),
                tags=("jazz", "ballad_jazz"),
                label="Ballad jazz arp intro",
                description="Rising 9th-chord arpeggio — slow intro.")
_add_bass_tech("ballad_jazz_walking_soft", pattern="walking_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "ballad_jazz"),
               approach_tones=True, swing_floor=0.22, velocity=70,
               label="Ballad jazz walking",
               description="Quiet swung walking bass — ballad weight.")
_add_drum_tech("ballad_jazz_brushes", pattern="halftime",
               roles=("verse", "chorus"),
               tags=("jazz", "ballad_jazz"), density=0.5,
               swing_floor=0.2,
               label="Ballad jazz brushes",
               description="Halftime brush-feel kit — ballad backbone.")


# ----- BEBOP ----------------------------------------------------------------
_add_chord_tech("bebop_dotted_verse", rhythm="dotted_8ths",
                voicing="ninth", roles=("verse",), tags=("jazz", "bebop"),
                label="Bebop dotted comping",
                description="Dense dotted-eighth comping — bebop verse.")
_add_bass_tech("bebop_walking_dense", pattern="walking_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "bebop"),
               approach_tones=True, swing_floor=0.32,
               label="Bebop fast walking",
               description="Fast swing walking with chromatic substitutions.")
_add_drum_tech("bebop_kit", pattern="jazz_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "bebop"), density=1.0, swing_floor=0.32,
               label="Bebop kit",
               description="Spang-a-lang ride + frequent ghost snare comping.")
_add_melody_tech("bebop_chromatic_lines",
                 roles=("verse", "chorus"),
                 tags=("jazz", "bebop"),
                 note_density=0.9, melody_style="blues",
                 label="Bebop chromatic lines",
                 description="Dense chromatic eighth-note bebop phrasing.")


# ----- JAZZ BLUES -----------------------------------------------------------
_add_chord_tech("jazz_blues_comp", rhythm="pulse_quarter",
                voicing="seventh", roles=("verse", "chorus"),
                tags=("jazz", "blues", "jazz_blues"),
                label="Jazz blues comp",
                description="Quarter-note dominant-7 comping — jazz blues.")
_add_chord_tech("jazz_blues_charleston", rhythm="charleston",
                voicing="ninth", roles=("verse", "chorus"),
                tags=("jazz", "blues", "jazz_blues"),
                label="Jazz blues charleston",
                description="Charleston rhythm on 9th-chord blues changes.")
_add_bass_tech("jazz_blues_walking", pattern="walking_swing",
               roles=("verse", "chorus"),
               tags=("jazz", "blues", "jazz_blues"),
               approach_tones=True, swing_floor=0.25,
               label="Jazz blues walking",
               description="Swung walking bass over I7-IV7-V7 blues changes.")
_add_melody_tech("jazz_blues_lines",
                 roles=("verse", "chorus"),
                 tags=("jazz", "blues", "jazz_blues"),
                 note_density=0.8, melody_style="blues",
                 label="Jazz blues melodic lines",
                 description="Blues-scale lines with chromatic decoration.")


# ---------------------------------------------------------------------------
# Piano comping styles
# ---------------------------------------------------------------------------
# Catalogued left-hand / right-hand patterns from jazz + classical
# pedagogy. These all target the ``chords`` instrument and re-use
# existing rhythm/voicing names — block, alberti, rolled (arpeggio_16th),
# dotted-eighth comp, sparse 2-and-4 charleston, sustained 9th pad,
# octave bass riff, and a split-hand walking-tenths technique that
# overlays a walking single-pitch line under a held chord on the same
# Chords track.

_add_chord_tech("piano_block_quarter",
                rhythm="pulse_quarter", voicing="seventh",
                roles=("verse", "chorus"), tags=("piano",), weight=2,
                label="Piano block (quarter)",
                description="Block 7th-chord on every beat — classic piano comping.")
_add_chord_tech("piano_alberti_bass",
                rhythm="alberti", voicing="seventh",
                roles=("intro", "verse"), tags=("piano",), weight=2,
                label="Alberti bass piano",
                description="Broken-chord Alberti pattern — Mozart-era piano LH idiom.")
_add_chord_tech("piano_rolled_16ths",
                rhythm="arpeggio_16th", voicing="ninth",
                roles=("verse", "chorus"), tags=("piano",), weight=2,
                label="Rolled 16th-note piano",
                description="Continuous 16th-note broken chords — flowing piano texture.")
_add_chord_tech("piano_dotted_jazz_comp",
                rhythm="dotted_8ths", voicing="ninth",
                roles=("verse", "chorus"), tags=("piano", "jazz"), weight=2,
                label="Jazz dotted comping",
                description="Dotted-8th stabs on 9th voicings — bebop / hard-bop piano.")
_add_chord_tech("piano_sparse_charleston",
                rhythm="charleston", voicing="ninth",
                roles=("verse",), tags=("piano", "jazz"), weight=2,
                label="Sparse charleston piano",
                description="Sparse 2-and-4 charleston — jazz piano comp behind a soloist.")
_add_chord_tech("piano_sustained_9th",
                rhythm="pad", voicing="ninth",
                roles=("intro", "verse", "outro"), tags=("piano", "ballad"),
                weight=2,
                label="Sustained 9th voicings",
                description="Long-held 9th-chord voicings — Bill Evans / ballad piano.")
_add_chord_tech("piano_octaves_riff",
                rhythm="elton_octaves", voicing="triad",
                roles=("chorus", "bridge"), tags=("piano",), weight=2,
                label="Octave riff piano",
                description="Elton-style octave riff — anthemic piano lift.")


def _piano_walking_tenths(midi, ctx: TechniqueContext) -> None:
    """Two-handed piano: walking single-pitch line in the bass clef +
    sustained chord above, both written to the Chords track so the
    listener hears one piano performance.

    Right hand renders the chord-voicing pitches as a pad; left hand
    renders a walking bass line on the lowest pitch of each chord (one
    octave below the chord's natural octave). The MidiExporter happily
    overlays both passes onto the same track.
    """
    midi.add_bass_line(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, pattern="walking",
        octave=2, track_name="Chords",
        program=0,  # piano
        approach_tones=True,
        seed=_seed(ctx), swing=ctx.swing, velocity=70,
    )
    midi.add_chord_progression(
        key=ctx.key, scale_name=ctx.scale,
        progression=ctx.progression, bars=ctx.bar_count,
        bar_offset=ctx.start_bar, rhythm="pad",
        voicing="seventh", track_name="Chords", program=0,
        swing=ctx.swing,
    )


_register(name="piano_walking_tenths", label="Walking tenths (split hands)",
          description="LH walks a single-pitch bass line while RH holds the chord — Bill Evans / cocktail piano.",
          instruments=("chords",), roles=("verse", "chorus"),
          tags=("piano", "jazz"), weight=2,
          apply=_piano_walking_tenths)


# ---------------------------------------------------------------------------
# Piano — more idiomatic patterns
# ---------------------------------------------------------------------------
_add_chord_tech("piano_arpeggio_classical", rhythm="arpeggio_up",
                voicing="seventh", roles=("intro", "verse", "outro"),
                tags=("piano", "ballad"),
                label="Classical broken chord", weight=2,
                description="Slow rising arpeggio — Romantic-era classical piano texture.")
_add_chord_tech("piano_arpeggio_down", rhythm="arpeggio_down",
                voicing="seventh", roles=("outro",),
                tags=("piano",),
                label="Descending arpeggio outro", weight=2,
                description="Falling arpeggio — settles the piece down.")
_add_chord_tech("piano_dotted_ragtime", rhythm="dotted_8ths",
                voicing="triad", roles=("verse", "chorus"),
                tags=("piano",),
                label="Ragtime dotted comping", weight=2,
                description="Dotted-eighth triadic comping — ragtime / honky-tonk feel.")
_add_chord_tech("piano_pad_intro", rhythm="pad",
                voicing="ninth", roles=("intro",),
                tags=("piano", "ballad"),
                label="Piano pad intro", weight=2,
                description="Soft 9th-chord pad — slow piano intro.")
_add_chord_tech("piano_stabs_2_4", rhythm="charleston",
                voicing="seventh", roles=("chorus", "bridge"),
                tags=("piano",),
                label="Piano stabs on 2 & 4", weight=2,
                description="Charleston-style stabs on the backbeat.")
_add_chord_tech("piano_block_pop", rhythm="stabs_8th",
                voicing="seventh", roles=("chorus",),
                tags=("piano", "pop"),
                label="Pop piano block 8ths", weight=2,
                description="Eighth-note block chords — pop piano chorus.")


# ---------------------------------------------------------------------------
# Guitar styles (chord-instrument, program=25 acoustic / 27 clean electric /
#                  29 overdriven). Track name stays "Chords" — the timbre
# locks to whichever guitar program the first guitar-technique fired with.
# ---------------------------------------------------------------------------
_add_chord_tech("guitar_acoustic_strum", rhythm="pulse_quarter",
                voicing="triad", program=25,
                roles=("verse", "chorus"), tags=("guitar", "acoustic"),
                weight=2,
                label="Acoustic strum",
                description="Steel-string acoustic quarter-note strum — folk / pop verse.")
_add_chord_tech("guitar_fingerstyle", rhythm="alberti",
                voicing="seventh", program=25,
                roles=("verse", "intro"), tags=("guitar", "acoustic"),
                weight=2,
                label="Fingerstyle picking",
                description="Travis-style alternating pick — fingerstyle acoustic verse.")
_add_chord_tech("guitar_clean_8ths", rhythm="stabs_8th",
                voicing="seventh", program=27,
                roles=("verse", "chorus"), tags=("guitar",),
                weight=2,
                label="Clean electric 8ths",
                description="Clean electric guitar 8th-note strum — pop rock.")
_add_chord_tech("guitar_overdrive_power", rhythm="van_halen_chug",
                voicing="power", program=29,
                roles=("verse", "chorus"), tags=("guitar", "rock"),
                weight=2,
                label="Overdrive power chords",
                description="Overdriven palm-mute power chord chug — hard rock.")
_add_chord_tech("guitar_jangle_arp", rhythm="arpeggio_up",
                voicing="seventh", program=27,
                roles=("verse", "intro"), tags=("guitar",),
                weight=2,
                label="Jangle arpeggio",
                description="Byrds-style 12-string jangle arpeggio.")


# ---------------------------------------------------------------------------
# Organ styles (program 18=Rock Organ / 19=Church Organ / 16=Drawbar)
# ---------------------------------------------------------------------------
_add_chord_tech("organ_hammond_pad", rhythm="pad",
                voicing="ninth", program=16,
                roles=("verse", "outro"), tags=("organ",),
                weight=2,
                label="Hammond pad",
                description="Drawbar-organ sustained 9ths — Hammond soul / rock pad.")
_add_chord_tech("organ_gospel_pulse", rhythm="pulse_quarter",
                voicing="seventh", program=18,
                roles=("verse", "chorus"), tags=("organ", "gospel"),
                weight=2,
                label="Gospel organ pulse",
                description="Rock-organ quarter pulses — gospel comping.")
_add_chord_tech("organ_church_sustain", rhythm="pad",
                voicing="triad", program=19,
                roles=("intro", "outro"), tags=("organ", "ballad"),
                weight=2,
                label="Church organ sustain",
                description="Long held triads on church organ — sacred / ballad intro.")
_add_chord_tech("organ_funk_stab", rhythm="stabs_8th",
                voicing="ninth", program=18,
                roles=("chorus", "bridge"), tags=("organ", "funk_rock"),
                weight=2,
                label="Funk organ stab",
                description="Stabbing 8th-note rock-organ — funky comp.")


# ---------------------------------------------------------------------------
# String section (program 48=Strings 1 / 45=Pizzicato / 44=Tremolo)
# ---------------------------------------------------------------------------
_add_chord_tech("strings_long_pad", rhythm="pad",
                voicing="ninth", program=48,
                roles=("intro", "verse", "outro"), tags=("strings", "ballad"),
                weight=2,
                label="Strings long pad",
                description="String-ensemble sustained pad — cinematic.")
_add_chord_tech("strings_pizzicato_stabs", rhythm="stabs_8th",
                voicing="triad", program=45,
                roles=("verse", "bridge"), tags=("strings",),
                weight=2,
                label="Pizzicato strings",
                description="Short pizzicato chord stabs — playful verse.")
_add_chord_tech("strings_tremolo_swell", rhythm="pad",
                voicing="seventh", program=44,
                roles=("bridge", "chorus"), tags=("strings",),
                weight=2,
                label="Tremolo strings swell",
                description="Tremolo strings on sustained chords — building tension.")
_add_chord_tech("strings_quarter_pulse", rhythm="pulse_quarter",
                voicing="seventh", program=48,
                roles=("chorus",), tags=("strings",),
                weight=2,
                label="Strings quarter pulse",
                description="Marcato quarter-note strings — chorus drive.")


# ---------------------------------------------------------------------------
# Brass section (program 61=Brass Section / 56=Trumpet)
# ---------------------------------------------------------------------------
_add_chord_tech("brass_stabs_horn", rhythm="stabs_8th",
                voicing="ninth", program=61,
                roles=("chorus", "bridge"), tags=("brass", "soul"),
                weight=2,
                label="Brass section stabs",
                description="Tight brass-section 8th-note stabs — soul / Motown chorus.")
_add_chord_tech("brass_swell_long", rhythm="pad",
                voicing="seventh", program=61,
                roles=("intro", "outro"), tags=("brass",),
                weight=2,
                label="Brass swell",
                description="Long-sustained brass swell.")
_add_chord_tech("brass_punch_2_4", rhythm="charleston",
                voicing="ninth", program=61,
                roles=("verse",), tags=("brass", "funk_rock"),
                weight=2,
                label="Brass 2-and-4 punch",
                description="Brass hits on the backbeat — funk horn section.")


# ---------------------------------------------------------------------------
# Synth styles (program 89=Warm Pad / 90=Polysynth / 81=Synth Lead Square)
# ---------------------------------------------------------------------------
_add_chord_tech("synth_warm_pad", rhythm="pad",
                voicing="ninth", program=89,
                roles=("intro", "verse", "outro"), tags=("synth",),
                weight=2,
                label="Warm synth pad",
                description="Lush warm-pad 9ths — ambient synth backbone.")
_add_chord_tech("synth_pluck_arp", rhythm="arpeggio_16th",
                voicing="seventh", program=82,
                roles=("verse", "chorus"), tags=("synth", "edm"),
                weight=2,
                label="Synth pluck arpeggio",
                description="Plucky 16th-note synth arpeggio.")
_add_chord_tech("synth_polysynth_stabs", rhythm="stabs_8th",
                voicing="seventh", program=90,
                roles=("chorus", "bridge"), tags=("synth", "pop", "edm"),
                weight=2,
                label="Polysynth stabs",
                description="80s-style polysynth chord stabs.")


# ---------------------------------------------------------------------------
# Drums — additional patterns
# ---------------------------------------------------------------------------
_add_drum_tech("drums_motown_backbeat", pattern="halftime",
               roles=("verse", "chorus"), tags=("soul", "motown"),
               density=0.9,
               label="Motown backbeat",
               description="Halftime backbeat with steady hat — Motown idiom.")
_add_drum_tech("drums_dnb_breaks", pattern="metal_blast",
               roles=("chorus", "bridge"), tags=("edm", "drum_n_bass"),
               density=1.0,
               label="Drum'n'bass breakbeat",
               description="Fast breakbeat-style pattern — DnB chorus.")
_add_drum_tech("drums_country_train", pattern="basic_rock",
               roles=("verse", "chorus"), tags=("country",), density=0.85,
               label="Country train beat alt",
               description="Brushy 8th-note kit with steady kick — country.")
_add_drum_tech("drums_afrobeat_kit", pattern="afrobeat",
               roles=("verse", "chorus", "bridge"), tags=("latin", "afro"),
               density=0.95,
               label="Afrobeat kit",
               description="Afrobeat-style multi-layered percussion.")
_add_drum_tech("drums_reggaeton_dembow", pattern="reggaeton",
               roles=("verse", "chorus"), tags=("latin",),
               density=0.95,
               label="Reggaeton dembow",
               description="Reggaeton dembow drum / percussion.")
_add_drum_tech("drums_samba", pattern="samba",
               roles=("verse", "chorus"), tags=("latin", "bossa_jazz"),
               density=0.9,
               label="Samba kit",
               description="Brazilian samba drum pattern.")
_add_drum_tech("drums_compound_6_8", pattern="compound_6_8",
               roles=("verse", "chorus", "bridge"), tags=("ballad",),
               density=0.85,
               label="Compound 6/8 feel",
               description="6/8 compound-time drum pattern.")
_add_drum_tech("drums_breakbeat_funk", pattern="funk",
               roles=("verse",), tags=("hip_hop",), density=0.9,
               label="Breakbeat funk loop",
               description="Funk breakbeat loop — sampled hip-hop feel.")
_add_drum_tech("drums_neil_peart_fill", pattern="neil_peart",
               roles=("bridge", "chorus"), tags=("rock",), density=1.0,
               label="Neil Peart-style fills",
               description="Tom-heavy prog-rock-style drum pattern.")
_add_drum_tech("drums_chad_smith_pocket", pattern="chad_smith",
               roles=("verse", "chorus"), tags=("funk_rock", "rock"),
               density=1.0,
               label="Chad Smith pocket",
               description="Tight funk-rock groove pocket.")


# ---------------------------------------------------------------------------
# Bass — additional patterns
# ---------------------------------------------------------------------------
_add_bass_tech("bass_jamerson_motown", pattern="walking",
               roles=("verse", "chorus"), tags=("soul", "motown"),
               approach_tones=True,
               label="Jamerson-style Motown bass",
               description="James Jamerson syncopated walking — Motown feel.")
_add_bass_tech("bass_dub_root_drone", pattern="root",
               roles=("verse",), tags=("reggae",), velocity=80,
               label="Dub root drone",
               description="Long sustained root with occasional accent — dub reggae.")
_add_bass_tech("bass_paul_mccartney_melodic", pattern="walking",
               roles=("verse", "chorus"), tags=("pop",),
               approach_tones=True,
               label="McCartney-style melodic bass",
               description="Melodic walking bass with chord-tone embellishment.")
_add_bass_tech("bass_country_chromatic_walk", pattern="walking",
               roles=("verse", "chorus"), tags=("country",),
               approach_tones=True,
               label="Country chromatic walk",
               description="Walking quarters with chromatic approaches — Nashville.")
_add_bass_tech("bass_synth_arp_edm", pattern="offbeat",
               roles=("verse", "chorus"), tags=("edm", "synth"),
               program=38,  # Synth Bass 1
               label="Synth bass arp",
               description="Offbeat synth-bass arp — EDM / synthwave.")
_add_bass_tech("bass_pedal_drone_low", pattern="root",
               roles=("intro", "bridge", "outro"), tags=("ballad", "modal_jazz"),
               velocity=65,
               label="Pedal drone bass",
               description="Long held root — pedal-point texture.")
_add_bass_tech("bass_picked_country_walk", pattern="root_fifth",
               roles=("verse",), tags=("country",),
               approach_tones=True,
               label="Picked country walking",
               description="Picked root-fifth with chromatic walks — country two-step.")
_add_bass_tech("bass_dance_house_pulse", pattern="offbeat",
               roles=("verse", "chorus"), tags=("edm", "disco"),
               label="Dance / house pulse",
               description="Eighth-note offbeat — house / dance drive.")


# ---------------------------------------------------------------------------
# Section-aware techniques — tagged with specific INSTRUMENT_REGISTRY ids
# so that picking trumpet / sax_tenor / violin etc. lands on idiomatic
# brass / wind / string vocabulary first, falling back to the generic
# role bucket for cells the section pack doesn't cover. The shared
# rhythm patterns (``brass_shout`` / ``tremolo`` / ``pizz_alternating``)
# let multiple section instruments coordinate at the rhythm level without
# any cross-instrument scheduling logic.
# ---------------------------------------------------------------------------

# ----- Brass -----
_add_chord_tech("trumpet_shout_lead", rhythm="brass_shout",
                voicing="ninth", roles=("chorus", "bridge"),
                tags=("brass", "shout", "big_band"),
                instruments=("trumpet",), weight=3,
                label="Trumpet shout lead",
                description="Driving 8th-note shout chorus on 9th voicings — big-band lead trumpet.")
_add_chord_tech("trumpet_fanfare", rhythm="fanfare_dotted",
                voicing="triad", roles=("intro", "chorus"),
                tags=("brass", "fanfare", "cinematic"),
                instruments=("trumpet",), weight=2,
                label="Trumpet fanfare",
                description="Heroic dotted-8th fanfare — Strauss / Williams.")
_add_melody_tech("trumpet_bebop_lines", melody_style="chord_tone",
                 roles=("verse", "bridge"),
                 tags=("brass", "jazz", "bebop"),
                 instruments=("trumpet",), weight=2,
                 note_density=0.85,
                 label="Trumpet bebop lines",
                 description="Chord-tone-targeted bebop lines with dense rhythmic activity.")
_add_chord_tech("trombone_shout_third", rhythm="brass_shout",
                voicing="triad", roles=("chorus", "bridge"),
                tags=("brass", "shout"),
                instruments=("trombone",), weight=2,
                label="Trombone shout (third)",
                description="Trombone supporting the brass shout on triadic voicing.")
_add_melody_tech("trombone_tailgate", melody_style="riff",
                 roles=("verse",),
                 tags=("brass", "dixieland"),
                 instruments=("trombone",), weight=2,
                 note_density=0.5,
                 label="Trombone tailgate",
                 description="Dixieland-style trombone tailgate riff with slide-friendly intervals.")
_add_melody_tech("sax_tenor_solo_lick", melody_style="blues",
                 roles=("verse", "bridge"),
                 tags=("brass", "jazz", "solo"),
                 instruments=("sax_tenor",), weight=3,
                 note_density=0.75,
                 label="Tenor sax solo lick",
                 description="Blues-scale solo lines — straight-ahead tenor sax solo.")
_add_melody_tech("sax_alto_counter_thirds", melody_style="chord_tone",
                 roles=("chorus",),
                 tags=("brass", "counter"),
                 instruments=("sax_alto",), weight=2,
                 note_density=0.6,
                 label="Alto sax counter-thirds",
                 description="Chord-tone counter-melody — shadows the lead a third below.")
_add_chord_tech("brass_section_swell", rhythm="brass_pad_swell",
                voicing="seventh", roles=("intro", "outro"),
                tags=("brass", "swell"),
                instruments=("brass_section",), weight=2,
                label="Brass section swell",
                description="Long brass crescendo into a hit — intro / outro.")

# ----- Woodwind -----
_add_melody_tech("flute_soaring_arc", melody_style="motif",
                 roles=("chorus", "bridge"),
                 tags=("woodwind", "lyrical"),
                 instruments=("flute",), weight=3,
                 note_density=0.55,
                 label="Flute soaring arc",
                 description="Lyrical arcing line in the upper register — orchestral lift.")
_add_melody_tech("flute_trill_cadence", melody_style="chord_tone",
                 roles=("outro",),
                 tags=("woodwind", "classical"),
                 instruments=("flute",), weight=2,
                 note_density=0.9,
                 label="Flute trill cadence",
                 description="Trill-heavy cadential figure — classical tail.")
_add_melody_tech("clarinet_legato_line", melody_style="motif",
                 roles=("verse",),
                 tags=("woodwind", "legato"),
                 instruments=("clarinet",), weight=2,
                 note_density=0.45,
                 label="Clarinet legato line",
                 description="Long-tone legato line — chamber color.")
_add_melody_tech("clarinet_smear_blues", melody_style="blues",
                 roles=("bridge",),
                 tags=("woodwind", "jazz", "dixieland"),
                 instruments=("clarinet",), weight=2,
                 note_density=0.7,
                 label="Clarinet smear blues",
                 description="Blues-scale smears — dixieland clarinet break.")
_add_melody_tech("oboe_lyrical_sparse", melody_style="motif",
                 roles=("intro", "verse"),
                 tags=("woodwind", "lyrical", "cinematic"),
                 instruments=("oboe",), weight=2,
                 note_density=0.35,
                 label="Oboe lyrical sparse",
                 description="Plaintive sparse oboe solo — film score color.")
_add_chord_tech("bassoon_staccato_pulse", rhythm="pulse_quarter",
                voicing="triad", roles=("verse",),
                tags=("woodwind", "comic", "bass_double"),
                instruments=("bassoon",), weight=2,
                label="Bassoon staccato pulse",
                description="Staccato quarter pulse — comic / cartoon character.")

# ----- Strings -----
_add_chord_tech("violin_divisi_pad_top", rhythm="pad",
                voicing="seventh", roles=("intro", "verse", "outro"),
                tags=("strings", "pad", "cinematic"),
                instruments=("violin",), weight=2,
                label="Violin divisi pad (top voice)",
                description="Sustained 7th-pad on violins — cinematic top voice.")
_add_chord_tech("violin_tremolo_swell", rhythm="tremolo",
                voicing="triad", roles=("bridge", "chorus"),
                tags=("strings", "tremolo", "tension"),
                instruments=("violin",), weight=2,
                label="Violin tremolo swell",
                description="Triadic tremolo — Herrmann tension build.")
_add_chord_tech("violin_staccato_ostinato", rhythm="string_ostinato_16ths",
                voicing="triad", roles=("verse", "bridge"),
                tags=("strings", "ostinato", "cinematic"),
                instruments=("violin",), weight=2,
                label="Violin staccato ostinato",
                description="Repeated 16ths with quarter accents — Reich / film ostinato.")
_add_chord_tech("viola_long_pad_middle", rhythm="pad",
                voicing="seventh", roles=("intro", "verse", "outro"),
                tags=("strings", "pad"),
                instruments=("viola",), weight=2,
                label="Viola long pad",
                description="Sustained 7th-pad on viola — middle-register fill.")
_add_bass_tech("cello_arco_bass", pattern="root_fifth",
               roles=("intro", "verse", "outro"),
               tags=("strings", "bass_double"),
               instruments=("cello",), weight=2,
               velocity=72,
               label="Cello arco bass",
               description="Sustained arco root-fifth — orchestral bass double.")
_add_chord_tech("cello_pizz_eighths", rhythm="pizz_alternating",
                voicing="triad", roles=("verse",),
                tags=("strings", "pizzicato"),
                instruments=("cello",), weight=2,
                program=45,  # Pizzicato Strings
                label="Cello pizzicato 8ths",
                description="Pizz on the upbeats — under sustained brass/wind.")
_add_bass_tech("contrabass_pedal", pattern="root",
               roles=("intro", "outro"),
               tags=("strings", "bass", "pedal"),
               instruments=("contrabass",), weight=2,
               velocity=60,
               label="Contrabass pedal",
               description="Sustained tonic / dominant pedal on contrabass.")
_add_chord_tech("string_section_shimmer", rhythm="tremolo",
                voicing="ninth", roles=("bridge",),
                tags=("strings", "tremolo", "shimmer"),
                instruments=("string_section",), weight=2,
                program=44,  # Tremolo Strings
                label="String section shimmer",
                description="Tremolo on extended voicings — section shimmer texture.")


# ---------------------------------------------------------------------------
# Vocal techniques — lead phrasing styles + backing-vocal stacks. Each lead
# technique pins a distinct phrasing profile (density / shape / dynamics /
# register) so the random song generator gives a song's vocal line a
# recognisable idiomatic character per section. Backing-vocal techniques
# register as chord-techs (so they flow through the voicing-layer rules)
# at GM 52 Choir Aahs.
# ---------------------------------------------------------------------------

# ----- Lead vocal phrasing techniques -----
_add_melody_tech("vocal_lead_ballad_sustain",
                 melody_style="motif", note_density=0.3,
                 phrase_shape="plateau", velocity_curve="arc",
                 velocity_range=(60, 90),
                 roles=("intro", "verse", "outro"),
                 tags=("vocal", "ballad", "lyrical"),
                 instruments=("vocal_lead",), weight=3,
                 label="Vocal ballad sustain",
                 description="Long-tone ballad phrasing — sparse, intimate, swelling.")
_add_melody_tech("vocal_lead_intimate_verse",
                 melody_style="motif", note_density=0.35,
                 phrase_shape="valley", velocity_range=(55, 85),
                 octave=4,
                 roles=("verse",),
                 tags=("vocal", "intimate", "ballad"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal intimate verse",
                 description="Low-register, sparse, conversational verse delivery.")
_add_melody_tech("vocal_lead_jazz_crooner",
                 melody_style="chord_tone", note_density=0.5,
                 phrase_shape="call_response", velocity_curve="fall",
                 roles=("verse",),
                 tags=("vocal", "jazz", "crooner"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal jazz crooner",
                 description="Laid-back call-response motif — Sinatra / Nat King Cole.")
_add_melody_tech("vocal_lead_country_twang",
                 melody_style="pentatonic", note_density=0.6,
                 phrase_shape="arc",
                 roles=("verse", "chorus"),
                 tags=("vocal", "country", "twang"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal country twang",
                 description="Pentatonic country phrasing — Dolly / Hank shape.")
_add_melody_tech("vocal_lead_hooky_motif",
                 melody_style="motif", note_density=0.6,
                 motif_development=["repeat", "sequence_up", "repeat", "cadence"],
                 roles=("chorus",),
                 tags=("vocal", "pop", "hook"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal hooky motif",
                 description="Earworm 2-bar motif sequenced up then resolved — pop chorus hook.")
_add_melody_tech("vocal_lead_pop_chorus_belt",
                 melody_style="motif", note_density=0.75,
                 phrase_shape="arc", velocity_curve="arc",
                 velocity_range=(80, 110),
                 roles=("chorus",),
                 tags=("vocal", "pop", "belt"),
                 instruments=("vocal_lead",), weight=3,
                 label="Vocal pop chorus belt",
                 description="Anthemic chorus belt — driving 8ths with crescendo.")
_add_melody_tech("vocal_lead_rnb_melisma",
                 melody_style="pentatonic", note_density=0.85,
                 phrase_shape="arc",
                 rhythm_motif="gospel_melisma_5_to_1",
                 lick_pool=["gospel_melisma_5_to_1"],
                 roles=("chorus", "bridge"),
                 tags=("vocal", "rnb", "soul", "melisma"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal R&B melisma",
                 description="Dense melismatic chord-tone runs — Aretha / Whitney style.")
_add_melody_tech("vocal_lead_gospel_lift",
                 melody_style="pentatonic", note_density=0.7,
                 phrase_shape="rise", velocity_curve="rise",
                 roles=("chorus", "outro"),
                 tags=("vocal", "gospel", "soul"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal gospel lift",
                 description="Rising pentatonic gospel adlib into the chorus / vamp.")
_add_melody_tech("vocal_lead_rock_belt",
                 melody_style="chord_tone", note_density=0.7,
                 phrase_shape="rise", velocity_curve="rise",
                 octave=6,
                 roles=("chorus", "bridge"),
                 tags=("vocal", "rock", "belt"),
                 instruments=("vocal_lead",), weight=2,
                 label="Vocal rock belt",
                 description="High-register power belt — chord-tone targeting at octave 6.")

# ----- Backing vocal techniques (register as chord-techs to flow through
# the voicing-layer proxy and route to the Backing Vocals track) -----
_add_chord_tech("vocal_harmony_oohs_pad", rhythm="pad",
                voicing="seventh", program=52,  # Choir Aahs
                roles=("intro", "verse", "chorus", "outro"),
                tags=("vocal", "pad", "oohs"),
                instruments=("vocal_harmony",), weight=3,
                label="Backing oohs pad",
                description="Sustained ooh-pad backing — bed under the lead.")
_add_chord_tech("vocal_harmony_aahs_chorus", rhythm="pad",
                voicing="ninth", program=52,
                roles=("chorus",),
                tags=("vocal", "pad", "aahs"),
                instruments=("vocal_harmony",), weight=2,
                label="Backing aahs chorus",
                description="Wide aah-pad on extensions — chorus expansion.")
_add_chord_tech("vocal_harmony_doowop_block", rhythm="stabs_8th",
                voicing="triad", program=52,
                roles=("chorus",),
                tags=("vocal", "doowop", "motown"),
                instruments=("vocal_harmony",), weight=2,
                label="Backing doowop block",
                description="Block triadic stabs — Beach Boys / doowop hits.")
_add_chord_tech("vocal_harmony_gospel_stack", rhythm="pad",
                voicing="ninth", program=52,
                roles=("chorus", "bridge", "outro"),
                tags=("vocal", "gospel", "soul"),
                instruments=("vocal_harmony",), weight=2,
                label="Backing gospel stack",
                description="Wide gospel-stack pad — choir-style 9ths.")
_add_chord_tech("vocal_harmony_motown_charleston", rhythm="charleston",
                voicing="seventh", program=52,
                roles=("verse", "chorus"),
                tags=("vocal", "motown", "soul"),
                instruments=("vocal_harmony",), weight=2,
                label="Backing Motown charleston",
                description="Motown call-and-response stabs on the charleston rhythm.")


logger.info(
    "Registered %d techniques in the bank.", len(BANK.all_techniques()),
)
