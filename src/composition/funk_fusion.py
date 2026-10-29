"""High-energy funk-fusion techniques (tag ``funk_fusion``).

The bouncy video-game fusion sound (think a kart racer's title screen): the
drums kick off and build, the band hits a one-bar unison riff, then fast
straight 16ths, a slap-style bass with thumb roots and popped octaves, horn
stabs, Rhodes chops, a hooky sax lead the horns answer, and a band-wide
unison riff that opens the tune, turns the chorus around and ends it.

The riff is the hook everyone plays together, so its notes are drawn from a
seed shared by the whole section (not each instrument's own rng): bass,
horns, sax, Rhodes and kick all land on the same accents.

Helpers (clock, harmony, voicings, track routing) come from
:mod:`src.composition.fusion`.
"""

from __future__ import annotations

import zlib
from typing import Optional

import numpy as np

from src.composition.techniques import TechniqueContext
from src.daw_integration.generic.midi_export import NoteEvent

from .builtins import _register
from .fusion import (
    ALL_ROLES, CLOSED_HAT, CRASH, KICK, OPEN_HAT, PEDAL_HAT, RIDE, SNARE,
    TOM_HI, TOM_LO, TOM_MID, _SEVENTH, _VOICINGS, _Clock, _Harmony, _emit,
    _fits, _human, _scale_pitches, _voice,
)

TAG = "funk_fusion"
HIGH_ROLES = ("chorus", "solo", "drop")


# ---------------------------------------------------------------------------
# The shared riff
# ---------------------------------------------------------------------------

# One bar of 16ths: (step, length). Accents land off the beat.
_RIFF_RHYTHMS = (
    ((0, 2), (3, 1), (4, 1), (6, 2), (9, 1), (10, 2), (13, 1), (14, 2)),
    ((0, 1), (2, 1), (3, 2), (6, 1), (7, 1), (8, 2), (11, 1), (12, 1), (14, 2)),
    ((0, 2), (2, 1), (3, 1), (6, 2), (8, 1), (10, 1), (11, 2), (14, 1), (15, 1)),
    ((0, 1), (1, 1), (2, 2), (6, 1), (7, 1), (8, 1), (10, 2), (13, 1), (14, 2)),
    ((2, 1), (3, 1), (4, 2), (7, 1), (8, 2), (10, 1), (11, 1), (12, 2), (15, 1)),
    ((0, 3), (3, 1), (4, 1), (5, 1), (6, 2), (10, 1), (11, 1), (12, 1), (14, 2)),
)
_PENTA = (0, 2, 4, 7, 9)      # major pentatonic; the blue note (3) slides into the 3rd (4)


def _shared_rng(ctx: TechniqueContext) -> np.random.Generator:
    """Same riff for every instrument in this section of this song."""
    key = f"{ctx.song_seed}|{ctx.key}|{ctx.scale}|{ctx.section_label}|{ctx.start_bar}|{ctx.bar_count}"
    return np.random.default_rng(zlib.crc32(key.encode()))


