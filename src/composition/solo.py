"""Guitar-solo engine: sequence licks into a phrased, building solo.

Turns a bare section (today a silent "pad") into an actual lead-guitar
solo by sequencing licks from :mod:`src.composition.licks` with:

* a **call-and-response** grammar (alternate call -> response phrases),
* **voice-leading** bias — prefer a next lick whose first note is near the
  previous lick's last note (Herremans),
* **repetition + exactly one variation** for memorability without monotony
  (Computoser), and
* an **intensity arc** — establish -> develop -> climax (register climb,
  higher velocity, top-register target) -> resolve with a turnaround lick.

The arc shape is a design inference (the sources support repetition-for-
intensity and space, but not an explicit arc); it is intentionally simple
and easy to tune.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import numpy as np

from src.composition.licks import Lick, licks_for, render_lick
from src.daw_integration.generic.midi_export import (
    MidiExporter,
    chord_at_position,
    expand_progression_plan,
)

_VARIATIONS = ("transpose_up", "transpose_down", "vary_ending",
               "notes_to_rests", "retrograde")


def vary_lick(lick: Lick, op: str) -> Lick:
    """Return a copy of ``lick`` with exactly one variation operation applied."""
    notes = [replace(n) for n in lick.notes]
    if op == "transpose_up":
        for n in notes:
            if n.degree is not None:
                n.degree += 1
    elif op == "transpose_down":
        for n in notes:
            if n.degree is not None:
                n.degree = max(0, n.degree - 1)
    elif op == "vary_ending":
        for n in reversed(notes):
            if n.degree is not None:
                n.degree += 2
                break
    elif op == "notes_to_rests":
        for i, n in enumerate(notes):
            if i % 3 == 2:
                n.degree = None
    elif op == "retrograde":
        degs = [n.degree for n in notes][::-1]
        for n, d in zip(notes, degs):
            n.degree = d
    return replace(lick, name=f"{lick.name}_{op}", notes=notes)


def _choose(pool: list[Lick], prev: Optional[Lick], rng) -> Lick:
    """Pick a lick from ``pool`` biased toward smooth voice-leading from ``prev``."""
    if not pool:
        raise ValueError("empty lick pool")
    if prev is None or len(pool) == 1:
        return pool[int(rng.integers(len(pool)))]
    plast = prev.last_degree()

    def score(lk: Lick) -> int:
        f = lk.first_degree()
        if f is None or plast is None:
            return 99
        return abs(f - plast)

    ordered = sorted(pool, key=score)
    top = ordered[: max(1, len(ordered) // 2)]
    return top[int(rng.integers(len(top)))]


def build_solo(
    midi: MidiExporter,
    *,
    bars: int,
    progression,
    key: str,
    scale_type: str = "minor",
    genre: str = "rock",
    rng=None,
    track_name: str = "Lead",
    program: int = 29,
    velocity: int = 90,
    swing: float = 0.0,
    octave: int = 4,
    bar_offset: int = 0,
    intensity_arc: bool = True,
) -> list[tuple[int, str]]:
    """Render a solo across ``bars`` bars; return (bar, lick_name) placements.

    ``bar_offset`` shifts the solo to a section that doesn't start at song
    bar 0. ``progression`` is sliced to this section already (as ``ctx``
    provides it).
    """
    if rng is None:
        rng = np.random.default_rng()
    if bars <= 0:
        return []

    events = expand_progression_plan(progression, bars)
    pools = {role: licks_for(genre, role)
             for role in ("call", "response", "riff", "turnaround")}
    everything = licks_for(genre)

    def pool_for(role: str) -> list[Lick]:
        return pools.get(role) or everything

    placements: list[tuple[int, str]] = []
    prev: Optional[Lick] = None
    want = "call"
    repeats = 0
    bpb = midi.beats_per_bar

    for bar in range(bars):
        progress = bar / max(bars, 1)
        last_bar = bar == bars - 1

        # Role selection across the arc.
        if intensity_arc and last_bar and pools.get("turnaround"):
            role = "turnaround"
        elif intensity_arc and 0.3 <= progress < 0.6 and pools.get("riff"):
            role = "riff"            # develop: denser repeated figures
        else:
            role = want

        # Repetition + one variation: sometimes restate the previous lick
        # varied, rather than a fresh one (caps consecutive repeats at 2).
        if (prev is not None and not last_bar and repeats < 2
                and rng.random() < 0.33):
            op = _VARIATIONS[int(rng.integers(len(_VARIATIONS)))]
            lick = vary_lick(prev, op)
            repeats += 1
        else:
            lick = _choose(pool_for(role), prev, rng)
            repeats = 0

        chord = chord_at_position(events, float(bar)) or "I"

        # Intensity arc: velocity ramp + climax register climb (~70-90%).
        vel = min(120, velocity + int(progress * 22))
        reg_bump = 1 if (intensity_arc and 0.68 <= progress < 0.92) else 0

        render_lick(
            midi, lick,
            key=key, chord_symbol=chord, scale_type=scale_type,
            bar_start_beats=(bar_offset + bar) * bpb,
            octave=octave, track_name=track_name, program=program,
            velocity=vel, swing=swing, register_octave_bump=reg_bump,
        )
        placements.append((bar_offset + bar, lick.name))
        prev = lick
        want = "response" if want == "call" else "call"

    return placements
