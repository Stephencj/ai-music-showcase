"""Transposable guitar-lick library + compiler.

Research (Herremans/Cunha; Computoser) says authentic guitar leads are
assembled from reusable ~1-bar *licks* that embed articulation, not
generated note-by-note. A lick here is written in **scale-degree space**
(degrees of a genre scale rooted at the key tonic — how guitarists think
in pentatonic "boxes"), with per-note articulation marks. The compiler
:func:`render_lick` lays a lick over a concrete chord, **snapping
strong-beat notes to the current chord's tones** (the recommended
transposition-to-chord-tones) while weak/passing notes stay in the scale,
and realises bends/vibrato via the MidiExporter articulation layer.

Articulation marks (each maps to a pitch-bend gesture *into* the written
target pitch, so the destination note is what's notated):
    bend_half     — bend up a semitone into the note  (wheel -1 -> 0)
    bend_whole    — bend up a whole tone into the note (wheel -2 -> 0)
    prebend_whole — pre-bent a whole tone, released down (wheel +2 -> 0)
    vibrato       — sustained vibrato LFO
    slide_up      — quick slide up into the note
    slide_down    — quick slide down off the note
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from src.daw_integration.generic.midi_export import (
    CHORD_FORMULAS,
    MidiExporter,
    SCALES,
    note_name_to_midi,
    roman_to_semitone_offset,
)

# Default scale a genre's licks are written against (degrees index into it).
GENRE_SCALE = {
    "rock": "pentatonic_minor",
    "blues": "blues",
    "country": "pentatonic_major",
}

# Articulation name -> (bend_from_st, bend_to_st) ramp, or None. The note's
# notated pitch is the *destination*; the wheel ramps into it.
_BEND_MAP = {
    "bend_half": (-1.0, 0.0),
    "bend_whole": (-2.0, 0.0),
    "prebend_whole": (2.0, 0.0),
    "bend_release_whole": (0.0, 2.0),  # up; release handled in render_lick
    "slide_up": (-3.0, 0.0),
    "slide_down": (0.0, -3.0),
}
_VIBRATO_ARTICS = {"vibrato"}


@dataclass
class LickNote:
    """One note of a lick in scale-degree space (or a rest)."""
    degree: Optional[int]            # index into the lick's scale; None == rest
    beat: float                      # onset within the bar, in beats
    dur: float                       # duration in beats
    octave: int = 0                  # octave offset from the base octave
    strong: bool = False             # snap to a chord tone at compile time
    articulation: Optional[str] = None
    velocity: Optional[int] = None   # overrides the call-level velocity


@dataclass
class Lick:
    """A ~1-bar transposable lick."""
    name: str
    genre: str
    role: str                        # call | response | riff | turnaround
    notes: list[LickNote]
    scale: Optional[str] = None      # scale the degrees index into; default per-genre
    register: str = "mid"            # low | mid | high

    def first_degree(self) -> Optional[int]:
        for n in self.notes:
            if n.degree is not None:
                return n.degree
        return None

    def last_degree(self) -> Optional[int]:
        for n in reversed(self.notes):
            if n.degree is not None:
                return n.degree
        return None


# ---------------------------------------------------------------------------
# Compiler helpers
# ---------------------------------------------------------------------------

def _degree_to_pitch(tonic: int, scale: list[int], degree: int, octave_off: int) -> int:
    n = len(scale)
    octs = degree // n
    idx = degree % n
    return tonic + scale[idx] + 12 * octs + 12 * octave_off


def chord_pitch_classes(chord_symbol: str, key: str, scale_type: str) -> set[int]:
    """Pitch classes (0-11) of the chord's tones in the given key."""
    tonic_pc = note_name_to_midi(key, 0) % 12
    offset, quality = roman_to_semitone_offset(chord_symbol, scale_type)
    root_pc = (tonic_pc + offset) % 12
    formula = CHORD_FORMULAS.get(quality, CHORD_FORMULAS["maj"])
    return {(root_pc + iv) % 12 for iv in formula}