def _riff_line(rng: np.random.Generator, count: int, start: int, end_on_tonic: bool) -> list[int]:
    """Semitones above the tonic for ``count`` riff notes: a walk over the
    major pentatonic (degree 5 = the octave) with blue-note slides."""
    degree = start
    out: list[int] = []
    for i in range(count):
        if i:
            step = int(rng.choice((-2, -1, -1, 0, 1, 1, 2)))
            degree = int(np.clip(degree + step, 0, 7))
        semis = _PENTA[degree % 5] + 12 * (degree // 5)
        # Bluesy slide: approach the 3rd from the minor 3rd.
        if semis % 12 == 4 and out and out[-1] % 12 != 3 and rng.random() < 0.5:
            out.append(semis - 1)
            continue
        out.append(semis)
    if end_on_tonic:
        out[-1] = 12 if out[-1] > 6 else 0
    return out


def riff_notes(ctx: TechniqueContext, bars: tuple[int, ...], feel: str = "intro") -> list[tuple[int, int, int, int]]:
    """The riff over the given section bars as (bar, step, length, semitones
    above the tonic). Each instrument places it in its own register.

    A riff is two bars, a call and its answer, repeated over ``bars``. A
    one-bar turnaround or ending plays just the answer, which resolves."""
    rng = _shared_rng(ctx)
    rhythm = _RIFF_RHYTHMS[int(rng.integers(0, len(_RIFF_RHYTHMS)))]
    call = _riff_line(rng, len(rhythm), int(rng.choice((0, 1, 2))), end_on_tonic=False)
    answer_start = int(np.clip(round(np.mean([_PENTA.index(p % 12) if p % 12 in _PENTA else 2 for p in call])) + 1, 0, 5))
    answer = _riff_line(rng, len(rhythm), answer_start, end_on_tonic=True)
    out = []
    answer_first = feel != "intro" and len(bars) == 1
    for n, bar in enumerate(bars):
        line = call if (n % 2 == 0) != answer_first else answer
        for (step, length), semis in zip(rhythm, line):
            out.append((bar, step, length, semis))
    return out


def riff_bars(ctx: TechniqueContext, feel: str) -> tuple[int, ...]:
    """Where the band plays the riff in a section of this role."""
    n = ctx.bar_count
    if feel == "intro":
        return (n - 1,)                        # drums build, then the band hits the riff
    if feel in HIGH_ROLES and n >= 4:
        return (n - 1,)                        # one-bar turnaround into what's next
    if feel == "outro":
        return tuple(range(max(0, n - 1)))     # riff, then the final hit
    return ()


# ---------------------------------------------------------------------------
# DRUMS
# ---------------------------------------------------------------------------

_KICKS = {
    "verse":  ((0, 6, 10), (0, 3, 8, 10, 14)),
    "high":   ((0, 4, 6, 10, 12), (0, 3, 6, 8, 11, 14)),
    "bridge": ((0, 10), (0, 6, 7)),
}


def _drums(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    bars = ctx.bar_count
    hits: list[tuple[int, float, int, float]] = []
    riff = riff_bars(ctx, feel)
    riff_steps: dict[int, list[tuple[int, int]]] = {}
    for bar, step, length, _ in riff_notes(ctx, riff, feel):
        riff_steps.setdefault(bar, []).append((step, length))
    high = feel in HIGH_ROLES
    kicks = _KICKS["high" if high else "bridge" if feel in ("bridge", "breakdown") else "verse"]

    for bar in range(bars):
        last = bar == bars - 1
        if feel == "outro" and last:
            hits += [(bar, 0, KICK, 118), (bar, 0, CRASH, 116), (bar, 0, SNARE, 108),
                     (bar, 0, TOM_LO, 100)]
            continue
        # In the intro the fill is the build in the bar before the riff.
        big_fill = (bar == bars - 2) if feel == "intro" else (last and feel != "outro")
        small_fill = (bar % 4 == 3) and not big_fill and bar not in riff and ctx.drum_fill >= 0.5
        if bar in riff_steps:
            # Riff bar: kick and snare punch the riff's accents, hats keep 8ths.
            for step, length in riff_steps[bar]:
                if length >= 2 or step % 4 == 0:
                    hits.append((bar, step, KICK, 110))
                    hits.append((bar, step, SNARE, 96 if step % 8 == 4 else 80))
            for step in range(0, clock.steps, 2):
                hits.append((bar, step, CLOSED_HAT, 80 if step % 4 == 0 else 58))
            if bar == riff[0]:
                hits.append((bar, 0, CRASH, 112))
            continue
        if feel in ("bridge", "breakdown"):
            half = bars // 2
            if bar < half:   # bass-and-drums breakdown, half-time
                for step in range(0, clock.steps, 2):
                    hits.append((bar, step, PEDAL_HAT if step % 4 else CLOSED_HAT, 64))
                hits.append((bar, 8, SNARE, 110))
            else:            # build: snare 8ths then 16ths, rising
                rate = 2 if bar < bars - 1 else 1
                for i, step in enumerate(range(0, clock.steps, rate)):
                    v = 60 + 40 * (bar - half + i / clock.steps * rate) / max(1, bars - half)
                    hits.append((bar, step, SNARE, v))
                hits.append((bar, 0, CRASH, 90))
            for step in kicks[bar % 2]:
                hits.append((bar, step, KICK, 100))
            continue
        # Groove: 16th hats, open on the offbeats in the high sections.
        for step in range(clock.steps):
            if (big_fill and step >= 8) or (small_fill and step >= 12):
                continue
            if high and step % 4 == 2:
                hits.append((bar, step, OPEN_HAT, 78))
            else:
                hits.append((bar, step, CLOSED_HAT, (90, 46, 66, 46)[step % 4] + (4 if high else 0)))
        hits += [(bar, 4, SNARE, 114), (bar, 12, SNARE, 116)]
        for step in kicks[bar % 2]:
            if (big_fill and step >= 8) or (small_fill and step >= 12):
                continue
            hits.append((bar, step, KICK, 108 if step == 0 else 96))
        for s in (7, 9, 15) if bar % 2 else (3, 7, 11):
            if not ((big_fill and s >= 8) or (small_fill and s >= 12)):
                hits.append((bar, s, SNARE, float(rng.integers(28, 42))))
        if bar % 4 == 0:
            hits.append((bar, 0, CRASH, 104 if bar == 0 else 92))
        if small_fill:
            for i, (step, key) in enumerate(((12, SNARE), (13, SNARE), (14, TOM_HI), (15, TOM_MID))):
                hits.append((bar, step, key, 84 + 6 * i))
        if big_fill:
            seq = (SNARE, SNARE, TOM_HI, TOM_HI, TOM_MID, TOM_MID, TOM_LO, TOM_LO)
            for i, key in enumerate(seq):
                hits.append((bar, 8 + i, key, 82 + 4 * i))
                if i % 2 == 0:
                    hits.append((bar, 8 + i, KICK, 92))

    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            hits += [(bar, st, CRASH, 112), (bar, st, KICK, 116), (bar, st, SNARE, 104)]

    notes = []
    for bar, step, key, vel in hits:
        t, v = _human(rng, clock.t(bar, step), vel, ms=2.5, vel_jitter=4.0 if vel > 50 else 3.0)
        dur = clock.step_len * (8 if key in (CRASH, RIDE, OPEN_HAT) else 1)
        notes.append(NoteEvent(pitch=key, start=t, end=t + dur, velocity=v))
    _emit(midi, ctx, notes, name="Drums", program=0, is_drum=True)


# ---------------------------------------------------------------------------
# SLAP BASS
# ---------------------------------------------------------------------------

# T thumb root, P popped octave, G dead note, 5 fifth, 7 seventh, B blue
# note (minor 3rd) hammering onto the 3rd, 3 major third, A approach.
_SLAP = {
    "verse": (
        ((0, "T", 2, 112), (2, "G", 1, 44), (3, "P", 1, 104), (4, "G", 1, 44), (6, "T", 1, 100),
         (7, "P", 1, 106), (8, "T", 2, 108), (10, "G", 1, 44), (11, "P", 1, 104), (12, "7", 1, 96),
         (13, "5", 1, 94), (14, "P", 1, 106), (15, "A", 1, 98)),
        ((0, "T", 1, 112), (1, "T", 1, 96), (2, "P", 1, 106), (3, "G", 1, 44), (4, "B", 1, 96),
         (5, "3", 1, 100), (6, "5", 2, 100), (8, "T", 1, 108), (9, "G", 1, 44), (10, "P", 1, 106),
         (11, "T", 1, 98), (12, "P", 2, 104), (14, "5", 1, 96), (15, "A", 1, 98)),
    ),
    "high": (
        ((0, "T", 1, 116), (1, "G", 1, 46), (2, "P", 1, 110), (3, "T", 1, 104), (4, "G", 1, 46),
         (5, "P", 1, 110), (6, "T", 1, 106), (7, "P", 1, 110), (8, "T", 1, 112), (9, "G", 1, 46),
         (10, "P", 1, 110), (11, "T", 1, 104), (12, "5", 1, 104), (13, "P", 1, 110), (14, "7", 1, 104),
         (15, "A", 1, 102)),
        ((0, "T", 2, 116), (2, "P", 1, 112), (3, "G", 1, 46), (4, "T", 1, 108), (6, "P", 1, 110),
         (7, "T", 1, 104), (8, "B", 1, 102), (9, "3", 1, 106), (10, "5", 1, 106), (11, "P", 1, 112),
         (12, "T", 1, 106), (13, "G", 1, 46), (14, "P", 1, 112), (15, "A", 1, 104)),
    ),
    "bridge": (
        ((0, "T", 3, 112), (3, "P", 1, 108), (4, "G", 1, 46), (5, "G", 1, 46), (6, "P", 2, 110),
         (8, "T", 1, 108), (9, "T", 1, 100), (10, "P", 1, 110), (11, "G", 1, 46), (12, "B", 1, 100),
         (13, "3", 1, 104), (14, "5", 1, 104), (15, "P", 1, 110)),
    ),
}
_LO, _HI = 31, 55


def _bass(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    riff = riff_bars(ctx, feel)
    by_bar: dict[int, list] = {}
    for bar, step, length, semis in riff_notes(ctx, riff, feel):
        by_bar.setdefault(bar, []).append((step, length, semis))
    bank = _SLAP["high" if feel in HIGH_ROLES else "bridge" if feel in ("bridge", "breakdown") else "verse"]
    notes: list[NoteEvent] = []
    prev: Optional[int] = None
    for bar in range(bars):
        if feel == "outro" and bar == bars - 1:
            root_pc, _ = harm.at(bar)
            p = _fits(harm.tonic + 36, _LO, _LO + 11)
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + clock.bar_len, velocity=118))
            continue
        if feel == "intro" and bar not in by_bar:
            continue                              # the intro is drums until the riff
        if bar in by_bar:
            for step, length, semis in by_bar[bar]:
                p = _fits(harm.tonic + semis + 36, _LO, _LO + 18)
                s, v = _human(rng, clock.t(bar, step), 112 if length > 1 else 104, ms=2.5, vel_jitter=4.0)
                notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.85, velocity=v))
                prev = p
            continue
        pattern = bank[bar % len(bank)]
        for step, deg, length, vel in pattern:
            pos = bar + step / clock.steps
            root_pc, quality = harm.at(pos)
            root = _fits(root_pc + 36, _LO, _LO + 11)
            third = 3 if quality in ("min7", "min", "dim") else 4
            if deg == "T":
                pitch = root
            elif deg == "P":
                pitch = root + 12
            elif deg == "5":
                pitch = root + 7
            elif deg == "7":
                pitch = root + _SEVENTH.get(quality, 10)
            elif deg == "3":
                pitch = root + third
            elif deg == "B":
                pitch = root + third - 1 if third == 4 else root + 2
            elif deg == "G":
                pitch = prev if prev is not None else root
            else:
                nxt_pc, _ = harm.at(min(bar + 1.0, bars - 1e-6))
                target = _fits(nxt_pc + 36, _LO, _LO + 11)
                pitch = target - 1 if bar + 1 < bars else root + 7
            pitch = _fits(pitch, _LO, _HI)
            if deg == "G":
                s, v = _human(rng, clock.t(bar, step), vel, ms=2.0, vel_jitter=3.0)
                e = s + clock.step_len * 0.3
            else:
                s, v = _human(rng, clock.t(bar, step), vel, ms=2.5, vel_jitter=4.0)
                e = s + clock.step_len * length * (0.6 if deg == "P" else 0.85)
            notes.append(NoteEvent(pitch=pitch, start=s, end=e, velocity=v))
            if deg != "G":
                prev = pitch
    _emit(midi, ctx, notes, name="Bass", program=36)


