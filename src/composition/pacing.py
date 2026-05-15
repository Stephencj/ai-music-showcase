"""Pacing strategies for the random song generator.

A :class:`PacingStrategy` is a named transform that takes a chord
progression and returns a re-paced version — different chord durations,
optionally with passing or secondary-dominant chords inserted.
``compose_song`` consults the active style preset's ``pacing_options``
(and ``bridge_pacing_options``) tuples and picks one strategy per
section using a seed-derived RNG, so every section can carry a
different harmonic rhythm — intro might pad on a slowly-changing
tonic, verse stays a 1-bar pulse, the bridge tries a short-long
pattern or inserts V/X secondary dominants.

Same seed → same picks (deterministic) so songs reproduce.

The renderer (:func:`src.daw_integration.generic.midi_export.expand_progression_plan`)
already accepts paced ``[(symbol, duration_bars)]`` lists, so strategies
just emit that canonical shape — no renderer changes needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

# Trailing chord-quality suffixes we strip to get the bare scale-degree
# stem. Longest first so "maj7" matches before "m7".
_SUFFIX_RE = re.compile(
    r"(maj7|min7|m7|sus2|sus4|add9|11|13|7|9|6|°|dim|o|\+|aug|m)$"
)


def _strip_suffix(symbol: str) -> str:
    """Return the bare Roman stem of ``symbol`` (e.g. ``"iim7"`` → ``"ii"``)."""
    s = symbol
    while True:
        m = _SUFFIX_RE.search(s)
        if m and m.start() > 0:
            s = s[: m.start()]
        else:
            break
    return s


def _is_tonic(symbol: str) -> bool:
    """``True`` for tonic / sub-tonic rest chords. I / i / vi / VI are
    where listeners feel 'home' so a stretched-tonic strategy holds
    these longer than the active dominant / subdominant chords."""
    stem = _strip_suffix(symbol)
    return stem in {"I", "i", "vi", "VI"}


def _normalize_pair(entry) -> tuple[str, float]:
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return str(entry[0]), float(entry[1])
    return str(entry), 1.0


def _normalize_progression(prog) -> list[tuple[str, float]]:
    return [_normalize_pair(p) for p in prog]


# Secondary-dominant lookup: chord X → the absolute-Roman symbol of V/X.
# Diatonic targets only; non-diatonic chords just hold (uniform_2 fallback).
SECONDARY_DOMS_MAJOR: dict[str, str] = {
    "ii":   "VI7",
    "iii":  "VII7",
    "IV":   "I7",
    "V":    "II7",
    "vi":   "III7",
}
SECONDARY_DOMS_MINOR: dict[str, str] = {
    # In a minor key the (V/X) targets are different because the scale
    # degrees are: i (m) – ii° – III – iv (m) – v/V – VI – VII.
    "iv":   "I7",
    "v":    "II7",
    "V":    "II7",
    "VI":   "III7",
    "VII":  "IV7",
}


def _key_secondary_doms(scale: str) -> dict[str, str]:
    """Pick the right secondary-dominant map for the active scale family."""
    if scale and scale.lower().startswith("min"):
        return SECONDARY_DOMS_MINOR
    return SECONDARY_DOMS_MAJOR


# Roman base → scale-degree index (0 = tonic). Matches what
# ``roman_to_semitone_offset`` uses internally; here we only need the
# coarse degree to detect adjacent-step movement for chromatic passing.
_DEGREE = {
    "I": 0, "i": 0,
    "II": 1, "ii": 1,
    "III": 2, "iii": 2,
    "IV": 3, "iv": 3,
    "V": 4, "v": 4,
    "VI": 5, "vi": 5,
    "VII": 6, "vii": 6,
}


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PacingStrategy:
    """One named harmonic-rhythm transform.

    ``apply(progression, key, scale)`` returns a new progression list of
    ``(symbol, duration_bars)`` tuples. The transform must be pure —
    same input always produces the same output — so seed-driven section
    picks remain reproducible.
    """

    name: str
    label: str
    description: str
    apply: Callable[[list, str, str], list]
    tags: tuple[str, ...] = ()


PACING_REGISTRY: dict[str, PacingStrategy] = {}


def _register(strategy: PacingStrategy) -> None:
    if strategy.name in PACING_REGISTRY:
        raise ValueError(f"duplicate pacing strategy {strategy.name!r}")
    PACING_REGISTRY[strategy.name] = strategy


# ---- uniform_1 ------------------------------------------------------------
def _uniform_1(prog, key, scale):
    return [(s, 1.0) for s, _ in _normalize_progression(prog)]


_register(PacingStrategy(
    name="uniform_1",
    label="Uniform 1-bar",
    description="Every chord holds for exactly one bar (the legacy default).",
    apply=_uniform_1,
))

# ---- uniform_2 ------------------------------------------------------------
def _uniform_2(prog, key, scale):
    return [(s, 2.0) for s, _ in _normalize_progression(prog)]


_register(PacingStrategy(
    name="uniform_2",
    label="Uniform 2-bar",
    description="Every chord stretched to two bars — modal vamp / ballad.",
    apply=_uniform_2,
))

# ---- stretch_tonic_2 ------------------------------------------------------
def _stretch_tonic_2(prog, key, scale):
    return [
        (s, 2.0 if _is_tonic(s) else 1.0)
        for s, _ in _normalize_progression(prog)
    ]


_register(PacingStrategy(
    name="stretch_tonic_2",
    label="Stretch tonic",
    description="Tonic chords (I / i / vi / VI) hold two bars; others one.",
    apply=_stretch_tonic_2,
))

# ---- short_long_subbar ----------------------------------------------------
def _short_long_subbar(prog, key, scale):
    pattern = [0.5, 0.5, 1.0, 1.0]
    items = _normalize_progression(prog)
    return [(s, pattern[i % len(pattern)]) for i, (s, _) in enumerate(items)]


_register(PacingStrategy(
    name="short_long_subbar",
    label="Short-long sub-bar",
    description="Repeating half-bar / one-bar pattern — bossa partido alto.",
    apply=_short_long_subbar,
))

# ---- ballad_4_2 -----------------------------------------------------------
def _ballad_4_2(prog, key, scale):
    items = _normalize_progression(prog)
    return [(s, 4.0 if i == 0 else 2.0) for i, (s, _) in enumerate(items)]


_register(PacingStrategy(
    name="ballad_4_2",
    label="Ballad 4+2",
    description="First chord holds four bars; remaining chords two bars each.",
    apply=_ballad_4_2,
))

# ---- cadence_accel --------------------------------------------------------
def _cadence_accel(prog, key, scale):
    items = _normalize_progression(prog)
    n = len(items)
    out = []
    for i, (s, _) in enumerate(items):
        # Last two chords compress to 1 bar each — pulls the ear toward
        # the resolution; everything before holds 2 bars.
        dur = 1.0 if (n >= 2 and i >= n - 2) else 2.0
        out.append((s, dur))
    return out


_register(PacingStrategy(
    name="cadence_accel",
    label="Cadence acceleration",
    description="Most chords hold two bars; last two compress to one bar each.",
    apply=_cadence_accel,
))

# ---- with_secondary_doms --------------------------------------------------
def _with_secondary_doms(prog, key, scale):
    """Stretch each chord over 2 bars; on bar 2 play V/Y where Y is the
    NEXT chord. That's the standard secondary-dominant idiom — the
    dominant pulls into the chord that follows. The last chord just
    holds (no chord to pull into)."""
    items = _normalize_progression(prog)
    dom_map = _key_secondary_doms(scale)
    out = []
    n = len(items)
    for i, (s, _) in enumerate(items):
        out.append((s, 1.0))
        if i + 1 < n:
            next_stem = _strip_suffix(items[i + 1][0])
            sec_dom = dom_map.get(next_stem)
            if sec_dom is not None:
                out.append((sec_dom, 1.0))
                continue
        # Either last chord OR no diatonic V/X — just hold the chord.
        out.append((s, 1.0))
    return out


_register(PacingStrategy(
    name="with_secondary_doms",
    label="V/X secondary dominants",
    description=(
        "Each chord paced over 2 bars; bar 2 inserts the secondary "
        "dominant of the NEXT chord (V/Y pulling into Y)."
    ),
    apply=_with_secondary_doms,
    tags=("chord_additions", "jazz"),
))

# ---- with_chromatic_passing -----------------------------------------------
def _with_chromatic_passing(prog, key, scale):
    """Stretch each chord to 1.5 bars; when the next chord is one
    scale-step above (e.g. I → ii or IV → V), insert a half-bar
    chromatic passing diminished chord built on the sharped tonic of
    the current chord (``#I°`` between I and ii). The renderer parses
    ``#I°`` as a sharp-rooted diminished triad."""
    items = _normalize_progression(prog)
    out = []
    n = len(items)
    for i, (s, _) in enumerate(items):
        cur_stem = _strip_suffix(s)
        if i + 1 < n:
            next_stem = _strip_suffix(items[i + 1][0])
            d1 = _DEGREE.get(cur_stem)
            d2 = _DEGREE.get(next_stem)
            if d1 is not None and d2 is not None and (d2 - d1) % 7 == 1:
                # Whole-step ascending — insert chromatic passing dim.
                # Strip case-sensitivity for the passing chord; uppercase
                # the stem so the renderer treats #X° as a diatonic-
                # sharped diminished root, not minor.
                passing = f"#{cur_stem.upper()}°"
                out.append((s, 1.5))
                out.append((passing, 0.5))
                continue
        # No passing chord — hold the chord for a full 2 bars so the
        # section duration matches what other strategies produce.
        out.append((s, 2.0))
    return out


_register(PacingStrategy(
    name="with_chromatic_passing",
    label="Chromatic passing",
    description=(
        "Each chord 1.5 bars with a half-bar chromatic diminished "
        "passing chord on whole-step ascending movement."
    ),
    apply=_with_chromatic_passing,
    tags=("chord_additions", "jazz", "broadway"),
))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def pick_pacing(rng, preset, section_role: str) -> PacingStrategy:
    """Pick a pacing strategy for one section using ``rng``.

    Bridge sections sample from ``preset.bridge_pacing_options`` when
    set (more adventurous pool); everything else samples from
    ``preset.pacing_options``. Empty pools fall back to ``uniform_1``
    so presets that opted out keep today's 1-bar-per-chord behavior.
    """
    bridge_pool = tuple(getattr(preset, "bridge_pacing_options", ()) or ())
    main_pool = tuple(getattr(preset, "pacing_options", ()) or ())
    pool = bridge_pool if (section_role == "bridge" and bridge_pool) else main_pool
    if not pool:
        return PACING_REGISTRY["uniform_1"]
    name = pool[int(rng.integers(0, len(pool)))]
    return PACING_REGISTRY.get(name, PACING_REGISTRY["uniform_1"])


def apply_pacing(progression: list, strategy: PacingStrategy,
                 key: str, scale: str) -> list:
    """Run ``strategy.apply`` against the progression. Returns a new
    list of ``(symbol, duration_bars)`` tuples ready for the renderer.
    """
    return strategy.apply(list(progression), key, scale)
