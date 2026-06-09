"""TechniqueBank — registry + weighted-random pick for musical techniques.

Each Technique is a self-contained transformation keyed by
``(instrument, section_role)``. A song generator picks one technique
per cell using a master seed and applies them in instrument order
over the relevant bar range.

Used by :mod:`src.composition.song_composer` and exposed to LLMs via
:mod:`src.serve.mcp_tools`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context passed into every Technique.apply()
# ---------------------------------------------------------------------------

@dataclass
class TechniqueContext:
    """Per-section, per-instrument state a Technique reads when applying."""

    start_bar: int                # inclusive
    end_bar: int                  # inclusive
    section_role: str             # canonical role token (intro / verse / …)
    section_label: str            # original UI label ("Verse 1")
    instrument: str               # role bucket or specific id ("chords" | …)
    key: str
    scale: str
    tempo: float
    time_signature: tuple[int, int]
    progression: list             # MidiExporter-compatible chord plan
    rng: np.random.Generator      # seed-isolated per (section, instrument)
    swing: float = 0.0
    genre: str = ""               # style preset id, so genre-aware techniques
                                  # (e.g. the sub-bass) can adapt their pattern
    # When ``compose_song`` knows the specific Instrument routing for
    # this cell, it's attached here. Factory-built techniques in
    # builtins.py read .program and .track_name from it so the
    # renderer lands on a per-instrument MIDI track. Tests that
    # construct a ctx directly leave it None — techniques fall back
    # to the renderer's hard-coded defaults ("Chords", "Bass", …).
    instrument_obj: object = None
    # Layer role assigned by
    # :func:`src.composition.voicing_layer.assign_layered_voicings`
    # when 2+ chord-role instruments stack in this section. The
    # ``_RoutedMidi`` proxy rewrites the technique's ``voicing=``
    # kwarg through ``effective_voicing(role, base)`` so piano /
    # brass / strings each emit a distinct slice of the chord. Solo
    # chord-role instruments leave this None and the technique's
    # voicing flows through unchanged.
    voicing_role: Optional[str] = None

    @property
    def bar_count(self) -> int:
        return max(1, self.end_bar - self.start_bar + 1)


# ---------------------------------------------------------------------------
# Technique
# ---------------------------------------------------------------------------

@dataclass
class Technique:
    """A named, weighted, role-tagged musical transformation."""

    name: str
    label: str
    description: str
    instruments: tuple[str, ...]
    section_roles: tuple[str, ...]
    apply: Callable[..., None] = field(repr=False)
    weight: int = 1
    tags: tuple[str, ...] = ()            # e.g. ("funk_rock", "groove")

    def matches(self, instrument: str, role: str) -> bool:
        return (
            instrument in self.instruments
            and role in self.section_roles
        )

    def to_dict(self) -> dict:
        """JSON-friendly summary for MCP introspection."""
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "instruments": list(self.instruments),
            "section_roles": list(self.section_roles),
            "weight": self.weight,
            "tags": list(self.tags),
        }


# ---------------------------------------------------------------------------
# Bank
# ---------------------------------------------------------------------------

class TechniqueBank:
    """Module-level registry of Technique objects.

    Multi-instrument techniques (e.g. an outro riff that passes bass →
    lead) register once and match for every instrument in their
    ``instruments`` tuple. Lookup is linear over the dict; the bank
    rarely exceeds a few hundred entries.
    """

    def __init__(self) -> None:
        self._by_name: dict[str, Technique] = {}

    def register(self, technique: Technique) -> Technique:
        if technique.name in self._by_name:
            logger.warning(
                "TechniqueBank: re-registering %r — overwriting prior entry",
                technique.name,
            )
        self._by_name[technique.name] = technique
        return technique

    def get(self, name: str) -> Optional[Technique]:
        return self._by_name.get(name)

    def all_techniques(self) -> list[Technique]:
        return list(self._by_name.values())

    def list_for(self, instrument: str, role: str) -> list[Technique]:
        """All techniques eligible for ``(instrument, role)``, sorted by
        descending weight then name (stable for tests)."""
        out = [
            t for t in self._by_name.values() if t.matches(instrument, role)
        ]
        out.sort(key=lambda t: (-t.weight, t.name))
        return out

    def pick(
        self,
        instrument: str,
        role: str,
        rng: np.random.Generator,
        *,
        preferred_tags: tuple[str, ...] = (),
    ) -> Optional[Technique]:
        """Weighted-random pick of a technique for one cell.

        ``preferred_tags`` lets a song generator nudge picks toward a
        genre — e.g. ``preferred_tags=("funk_rock",)`` doubles the
        weight of techniques carrying that tag.
        """
        candidates = self.list_for(instrument, role)
        if not candidates:
            return None
        weights = []
        # Boost each candidate by 8× *per matched preferred tag*. So a
        # technique tagged `("jazz", "bossa_jazz")` competing against a
        # generic "jazz" technique under preferred_tags=("jazz",
        # "bossa_jazz") gets 8×8=64× while the generic one gets 8×.
        # The high multiplier counts against the ~80-100 baseline-
        # technique pool, which would otherwise drown out a genre with
        # only 1-2 candidates per cell. Cells with no tagged candidate
        # at all fall back to the cross-genre baseline.
        for t in candidates:
            w = max(1, int(t.weight))
            if preferred_tags:
                for tag in preferred_tags:
                    if tag in t.tags:
                        w *= 8
            weights.append(w)
        total = float(sum(weights))
        roll = float(rng.random()) * total
        acc = 0.0
        for t, w in zip(candidates, weights):
            acc += w
            if roll <= acc:
                return t
        return candidates[-1]


# Singleton populated at import time by src/composition/builtins.py.
BANK = TechniqueBank()


# ---------------------------------------------------------------------------
# Per-instrument routing proxy
# ---------------------------------------------------------------------------

class _RoutedMidi:
    """Wrap a MidiExporter so the four arrangement-level renderer calls
    land on the track + GM patch named by ``ctx.instrument_obj``.

    The hand-rolled techniques in :mod:`src.composition.builtins` call
    ``midi.add_chord_progression(...)`` without routing kwargs and let
    the renderer's defaults (``"Chords"`` / ``"Bass"`` / ``"Melody"`` /
    ``"Drums"``) win. That used to be fine when every cell wrote to one
    of those four shared tracks. Now ``compose_song`` runs one pass per
    enabled :class:`~src.composition.instruments.Instrument`, and each
    must land on its own per-instrument track — otherwise picking
    ``trumpet`` + ``sax_tenor`` both collapses into "Melody" and we
    lose the timbre.

    The proxy injects ``program=`` and ``track_name=`` (or just
    ``track_name=`` for drums, which has no program kwarg) into the
    four renderer methods. Every other attribute pass-through is
    untouched, so techniques that touch ``midi.tracks`` or build
    intermediate state still work.
    """

    _WITH_PROGRAM = frozenset({
        "add_chord_progression",
        "add_bass_line",
        "add_melody",
    })
    _TRACK_ONLY = frozenset({"add_drum_pattern"})

    def __init__(self, midi, inst, ctx=None) -> None:
        object.__setattr__(self, "_midi", midi)
        object.__setattr__(self, "_inst", inst)
        object.__setattr__(self, "_ctx", ctx)

    def __getattr__(self, name):
        attr = getattr(self._midi, name)
        inst = self._inst
        if inst is None:
            return attr
        if name in self._WITH_PROGRAM:
            program, track_name = inst.program, inst.track_name
            default_octave = getattr(inst, "default_octave", None)
            voicing_role = getattr(self._ctx, "voicing_role", None)
            def routed(*args, **kwargs):
                kwargs["program"] = program
                kwargs["track_name"] = track_name
                # setdefault — techniques that pin an octave explicitly
                # (e.g. a brass-shout lead at octave 5) win; everything
                # else gets the instrument's registered default register.
                if default_octave is not None:
                    kwargs.setdefault("octave", default_octave)
                # Stratified voicing — only fires when compose_song
                # assigned a layer role (2+ chord-role instruments). Solo
                # chord instruments leave voicing_role=None so the
                # technique's voicing passes through. The rewrite uses
                # setdefault-style update on whatever the technique passed.
                if voicing_role and "voicing" in kwargs:
                    from src.composition.voicing_layer import effective_voicing
                    kwargs["voicing"] = effective_voicing(
                        voicing_role, kwargs["voicing"],
                    )
                return attr(*args, **kwargs)
            return routed
        if name in self._TRACK_ONLY:
            track_name = inst.track_name
            def routed(*args, **kwargs):
                kwargs["track_name"] = track_name
                return attr(*args, **kwargs)
            return routed
        return attr

    def __setattr__(self, name, value):
        setattr(self._midi, name, value)


def apply_technique(midi, technique: Technique, ctx: TechniqueContext) -> None:
    """Apply ``technique`` with per-instrument routing when ``ctx`` has
    an ``instrument_obj`` attached. Otherwise pass-through — keeps every
    direct unit-test that constructs a ctx without an Instrument working
    against the renderer's hard-coded default track names.
    """
    inst = getattr(ctx, "instrument_obj", None)
    routed = _RoutedMidi(midi, inst, ctx=ctx) if inst is not None else midi
    technique.apply(routed, ctx)