# ---------------------------------------------------------------------------
# HORN SECTION
# ---------------------------------------------------------------------------

# (step, length, velocity) stab patterns per 2 bars (steps 0-31).
_STABS = {
    "verse": ((30, 1, 106),),                              # one push every two bars
    "high": ((0, 2, 112), (14, 1, 104), (30, 2, 112)),
    "bridge": ((0, 4, 104), (16, 4, 108)),
}
HIT_CLEAR = 3        # 16ths kept clear of other stabs around a hit point


def hit_steps(ctx: TechniqueContext, clock: "_Clock") -> dict[int, set[int]]:
    """This section's hit points as bar → 16th steps (nearest 16th)."""
    out: dict[int, set[int]] = {}
    first = ctx.start_bar * clock.steps
    for t in ctx.hits:
        step = int(round(t / clock.step_len)) - first
        if 0 <= step < ctx.bar_count * clock.steps:
            out.setdefault(step // clock.steps, set()).add(step % clock.steps)
    return out


def _near_hit(hits: dict[int, set[int]], bar: int, step: int, steps: int) -> bool:
    at = bar * steps + step
    return any(abs(at - (b * steps + s)) <= HIT_CLEAR for b, ss in hits.items() for s in ss)


def _horn_voicing(root_pc: int, quality: str, top_near: int) -> list[int]:
    """Close-position 4-note brass voicing, top voice near ``top_near``."""
    shape = (0,) + tuple(iv for iv in _VOICINGS.get(quality, _VOICINGS["7"]) if iv % 12 != 0)[:3]
    pcs = sorted({(root_pc + iv) % 12 for iv in shape})
    top = min((p for p in range(top_near - 6, top_near + 7) if p % 12 in pcs), key=lambda p: abs(p - top_near))
    voices = [top]
    for _ in range(3):
        nxt = voices[-1] - 1
        while (nxt % 12 not in pcs or nxt % 12 in {v % 12 for v in voices}) and nxt > top - 24:
            nxt -= 1
        voices.append(nxt)
    return sorted(voices)


def _part(voicing: list[int], part: str) -> list[int]:
    """Top two voices to the trumpet, bottom two to the trombone."""
    if part == "trumpet":
        return voicing[-2:]
    if part == "trombone":
        return voicing[:2]
    return voicing


def _horns(midi, ctx: TechniqueContext, feel: str) -> None:
    """Brass section stabs. A trumpet plays the top of each voicing and the
    riff's upper octave, a trombone the bottom and lower octave; a composite
    Brass Section track plays both."""
    part = ctx.instrument if ctx.instrument in ("trumpet", "trombone") else "section"
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    riff = riff_bars(ctx, feel)
    notes: list[NoteEvent] = []
    riff_set = set(riff)
    # The riff in octaves: trumpet line on top, trombone an octave below.
    for bar, step, length, semis in riff_notes(ctx, riff, feel):
        top = _fits(harm.tonic + semis + 60, 62, 77)
        s, v = _human(rng, clock.t(bar, step), 108 if length > 1 else 100, ms=3.0, vel_jitter=4.0)
        octaves = {"trumpet": (top,), "trombone": (top - 12,)}.get(part, (top, top - 12))
        for p in octaves:
            notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.8, velocity=v))
    pattern = _STABS["high" if feel in HIGH_ROLES else "bridge" if feel in ("bridge", "breakdown") else "verse"]
    top_near = 74 if feel in HIGH_ROLES else 70
    hits = hit_steps(ctx, clock)
    for bar, steps_ in hits.items():
        for st in steps_:
            root_pc, quality = harm.at(bar + st / clock.steps)
            s, v = _human(rng, clock.t(bar, st), 120, ms=1.5, vel_jitter=2.0)
            for p in _part(_horn_voicing(root_pc, quality, 76), part):
                notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * 2 * 0.85, velocity=v))
    for pair in range(0, bars, 2):
        for step, length, vel in pattern:
            bar = pair + step // clock.steps
            if bar >= bars or bar in riff_set or feel == "intro":
                continue
            if feel == "outro" and bar == bars - 1 and step:
                continue
            st = step % clock.steps
            if _near_hit(hits, bar, st, clock.steps):
                continue
            pos = bar + st / clock.steps
            if st >= clock.steps - 2 and bar + 1 < bars:
                pos = bar + 1.0                   # stab pushes the next chord
            root_pc, quality = harm.at(pos)
            s, v = _human(rng, clock.t(bar, st), vel, ms=3.0, vel_jitter=4.0)
            for p in _part(_horn_voicing(root_pc, quality, top_near), part):
                notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.8, velocity=v))
    if feel == "outro":
        bar = bars - 1
        for p in _part(_horn_voicing(harm.tonic, "maj", 77), part):
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + 0.35, velocity=118))
    _emit(midi, ctx, notes, name={"trumpet": "Trumpet", "trombone": "Trombone"}.get(part, "Horns"),
          program={"trumpet": 56, "trombone": 57}.get(part, 61))


