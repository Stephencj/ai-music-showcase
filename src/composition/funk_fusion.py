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
    chord_tones, fit_to_chord,
    ALL_ROLES, CLOSED_HAT, CRASH, KICK, OPEN_HAT, PEDAL_HAT, RIDE, SNARE, STICK,
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
            # The ending riff stops after beat 3 and the drums pick up into the
            # final hit, which is the resolution (no early landing on the tonic).
            if feel == "outro" and bar == bars[-1] and step + length > 12:
                continue
            out.append((bar, step, length, semis))
    return out


def _arrangement(ctx: TechniqueContext) -> set[str]:
    """Arrangement variants, comma separated (e.g. "hits_only,calm")."""
    return {a.strip() for a in (getattr(ctx, "arrangement", "") or "").replace("+", ",").split(",") if a.strip()}


def _hits_only(ctx: TechniqueContext) -> bool:
    return "hits_only" in _arrangement(ctx)


def _calm(ctx: TechniqueContext, part: str) -> bool:
    """"calm" makes the band plainer for background use; "calm_drums",
    "calm_bass" and "calm_keys" do it per part. Drums: straight 8th hats and a
    backbeat without ghosts or open hats; bass: legato finger bass on roots
    and fifths; keys: sustained Rhodes chords."""
    arr = _arrangement(ctx)
    return "calm" in arr or f"calm_{part}" in arr


def _calm_drums(midi, ctx: TechniqueContext, feel: str) -> None:
    rng, clock, bars = ctx.rng, _Clock(ctx), ctx.bar_count
    hits: list[tuple[int, float, int, float]] = []
    for bar in range(bars):
        last = bar == bars - 1
        if feel == "outro" and last:
            hits += [(bar, 0, KICK, 112), (bar, 0, CRASH, 104)]
            continue
        if feel == "intro" and bar < bars - 1:
            for step in range(0, 16, 2):
                hits.append((bar, step, CLOSED_HAT, 58 if step % 4 else 68))
            continue
        fill = last and feel != "outro"
        for step in range(0, 12 if fill else 16, 2):
            hits.append((bar, step, CLOSED_HAT, 70 if step % 4 == 0 else 52))
        hits += [(bar, 4, SNARE, 94), (bar, 12, SNARE, 96)]
        hits += [(bar, 0, KICK, 98), (bar, 8, KICK, 90)] + ([(bar, 10, KICK, 80)] if bar % 2 else [])
        if bar == 0 and feel in HIGH_ROLES:
            hits.append((bar, 0, CRASH, 84))
        if fill:
            hits += [(bar, 12, SNARE, 84), (bar, 14, TOM_MID, 86), (bar, 15, TOM_LO, 90)]
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            hits += [(bar, st, KICK, 116), (bar, st, SNARE, 104), (bar, st, CRASH, 104)]
    notes = []
    for bar, step, key, vel in hits:
        t, v = _human(rng, clock.t(bar, step), vel, ms=3.0, vel_jitter=3.0)
        dur = clock.step_len * (8 if key == CRASH else 1)
        notes.append(NoteEvent(pitch=key, start=t, end=t + dur, velocity=v))
    _emit(midi, ctx, notes, name="Drums", program=0, is_drum=True)


def _calm_bass(midi, ctx: TechniqueContext, feel: str) -> None:
    rng, clock, harm, bars = ctx.rng, _Clock(ctx), _Harmony(ctx), ctx.bar_count
    notes: list[NoteEvent] = []
    for bar in range(bars):
        if feel == "intro" and bar < bars - 1:
            continue
        if feel == "outro" and bar == bars - 1:
            p = _fits(harm.tonic + 36, _LO, _LO + 11)
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + clock.bar_len, velocity=96))
            continue
        # Root on 1, held; fifth on beat 4 leading on. Legato: each note runs into the next.
        for step, length, fifth, vel in ((0, 12, False, 94), (12, 4, True, 82)):
            root_pc, quality = harm.at(bar + step / clock.steps)
            root = _fits(root_pc + 36, _LO, _LO + 11)
            pitch = root + (6 if quality == "dim" else 7) if fifth else root
            s, v = _human(rng, clock.t(bar, step), vel, ms=4.0, vel_jitter=3.0)
            notes.append(NoteEvent(pitch=pitch, start=s, end=clock.t(bar, step + length) - 0.01, velocity=v))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            root_pc, _ = harm.at(bar + st / clock.steps)
            t0 = clock.t(bar, st)
            notes = [n for n in notes if not (t0 - 0.02 <= n.start < t0 + clock.step_len * 2)]
            notes.append(NoteEvent(pitch=_fits(root_pc + 36, _LO, _LO + 11), start=t0, end=t0 + clock.step_len * 3, velocity=112))
    _emit(midi, ctx, notes, name="Bass", program=33)


