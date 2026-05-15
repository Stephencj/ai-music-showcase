"""Stratified per-instrument chord voicing rules.

When multiple chord-role instruments fire together in a section, each
should occupy a distinct register / chord-density slice — otherwise
they all play the same notes in the same octave and the result is
muddy. Standard orchestration practice:

- **mid_comp** (low comp register, octave ~3) — piano / guitar / organ
  / electric piano play rootless 9ths or shell voicings (3 + 7 +
  extensions). Supports harmony without doubling the bass.
- **pad** (middle register, octave ~4) — viola / brass section /
  string section sustain full seventh / ninth voicings as a harmonic
  bed.
- **top** (high register, octave ~5+) — woodwinds / synth pad lay a
  thin shell or open-fifth on top, capping the stack.

Solo chord instruments (only one selected) get NO layering applied —
the technique's pinned voicing renders unchanged.

The mapping is consulted by :class:`src.composition.techniques._RoutedMidi`
which rewrites the ``voicing=`` kwarg of ``add_chord_progression`` at
apply time, and by ``compose_midi`` for the legacy single-shot path.
"""

from __future__ import annotations

from typing import Optional


# Canonical layer-role names. Exposed for tests + introspection.
LAYER_ROLES: tuple[str, ...] = ("mid_comp", "pad", "top")


# (layer_role, base_voicing) → effective voicing string the renderer
# should receive. Base voicings not listed pass through unchanged so
# exotic technique-pinned voicings (quartal / quintal / drop2 / etc.)
# stay intact when the technique chose them deliberately.
LAYERED_VOICING_MAP: dict[str, dict[str, str]] = {
    "mid_comp": {
        # Rootless 9ths (3-5-7-9) — Bill Evans / jazz piano comp idiom.
        "ninth":   "rootless",
        "add9":    "rootless",
        # Shell (3 + 7) — Hank Jones / Wynton Kelly minimalist comp.
        "seventh": "shell",
        "maj7":    "shell",
        "sixth":   "shell",
        # Triad / power stay intact — they're already sparse enough.
    },
    "pad": {
        # Pads keep full extensions but drop the rootless option (we
        # want sustaining warmth, not rhythmic comp).
        "ninth":   "ninth",
        "add9":    "ninth",
        "seventh": "seventh",
        "maj7":    "seventh",
        "triad":   "seventh",     # warm bare triads up to seventh
        "shell":   "seventh",
    },
    "top": {
        # The top voice caps the stack — shell or open-5 keeps it
        # out of the melody's way and avoids clashing with mid/pad
        # extensions.
        "ninth":   "shell",
        "add9":    "shell",
        "seventh": "shell",
        "maj7":    "shell",
        "triad":   "open5",
    },
}


def effective_voicing(role: Optional[str], base: str) -> str:
    """Translate ``(role, base_voicing)`` → the voicing the renderer
    should actually use. ``role=None`` (or unknown role) passes the
    base voicing through unchanged."""
    if not role:
        return base
    mapping = LAYERED_VOICING_MAP.get(role, {})
    return mapping.get(base, base)


def assign_layered_voicings(chord_instruments) -> dict[str, str]:
    """Assign each chord-role :class:`Instrument` a layer role.

    Empty / single instrument → returns ``{}`` so the caller knows
    layering is off and the technique's voicing flows through.

    With 2+ instruments, sort by ``(default_octave, family, id)``
    ascending and assign:

    - Lowest register → ``mid_comp`` (the comp instrument)
    - Highest register → ``top``
    - Anyone in between → ``pad``

    Instruments with a pinned ``voicing_role`` on the registry entry
    (``synth_pad`` / ``string_section`` / ``brass_section`` /
    ``woodwind_section``) keep their pinned role regardless of where
    they sort — they have a canonical semantic place in the arrangement.
    """
    if len(chord_instruments) < 2:
        return {}

    sorted_insts = sorted(
        chord_instruments,
        key=lambda i: (
            i.default_octave if i.default_octave is not None else 3,
            getattr(i, "family", ""),
            i.id,
        ),
    )
    n = len(sorted_insts)
    out: dict[str, str] = {}
    for idx, inst in enumerate(sorted_insts):
        pinned = getattr(inst, "voicing_role", None)
        if pinned:
            out[inst.id] = pinned
            continue
        if idx == 0:
            out[inst.id] = "mid_comp"
        elif idx == n - 1:
            out[inst.id] = "top"
        else:
            out[inst.id] = "pad"
    return out
