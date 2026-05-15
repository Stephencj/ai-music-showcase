"""Named instrument registry for the TechniqueBank pipeline.

Each :class:`Instrument` is the routing target for one or more bank
techniques: it carries a GM patch + a stable track name + the role
bucket it fulfils. Section composites (Brass Section, Woodwind
Section, String Section) collapse to one track at the section's
characteristic patch; expanding the family swaps to per-instrument
tracks.

``INSTRUMENT_REGISTRY`` is the single source of truth. The UI reads
``FAMILIES`` to lay out grouped checkbox accordions; ``compose_song``
walks the user's selection, looking up each id in the registry and
threading it into ``TechniqueContext.instrument`` so the bank's
techniques route their notes to the right track.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Family group keys — keep stable so UI accordions don't reshuffle.
# ---------------------------------------------------------------------------

FAMILIES: tuple[str, ...] = (
    "rhythm",        # drum kit, percussion (drums role)
    "bass",          # electric / upright / synth bass
    "chord_lead",    # piano, organ, guitars, lead synths
    "brass",         # section + trumpet / trombone / saxes
    "woodwind",      # section + flute / clarinet / oboe / bassoon
    "strings",       # section + violin / viola / cello / contrabass
)

# Human-readable labels for each family (used as accordion titles in the UI).
FAMILY_LABELS: dict[str, str] = {
    "rhythm":     "Rhythm Section",
    "bass":       "Bass",
    "chord_lead": "Chord / Lead",
    "brass":      "Brass",
    "woodwind":   "Woodwinds",
    "strings":    "Strings",
}


# ---------------------------------------------------------------------------
# Instrument dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Instrument:
    """A named playable instrument routed to its own MIDI track.

    ``role`` is the bank "role bucket" this instrument fulfils — one of
    ``chords``, ``bass``, ``melody``, ``drums``. Every existing
    technique tagged with a role token also matches this instrument,
    so the bank stays backwards compatible while gaining per-instrument
    track routing.

    ``is_section`` marks composite picks (e.g. "Brass Section") whose
    ``members`` expand into the per-instrument ids when the user
    toggles them on in the UI. Treating the section as one logical
    pick keeps the default UX simple; expanding the family exposes
    the individual instruments.
    """

    id: str                          # stable token, e.g. "electric_guitar_clean"
    label: str                       # display name + default track name
    family: str                      # FAMILIES entry
    role: str                        # "chords" | "bass" | "melody" | "drums"
    program: int                     # GM patch
    is_drum: bool = False
    is_section: bool = False
    members: tuple[str, ...] = ()    # only meaningful when is_section is True
    velocity_floor: int = 0          # for quiet section instruments

    @property
    def track_name(self) -> str:
        """MIDI track name. Mirrors ``label`` unless we ever need to
        disambiguate two instruments with the same display name."""
        return self.label


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

INSTRUMENT_REGISTRY: dict[str, Instrument] = {}


def _add(inst: Instrument) -> None:
    if inst.id in INSTRUMENT_REGISTRY:
        raise ValueError(f"duplicate instrument id {inst.id!r}")
    INSTRUMENT_REGISTRY[inst.id] = inst


# Rhythm — channel 10 drum kits
_add(Instrument("drum_kit",   "Drum kit",   "rhythm", "drums", 0, is_drum=True))
_add(Instrument("percussion", "Percussion", "rhythm", "drums", 0, is_drum=True))

# Bass
_add(Instrument("electric_bass", "Electric Bass", "bass", "bass", 33))
_add(Instrument("upright_bass",  "Upright Bass",  "bass", "bass", 32))
_add(Instrument("synth_bass",    "Synth Bass",    "bass", "bass", 38))

# Chord / lead instruments
_add(Instrument("piano",                 "Piano",                "chord_lead", "chords", 0))
_add(Instrument("electric_piano",        "Electric Piano",       "chord_lead", "chords", 4))
_add(Instrument("organ_hammond",         "Organ (Hammond)",      "chord_lead", "chords", 16))
_add(Instrument("organ_church",          "Organ (Church)",       "chord_lead", "chords", 19))
_add(Instrument("acoustic_guitar",       "Acoustic Guitar",      "chord_lead", "chords", 25))
_add(Instrument("electric_guitar_clean", "Electric Guitar (clean)", "chord_lead", "chords", 27))
_add(Instrument("electric_guitar_dirty", "Electric Guitar (dirty)", "chord_lead", "chords", 29))
_add(Instrument("lead_guitar",           "Lead Guitar",          "chord_lead", "melody", 30))
_add(Instrument("synth_pad",             "Synth Pad",            "chord_lead", "chords", 89))
_add(Instrument("synth_lead",            "Synth Lead",           "chord_lead", "melody", 81))

# Brass — section composite + individual instruments
_add(Instrument("brass_section", "Brass Section", "brass", "chords", 61,
                is_section=True,
                members=("trumpet", "trombone", "sax_alto", "sax_tenor")))
_add(Instrument("trumpet",       "Trumpet",       "brass", "melody", 56))
_add(Instrument("trombone",      "Trombone",      "brass", "melody", 57))
_add(Instrument("sax_alto",      "Alto Sax",      "brass", "melody", 65))
_add(Instrument("sax_tenor",     "Tenor Sax",     "brass", "melody", 66))
_add(Instrument("sax_baritone",  "Baritone Sax",  "brass", "melody", 67))

# Woodwinds
_add(Instrument("woodwind_section", "Woodwind Section", "woodwind", "chords", 71,
                is_section=True,
                members=("flute", "clarinet", "oboe", "bassoon")))
_add(Instrument("flute",    "Flute",    "woodwind", "melody", 73))
_add(Instrument("clarinet", "Clarinet", "woodwind", "melody", 71))
_add(Instrument("oboe",     "Oboe",     "woodwind", "melody", 68))
_add(Instrument("bassoon",  "Bassoon",  "woodwind", "bass",   70))

# Strings
_add(Instrument("string_section", "String Section", "strings", "chords", 48,
                is_section=True,
                members=("violin", "viola", "cello", "contrabass")))
_add(Instrument("violin",     "Violin",     "strings", "melody", 40))
_add(Instrument("viola",      "Viola",      "strings", "chords", 41))
_add(Instrument("cello",      "Cello",      "strings", "bass",   42))
_add(Instrument("contrabass", "Contrabass", "strings", "bass",   43))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def instruments_for_family(family: str) -> list[Instrument]:
    """All instruments in a family, in registry order (so UI is stable)."""
    return [
        inst for inst in INSTRUMENT_REGISTRY.values()
        if inst.family == family
    ]


def expand_selection(selection: list[str]) -> list[Instrument]:
    """Resolve a list of instrument ids → concrete Instrument list.

    Section composites are expanded into their members ONLY if the
    user has also ticked any member individually elsewhere — otherwise
    the section stays as a single track at the composite patch. This
    matches the user's mental model: "Brass Section" is one timbre
    until they specifically pick trumpet / trombone / sax.
    """
    out: list[Instrument] = []
    seen_ids: set[str] = set()
    selection_set = set(selection)

    for sel_id in selection:
        inst = INSTRUMENT_REGISTRY.get(sel_id)
        if inst is None:
            continue
        if inst.id in seen_ids:
            continue
        # Section composite: keep as-is unless any of its members are
        # ALSO selected individually — in which case it's better to
        # drop the composite (the user is curating per-instrument).
        if inst.is_section and any(m in selection_set for m in inst.members):
            continue
        seen_ids.add(inst.id)
        out.append(inst)
    return out


def role_of(inst_id: str) -> Optional[str]:
    """``"chords"`` / ``"bass"`` / ``"melody"`` / ``"drums"`` for an id."""
    inst = INSTRUMENT_REGISTRY.get(inst_id)
    return inst.role if inst else None