def _kick_steps(feel: str, bar: int, bars: int) -> tuple[int, ...]:
    """The steps the kit's kick plays in this bar (mirrors _drums)."""
    if feel in ("bridge", "breakdown"):
        return _TOM_KICKS if bar < bars // 2 else _KICKS["bridge"][bar % 2]
    return _KICKS["high" if feel in HIGH_ROLES else "verse"][bar % 2]


def _pocket_bass(midi, ctx: TechniqueContext, feel: str) -> None:
    """"pocket_bass": a finger bass locked to the kick — a note on every kick
    (root held on the downbeat, then octave and fifth), a dead note answering
    the snare now and then, a walk-up into each new chord."""
    rng, clock, harm, bars = ctx.rng, _Clock(ctx), _Harmony(ctx), ctx.bar_count
    notes: list[NoteEvent] = []
    for bar in range(bars):
        if feel == "intro" and bar < bars - 1:
            continue
        if feel == "outro" and bar == bars - 1:
            p = _fits(harm.tonic + 36, _LO, _LO + 11)
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + clock.bar_len, velocity=100))
            continue
        kicks = sorted(_kick_steps(feel, bar, bars))
        nxt_pc, _ = harm.at(min(bar + 1.0, bars - 1e-6))
        changes = bar + 1 < bars and harm.at(bar + 0.99)[0] != nxt_pc
        for i, step in enumerate(kicks):
            if changes and step >= 14:
                continue                                       # leave room for the walk-up
            root_pc, quality = harm.at(bar + step / clock.steps)
            root = _fits(root_pc + 36, _LO, _LO + 11)
            pitch = root if i == 0 else (root + 12, root + 7, root)[i % 3]
            end_step = kicks[i + 1] if i + 1 < len(kicks) else 16
            length = max(1, end_step - step)
            s, v = _human(rng, clock.t(bar, step), 104 if i == 0 else 92, ms=3.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=pitch, start=s, end=s + clock.step_len * min(length, 6) * 0.88, velocity=v))
        if bar % 2 == 1:                                        # a dead note answering the backbeat
            root_pc, _ = harm.at(bar + 13 / 16)
            s, v = _human(rng, clock.t(bar, 13), 46, ms=2.0, vel_jitter=3.0)
            notes.append(NoteEvent(pitch=_fits(root_pc + 36, _LO, _LO + 11), start=s, end=s + clock.step_len * 0.3, velocity=v))
        if changes:                                             # walk up a whole and half step into the change
            target = _fits(nxt_pc + 36, _LO, _LO + 11)
            for k, (step, semis) in enumerate(((14, -2), (15, -1))):
                s, v = _human(rng, clock.t(bar, step), 86 + 4 * k, ms=2.5, vel_jitter=3.0)
                notes.append(NoteEvent(pitch=target + semis, start=s, end=s + clock.step_len * 0.85, velocity=v))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            root_pc, _ = harm.at(bar + st / clock.steps)
            t0 = clock.t(bar, st)
            notes = [n for n in notes if not (t0 - 0.02 <= n.start < t0 + clock.step_len * 2)]
            notes.append(NoteEvent(pitch=_fits(root_pc + 36, _LO, _LO + 11), start=t0, end=t0 + clock.step_len * 3, velocity=112))
    _emit(midi, ctx, notes, name="Bass", program=33)


