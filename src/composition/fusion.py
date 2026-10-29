"""Upbeat jazz-fusion techniques (tag ``fusion``).

Straight 16th-note fusion in the Spyro Gyra / Yellowjackets mould, the sound
of a bright corporate sizzle reel: a tight kit with ghosted snare and 16th
hats, a syncopated electric bass with octaves, dead notes and chromatic
approaches, Rhodes comping on rootless 9th voicings with pushes into the next
chord, and an alto-sax melody built from a two-bar motif that answers itself.

The swing-era jazz techniques walk the bass and swing the 8ths, which is not
this style, so ``fusion_full`` picks only from these (see
``_STRICT_GENRES`` in :mod:`src.composition.song_composer`).

Every technique writes notes directly (so the groove is exactly as written)
onto the track of the instrument it was routed to.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from src.composition.techniques import TechniqueContext
from src.daw_integration.generic.midi_export import (
    SCALES,
    NoteEvent,
    expand_progression_plan,
    note_name_to_midi,
    roman_to_semitone_offset,
)

from .builtins import _register

TAG = "fusion"
ALL_ROLES = ("intro", "verse", "prechorus", "chorus", "bridge", "solo",
             "breakdown", "drop", "outro")

# GM drum keys.
KICK, SNARE, STICK, CLOSED_HAT, PEDAL_HAT, OPEN_HAT = 36, 38, 37, 42, 44, 46
CRASH, RIDE, TOM_HI, TOM_MID, TOM_LO = 49, 51, 50, 47, 45


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _Clock:
    """Bar/16th positions → seconds for one section."""

    def __init__(self, ctx: TechniqueContext) -> None:
        num, den = ctx.time_signature
        self.steps = max(1, int(round(num * 16 / den)))   # 16ths per bar
        self.bar_len = num * (4.0 / den) * 60.0 / ctx.tempo
        self.step_len = self.bar_len / self.steps
        self.start_bar = ctx.start_bar

    def t(self, bar: int, step: float) -> float:
        return (self.start_bar + bar) * self.bar_len + step * self.step_len


class _Harmony:
    """Chord at any point of the section, as (root pitch class, quality)."""

    def __init__(self, ctx: TechniqueContext) -> None:
        self.tonic = note_name_to_midi(ctx.key, 0) % 12
        self.scale = ctx.scale
        self.events = expand_progression_plan(ctx.progression, ctx.bar_count)
        self.bars = ctx.bar_count

    def at(self, bar_pos: float) -> tuple[int, str]:
        bar_pos = min(max(bar_pos, 0.0), self.bars - 1e-6)
        symbol = None
        for ev in self.events:
            if ev.start_bar - 1e-9 <= bar_pos < ev.end_bar - 1e-9:
                symbol = ev.symbol
                break
        if symbol is None:
            symbol = self.events[-1].symbol if self.events else "i7"
        off, quality = roman_to_semitone_offset(symbol, self.scale)
        return (self.tonic + off) % 12, quality

    def changes_at(self, bar_pos: float) -> bool:
        return any(abs(ev.start_bar - bar_pos) < 1e-6 for ev in self.events)


def _emit(midi, ctx: TechniqueContext, notes: list[NoteEvent], *,
          name: str, program: int, is_drum: bool = False) -> None:
    """Append notes to the routed instrument's track (or create it)."""
    if not notes:
        return
    inst = ctx.instrument_obj
    track_name = getattr(inst, "track_name", None) or name
    prog = getattr(inst, "program", program) if inst is not None else program
    drum = bool(getattr(inst, "is_drum", is_drum)) if inst is not None else is_drum
    for track in midi.tracks:
        if track.name == track_name and track.is_drum == drum:
            track.notes.extend(notes)
            return
    midi.add_notes(notes, track_name=track_name, program=prog, is_drum=drum)


def _human(rng: np.random.Generator, t: float, vel: float, *, ms: float = 4.0,
           vel_jitter: float = 6.0) -> tuple[float, int]:
    jitter = float(rng.normal(0.0, ms / 1000.0))
    v = int(round(vel + float(rng.normal(0.0, vel_jitter))))
    return max(0.0, t + jitter), int(min(127, max(1, v)))


