"""Laid-back neo-soul / chill R&B techniques (tag ``neo_soul``).

Around 89 BPM on minor-7th vamps (i7–iv7 with major-7 and dominant
turnarounds): a relaxed kit with straight 8th hats, a backbeat that sits a
touch behind, ghost notes and a short band stop at the end of each 4-bar
phrase; a round bass on roots, fifths and approach notes; lush Rhodes on 9th
voicings leading the band; and a clean guitar answering in short, singing
phrases.

Hit points (``ctx.hits``) give soft accents in the groove: a Rhodes chord and a
kick, with a crash on a bar's first beat. Helpers come from
:mod:`src.composition.fusion` and :mod:`src.composition.funk_fusion`.
"""

from __future__ import annotations

import zlib
from typing import Optional

import numpy as np

from src.composition.techniques import TechniqueContext
from src.daw_integration.generic.midi_export import NoteEvent

from .builtins import _register
from .fusion import (
    ALL_ROLES, CLOSED_HAT, CRASH, KICK, OPEN_HAT, SNARE, STICK, TOM_HI, TOM_LO, TOM_MID,
    _SEVENTH, _VOICINGS, _Clock, _Harmony, _emit, _fits, _human, _scale_pitches, _voice,
)
from .funk_fusion import _TOM_GROOVE, hit_steps

TAG = "neo_soul"
HIGH_ROLES = ("chorus", "solo", "drop")
SOFT_ROLES = ("bridge", "breakdown")
LAID_BACK = 0.014          # seconds the backbeat sits behind


def _phrase_stop(ctx: TechniqueContext, bar: int, feel: str) -> bool:
    """The band stops for the last 8th of every 4th bar (not a section's last
    bar, which belongs to the fill), the way the vibe breathes. Explicit
    ``ctx.stops`` replace these."""
    if getattr(ctx, "stops", ()):
        return False
    return feel in ("verse", "chorus", "prechorus") and bar % 4 == 3 and bar != ctx.bar_count - 1


def _stop_window(clock: _Clock, bar: int) -> tuple[float, float]:
    return clock.t(bar, 14), clock.t(bar + 1, 0)


def _apply_stops(notes: list[NoteEvent], ctx: TechniqueContext, clock: _Clock, feel: str) -> list[NoteEvent]:
    if getattr(ctx, "stops", ()):
        windows = [(float(a), float(b)) for a, b in ctx.stops]   # explicit band stops (song seconds)
    else:
        windows = [_stop_window(clock, b) for b in range(ctx.bar_count) if _phrase_stop(ctx, b, feel)]
    if not windows:
        return notes
    out = []
    for n in notes:
        if any(a - 0.01 <= n.start < b - 0.01 for a, b in windows):
            continue
        for a, b in windows:
            if n.start < a < n.end:
                n = NoteEvent(pitch=n.pitch, start=n.start, end=max(n.start + 0.03, a), velocity=n.velocity)
        out.append(n)
    return out


# ---------------------------------------------------------------------------
# DRUMS
# ---------------------------------------------------------------------------

_KICK_VERSE = ((0, 7, 10), (0, 6, 10, 15))
_KICK_HIGH = ((0, 3, 7, 10), (0, 6, 8, 10, 15))