def _calm_rhodes(midi, ctx: TechniqueContext, feel: str) -> None:
    rng, clock, harm, bars = ctx.rng, _Clock(ctx), _Harmony(ctx), ctx.bar_count
    notes: list[NoteEvent] = []
    previous: Optional[list[int]] = None
    for ev in harm.events:                                  # one sustained chord per change
        root_pc, quality = harm.at(ev.start_bar)
        if feel == "outro" and ev is harm.events[-1]:
            quality = "maj"
        voicing = _voice(root_pc, quality, previous)
        previous = voicing
        start = clock.t(0, ev.start_bar * clock.steps)
        end = clock.t(0, ev.end_bar * clock.steps) - 0.02
        for i, p in enumerate(voicing):
            s, v = _human(rng, start + i * 0.012, 70, ms=4.0, vel_jitter=3.0)
            notes.append(NoteEvent(pitch=p, start=s, end=end, velocity=v))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            root_pc, quality = harm.at(bar + st / clock.steps)
            for p in _voice(root_pc, quality, previous):
                notes.append(NoteEvent(pitch=p, start=clock.t(bar, st), end=clock.t(bar, st) + clock.step_len * 3, velocity=90))
    _emit(midi, ctx, notes, name="Chords", program=4)


def riff_bars(ctx: TechniqueContext, feel: str) -> tuple[int, ...]:
    """Where the band plays the riff in a section of this role."""
    if _hits_only(ctx):
        return ()
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

# Bridge/breakdown opening: toms carry the groove (low/mid/high around the
# kick, a cross-stick on 4), instead of a sparse half-time beat.
_TOM_GROOVE = (
    (0, TOM_LO, 104), (3, TOM_LO, 84), (5, TOM_MID, 90), (7, TOM_MID, 78),
    (8, TOM_LO, 98), (10, TOM_HI, 86), (11, TOM_MID, 80), (12, STICK, 92),
    (14, TOM_LO, 92),
)
_TOM_KICKS = (0, 6, 10)

_KICKS = {
    "verse":  ((0, 6, 10), (0, 3, 8, 10, 14)),
    "high":   ((0, 4, 6, 10, 12), (0, 3, 6, 8, 11, 14)),
    "bridge": ((0, 10), (0, 6, 7)),
}


def _drums(midi, ctx: TechniqueContext, feel: str) -> None:
    if _calm(ctx, "drums"):
        return _calm_drums(midi, ctx, feel)
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
            hits += [(bar, 0, KICK, 124), (bar, 0, CRASH, 122), (bar, 0, SNARE, 114),
                     (bar, 0, TOM_LO, 108)]
            continue
        if feel == "outro" and bar == bars - 2 and bar in riff_steps:
            for i, step in enumerate(range(12, 16)):   # snare pickup into the final hit
                hits.append((bar, step, SNARE, 84 + 9 * i))
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
            if bar < half:   # bass-and-drums: a rolling tom groove
                for step, key, vel in _TOM_GROOVE:
                    hits.append((bar, step, key, vel))
                for step in range(0, clock.steps, 4):
                    hits.append((bar, step + 2, CLOSED_HAT, 52))   # quiet offbeat hat keeps time
                if bar % 2 == 1 and bar < half - 1:
                    for i, (step, key) in enumerate(((12, TOM_HI), (13, TOM_HI), (14, TOM_MID), (15, TOM_LO))):
                        hits.append((bar, step, key, 88 + 6 * i))
            else:            # build: snare 8ths then 16ths, rising
                rate = 2 if bar < bars - 1 else 1
                for i, step in enumerate(range(0, clock.steps, rate)):
                    v = 60 + 40 * (bar - half + i / clock.steps * rate) / max(1, bars - half)
                    hits.append((bar, step, SNARE, v))
                hits.append((bar, 0, CRASH, 90))
            for step in (_TOM_KICKS if bar < half else kicks[bar % 2]):
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

    # Hit points: clear the kit around each one, then everything lands on it.
    points = hit_steps(ctx, clock)
    if points and _groove(ctx):
        # In the groove: a kick under the stab, a crash only on a bar's first
        # beat (hits-only: the whole kit lands every hit).
        for bar, steps_ in points.items():
            for st in steps_:
                hits.append((bar, st, KICK, 118 if _hits_only(ctx) else 112))
                if _hits_only(ctx):
                    hits += [(bar, st, SNARE, 108), (bar, st, CRASH, 110)]
                elif st == 0:
                    hits.append((bar, st, CRASH, 104))
    elif points:
        hits = [h for h in hits if not _near_hit(points, h[0], int(h[1]), clock.steps, clear=1)]
        for bar, steps_ in points.items():
            for st in steps_:
                hits += [(bar, st, CRASH, 122), (bar, st, KICK, 124), (bar, st, SNARE, 112),
                         (bar, st, TOM_LO, 100)]

    notes = []
    for bar, step, key, vel in hits:
        t, v = _human(rng, clock.t(bar, step), vel, ms=2.5, vel_jitter=4.0 if vel > 50 else 3.0)
        dur = clock.step_len * (8 if key in (CRASH, RIDE, OPEN_HAT) else 1)
        notes.append(NoteEvent(pitch=key, start=t, end=t + dur, velocity=v))
    _emit(midi, ctx, _breathe(notes, ctx, clock), name="Drums", program=0, is_drum=True)


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
    if "pocket_bass" in _arrangement(ctx):
        return _pocket_bass(midi, ctx, feel)
    if _calm(ctx, "bass"):
        return _calm_bass(midi, ctx, feel)
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
    # The bass keeps grooving through groove-style hits (it lands them in hits-only).
    points = {} if (_groove(ctx) and not _hits_only(ctx)) else hit_steps(ctx, clock)
    if points:
        step_len = clock.step_len
        def near(n):
            return any(-1.5 * step_len <= n.start - clock.t(b, s) <= 2.5 * step_len
                       for b, ss in points.items() for s in ss)
        notes = [n for n in notes if not near(n)]
        for bar, steps_ in points.items():
            for st in steps_:
                root_pc, _ = harm.at(bar + st / clock.steps)
                p = _fits(root_pc + 36, _LO, _LO + 11)
                t0 = clock.t(bar, st)
                notes.append(NoteEvent(pitch=p, start=t0, end=t0 + step_len * 3, velocity=124))
    _emit(midi, ctx, _breathe(notes, ctx, clock), name="Bass", program=36)


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


