"""Generation "feel" knobs — the per-song controls surfaced in the UI.

One source of truth for the tunable generation parameters (lead
arrangement, harmony colour, dynamics, drum fills, bass motion). Each
genre has sensible defaults (drawn from :func:`harmony_profile` plus a few
new arrangement defaults); the UI passes overrides which are merged and
clamped here. ``resolve_knobs(genre, None)`` reproduces today's hardcoded
behaviour exactly, so the knobs are purely additive.

Knob meanings:
  voicing_variety  per-chord voicing-variety probability (0..1)
  reharm_prob      per-section reharmonization probability (0..1)
  bass_inversion   per-bar passing-inversion probability (0..1)
  dynamics         section energy-contrast intensity (0=flat, 1=normal, up to 2)
  drum_fill        multiplier on transition-fill probability (0..2)
  lead_amount      multiplier on the lead's verse/bridge play probability (0..2)
  lead_intro       probability the lead riffs the intro (0..1)
  lead_outro       probability the lead riffs the outro (0..1)
  lead_fills       probability the lead drops a fill in a non-featured section (0..1)
"""
from __future__ import annotations

from typing import Optional

from src.composition.harmony import harmony_profile

# New arrangement/feel defaults (not part of HarmonyProfile). Lead
# intro/outro/fills are "occasional by default" per the product decision.
_ARRANGEMENT_DEFAULTS = {
    "dynamics": 1.0,
    "drum_fill": 1.0,
    "lead_amount": 1.0,
    "lead_intro": 0.3,
    "lead_outro": 0.3,
    "lead_fills": 0.4,
}

# Clamp ranges. Multiplier knobs allow up to 2× (push past the genre norm);
# probabilities stay in [0, 1].
_CLAMP = {
    "voicing_variety": (0.0, 1.0),
    "reharm_prob": (0.0, 1.0),
    "bass_inversion": (0.0, 1.0),
    "dynamics": (0.0, 2.0),
    "drum_fill": (0.0, 2.0),
    "lead_amount": (0.0, 2.0),
    "lead_intro": (0.0, 1.0),
    "lead_outro": (0.0, 1.0),
    "lead_fills": (0.0, 1.0),
}

KNOB_KEYS = tuple(_CLAMP.keys())


def default_knobs(genre: Optional[str]) -> dict:
    """The genre's default knob values (what compose_song uses with no UI)."""
    p = harmony_profile(genre)
    return {
        "voicing_variety": p.voicing_variety,
        "reharm_prob": p.reharm_prob,
        "bass_inversion": p.bass_inversion,
        **_ARRANGEMENT_DEFAULTS,
    }


def resolve_knobs(genre: Optional[str], overrides: Optional[dict] = None) -> dict:
    """Merge UI ``overrides`` over the genre defaults and clamp.

    ``None``/missing override values keep the genre default, so
    ``resolve_knobs(genre, None)`` == ``default_knobs(genre)``.
    """
    k = default_knobs(genre)
    if overrides:
        for key, val in overrides.items():
            if key in k and val is not None:
                lo, hi = _CLAMP.get(key, (0.0, 1.0))
                k[key] = max(lo, min(hi, float(val)))
    return k
