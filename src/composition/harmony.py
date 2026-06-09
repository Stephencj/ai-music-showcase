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


# Tasteful diatonic colour — pop / country / generic. Sparse secondary doms.
_TASTEFUL = HarmonyProfile(
    voicing_variety=0.35, voicing_family="diatonic_color",
    reharm=(("with_secondary_doms", 1),),
)
# Rock / metal — power-driven, very little reharm.
_ROCK = HarmonyProfile(
    voicing_variety=0.30, voicing_family="rock",
    reharm=(),
)
# Jazz / funk / soul / blues — extended colour + adventurous reharm.
_JAZZ = HarmonyProfile(
    voicing_variety=0.60, voicing_family="jazz",
    reharm=(("with_secondary_doms", 2), ("with_tritone_sub", 1),
            ("with_borrowed_chords", 1)),
)
# Classical / cinematic — triadic + suspensions, occasional secondary dom.
_CLASSICAL = HarmonyProfile(
    voicing_variety=0.25, voicing_family="classical",
    reharm=(("with_secondary_doms", 1),),
)


def harmony_profile(genre: str | None) -> HarmonyProfile:
    g = (genre or "").lower()
    if any(k in g for k in ("jazz", "funk", "soul", "blues", "rnb",
                            "gospel", "afrobeat", "saloon", "disco")):
        return _JAZZ
    if any(k in g for k in ("rock", "metal", "punk", "grunge")):
        return _ROCK
    if any(k in g for k in ("classical", "cinematic", "baroque", "waltz",
                            "romantic", "holiday", "game_", "gamelan")):
        return _CLASSICAL
    return _TASTEFUL