def snap_to_chord_tone(pitch: int, chord_pcs: set[int]) -> int:
    """Nudge ``pitch`` to the nearest pitch whose class is a chord tone."""
    if not chord_pcs:
        return pitch
    for d in range(0, 7):
        for cand in (pitch - d, pitch + d):
            if cand % 12 in chord_pcs:
                return cand
    return pitch


def _swung(beat: float, swing: float) -> float:
    """Delay the 'and' of each beat by ``swing`` (0 straight, ~0.33 triplet)."""
    if swing <= 0:
        return beat
    base = math.floor(beat)
    frac = beat - base
    if abs(frac - 0.5) < 1e-3:
        return base + 0.5 + swing * 0.5
    return beat


def render_lick(
    midi: MidiExporter,
    lick: Lick,
    *,
    key: str,
    chord_symbol: str,
    scale_type: str = "major",
    bar_start_beats: float,
    octave: int = 4,
    track_name: str = "Lead",
    program: int = 29,
    velocity: int = 92,
    swing: float = 0.0,
    register_octave_bump: int = 0,
) -> list[int]:
    """Render one lick over one chord; return the emitted MIDI pitches.

    ``bar_start_beats`` is the lick's bar onset in beats from song start.
    Strong-beat degrees snap to ``chord_symbol``'s chord tones; weak ones
    stay in the lick's scale. Articulation marks become pitch bends /
    vibrato via :meth:`MidiExporter.add_articulated_note`.
    """
    scale_name = lick.scale or GENRE_SCALE.get(lick.genre, "pentatonic_minor")
    scale = SCALES.get(scale_name, SCALES["pentatonic_minor"])
    tonic = note_name_to_midi(key, octave)
    chord_pcs = chord_pitch_classes(chord_symbol, key, scale_type)
    reg = {"low": -1, "mid": 0, "high": 1}.get(lick.register, 0) + register_octave_bump
    beat_dur = midi.beat_duration
    emitted: list[int] = []

    for ln in lick.notes:
        if ln.degree is None:
            continue
        pitch = _degree_to_pitch(tonic, scale, ln.degree, ln.octave + reg)
        if ln.strong:
            pitch = snap_to_chord_tone(pitch, chord_pcs)
        pitch = max(0, min(127, pitch))

        onset_beats = bar_start_beats + _swung(ln.beat, swing)
        start = onset_beats * beat_dur
        dur = max(ln.dur * beat_dur, 0.05)
        vel = ln.velocity if ln.velocity is not None else velocity

        art = ln.articulation
        bend = _BEND_MAP.get(art) if art else None
        vibrato = art in _VIBRATO_ARTICS if art else False

        midi.add_articulated_note(
            track_name, pitch, start, dur,
            velocity=vel, program=program, bend=bend, vibrato=vibrato,
        )
        # bend-and-release: append the downward half on the same track.
        if art == "bend_release_whole":
            track = midi._track_for(track_name, program=program)
            midi._emit_bend(track, start + dur * 0.5, dur * 0.5, 2.0, 0.0)
        emitted.append(pitch)

    return emitted


# ---------------------------------------------------------------------------
# Lick library (Rock first; Blues/Country added in Phase 5)
# ---------------------------------------------------------------------------

def _ln(degree, beat, dur, **kw):
    return LickNote(degree=degree, beat=beat, dur=dur, **kw)