# ---------------------------------------------------------------------------
# RHODES CHOPS
# ---------------------------------------------------------------------------

_CHOPS = {
    "verse": ((2, 1, 78), (6, 1, 74), (7, 1, 66), (10, 1, 78), (14, 1, 76), (15, 1, 66)),
    "high": ((0, 1, 86), (2, 1, 78), (3, 1, 70), (6, 1, 82), (8, 1, 84), (10, 1, 78), (11, 1, 70), (14, 2, 84)),
}


def _rhodes(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    riff = riff_bars(ctx, feel)
    accents: dict[int, list[int]] = {}
    for bar, step, length, _ in riff_notes(ctx, riff, feel):
        if length >= 2 or step % 4 == 0:
            accents.setdefault(bar, []).append(step)
    notes: list[NoteEvent] = []
    previous: Optional[list[int]] = None

    def chord(bar, step, length, vel, pos):
        nonlocal previous
        root_pc, quality = harm.at(pos)
        voicing = _voice(root_pc, quality, previous)
        previous = voicing
        start = clock.t(bar, step)
        for p in voicing:
            s, v = _human(rng, start, vel, ms=3.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.75, velocity=v))

    for bar in range(bars):
        if feel == "outro" and bar == bars - 1:
            chord(bar, 0, clock.steps, 96, float(bar))
            continue
        if bar in accents:
            for step in accents[bar]:
                chord(bar, step, 1, 90, bar + step / clock.steps)
            continue
        if feel == "intro":
            continue
        if feel in ("bridge", "breakdown") and bar < bars // 2:
            continue                              # breakdown: bass and drums only
        pattern = _CHOPS["high" if feel in HIGH_ROLES else "verse"]
        if feel in ("bridge", "breakdown"):
            pattern = ((0, 8, 80), (8, 8, 84))
        for step, length, vel in pattern:
            pos = bar + step / clock.steps
            if step >= clock.steps - 2 and bar + 1 < bars:
                pos = bar + 1.0
            chord(bar, step, length, vel, pos)
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            chord(bar, st, 2, 98, bar + st / clock.steps)
    _emit(midi, ctx, notes, name="Chords", program=4)


