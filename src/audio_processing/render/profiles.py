"""Genre-aware mix profiles.

A :class:`MixProfile` is a named bundle of (per-family gain/pan
overrides, master preset, optional sidechain rules) that the render
pipeline picks based on the active StylePreset's genre. ``pop`` is
the streaming-target default — vocal forward, light sidechain on
bass / pad. ``rock`` pushes drums + guitars. ``ballad`` lifts strings
and gentles the comp. ``edm`` aggressively sidechain-ducks bass and
pads against the kick. ``jazz`` keeps drums dry + strings wide.
``cinematic`` favors sweep, long verb, transparent master.

Profiles compose with the base ``_FAMILY_MIX`` table — only fields
they specify are overridden; everything else inherits the industry
default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MixProfile:
    """One named mix profile.

    ``family_overrides[family] = {"gain_db": -2, "pan": 0.1, "stereo_widen": 0.3}``
    is a partial override of :class:`mix.MixDefaults`. Missing keys
    inherit the base defaults.

    ``master_preset`` picks the master-bus chain ("default" /
    "loud" / "cinematic" / "transparent").

    ``sidechain_kick_into`` lists families that should be ducked by
    the kick's envelope. Empty = no ducking.
    """

    name: str
    label: str
    family_overrides: dict = field(default_factory=dict)
    master_preset: str = "default"
    sidechain_kick_into: tuple[str, ...] = ()
    # Per-track defaults on top of the family, keyed by a lowercase substring
    # of the track name (``{"sax": {"gain_db": 2.0}}``), for parts that share
    # a family but play different roles (the sax lead vs. the horn stabs).
    # A producer's own per-track settings win.
    track_overrides: dict = field(default_factory=dict)
    # Per-family effect chain swaps by name (effects.NAMED_CHAINS), e.g.
    # {"lead": "tight_lead"} for a dry, punchy lead.
    family_chains: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Six built-in profiles
# ---------------------------------------------------------------------------

_POP = MixProfile(
    name="pop",
    label="Pop (vocal forward)",
    family_overrides={
        # Balanced front-to-back for INSTRUMENTAL full songs (stem-RMS verified):
        # drums/bass anchor the groove; chords + lead sit ~2-3 dB under them so
        # the harmony is present and nothing track dominates.
        "drums":      {"gain_db": -2.0},
        "bass":       {"gain_db": -4.5},
        "chords":     {"gain_db": -4.0},
        "lead_vocal": {"gain_db": -9.5},
        "bvocal":     {"gain_db": -7.5},
        "strings":    {"gain_db": -8.0},
    },
    master_preset="default",
    sidechain_kick_into=("pad",),   # light pad duck only
)

_ROCK = MixProfile(
    name="rock",
    label="Rock (drums + guitars forward)",
    family_overrides={
        "drums":      {"gain_db": -1.5},
        "bass":       {"gain_db": -3.5},
        "chords":     {"gain_db": -4.0},      # rhythm guitars present
        "lead":       {"gain_db": -3.0},      # lead guitar forward, not blaring
        "lead_vocal": {"gain_db": -9.0},      # instrumental melody sits with chords
        "bvocal":     {"gain_db": -10.0},
        "strings":    {"gain_db": -12.0},
        "brass":      {"gain_db": -9.0},
    },
    master_preset="loud",
    sidechain_kick_into=(),
)

_JAZZ = MixProfile(
    name="jazz",
    label="Jazz (transparent, wide)",
    family_overrides={
        "drums":      {"gain_db": -4.0},      # drums softer, more acoustic
        "bass":       {"gain_db": -3.5},
        "chords":     {"gain_db": -4.0},      # piano present (jazz comp)
        "lead":       {"gain_db": -4.0},      # solo forward but not dominating
        "lead_vocal": {"gain_db": -9.0},      # instrumental melody sits with piano
        "brass":      {"gain_db": -5.0},      # horns up
        "woodwind":   {"gain_db": -7.0},
        "strings":    {"gain_db": -8.0},
    },
    master_preset="transparent",
    sidechain_kick_into=(),
)

_FUNK_FUSION = MixProfile(
    name="funk_fusion",
    label="Funk fusion (horn stabs + sax lead forward)",
    family_overrides={
        "drums":      {"gain_db": -3.0},
        "bass":       {"gain_db": -3.0},
        "chords":     {"gain_db": -6.5, "pan": -0.2},   # Rhodes chops sit under the horns
        "brass":      {"gain_db": -3.5, "pan": 0.0},    # short stabs need to punch
        "lead":       {"gain_db": -11.5, "pan": 0.0},   # the synth lead, centre
        "strings":    {"gain_db": -6.0, "pan": 0.0, "stereo_widen": 0.35},
    },
    family_chains={"lead": "tight_lead"},               # dry and punchy like the band
    master_preset="loud",
    sidechain_kick_into=(),
    track_overrides={
        "sax":      {"gain_db": -3.5},                  # lead, centre, level with the stabs
        "synth":    {"gain_db": 0.0},                   # synth lead (family "lead")
        "trumpet":  {"pan": 0.35},
        "trombone": {"pan": 0.15},
        "french horn": {"gain_db": -4.0, "pan": -0.25},  # a warm pad under the strings
    },
)

_NEO_SOUL = MixProfile(
    name="neo_soul",
    label="Neo-soul (Rhodes forward, laid-back kit, dry lead)",
    family_overrides={
        "drums":      {"gain_db": -4.0},
        "bass":       {"gain_db": -3.0},
        "chords":     {"gain_db": -3.0, "pan": 0.0},    # the Rhodes leads the band
        "lead":       {"gain_db": -8.0, "pan": 0.1},
    },
    master_preset="default",
    sidechain_kick_into=(),
    family_chains={"lead": "tight_lead"},
)

_BALLAD = MixProfile(
    name="ballad",
    label="Ballad (vocal + strings forward)",
    family_overrides={
        "drums":      {"gain_db": -5.0},      # drums very soft
        "bass":       {"gain_db": -5.0},
        "chords":     {"gain_db": -5.0},
        "lead_vocal": {"gain_db": -8.0},      # melody slightly forward (ballad), still balanced
        "bvocal":     {"gain_db": -9.0},
        "strings":    {"gain_db": -6.0},      # strings forward, wide
        "woodwind":   {"gain_db": -8.0},
    },
    master_preset="transparent",
    sidechain_kick_into=(),
)

_EDM = MixProfile(
    name="edm",
    label="EDM (kick forward, sidechain pumping)",
    family_overrides={
        "drums":      {"gain_db": -0.5},      # kick max (EDM character)
        "bass":       {"gain_db": -2.0},
        "chords":     {"gain_db": -5.0},
        "pad":        {"gain_db": -6.0},
        "lead_vocal": {"gain_db": -9.0},      # instrumental melody balanced
        "bvocal":     {"gain_db": -10.0},
        "lead":       {"gain_db": -6.0},      # synth lead present, not piercing
    },
    master_preset="loud",
    sidechain_kick_into=("bass", "pad", "chords"),
)

_CINEMATIC = MixProfile(
    name="cinematic",
    label="Cinematic (strings + brass swell)",
    family_overrides={
        "drums":      {"gain_db": -3.5},
        "bass":       {"gain_db": -4.5},
        "strings":    {"gain_db": -5.0, "stereo_widen": 0.5},  # strings lead (cinematic)
        "brass":      {"gain_db": -5.0},
        "woodwind":   {"gain_db": -7.0},
        "lead_vocal": {"gain_db": -9.0},      # instrumental melody balanced
        "chords":     {"gain_db": -6.0},
    },
    master_preset="cinematic",
    sidechain_kick_into=(),
)


MIX_PROFILES: dict[str, MixProfile] = {
    p.name: p for p in (_POP, _ROCK, _JAZZ, _BALLAD, _EDM, _CINEMATIC, _FUNK_FUSION, _NEO_SOUL)
}


# ---------------------------------------------------------------------------
# Genre-key → profile resolution
# ---------------------------------------------------------------------------

# Each style-preset key in styles.STYLES resolves to one of the six
# profiles below. Unmapped presets fall back to ``pop`` (vocal-forward
# streaming target).
_PRESET_TO_PROFILE: dict[str, str] = {
    # Pop family.
    "pop":                  "pop",
    "pop_full_song":        "pop",
    "pop_dynamic":          "pop",
    "indie_pop":            "pop",
    "latin_pop":            "pop",
    "j_pop":                "pop",
    # Rock / metal.
    "rock":                 "rock",
    "rock_anthem_full":     "rock",
    "rock_buildup":         "rock",
    "metal":                "rock",
    "metal_full":           "rock",
    "punk":                 "rock",
    "country":              "rock",          # full-band country leans rock
    "country_full":         "rock",
    # Jazz / soul / funk.
    "jazz":                 "jazz",
    "jazz_fusion":          "jazz",
    "fusion_full":          "jazz",
    "funk_fusion_full":     "funk_fusion",
    "neo_soul_full":        "neo_soul",
    "jazz_aaba_full":       "jazz",
    "jazz_hard_bop_full":   "jazz",
    "jazz_modal_full":      "jazz",
    "jazz_ballad_full":     "ballad",
    "jazz_piano_full":      "jazz",
    "jazz_bossa_full":      "jazz",
    "jazz_blues_full":      "jazz",
    "jazz_bebop_full":      "jazz",
    "jazz_trade_fours":     "jazz",
    "funk":                 "rock",
    "funk_full_song":       "rock",
    "funk_dynamic":         "rock",
    "soul_motown_full":     "pop",
    "reggae_full":          "pop",
    "disco_full":           "pop",
    "blues_12bar_full":     "jazz",
    "bossa_nova":           "jazz",
    "afrobeat":             "pop",
    "salsa":                "pop",
    "flamenco":             "jazz",
    # Ballad.
    "ballad":               "ballad",
    "ballad_full":           "ballad",
    # EDM / dance.
    "edm":                   "edm",
    "edm_full_song":        "edm",
    "house":                 "edm",
    "trance":                "edm",
    # Hip-hop.
    "hip_hop":              "pop",
    "hip_hop_full":         "pop",
    # Cinematic.
    "cinematic_epic":       "cinematic",
    "cinematic_heroic":     "cinematic",
    "cinematic_dark":       "cinematic",
    # Cultural — mostly default to pop unless tagged.
    "gamelan_ambient":      "cinematic",
    "bollywood":            "pop",
    "bhangra":              "pop",
    "reggaeton":            "pop",
    "oud_ballad":           "ballad",
}


def resolve_profile(style_name: Optional[str]) -> MixProfile:
    """Return the MixProfile for a style-preset name. Falls back to
    ``pop`` when the style isn't mapped or is ``None``.
    """
    if not style_name:
        return MIX_PROFILES["pop"]
    profile_name = _PRESET_TO_PROFILE.get(style_name, "pop")
    return MIX_PROFILES.get(profile_name, MIX_PROFILES["pop"])


def apply_profile_to_family_mix(profile: MixProfile,
                                base_mix: dict) -> dict:
    """Build a per-family MixDefaults dict by overlaying ``profile``'s
    overrides on top of ``base_mix`` (typically ``_FAMILY_MIX`` from
    ``mix.py``). Returns a new dict — the base is not mutated.
    """
    from .mix import MixDefaults    # avoid circular import

    out: dict = dict(base_mix)
    for family, overrides in profile.family_overrides.items():
        current = out.get(family) or out.get("extra")
        if current is None:
            continue
        merged = MixDefaults(
            pan=overrides.get("pan", current.pan),
            gain_db=overrides.get("gain_db", current.gain_db),
            stereo_widen=overrides.get("stereo_widen",
                                       getattr(current, "stereo_widen", 0.0)),
        )
        out[family] = merged
    return out