_ROCK_LICKS = [
    Lick("rock_box_call_a", "rock", "call", [
        _ln(0, 0.0, 0.5, strong=True),
        _ln(1, 0.5, 0.5),
        _ln(3, 1.0, 1.0, strong=True, articulation="bend_whole"),
        _ln(4, 2.0, 0.5),
        _ln(3, 2.5, 0.5),
        _ln(1, 3.0, 1.0, articulation="vibrato"),
    ]),
    Lick("rock_box_resp_a", "rock", "response", [
        _ln(4, 0.0, 0.5),
        _ln(3, 0.5, 0.5),
        _ln(2, 1.0, 0.5),
        _ln(1, 1.5, 0.5, articulation="bend_half"),
        _ln(0, 2.0, 2.0, strong=True, articulation="vibrato"),
    ]),
    Lick("rock_box_riff", "rock", "riff", [
        _ln(0, 0.0, 0.5, strong=True), _ln(4, 0.5, 0.5),
        _ln(0, 1.0, 0.5), _ln(3, 1.5, 0.5),
        _ln(0, 2.0, 0.5, strong=True), _ln(4, 2.5, 0.5),
        _ln(0, 3.0, 0.5), _ln(3, 3.5, 0.5),
    ]),
    Lick("rock_climb_call", "rock", "call", [
        _ln(0, 0.0, 0.5, strong=True), _ln(1, 0.5, 0.5),
        _ln(2, 1.0, 0.5), _ln(3, 1.5, 0.5),
        _ln(4, 2.0, 1.0, articulation="bend_half"),
        _ln(5, 3.0, 1.0, strong=True, articulation="vibrato"),
    ]),
    Lick("rock_turnaround", "rock", "turnaround", [
        _ln(4, 0.0, 0.5, articulation="bend_whole"),
        _ln(3, 0.5, 0.5), _ln(2, 1.0, 0.5), _ln(1, 1.5, 0.5),
        _ln(0, 2.0, 2.0, strong=True, articulation="vibrato"),
    ]),
]

# Blues: blue-note (b5) call/response with space and shuffle phrasing.
# Written in the "blues" scale: [root, b3, 4, b5, 5, b7] -> idx 0..5.
_BLUES_LICKS = [
    Lick("blues_call_a", "blues", "call", [
        _ln(3, 0.0, 0.5, articulation="bend_half"),          # b5 blue note, bent
        _ln(4, 0.5, 1.0, strong=True, articulation="vibrato"),  # 5
        _ln(None, 1.5, 0.5),                                  # space
        _ln(1, 2.0, 1.0, articulation="bend_whole"),          # b3 bent
        _ln(0, 3.0, 1.0, strong=True),                        # root
    ]),
    Lick("blues_resp_a", "blues", "response", [
        _ln(5, 0.0, 0.5),                                     # b7
        _ln(4, 0.5, 0.5),                                     # 5
        _ln(3, 1.0, 0.5, articulation="bend_half"),           # b5
        _ln(2, 1.5, 0.5),                                     # 4
        _ln(1, 2.0, 0.5),                                     # b3
        _ln(0, 2.5, 1.5, strong=True, articulation="vibrato"),  # root resolve
    ]),
    Lick("blues_shuffle_riff", "blues", "riff", [
        _ln(0, 0.0, 0.5, strong=True), _ln(4, 0.5, 0.5),
        _ln(0, 1.0, 0.5), _ln(5, 1.5, 0.5),
        _ln(0, 2.0, 0.5, strong=True), _ln(4, 2.5, 0.5),
        _ln(0, 3.0, 0.5), _ln(5, 3.5, 0.5),
    ]),
    Lick("blues_turnaround", "blues", "turnaround", [
        _ln(5, 0.0, 0.5, articulation="bend_half"),
        _ln(4, 0.5, 0.5), _ln(2, 1.0, 0.5), _ln(1, 1.5, 0.5),
        _ln(0, 2.0, 1.0, strong=True),
        _ln(3, 3.0, 0.5, articulation="bend_half"),           # b5 lead-in
        _ln(4, 3.5, 0.5, strong=True, articulation="vibrato"),
    ]),
]

LICKS: dict[str, list[Lick]] = {
    "rock": _ROCK_LICKS,
    "blues": _BLUES_LICKS,
}


def licks_for(genre: str, role: Optional[str] = None) -> list[Lick]:
    """Return licks for a genre, optionally filtered by role."""
    pool = LICKS.get(genre, LICKS.get("rock", []))
    if role is not None:
        pool = [lk for lk in pool if lk.role == role]
    return list(pool)