def _fits(pitch: int, lo: int, hi: int) -> int:
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch


# ---------------------------------------------------------------------------
# DRUMS
# ---------------------------------------------------------------------------

_HAT_16 = (82, 42, 60, 44)          # accent on the beat, lighter on the e/a
_KICKS_VERSE = ((0, 7, 10), (0, 6, 10, 13), (0, 3, 10), (0, 7, 8, 14))
_KICKS_CHORUS = ((0, 3, 6, 10), (0, 6, 8, 11, 14), (0, 3, 8, 10, 13))
_GHOST_SPOTS = (1, 6, 7, 9, 11, 15)


def _drum_fill(rng, clock, bar, notes, strength: float) -> None:
    kind = int(rng.integers(0, 3))
    if kind == 0:     # snare 16ths on beat 4, rising
        for i, step in enumerate(range(12, 16)):
            notes.append((bar, step, SNARE, 70 + 9 * i))
    elif kind == 1:   # snare → toms down beats 3-4
        seq = [SNARE, SNARE, TOM_HI, TOM_HI, TOM_MID, TOM_MID, TOM_LO, TOM_LO]
        for i, key in enumerate(seq):
            notes.append((bar, 8 + i, key, 76 + 3 * i))
    else:             # syncopated hits
        for step, key, v in ((10, SNARE, 90), (11, TOM_HI, 86), (13, TOM_MID, 92),
                             (14, TOM_LO, 98), (15, SNARE, 80)):
            notes.append((bar, step, key, v))
    notes.append((bar + 1, 0, CRASH, 100 * strength))