def _groove(ctx: TechniqueContext) -> bool:
    return getattr(ctx, "hit_style", "punch") == "groove"


def hit_steps(ctx: TechniqueContext, clock: "_Clock") -> dict[int, set[int]]:
    """This section's hit points as bar → 16th steps: the nearest 16th, or in
    "groove" style the next beat (up to a beat late, so it sits in the time)."""
    out: dict[int, set[int]] = {}
    first = ctx.start_bar * clock.steps
    # Next beat; at slow tempos (beats over 0.45 s) the next 8th, so a
    # groove hit is never more than about a third of a second late.
    grid = 4 if 4 * clock.step_len <= 0.45 else 2
    for t in ctx.hits:
        if _groove(ctx):
            step = int(np.ceil((t - 0.03) / (grid * clock.step_len))) * grid - first
        else:
            step = int(round(t / clock.step_len)) - first
        if 0 <= step < ctx.bar_count * clock.steps:
            out.setdefault(step // clock.steps, set()).add(step % clock.steps)
    return out


BREATH = 2           # 16ths of silence before a hit that lands on a downbeat


def _breathe(notes: list[NoteEvent], ctx: TechniqueContext, clock: "_Clock") -> list[NoteEvent]:
    """Leave an 8th of air before each downbeat hit point (band, breath, hit),
    which makes the hit land far bigger than more volume would. "groove"
    hits don't stop the band."""
    if _groove(ctx):
        return notes
    gaps = []
    for t in ctx.hits:
        step = int(round(t / clock.step_len))
        if step % clock.steps == 0:
            h = step * clock.step_len
            gaps.append((h - BREATH * clock.step_len, h))
    if not gaps:
        return notes
    out = []
    for n in notes:
        keep = True
        for g0, h in gaps:
            if g0 - 0.004 <= n.start < h - 0.012:
                keep = False
                break
            if n.start < g0 < n.end:
                if g0 - n.start < 0.03:          # too short to keep: drop it
                    keep = False
                    break
                n = NoteEvent(pitch=n.pitch, start=n.start, end=g0, velocity=n.velocity)
        if keep:
            out.append(n)
    return out


def _near_hit(hits: dict[int, set[int]], bar: int, step: int, steps: int, clear: int = HIT_CLEAR) -> bool:
    at = bar * steps + step
    return any(abs(at - (b * steps + s)) <= clear for b, ss in hits.items() for s in ss)


def _horn_voicing(root_pc: int, quality: str, top_near: int) -> list[int]:
    """Spread "shout" voicing: trombone on the low root and the 7th (the
    guide tone), trumpet on the 3rd and the 9th up top near ``top_near``."""
    third = 5 if quality == "sus4" else 3 if quality in ("min7", "min", "dim") else 4
    seventh = 9 if quality == "maj" else _SEVENTH.get(quality, 10)
    root = _fits(root_pc + 48, 46, 57)
    guide = root + seventh
    top = min((p for p in range(top_near - 6, top_near + 7) if p % 12 == (root_pc + 14) % 12),
              key=lambda p: abs(p - top_near))
    mid = max(p for p in range(top - 12, top - 2) if p % 12 == (root_pc + third) % 12)
    return sorted({root, guide, mid, top})


def _close_voicing(root_pc: int, quality: str, top_near: int) -> list[int]:
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


def unison_pitch(root_pc: int, quality: str, lo: int = 70, hi: int = 79) -> int:
    """A 70s-section unison note: the chord's root or fifth, up top."""
    fifth = (root_pc + (6 if quality == "dim" else 7)) % 12
    cands = [p for p in range(lo, hi + 1) if p % 12 in (root_pc % 12, fifth)]
    return min(cands, key=lambda p: abs(p - 75))


def _seventies_hits(ctx, clock, harm, feel, part, rng) -> list[NoteEvent]:
    """Tight unison-octave punches on the hit points (trumpet up top, trombone
    an octave under), and a final hit that holds then falls off."""
    out: list[NoteEvent] = []
    octaves = {"trumpet": (0,), "trombone": (-12,)}.get(part, (0, -12))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            root_pc, quality = harm.at(bar + st / clock.steps)
            top = unison_pitch(root_pc, quality)
            s, v = _human(rng, clock.t(bar, st), 122, ms=1.0, vel_jitter=1.0)
            for o in octaves:
                out.append(NoteEvent(pitch=top + o, start=s, end=s + clock.step_len * 2 * 0.85, velocity=v))
    if feel == "outro":
        t0 = clock.t(ctx.bar_count - 1, 0)
        top = unison_pitch(harm.tonic, "maj", 72, 79)
        hold = 0.55
        for o in octaves:
            out.append(NoteEvent(pitch=top + o, start=t0, end=t0 + hold, velocity=124))
        if part in ("trumpet", "section"):           # the classic fall-off
            out += _gliss(ctx, harm, t0 + hold, t0 + hold + 0.28, top, top - 9, 96, 54)
    return out


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
    if _hits_only(ctx):
        notes += _seventies_hits(ctx, clock, harm, feel, part, rng)
        _emit(midi, ctx, notes, name={"trumpet": "Trumpet", "trombone": "Trombone"}.get(part, "Horns"),
              program={"trumpet": 56, "trombone": 57}.get(part, 61))
        return
    pattern = _STABS["high" if feel in HIGH_ROLES else "bridge" if feel in ("bridge", "breakdown") else "verse"]
    top_near = 74 if feel in HIGH_ROLES else 70
    hits = hit_steps(ctx, clock)
    for bar, steps_ in hits.items():
        for st in steps_:
            root_pc, quality = harm.at(bar + st / clock.steps)
            s, v = _human(rng, clock.t(bar, st), 116 if _groove(ctx) else 126, ms=1.0, vel_jitter=1.0)
            voicing = _part(_horn_voicing(root_pc, quality, 77), part)
            if part != "trumpet" and voicing[0] - 12 >= 40 and not _groove(ctx):
                voicing = [voicing[0] - 12] + voicing          # weight under the hit
            for p in voicing:
                notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * 3 * 0.9, velocity=v))
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
        voicing = _part(_horn_voicing(harm.tonic, "maj", 77), part)
        if part != "trumpet" and voicing[0] - 12 >= 40:
            voicing = [voicing[0] - 12] + voicing
        for p in voicing:
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + 0.9, velocity=124))
    _emit(midi, ctx, _breathe(notes, ctx, clock), name={"trumpet": "Trumpet", "trombone": "Trombone"}.get(part, "Horns"),
          program={"trumpet": 56, "trombone": 57}.get(part, 61))