# ---------------------------------------------------------------------------
# SAX LEAD
# ---------------------------------------------------------------------------

# Two-bar hooks with repeated notes and 16th pickups: (step, length, degree
# move). A move of None repeats the note; "b" is a blue-note grace into it.
_HOOKS = (
    ((0, 1, 0), (1, 1, None), (2, 2, 1), (4, 2, 1), (7, 1, -1), (8, 3, "b"), (12, 2, -1),
     (14, 2, -1), (18, 2, 2), (20, 4, 1), (26, 2, -1), (28, 4, -2)),
    ((2, 1, 0), (3, 1, None), (4, 2, 2), (6, 1, -1), (7, 3, 1), (10, 2, "b"), (12, 4, -1),
     (18, 1, 1), (19, 1, None), (20, 2, 1), (22, 2, -2), (24, 6, -1)),
    ((0, 2, 0), (3, 1, 1), (4, 1, None), (6, 2, 1), (8, 1, -1), (9, 1, None), (10, 4, "b"),
     (16, 2, 2), (18, 2, -1), (20, 2, -1), (22, 2, 1), (24, 8, -2)),
)


def _sax(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    riff = riff_bars(ctx, feel)
    notes: list[NoteEvent] = []
    # The sax doubles the riff an octave above the trombone, with the trumpet.
    for bar, step, length, semis in riff_notes(ctx, riff, feel):
        p = _fits(harm.tonic + semis + 60, 62, 77)
        s, v = _human(rng, clock.t(bar, step), 104, ms=3.0, vel_jitter=4.0)
        notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.85, velocity=v))
    if feel in ("bridge", "breakdown", "intro", "outro"):
        _emit(midi, ctx, notes, name="Melody", program=65)
        return
    lo, hi = (65, 79) if feel in HIGH_ROLES else (62, 76)
    pool = _scale_pitches(harm.tonic, ctx.scale, lo, hi)
    hook = _HOOKS[int(_shared_rng(ctx).integers(0, len(_HOOKS)))]
    riff_set = set(riff)
    centre = 71 if feel in HIGH_ROLES else 67
    idx = min(range(len(pool)), key=lambda i: abs(pool[i] - centre))
    for n_phrase, p_bar in enumerate(range(0, bars, 2)):
        if p_bar in riff_set or n_phrase % 2 == 1 or (feel == "verse" and n_phrase > 0):
            continue                               # one phrase in, one out; a verse gets one
        start_idx = idx + (2 if n_phrase % 2 else 0)
        i_cur = int(np.clip(start_idx, 0, len(pool) - 1))
        for step, length, move in hook:
            bar = p_bar + step // clock.steps
            if bar >= bars or bar in riff_set:
                break
            grace = move == "b"
            if move not in (None, "b"):
                i_cur = int(np.clip(i_cur + move, 0, len(pool) - 1))
            pitch = pool[i_cur]
            pos = bar + (step % clock.steps) / clock.steps
            if length >= 3:
                root_pc, quality = harm.at(pos)
                tones = {root_pc % 12} | {(root_pc + iv) % 12 for iv in _VOICINGS.get(quality, _VOICINGS["7"])}
                pitch = min((p for p in pool if p % 12 in tones), key=lambda p: abs(p - pitch), default=pitch)
                i_cur = pool.index(pitch) if pitch in pool else i_cur
            start = clock.t(p_bar, step)
            vel = 96 + (8 if feel in HIGH_ROLES else 0) - (6 if length == 1 else 0)
            if grace:
                g, gv = _human(rng, start - clock.step_len * 0.35, vel - 14, ms=1.5, vel_jitter=3.0)
                notes.append(NoteEvent(pitch=pitch - 1, start=g, end=start, velocity=gv))
            s, v = _human(rng, start, vel, ms=4.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=pitch, start=s, end=start + clock.step_len * length * 0.92, velocity=v))
    _emit(midi, ctx, notes, name="Melody", program=65)


