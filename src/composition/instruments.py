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
    "vocal",         # lead vocal + backing harmonies
)

# Human-readable labels for each family (used as accordion titles in the UI).
FAMILY_LABELS: dict[str, str] = {
    "rhythm":     "Rhythm Section",
    "bass":       "Bass",
    "chord_lead": "Chord / Lead",
    "brass":      "Brass",
    "woodwind":   "Woodwinds",
    "strings":    "Strings",
    "vocal":      "Vocals",
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
    # Default octave for this instrument's renderer calls (C4 = MIDI 60
    # ⇒ octave 4). Read by ``_RoutedMidi`` and injected via setdefault
    # so techniques that explicitly pass ``octave=`` still win — only
    # the unspecified case picks up the instrument default. ``None``
    # means "leave whatever the renderer's default is" (used by drum
    # tracks, which have no pitched octave).
    default_octave: Optional[int] = None
    # Pinned layer role for stratified-voicing assignment when 2+
    # chord-role instruments stack (see
    # :mod:`src.composition.voicing_layer`). ``None`` lets the
    # assigner derive the role from register; a few instruments have
    # a canonical role regardless of the stack (``synth_pad`` is
    # always a pad, ``woodwind_section`` always caps the top).
    voicing_role: Optional[str] = None

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
# Add-on percussion LAYERS — selectable alongside the main kit; the composer
# renders them with a complementary (off-beat, no kick/snare) pattern so they
# sit with the drums instead of competing. Role "percussion" → own track.
_add(Instrument("latin_perc",  "Latin percussion",  "rhythm", "percussion", 0, is_drum=True))
_add(Instrument("hiphop_perc", "Hip-hop percussion", "rhythm", "percussion", 0, is_drum=True))

# Bass — written low (E1–G3 typical).
_add(Instrument("electric_bass", "Electric Bass", "bass", "bass", 33, default_octave=2))
_add(Instrument("upright_bass",  "Upright Bass",  "bass", "bass", 32, default_octave=2))
_add(Instrument("synth_bass",    "Synth Bass",    "bass", "bass", 38, default_octave=2))

# Chord / lead instruments — comp register. Solo synth_lead / lead_guitar
# sit one octave higher than the comp instruments.
_add(Instrument("piano",                 "Piano",                "chord_lead", "chords", 0,  default_octave=3))
_add(Instrument("electric_piano",        "Electric Piano",       "chord_lead", "chords", 4,  default_octave=3))
_add(Instrument("organ_hammond",         "Organ (Hammond)",      "chord_lead", "chords", 16, default_octave=3))
_add(Instrument("organ_church",          "Organ (Church)",       "chord_lead", "chords", 19, default_octave=3))
_add(Instrument("acoustic_guitar",       "Acoustic Guitar",      "chord_lead", "chords", 25, default_octave=3))
_add(Instrument("electric_guitar_clean", "Electric Guitar (clean)", "chord_lead", "chords", 27, default_octave=3))
_add(Instrument("electric_guitar_dirty", "Electric Guitar (dirty)", "chord_lead", "chords", 29, default_octave=3))
_add(Instrument("lead_guitar",           "Lead Guitar",          "chord_lead", "melody", 30, default_octave=4))
_add(Instrument("synth_pad",             "Synth Pad",            "chord_lead", "chords", 89, default_octave=3, voicing_role="pad"))
_add(Instrument("synth_lead",            "Synth Lead",           "chord_lead", "melody", 81, default_octave=5))

# Brass — section composite + individual instruments. Trumpet / alto sit
# in the soprano register; trombone / tenor are tenor-voice; baritone
# sax sits at trombone register.
_add(Instrument("brass_section", "Brass Section", "brass", "chords", 61,
                is_section=True,
                members=("trumpet", "trombone", "sax_alto", "sax_tenor"),
                default_octave=4, voicing_role="pad"))
_add(Instrument("trumpet",       "Trumpet",       "brass", "melody", 56, default_octave=5))
_add(Instrument("trombone",      "Trombone",      "brass", "melody", 57, default_octave=4))
_add(Instrument("sax_alto",      "Alto Sax",      "brass", "melody", 65, default_octave=5))
_add(Instrument("sax_tenor",     "Tenor Sax",     "brass", "melody", 66, default_octave=4))
_add(Instrument("sax_baritone",  "Baritone Sax",  "brass", "melody", 67, default_octave=4))

# Woodwinds — flute / oboe / clarinet sit in the soprano register;
# bassoon doubles bass.
_add(Instrument("woodwind_section", "Woodwind Section", "woodwind", "chords", 71,
                is_section=True,
                members=("flute", "clarinet", "oboe", "bassoon"),
                default_octave=5, voicing_role="top"))
_add(Instrument("flute",    "Flute",    "woodwind", "melody", 73, default_octave=5))
_add(Instrument("clarinet", "Clarinet", "woodwind", "melody", 71, default_octave=5))
_add(Instrument("oboe",     "Oboe",     "woodwind", "melody", 68, default_octave=5))
_add(Instrument("bassoon",  "Bassoon",  "woodwind", "bass",   70, default_octave=3))

# Strings — violin section sits brighter than viola; cello + contrabass
# split bass duty.
_add(Instrument("string_section", "String Section", "strings", "chords", 48,
                is_section=True,
                members=("violin", "viola", "cello", "contrabass"),
                default_octave=4, voicing_role="pad"))
_add(Instrument("violin",     "Violin",     "strings", "melody", 40, default_octave=5))
_add(Instrument("viola",      "Viola",      "strings", "chords", 41, default_octave=4))
_add(Instrument("cello",      "Cello",      "strings", "bass",   42, default_octave=3))
_add(Instrument("contrabass", "Contrabass", "strings", "bass",   43, default_octave=2))

# Vocals — lead is GM 53 Voice Oohs; backing is GM 52 Choir Aahs pinned
# to the "pad" voicing slot so backing layers behind whatever else is
# in the chord stack.
_add(Instrument("vocal_lead",    "Lead Vocal",     "vocal", "melody", 53,
                default_octave=5))
_add(Instrument("vocal_harmony", "Backing Vocals", "vocal", "chords", 52,
                default_octave=5, voicing_role="pad"))


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