# ---------------------------------------------------------------------------
# RHODES CHOPS
# ---------------------------------------------------------------------------

_CHOPS = {
    "verse": ((2, 1, 78), (6, 1, 74), (7, 1, 66), (10, 1, 78), (14, 1, 76), (15, 1, 66)),
    "high": ((0, 1, 86), (2, 1, 78), (3, 1, 70), (6, 1, 82), (8, 1, 84), (10, 1, 78), (11, 1, 70), (14, 2, 84)),
}


def _rhodes(midi, ctx: TechniqueContext, feel: str) -> None:
    if _calm(ctx, "keys"):
        return _calm_rhodes(midi, ctx, feel)
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

    def chord(bar, step, length, vel, pos, quality_override=None):
        nonlocal previous
        root_pc, quality = harm.at(pos)
        voicing = _voice(root_pc, quality_override or quality, previous)
        previous = voicing
        start = clock.t(bar, step)
        for p in voicing:
            s, v = _human(rng, start, vel, ms=3.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.75, velocity=v))

    for bar in range(bars):
        if feel == "outro" and bar == bars - 1:
            # End on a clean 6/9 tonic: no major 7th rubbing the melody's final note.
            chord(bar, 0, clock.steps, 96, float(bar), quality_override="maj")
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
    _emit(midi, ctx, _breathe(notes, ctx, clock), name="Chords", program=4)


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


