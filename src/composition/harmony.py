"""Genre-keyed harmony policy.

Single source of genre-dependence for the chord engine: how much per-chord
voicing variety a genre gets (so progressions aren't one uniform voicing —
"mostly 7 chords") and which reharmonization strategies are eligible beyond
the bridge. Mirrors the lead engine's genre maps. Consumed by
``_add_chord_tech`` (voicing) and section pacing (reharm).

Appetite (confirmed with the user): tasteful colour for pop/rock/country,
adventurous (tritone subs, borrowed chords) for jazz/funk/soul/blues,
conservative for classical/cinematic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarmonyProfile:
    # Per-chord probability of deviating from the preset's home voicing.
    voicing_variety: float
    # Key into midi_export.VOICING_PALETTES.
    voicing_family: str
    # (strategy_name, weight) reharm strategies eligible in NON-bridge
    # sections (bridges already sample the preset's bridge_pacing_options).
    reharm: tuple
    # Base per-section probability of applying a reharm strategy in a
    # verse/chorus (scaled up for bridges). Higher = more adventurous.
    reharm_prob: float
    # Per-bar chance of a passing bass inversion (slash chord) on the
    # simple root/root_fifth patterns, for smoother bass motion.
    bass_inversion: float = 0.0


# Tasteful diatonic colour — pop / country / generic. Sparse secondary doms.
_TASTEFUL = HarmonyProfile(
    voicing_variety=0.35, voicing_family="diatonic_color",
    reharm=(("with_secondary_doms", 1),), reharm_prob=0.12, bass_inversion=0.18,
)
# Rock / metal — power-driven, basically no reharm.
_ROCK = HarmonyProfile(
    voicing_variety=0.30, voicing_family="rock",
    reharm=(), reharm_prob=0.0, bass_inversion=0.0,
)
# Jazz / funk / soul / blues — extended colour + adventurous reharm.
_JAZZ = HarmonyProfile(
    voicing_variety=0.55, voicing_family="jazz",
    reharm=(("with_secondary_doms", 2), ("with_tritone_sub", 1),
            ("with_borrowed_chords", 1)), reharm_prob=0.30, bass_inversion=0.28,
)
# Classical / cinematic — triadic + suspensions, occasional secondary dom.
_CLASSICAL = HarmonyProfile(
    voicing_variety=0.25, voicing_family="classical",
    reharm=(("with_secondary_doms", 1),), reharm_prob=0.10, bass_inversion=0.15,
)
# Blues — rich jazzy voicings, but the 12-bar FORM is rigid: never repace
# or reharmonize it (that breaks the canonical I7-IV7-V7 structure).
_BLUES = HarmonyProfile(
    voicing_variety=0.50, voicing_family="jazz",
    reharm=(), reharm_prob=0.0,
)


def harmony_profile(genre: str | None) -> HarmonyProfile:
    g = (genre or "").lower()
    if "blues" in g:                       # rigid form — checked before jazz
        return _BLUES
    if any(k in g for k in ("jazz", "funk", "soul", "rnb",
                            "gospel", "afrobeat", "saloon", "disco")):
        return _JAZZ
    if any(k in g for k in ("rock", "metal", "punk", "grunge")):
        return _ROCK
    if any(k in g for k in ("classical", "cinematic", "baroque", "waltz",
                            "romantic", "holiday", "game_", "gamelan")):
        return _CLASSICAL
    return _TASTEFUL