for _feel in ALL_ROLES:
    _register(name=f"funk_fusion_kit_{_feel}", label=f"Funk-fusion kit ({_feel})",
              description="Driving 16th hats (open offbeats in the chorus), punchy kick and "
                          "backbeat with ghosts, fills every four bars, kicks on the band riff.",
              instruments=("drums",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _drums(midi, ctx, _f))
    _register(name=f"funk_fusion_slap_{_feel}", label=f"Slap bass ({_feel})",
              description="Thumb roots, popped octaves, dead notes and blue-note hammer-ons; "
                          "plays the band riff an octave down.",
              instruments=("bass",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _bass(midi, ctx, _f))
    _register(name=f"funk_fusion_horns_{_feel}", label=f"Horn stabs ({_feel})",
              description="Trumpet-and-trombone stabs on close voicings that push the next "
                          "chord, and the band riff in octaves.",
              instruments=("brass_section", "trumpet", "trombone"), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _horns(midi, ctx, _f))
    _register(name=f"funk_fusion_rhodes_{_feel}", label=f"Rhodes chops ({_feel})",
              description="Short percussive Rhodes chords on the offbeats, accents with the riff.",
              instruments=("chords",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _rhodes(midi, ctx, _f))
    _register(name=f"funk_fusion_sax_{_feel}", label=f"Sax hook ({_feel})",
              description="Hooky alto-sax lead with repeated notes, 16th pickups and blue-note "
                          "graces; doubles the band riff.",
              instruments=("melody",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _sax(midi, ctx, _f))