# Lead registers: (riff doubling), (hook in low sections), (hook in high
# sections), hook centres, and the final note. A synth lead sits about an
# octave up, above the trumpet (C5-C6, peaking near G6), where fusion synth
# leads live; a sax stays in its sweet spot.
_LEAD_REGISTER = {
    "synth":  {"riff": (72, 86), "low": (72, 86), "high": (76, 91), "centre_low": 76, "centre_high": 81, "final": (79, 91)},
    "sax":    {"riff": (62, 77), "low": (62, 76), "high": (65, 79), "centre_low": 67, "centre_high": 71, "final": (67, 80)},
    # Trumpet's singing range (the horn-section and trumpet voices).
    "horn":   {"riff": (62, 77), "low": (62, 77), "high": (65, 81), "centre_low": 68, "centre_high": 73, "final": (67, 82)},
    "guitar": {"riff": (60, 76), "low": (60, 76), "high": (64, 81), "centre_low": 67, "centre_high": 72, "final": (64, 79)},
    # An octave up, up to the guitar's top D (D6).
    "guitar_high": {"riff": (72, 86), "low": (72, 86), "high": (74, 86), "centre_low": 79, "centre_high": 81, "final": (74, 86)},
}


def _voice_register(name: str | None) -> str:
    """The register a lead voice declares (one source of truth: the voice)."""
    from src.audio_processing.render.lead_voices import voice
    reg = voice(name).register
    return reg if reg in _LEAD_REGISTER else "synth"
RUN_INTO = ("verse", "prechorus", "bridge", "breakdown")
# The transition run: 8ths speeding into 16ths, ending two 16ths before the
# next section (the breath before its hit). (step, length in 16ths)
_RUN = ((4, 2), (6, 2), (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 1))


def _lead_run(ctx: TechniqueContext, clock: "_Clock", harm: "_Harmony", bar: int,
              reg: dict, rng: np.random.Generator, synth: bool) -> list[NoteEvent]:
    """A rising scale run in ``bar`` that throws the lead into the next section."""
    pool = _scale_pitches(harm.tonic, ctx.scale, reg["low"][0] - 7, reg["high"][1])
    home = {harm.tonic % 12, (harm.tonic + 4) % 12, (harm.tonic + 7) % 12}
    target = min((p for p in pool if p % 12 in home), key=lambda p: abs(p - reg["centre_high"]))
    top = pool.index(target)
    first = max(0, top - (len(_RUN) - 1))
    notes = []
    for i, (step, length) in enumerate(_RUN):
        root_pc, quality = harm.at(bar + step / clock.steps)
        pitch = fit_to_chord(pool[min(first + i, top)], root_pc, quality, pool)
        if notes and pitch <= notes[-1].pitch:          # keep the run rising
            higher = [p for p in pool if p > notes[-1].pitch
                      and fit_to_chord(p, root_pc, quality, pool) == p]
            pitch = higher[0] if higher else notes[-1].pitch + 1
        start = clock.t(bar, step)
        s, v = _human(rng, start, 88 + 24 * i / (len(_RUN) - 1), ms=2.5, vel_jitter=3.0)
        gate = clock.step_len * length * (0.85 if synth else 0.92)
        notes.append(NoteEvent(pitch=pitch, start=s, end=start + gate, velocity=v))
    return notes


GLISS_NOTE = 0.03          # seconds per note in a glissando (a hand swipe on the keys)


