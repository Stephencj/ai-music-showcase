"""High-level song composition: TechniqueBank + compose_song().

The TechniqueBank is a named, weighted-random registry of musical
techniques keyed by (instrument, section_role). Each technique is a
seedable transformation that applies to one bar range of a MidiExporter.

A song spec is a list of sections with roles (intro / verse / chorus /
bridge / outro). ``compose_song()`` picks one technique per
(instrument, section) using a master seed, applies them in order, and
returns paths + a human-readable summary.

The bank itself is populated at import time by ``src.composition.builtins``.
"""

from src.composition.instruments import (
    FAMILIES,
    FAMILY_LABELS,
    INSTRUMENT_REGISTRY,
    Instrument,
    expand_selection,
    instruments_for_family,
    role_of,
)
from src.composition.roles import role_for_label, SECTION_ROLES
from src.composition.techniques import (
    BANK,
    Technique,
    TechniqueBank,
    TechniqueContext,
)

# Importing builtins registers every technique with the BANK singleton.
# This side-effect is intentional — the module is documentation + registry.
from src.composition import builtins  # noqa: F401
from src.composition import fusion  # noqa: F401

__all__ = [
    "BANK",
    "FAMILIES",
    "FAMILY_LABELS",
    "INSTRUMENT_REGISTRY",
    "Instrument",
    "SECTION_ROLES",
    "Technique",
    "TechniqueBank",
    "TechniqueContext",
    "expand_selection",
    "instruments_for_family",
    "role_for_label",
    "role_of",
]