def _drums(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    bars = ctx.bar_count
    steps = clock.steps
    hits: list[tuple[int, float, int, float]] = []   # bar, step, key, velocity
    fill = ctx.drum_fill >= 0.5 and feel not in ("outro",) and bars >= 2
    kicks = _KICKS_CHORUS if feel in ("chorus", "solo", "drop") else _KICKS_VERSE
    k_a, k_b = (kicks[int(rng.integers(0, len(kicks)))] for _ in range(2))

    for bar in range(bars):
        last = bar == bars - 1
        if feel == "outro" and last:
            hits += [(bar, 0, KICK, 112), (bar, 0, CRASH, 110), (bar, 0, SNARE, 96)]
            continue
        fill_bar = fill and last
        hat_end = 8 if fill_bar else steps
        if feel == "intro":
            for step in range(0, hat_end, 2):
                hits.append((bar, step, CLOSED_HAT, 70 if step % 4 == 0 else 48))
            hits += [(bar, 4, STICK, 72), (bar, 12, STICK, 76)]
            for step in ((0, 10) if bar % 2 == 0 else (0, 6, 10)):
                hits.append((bar, step, KICK, 92))
        elif feel in ("bridge", "breakdown"):
            # Half-time: snare on 3, ride 8ths.
            for step in range(0, hat_end, 2):
                hits.append((bar, step, RIDE, 72 if step % 4 == 0 else 54))
            hits.append((bar, 8, SNARE, 108))
            for step in (0, 10, 14) if bar % 2 else (0, 7):
                hits.append((bar, step, KICK, 96))
        else:
            for step in range(hat_end):
                v = _HAT_16[step % 4]
                if feel in ("chorus", "solo", "drop"):
                    v += 6
                hits.append((bar, step, CLOSED_HAT, v))
            # Open the hat on the "and" of 4 every other bar (choked by the next closed hit).
            if bar % 2 == 1 and not fill_bar:
                hits = [h for h in hits if not (h[0] == bar and h[1] == 14 and h[2] == CLOSED_HAT)]
                hits.append((bar, 14, OPEN_HAT, 74))
            hits += [(bar, 4, SNARE, 110), (bar, 12, SNARE, 112)]
            kick = k_a if bar % 2 == 0 else k_b
            for step in kick:
                if fill_bar and step >= 8:
                    continue
                hits.append((bar, step, KICK, 104 if step == 0 else 92))
            taken = set(kick) | {4, 12}
            spots = [s for s in _GHOST_SPOTS if s not in taken and (not fill_bar or s < 8)]
            for s in rng.choice(spots, size=min(len(spots), int(rng.integers(2, 4))), replace=False):
                hits.append((bar, int(s), SNARE, float(rng.integers(26, 40))))
        if bar == 0 and feel in ("chorus", "solo", "drop", "verse"):
            hits.append((bar, 0, CRASH, 100))
        if feel in ("chorus", "drop") and bar % 4 == 0 and bar > 0:
            hits.append((bar, 0, CRASH, 92))
        if fill_bar:
            _drum_fill(rng, clock, bar, hits, 0.0)  # the next section brings its own crash
            hits = [h for h in hits if h[0] < bars]

    notes: list[NoteEvent] = []
    for bar, step, key, vel in hits:
        t, v = _human(rng, clock.t(bar, step), vel, ms=3.0, vel_jitter=4.0 if vel > 50 else 3.0)
        dur = clock.step_len * (8 if key in (CRASH, RIDE, OPEN_HAT) else 1)
        notes.append(NoteEvent(pitch=key, start=t, end=t + dur, velocity=v))
    _emit(midi, ctx, notes, name="Drums", program=0, is_drum=True)


for _feel in ALL_ROLES:
    _register(
        name=f"fusion_kit_{_feel}", label=f"Fusion kit ({_feel})",
        description="Straight-16th fusion groove: accented 16th hats, backbeat "
                    "with ghosted snare, syncopated kick, fills into the next section.",
        instruments=("drums",), roles=(_feel,), weight=4, tags=(TAG,),
        apply=lambda midi, ctx, _f=_feel: _drums(midi, ctx, _f),
    )


# ---------------------------------------------------------------------------
# BASS
# ---------------------------------------------------------------------------

# (step, degree, length in 16ths, velocity). R root, O octave, 5 fifth,
# 7 seventh, G dead note (ghost), A chromatic approach to the next chord.
_BASS_VERSE = (
    ((0, "R", 2, 104), (2, "G", 1, 40), (3, "R", 1, 80), (6, "O", 2, 94),
     (8, "5", 2, 86), (10, "R", 1, 76), (11, "G", 1, 40), (12, "7", 2, 86),
     (14, "O", 1, 82), (15, "A", 1, 86)),
    ((0, "R", 3, 106), (3, "R", 1, 72), (5, "G", 1, 40), (6, "5", 2, 90),
     (9, "O", 2, 94), (11, "7", 1, 76), (12, "5", 2, 86), (14, "R", 1, 80),
     (15, "A", 1, 86)),
    ((0, "R", 2, 104), (3, "O", 1, 90), (4, "G", 1, 38), (6, "R", 1, 82),
     (7, "5", 2, 88), (10, "O", 2, 92), (12, "R", 1, 80), (13, "G", 1, 38),
     (14, "7", 1, 84), (15, "A", 1, 86)),
)
_BASS_CHORUS = (
    ((0, "R", 2, 106), (2, "O", 1, 92), (4, "R", 2, 96), (6, "O", 1, 92),
     (7, "G", 1, 40), (8, "R", 2, 100), (10, "O", 1, 92), (12, "5", 2, 90),
     (14, "7", 1, 86), (15, "A", 1, 88)),
    ((0, "R", 3, 108), (3, "O", 1, 92), (6, "R", 1, 90), (7, "O", 1, 92),
     (8, "5", 2, 92), (10, "R", 1, 86), (11, "O", 1, 92), (12, "7", 2, 90),
     (14, "5", 1, 86), (15, "A", 1, 88)),
)
_BASS_SPARSE = (((0, "R", 8, 92), (8, "5", 6, 82), (14, "O", 1, 76), (15, "A", 1, 80)),)
_BASS_HALF = (((0, "R", 6, 96), (6, "R", 2, 80), (10, "5", 4, 86), (14, "7", 1, 80), (15, "A", 1, 82)),)

_SEVENTH = {"min7": 10, "min": 10, "7": 10, "maj7": 11, "maj": 11, "dim": 9, "sus4": 10, "sus2": 10, "aug": 10}


def _bass(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    lo, hi = 31, 50                 # B0..D3, the electric bass's home
    if feel in ("intro", "outro"):
        bank = _BASS_SPARSE
    elif feel in ("bridge", "breakdown"):
        bank = _BASS_HALF
    elif feel in ("chorus", "solo", "drop"):
        bank = _BASS_CHORUS
    else:
        bank = _BASS_VERSE
    a, b = (bank[int(rng.integers(0, len(bank)))] for _ in range(2))
    notes: list[NoteEvent] = []
    prev = None
    for bar in range(bars):
        pattern = a if bar % 2 == 0 else b
        if feel == "outro" and bar == bars - 1:
            pattern = ((0, "R", clock.steps * 2, 100),)
        for step, deg, length, vel in pattern:
            pos = bar + step / clock.steps
            root_pc, quality = harm.at(pos)
            root = _fits(root_pc + 36, lo, lo + 11)
            if deg == "R":
                pitch = root
            elif deg == "O":
                pitch = root + 12 if root + 12 <= hi else root
            elif deg == "5":
                pitch = root + (6 if quality == "dim" else 8 if quality == "aug" else 7)
            elif deg == "7":
                pitch = root + _SEVENTH.get(quality, 10)
            elif deg == "G":
                pitch = prev if prev is not None else root
            else:  # approach the next chord's root by a half step
                nxt_pc, _ = harm.at(min(bar + 1.0, bars - 1e-6))
                target = _fits(nxt_pc + 36, lo, lo + 11)
                if bar + 1 >= bars:
                    pitch = root + 7
                else:
                    pitch = target - 1 if (prev is None or prev < target) else target + 1
            pitch = _fits(pitch, lo, hi + 5)
            if deg == "G":
                start, v = _human(rng, clock.t(bar, step), vel, ms=3.0, vel_jitter=3.0)
                end = start + clock.step_len * 0.35       # muted "dead" note
            else:
                start, v = _human(rng, clock.t(bar, step), vel, ms=4.0, vel_jitter=5.0)
                end = start + clock.step_len * length * 0.92
            notes.append(NoteEvent(pitch=pitch, start=start, end=end, velocity=v))
            if deg != "G":
                prev = pitch
    _emit(midi, ctx, notes, name="Bass", program=33)


for _feel in ALL_ROLES:
    _register(
        name=f"fusion_bass_{_feel}", label=f"Fusion bass ({_feel})",
        description="Syncopated 16th electric bass: roots and octaves, dead notes, "
                    "fifths and sevenths, chromatic approach into each chord.",
        instruments=("bass",), roles=(_feel,), weight=4, tags=(TAG,),
        apply=lambda midi, ctx, _f=_feel: _bass(midi, ctx, _f),
    )


# ---------------------------------------------------------------------------
# RHODES COMPING
# ---------------------------------------------------------------------------

# Rootless voicings (semitones above the root), the Rhodes fusion colour.
_VOICINGS = {
    "min7": (3, 7, 10, 14), "min": (3, 7, 10, 14),
    "7": (4, 9, 10, 14), "maj7": (4, 7, 11, 14), "maj": (4, 7, 9, 14),
    "dim": (3, 6, 9, 12), "sus4": (5, 7, 10, 14), "sus2": (2, 7, 10, 14),
    "aug": (4, 8, 10, 14),
}
# (step, length in 16ths, velocity)
_COMP_VERSE = (
    ((0, 2, 84), (3, 3, 70), (10, 2, 74), (14, 2, 80)),
    ((2, 2, 78), (6, 4, 74), (11, 2, 70), (14, 2, 82)),
    ((0, 3, 82), (6, 2, 72), (8, 1, 64), (11, 3, 76)),
)
_COMP_CHORUS = (
    ((0, 6, 86), (6, 2, 76), (10, 6, 82)),
    ((0, 3, 86), (3, 3, 78), (8, 4, 82), (14, 2, 84)),
)


def _voice(root_pc: int, quality: str, previous: Optional[list[int]]) -> list[int]:
    shape = _VOICINGS.get(quality, _VOICINGS["min7"])
    candidates: list[list[int]] = []
    for base in range(46, 64):
        if base % 12 != root_pc:
            continue
        chord = sorted(base + iv for iv in shape)
        for inv in range(len(chord)):
            v = sorted(chord[inv:] + [p + 12 for p in chord[:inv]])
            if 50 <= v[0] and v[-1] <= 77:
                candidates.append(v)
    if not candidates:
        base = _fits(root_pc + 48, 48, 59)
        return sorted(base + iv for iv in shape)
    if previous is None:
        return min(candidates, key=lambda v: abs(sum(v) / len(v) - 64))
    return min(candidates, key=lambda v: sum(min(abs(p - q) for q in previous) for p in v))


def _rhodes(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    notes: list[NoteEvent] = []
    previous: Optional[list[int]] = None

    def chord_notes(start, end, pos, vel, roll=0.0):
        nonlocal previous
        root_pc, quality = harm.at(pos)
        voicing = _voice(root_pc, quality, previous)
        previous = voicing
        for i, p in enumerate(voicing):
            s, v = _human(rng, start + i * roll, vel - (3 if i == 0 else 0), ms=5.0, vel_jitter=4.0)
            notes.append(NoteEvent(pitch=p, start=s, end=max(s + 0.05, end), velocity=v))

    if feel in ("intro", "outro", "bridge", "breakdown"):
        # Held chords, one per change, gently rolled.
        for ev in harm.events:
            start = clock.t(0, ev.start_bar * clock.steps)
            end = clock.t(0, ev.end_bar * clock.steps) - 0.03
            if feel == "outro" and ev is harm.events[-1]:
                end += clock.bar_len
            chord_notes(start, end, ev.start_bar, 72 if feel != "bridge" else 68, roll=0.018)
    else:
        bank = _COMP_CHORUS if feel in ("chorus", "solo", "drop") else _COMP_VERSE
        a, b = (bank[int(rng.integers(0, len(bank)))] for _ in range(2))
        for bar in range(bars):
            for step, length, vel in (a if bar % 2 == 0 else b):
                pos = bar + step / clock.steps
                # A hit in the last 8th of a bar pushes the next bar's chord.
                if step >= clock.steps - 2 and bar + 1 < bars:
                    pos = bar + 1.0
                start = clock.t(bar, step)
                end = start + clock.step_len * length * 0.9
                chord_notes(start, end, pos, vel)
    _emit(midi, ctx, notes, name="Chords", program=4)


for _feel in ALL_ROLES:
    _register(
        name=f"fusion_rhodes_{_feel}", label=f"Fusion Rhodes ({_feel})",
        description="Rhodes comping on rootless 9th voicings with voice leading, "
                    "syncopated stabs that push into the next chord; held chords "
                    "in intro, bridge and outro.",
        instruments=("chords",), roles=(_feel,), weight=4, tags=(TAG,),
        apply=lambda midi, ctx, _f=_feel: _rhodes(midi, ctx, _f),
    )


# ---------------------------------------------------------------------------
# SAX MELODY
# ---------------------------------------------------------------------------

# Two-bar rhythmic motifs: (step from the phrase start, length in 16ths).
_MOTIFS = (
    ((0, 2), (2, 2), (4, 4), (10, 2), (12, 4), (18, 2), (20, 2), (22, 6)),
    ((2, 2), (4, 2), (6, 4), (12, 2), (14, 6), (24, 2), (26, 2), (28, 4)),
    ((0, 3), (3, 3), (6, 2), (8, 6), (16, 2), (19, 3), (22, 2), (24, 8)),
    ((1, 1), (2, 2), (4, 2), (7, 3), (10, 6), (18, 2), (20, 2), (22, 2), (24, 6)),
)
# Contour per phrase as scale-degree steps between notes.
_CONTOURS = (
    (1, 1, 2, -1, -1, 2, 1, -2, -1),
    (2, 1, -1, 2, -2, -1, 1, 1, -2),
    (-1, 2, 2, -1, -2, 1, 2, -1, -1),
)


def _scale_pitches(tonic_pc: int, scale: str, lo: int, hi: int) -> list[int]:
    steps = SCALES.get(scale, SCALES["dorian"])
    return [p for p in range(lo, hi + 1) if (p - tonic_pc) % 12 in steps]


def _chord_tones(root_pc: int, quality: str) -> set[int]:
    shape = _VOICINGS.get(quality, _VOICINGS["min7"])
    return {root_pc % 12} | {(root_pc + iv) % 12 for iv in shape}


def _sax(midi, ctx: TechniqueContext, feel: str) -> None:
    rng = ctx.rng
    clock = _Clock(ctx)
    harm = _Harmony(ctx)
    bars = ctx.bar_count
    if feel in ("intro",) and not ctx.lead_fill:
        return
    if feel in ("chorus", "solo", "drop"):
        lo, hi, centre = 64, 79, 72
    else:
        lo, hi, centre = 60, 76, 67
    pool = _scale_pitches(harm.tonic, ctx.scale, lo, hi)
    motif = _MOTIFS[int(rng.integers(0, len(_MOTIFS)))]
    contour = _CONTOURS[int(rng.integers(0, len(_CONTOURS)))]
    notes: list[NoteEvent] = []
    phrase_steps = clock.steps * 2

    # Which 2-bar phrases play: verses leave every other phrase for the band.
    phrases = list(range(0, bars, 2))
    if feel in ("verse", "prechorus", "bridge", "breakdown"):
        phrases = [p for i, p in enumerate(phrases) if i % 2 == 0]
    if feel == "outro":
        phrases = phrases[:1]
    if ctx.lead_fill:
        phrases = phrases[-1:]

    def nearest(pitch: int, pcs: Optional[set[int]] = None) -> int:
        cands = [p for p in pool if pcs is None or p % 12 in pcs] or pool
        return min(cands, key=lambda p: abs(p - pitch))

    start_pitch = nearest(centre)
    for n_phrase, p_bar in enumerate(phrases):
        last_phrase = n_phrase == len(phrases) - 1
        # Answer phrases rise; the final one comes home.
        lift = 2 if n_phrase % 2 == 1 else 0
        pitch = nearest(start_pitch + lift)
        idx = pool.index(pitch)
        for i, (step, length) in enumerate(motif):
            bar = p_bar + step // clock.steps
            if bar >= bars:
                break
            pos = bar + (step % clock.steps) / clock.steps
            root_pc, quality = harm.at(pos)
            strong = (step % 4 == 0) or length >= 4
            if i > 0:
                idx = int(np.clip(idx + contour[(i - 1) % len(contour)], 0, len(pool) - 1))
            pitch = pool[idx]
            if strong:
                pitch = nearest(pitch, _chord_tones(root_pc, quality))
                idx = pool.index(pitch)
            is_last = last_phrase and i == len(motif) - 1
            if is_last:
                pitch = nearest(pitch, {root_pc % 12, (root_pc + 7) % 12})
            dur_steps = length + (clock.steps if is_last and feel == "outro" else 0)
            start = clock.t(p_bar, step)
            end = start + clock.step_len * dur_steps * 0.95
            arc = 1.0 - abs((i / max(1, len(motif) - 1)) - 0.6)
            vel = 74 + 20 * arc + (6 if feel in ("chorus", "solo") else 0)
            s, v = _human(rng, start, vel, ms=6.0, vel_jitter=5.0)
            notes.append(NoteEvent(pitch=pitch, start=s, end=end, velocity=v))
        # Next phrase starts from where this one's motif began, sequenced to the new chord.
        start_pitch = notes[-len(motif)].pitch if len(notes) >= len(motif) else start_pitch
    _emit(midi, ctx, notes, name="Melody", program=65)


for _feel in ALL_ROLES:
    _register(
        name=f"fusion_sax_{_feel}", label=f"Fusion sax melody ({_feel})",
        description="Alto-sax melody from a two-bar motif that answers itself, chord "
                    "tones on the strong beats, space in the verses, a higher chorus.",
        instruments=("melody",), roles=(_feel,), weight=4, tags=(TAG,),
        apply=lambda midi, ctx, _f=_feel: _sax(midi, ctx, _f),
    )