def _gliss(ctx: TechniqueContext, harm: "_Harmony", start: float, end: float,
           from_pitch: int, to_pitch: int, vel_from: float, vel_to: float) -> list[NoteEvent]:
    """A keyboard glissando: every scale note between two pitches, swiped
    fast from ``start`` to ``end`` (separate notes, each re-attacked)."""
    lo, hi = sorted((from_pitch, to_pitch))
    pool = _scale_pitches(harm.tonic, ctx.scale, lo, hi)
    if from_pitch > to_pitch:
        pool = pool[::-1]
    span = max(end - start, 0.05)
    every = max(1, int(np.ceil(len(pool) * GLISS_NOTE / span)))   # skip notes if it's short
    pool = pool[::every]
    gap = span / max(1, len(pool))
    notes = []
    for i, p in enumerate(pool):
        t = start + i * gap
        v = vel_from + (vel_to - vel_from) * i / max(1, len(pool) - 1)
        notes.append(NoteEvent(pitch=p, start=t, end=t + max(0.012, gap - 0.011), velocity=int(round(v))))
    return notes


def _flares(ctx: TechniqueContext, clock: "_Clock", harm: "_Harmony", feel: str,
            reg: dict) -> list[tuple[list[NoteEvent], bool]]:
    """Lead glissandos as (notes, is_rip_down): a rip down off a section's
    opening hit, a swipe up into a downbeat hit mid-section, and a swipe up
    into the final hit."""
    out: list[tuple[list[NoteEvent], bool]] = []
    home = {harm.tonic % 12, (harm.tonic + 7) % 12}
    top = min((p for p in _scale_pitches(harm.tonic, ctx.scale, *reg["high"]) if p % 12 in home),
              key=lambda p: abs(p - (reg["centre_high"] + 3)))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            if st:
                continue
            if bar == 0 and feel in HIGH_ROLES:
                out.append((_gliss(ctx, harm, clock.t(0, 2), clock.t(0, 6), top + 2, top - 17, 112, 80), True))
            elif bar > 0:
                out.append((_gliss(ctx, harm, clock.t(bar, 0) - 4 * clock.step_len, clock.t(bar, 0) - 0.012,
                                   top - 15, top, 84, 114), False))
    if feel == "outro" and ctx.bar_count >= 2:
        final = clock.t(ctx.bar_count - 1, 0)
        landing = _fits(harm.tonic + 72, *reg["final"])
        out.append((_gliss(ctx, harm, final - 4 * clock.step_len, final - 0.012, landing - 17, landing - 1, 86, 116), False))
    return out