def _drums(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    bars = ctx.bar_count
    hits: list[tuple[int, float, int, float, float]] = []      # bar, step, key, vel, extra delay
    high = feel in HIGH_ROLES
    for bar in range(bars):
        last = bar == bars - 1
        if feel == "outro" and last:
            hits += [(bar, 0, KICK, 104, 0), (bar, 0, CRASH, 96, 0)]
            continue
        if feel == "intro" and bar < bars - 1:
            for step in range(0, 16, 2):                        # just hats while the Rhodes sets it up
                hits.append((bar, step, CLOSED_HAT, 54 if step % 4 else 66, 0))
            if bar == bars - 2:
                for i, step in enumerate(range(12, 16)):
                    hits.append((bar, step, SNARE, 50 + 10 * i, 0))
            continue
        if feel in SOFT_ROLES:
            half = bars // 2
            if bar < half:
                for step, key, vel in _TOM_GROOVE:
                    hits.append((bar, step, key, vel - 14, 0))   # softer toms for this feel
                hits.append((bar, 0, KICK, 92, 0))
            else:
                for step in range(0, 16, 2):
                    hits.append((bar, step, CLOSED_HAT, 58, 0))
                hits += [(bar, 4, STICK, 84, LAID_BACK), (bar, 12, STICK, 88, LAID_BACK),
                         (bar, 0, KICK, 96, 0), (bar, 10, KICK, 88, 0)]
            continue
        stop = _phrase_stop(ctx, bar, feel)
        fill = last and feel != "outro"
        end = 12 if fill else (14 if stop else 16)
        for step in range(0, end, 2):                           # straight 8ths
            hits.append((bar, step, CLOSED_HAT, (74 if step % 4 == 0 else 56) + (4 if high else 0), 0))
        if not fill and not stop and rng.random() < 0.35:
            hits.append((bar, 15, CLOSED_HAT, 38, 0))           # a lazy 16th pickup
        if bar % 4 == 1 and not fill:
            hits = [h for h in hits if not (h[0] == bar and h[1] == 14 and h[2] == CLOSED_HAT)]
            hits.append((bar, 14, OPEN_HAT, 60, 0))
        hits += [(bar, 4, SNARE, 98, LAID_BACK), (bar, 12, SNARE, 102, LAID_BACK)]
        for s in (6, 14) if bar % 2 else (7,):
            if s < end:
                hits.append((bar, s, SNARE, float(rng.integers(24, 34)), LAID_BACK))
        kicks = (_KICK_HIGH if high else _KICK_VERSE)[bar % 2]
        for step in kicks:
            if step < end:
                hits.append((bar, step, KICK, 100 if step == 0 else 86, 0))
        if bar == 0 and feel in ("verse", "chorus", "solo"):
            hits.append((bar, 0, CRASH, 88 if high else 78, 0))
        if fill:
            for i, (step, key) in enumerate(((12, SNARE), (13, TOM_HI), (14, TOM_MID), (15, TOM_LO))):
                hits.append((bar, step, key, 74 + 6 * i, 0))
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            hits.append((bar, st, KICK, 104, 0))
            if st == 0:
                hits.append((bar, st, CRASH, 92, 0))
    notes = []
    for bar, step, key, vel, delay in hits:
        t, v = _human(rng, clock.t(bar, step) + delay, vel, ms=4.0, vel_jitter=4.0 if vel > 50 else 3.0)
        dur = clock.step_len * (8 if key in (CRASH, OPEN_HAT) else 1)
        notes.append(NoteEvent(pitch=key, start=t, end=t + dur, velocity=v))
    _emit(midi, ctx, _apply_stops(notes, ctx, clock, feel), name="Drums", program=0, is_drum=True)


# ---------------------------------------------------------------------------
# BASS
# ---------------------------------------------------------------------------

# (step, length in 16ths, degree, velocity): R root, 5 fifth, O octave,
# 7 seventh, A approach to the next chord.
_BASS = {
    # W = a chromatic walk-up into the next chord (three half steps).
    "verse": (((0, 5, "R", 96), (6, 2, "5", 80), (10, 2, "W3", 80), (12, 2, "W2", 82), (14, 2, "W1", 84)),
              ((0, 3, "R", 96), (3, 3, "R", 70), (8, 2, "O", 84), (10, 2, "7", 80), (14, 2, "A", 78))),
    "high": (((0, 3, "R", 100), (3, 1, "R", 74), (6, 2, "5", 86), (8, 2, "O", 88), (10, 3, "R", 90),
              (14, 2, "A", 84)),
             ((0, 2, "R", 100), (2, 2, "5", 80), (4, 2, "O", 84), (7, 3, "R", 88), (10, 2, "7", 84),
              (12, 2, "5", 82), (14, 2, "A", 84))),
    "soft": (((0, 12, "R", 92), (12, 4, "5", 78)),),
}


def _bass(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    bank = _BASS["high" if feel in HIGH_ROLES else "soft" if feel in SOFT_ROLES else "verse"]
    lo = 31
    notes = []
    prev: Optional[int] = None
    for bar in range(bars):
        if feel == "intro" and bar < bars - 1:
            continue                                            # the bass walks in on the intro's last bar
        if feel == "outro" and bar == bars - 1:
            p = _fits(harm.tonic + 36, lo, lo + 11)
            notes.append(NoteEvent(pitch=p, start=clock.t(bar, 0), end=clock.t(bar, 0) + clock.bar_len, velocity=100))
            continue
        for step, length, deg, vel in bank[bar % len(bank)]:
            root_pc, quality = harm.at(bar + step / clock.steps)
            root = _fits(root_pc + 36, lo, lo + 11)
            if deg == "R":
                pitch = root
            elif deg == "5":
                pitch = root + 7
            elif deg == "O":
                pitch = root + 12
            elif deg == "7":
                pitch = root + _SEVENTH.get(quality, 10)
            elif deg.startswith("W"):
                nxt_pc, _ = harm.at(min(bar + 1.0, bars - 1e-6))
                target = _fits(nxt_pc + 36, lo, lo + 11)
                pitch = target - int(deg[1:])
            else:
                nxt_pc, _ = harm.at(min(bar + 1.0, bars - 1e-6))
                target = _fits(nxt_pc + 36, lo, lo + 11)
                pitch = target - 1 if (prev is None or prev < target) else target + 2
            start, v = _human(rng, clock.t(bar, step), vel, ms=6.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=pitch, start=start + 0.008, end=start + clock.step_len * length * 0.95, velocity=v))
            prev = pitch
    _emit(midi, ctx, _apply_stops(notes, ctx, clock, feel), name="Bass", program=33)


# ---------------------------------------------------------------------------
# RHODES
# ---------------------------------------------------------------------------

_COMP = {
    # A steady, soft 8th-note pulse alternating with a lazier bar.
    "verse": (((0, 2, 70), (2, 2, 56), (4, 2, 62), (6, 2, 56), (8, 2, 66), (10, 2, 56), (12, 2, 60), (14, 2, 64)),
              ((0, 6, 70), (6, 4, 62), (14, 2, 66))),
    "high": (((0, 3, 76), (3, 3, 68), (8, 4, 72), (14, 2, 74)), ((0, 6, 76), (6, 2, 66), (10, 4, 72), (14, 2, 74))),
    "soft": (((0, 16, 64),),),
}


def _rhodes(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    notes: list[NoteEvent] = []
    previous: Optional[list[int]] = None

    def chord(bar, step, length, vel, pos, roll=0.012):
        nonlocal previous
        root_pc, quality = harm.at(pos)
        voicing = _voice(root_pc, quality, previous)
        previous = voicing
        start = clock.t(bar, step)
        for i, p in enumerate(voicing):
            s, v = _human(rng, start + i * roll, vel, ms=5.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=p, start=s, end=s + clock.step_len * length * 0.95, velocity=v))

    bank = _COMP["high" if feel in HIGH_ROLES else "soft" if feel in SOFT_ROLES or feel == "intro" else "verse"]
    for bar in range(bars):
        if feel == "outro" and bar == bars - 1:
            chord(bar, 0, 16, 74, float(bar), roll=0.03)
            continue
        for step, length, vel in bank[bar % len(bank)]:
            pos = bar + step / clock.steps
            if step >= 14 and bar + 1 < bars:
                pos = bar + 1.0                                   # push into the next chord
            chord(bar, step, length, vel, pos)
    for bar, steps_ in hit_steps(ctx, clock).items():
        for st in steps_:
            chord(bar, st, 4, 88, bar + st / clock.steps, roll=0.006)
    _emit(midi, ctx, _apply_stops(notes, ctx, clock, feel), name="Chords", program=4)


# ---------------------------------------------------------------------------
# LEAD (clean guitar or any lead)
# ---------------------------------------------------------------------------

# Two-bar phrases: (step, length in 16ths, scale move, slide-in?)
_PHRASES = (
    ((2, 2, 0, False), (4, 1, 1, False), (5, 3, 1, True), (8, 2, -1, False), (10, 6, -1, True),
     (18, 2, 2, False), (20, 2, -1, False), (22, 6, -1, True)),
    ((0, 3, 0, True), (3, 1, 1, False), (4, 4, 1, False), (10, 2, -2, False), (12, 4, 1, True),
     (20, 2, 1, False), (22, 2, -1, False), (24, 6, -2, True)),
    ((3, 1, 0, False), (4, 2, 2, True), (6, 2, -1, False), (8, 6, -1, False),
     (16, 2, 1, False), (18, 2, 1, False), (20, 8, -2, True)),
)


def _theme(ctx: TechniqueContext):
    """The song's one hook: a two-bar phrase chosen from the song seed only,
    so every section that plays it plays the same notes."""
    rng = np.random.default_rng(zlib.crc32(f"{ctx.song_seed}|neo-soul theme".encode()))
    return _PHRASES[int(rng.integers(0, len(_PHRASES)))]


def _answer(theme):
    """The hook's answer: same rhythm, the last notes turn back down."""
    out = list(theme)
    for k in range(max(0, len(out) - 3), len(out)):
        step, length, move, slide = out[k]
        out[k] = (step, length, -abs(move) or -1, slide)
    return tuple(out)


# Where the hook plays within a section, per 2-bar slot: "T" theme, "A" its
# answer, "-" rest (room for the Rhodes).
_HOOK_PLAN = {
    "high": ("T", "A", "T", "A"),
    "verse": ("T", "-", "A", "-"),
    "soft": ("A", "-", "-", "-"),
}


def _lead(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    notes: list[NoteEvent] = []
    if feel in ("intro",):
        return
    # One pool and one starting note for the whole song, so the hook is the
    # same notes wherever it returns.
    pool = _scale_pitches(harm.tonic, ctx.scale, 60, 81)
    start_idx = min(range(len(pool)), key=lambda i: abs(pool[i] - 69))
    theme = _theme(ctx)
    plan = _HOOK_PLAN["high" if feel in HIGH_ROLES else "soft" if feel in SOFT_ROLES else "verse"]
    for slot, p_bar in enumerate(range(0, bars, 2)):
        kind = plan[slot % len(plan)]
        if kind == "-":
            continue
        phrase = theme if kind == "T" else _answer(theme)
        i_cur = start_idx
        for step, length, move, slide in phrase:
            bar = p_bar + step // clock.steps
            if bar >= bars or (feel == "outro" and bar >= bars - 1):
                break
            i_cur = int(np.clip(i_cur + move, 0, len(pool) - 1))
            pitch = pool[i_cur]
            if length >= 4:
                root_pc, quality = harm.at(bar + (step % clock.steps) / clock.steps)
                tones = {root_pc % 12} | {(root_pc + iv) % 12 for iv in _VOICINGS.get(quality, _VOICINGS["min7"])}
                pitch = min((p for p in pool if p % 12 in tones), key=lambda p: abs(p - pitch), default=pitch)
                i_cur = pool.index(pitch) if pitch in pool else i_cur
            start = clock.t(p_bar, step) + 0.01                   # a touch behind, relaxed
            vel = 84 + (6 if feel in HIGH_ROLES else 0) - (6 if length == 1 else 0)
            if slide:
                g, gv = _human(rng, start - clock.step_len * 0.4, vel - 16, ms=1.5, vel_jitter=2.0)
                notes.append(NoteEvent(pitch=pitch - 2, start=g, end=start, velocity=gv))
            s, v = _human(rng, start, vel, ms=5.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=pitch, start=s, end=start + clock.step_len * length * 0.92, velocity=v))
    if feel == "outro":
        t0 = clock.t(bars - 1, 0)
        notes.append(NoteEvent(pitch=_fits(harm.tonic + 72, 67, 79), start=t0, end=t0 + clock.bar_len * 0.9, velocity=92))
    _emit(midi, ctx, _apply_stops(notes, ctx, clock, feel), name="Lead", program=81)


for _feel in ALL_ROLES:
    _register(name=f"neo_soul_kit_{_feel}", label=f"Neo-soul kit ({_feel})",
              description="Laid-back kit: straight 8th hats, a backbeat a touch behind, ghost notes, a "
                          "phrase-end stop; toms then a rim groove in bridges.",
              instruments=("drums",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _drums(midi, ctx, _f))
    _register(name=f"neo_soul_bass_{_feel}", label=f"Neo-soul bass ({_feel})",
              description="Round bass on roots, fifths and approach notes, laid back.",
              instruments=("bass",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _bass(midi, ctx, _f))
    _register(name=f"neo_soul_rhodes_{_feel}", label=f"Neo-soul Rhodes ({_feel})",
              description="Lush Rhodes 9th voicings, rolled, comping lazily and pushing the changes.",
              instruments=("chords",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _rhodes(midi, ctx, _f))
    _register(name=f"neo_soul_lead_{_feel}", label=f"Neo-soul lead ({_feel})",
              description="Short singing phrases with slides, answering the Rhodes.",
              instruments=("melody",), roles=(_feel,), weight=4, tags=(TAG,),
              apply=lambda midi, ctx, _f=_feel: _lead(midi, ctx, _f))
