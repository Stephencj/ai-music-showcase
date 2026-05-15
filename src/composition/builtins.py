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


def _add_chord_tech(name, *, rhythm, roles, label, description,
                    tags=(), weight=1, voicing="seventh",
                    velocity=None):
    def _apply(midi, ctx):
        kwargs = dict(
            key=ctx.key, scale_name=ctx.scale,
            progression=ctx.progression, bars=ctx.bar_count,
            bar_offset=ctx.start_bar, rhythm=rhythm,
            voicing=voicing, swing=ctx.swing,
        )
        if velocity is not None:
            kwargs["velocity"] = velocity
        midi.add_chord_progression(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=("chords",), roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_bass_tech(name, *, pattern, roles, label, description,
                   tags=(), weight=1, approach_tones=False,
                   velocity=None, swing_floor=None):
    def _apply(midi, ctx):
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
        midi.add_bass_line(**kwargs)
    _register(name=name, label=label, description=description,
              instruments=("bass",), roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_drum_tech(name, *, pattern, roles, label, description,
                   tags=(), weight=1, density=1.0, swing_floor=None):
    def _apply(midi, ctx):
        midi.add_drum_pattern(
            pattern=pattern, bars=ctx.bar_count,
            bar_offset=ctx.start_bar, density=density,
            seed=_seed(ctx),
            swing=max(ctx.swing, swing_floor or 0.0),
        )
    _register(name=name, label=label, description=description,
              instruments=("drums",), roles=roles, tags=tags,
              weight=weight, apply=_apply)


def _add_melody_tech(name, *, roles, label, description,
                     tags=(), weight=1, note_density=0.6,
                     melody_style="motif"):
    def _apply(midi, ctx):
        midi.add_melody(
            key=ctx.key, scale_name=ctx.scale,
            bars=ctx.bar_count, bar_offset=ctx.start_bar,
            seed=_seed(ctx), swing=ctx.swing,
            note_density=note_density, melody_style=melody_style,
        )
    _register(name=name, label=label, description=description,
              instruments=("melody",), roles=roles, tags=tags,
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


logger.info(
    "Registered %d techniques in the bank.", len(BANK.all_techniques()),
)