def _sax(midi, ctx: TechniqueContext, feel: str) -> None:
    """The lead: alto sax or synth lead (a synth sits about an octave higher).
    Before a chorus it plays a rising run that carries into the section."""
    program_in = getattr(ctx.instrument_obj, "program", 65)
    guitar_lead = ctx.instrument == "lead_guitar" or program_in in (29, 30)
    # "synth" = rendered as a lead voice (synth and/or sampled layers).
    synth = guitar_lead or ctx.instrument == "synth_lead" or program_in in range(80, 88)
    name, program = ("Lead", 81) if synth else ("Melody", 65)
    rng = ctx.rng
    if _hits_only(ctx):
        # No melody, runs or flares: the lead joins the horns' unison hits.
        clock, harm = _Clock(ctx), _Harmony(ctx)
        _emit(midi, ctx, _seventies_hits(ctx, clock, harm, feel, "trumpet", rng), name=name, program=program)
        return
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    riff = riff_bars(ctx, feel)
    notes: list[NoteEvent] = []
    if guitar_lead:
        reg_name = _voice_register("guitar_stack")
    elif synth:
        reg_name = _voice_register(ctx.lead_voice)
    else:
        reg_name = "sax"
    reg = _LEAD_REGISTER[reg_name]
    synth_gate = synth and reg_name == "synth"     # real-instrument voices phrase longer
    # The lead doubles the riff: a sax with the trumpet, a synth an octave above it.
    for bar, step, length, semis in riff_notes(ctx, riff, feel):
        p = _fits(harm.tonic + semis + 60, *reg["riff"])
        s, v = _human(rng, clock.t(bar, step), 104, ms=3.0, vel_jitter=4.0)
        gate = clock.step_len * (min(length, 4) * 0.82 if synth_gate else length * 0.85)
        notes.append(NoteEvent(pitch=p, start=s, end=s + gate, velocity=v))
    if feel == "outro":
        # Resolve on the final hit: the tonic, held, up in the lead's register.
        t0 = clock.t(bars - 1, 0)
        notes.append(NoteEvent(pitch=_fits(harm.tonic + 72, *reg["final"]), start=t0, end=t0 + clock.bar_len * 0.9, velocity=112))
    run_bar = bars - 1 if feel in RUN_INTO and bars >= 2 and (bars - 1) not in riff else None
    if run_bar is not None:
        notes += _lead_run(ctx, clock, harm, run_bar, reg, rng, synth_gate)
    def finish(notes: list[NoteEvent]) -> None:
        # Flares replace whatever the lead was playing under them and run
        # straight through the breath into their hit.
        groups = _flares(ctx, clock, harm, feel, reg)
        flares = [n for group, _ in groups for n in group]
        windows = []
        for group, rip in groups:
            if group:
                # After a rip down, an 8th of room so the line re-enters cleanly;
                # a swipe up lands on its hit, so nothing after it is touched.
                tail = 2 * clock.step_len if rip else 0.0
                windows.append((group[0].start, group[-1].end + tail))
        notes = [n for n in notes if not any(a - 0.01 <= n.start <= b for a, b in windows)]
        _emit(midi, ctx, _breathe(notes, ctx, clock) + flares, name=name, program=program)

    if feel in ("bridge", "breakdown", "intro", "outro"):
        finish(notes)
        return
    lo, hi = reg["high"] if feel in HIGH_ROLES else reg["low"]
    pool = _scale_pitches(harm.tonic, ctx.scale, lo, hi)
    hook = _HOOKS[int(_shared_rng(ctx).integers(0, len(_HOOKS)))]
    riff_set = set(riff)
    centre = reg["centre_high"] if feel in HIGH_ROLES else reg["centre_low"]
    idx = min(range(len(pool)), key=lambda i: abs(pool[i] - centre))
    for n_phrase, p_bar in enumerate(range(0, bars, 2)):
        if p_bar in riff_set or n_phrase % 2 == 1 or (feel == "verse" and n_phrase > 0):
            continue                               # one phrase in, one out; a verse gets one
        start_idx = idx + (2 if n_phrase % 2 else 0)
        i_cur = int(np.clip(start_idx, 0, len(pool) - 1))
        for step, length, move in hook:
            bar = p_bar + step // clock.steps
            if bar >= bars or bar in riff_set or bar == run_bar:
                break
            grace = move == "b"
            if move not in (None, "b"):
                i_cur = int(np.clip(i_cur + move, 0, len(pool) - 1))
            pitch = pool[i_cur]
            pos = bar + (step % clock.steps) / clock.steps
            root_pc, quality = harm.at(pos)
            if length >= 3:
                tones = chord_tones(root_pc, quality)
                pitch = min((p for p in pool if p % 12 in tones), key=lambda p: abs(p - pitch), default=pitch)
            else:
                pitch = fit_to_chord(pitch, root_pc, quality, pool,
                                     prefer_up=not (isinstance(move, int) and move < 0))
            i_cur = pool.index(pitch) if pitch in pool else i_cur
            start = clock.t(p_bar, step)
            vel = 96 + (8 if feel in HIGH_ROLES else 0) - (6 if length == 1 else 0)
            if grace:
                g, gv = _human(rng, start - clock.step_len * 0.35, vel - 14, ms=1.5, vel_jitter=3.0)
                notes.append(NoteEvent(pitch=pitch - 1, start=g, end=start, velocity=gv))
            s, v = _human(rng, start, vel, ms=4.0, vel_jitter=4.0)
            # The synth plays it fairly short and punchy; a sax breathes longer.
            gate = clock.step_len * (min(length, 4) * 0.82 if synth_gate else length * 0.92)
            notes.append(NoteEvent(pitch=pitch, start=s, end=start + gate, velocity=v))
    finish(notes)


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
    _register(name=f"funk_fusion_sax_{_feel}", label=f"Lead hook ({_feel})",
              description="Hooky lead (synth or alto sax) with repeated notes, 16th pickups and "
                          "blue-note graces; doubles the band riff and resolves on the final hit.",
              instruments=("melody",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _sax(midi, ctx, _f))
