"""User-facing genre catalog — a consolidated, de-duplicated view over the raw
``STYLES`` presets.

The engine has grown several presets per genre: a short loop (``pop``), a
feature demo (``pop_dynamic``) and a full-song template (``pop_full_song``).
With the section-based paradigm that's redundant in the picker, so this module
collapses them into ONE user-facing genre that resolves to:

  * ``song``    — the preset used to generate a whole song (the full-song
                  template when one exists),
  * ``section`` — the lighter preset used for a single section's *feel* in a
                  multi-preset song.

Genres are grouped into a handful of families for the radial "genre wheel"
picker. Feature-demo presets are simply left out of the catalog (still in
STYLES, so old blocks regenerate). Anything in STYLES but not mapped here stays
reachable via search but isn't surfaced on the wheel.
"""

from __future__ import annotations

# (display name, song preset, section preset). song == section when a genre has
# no separate short/full split. Order within a family is roughly by prominence.
GENRE_FAMILIES: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    # (family label, color, genres)
    ("Pop", "#ec4899", [
        ("Pop",            "pop_full_song",    "pop"),
        ("Ballad",         "ballad_full",      "ballad_full"),
        ("Boy Band",       "boy_band",         "boy_band"),
        ("J-Pop",          "j_pop",            "j_pop"),
    ]),
    ("Rock & Metal", "#ef4444", [
        ("Rock",           "rock_anthem_full", "rock"),
        ("Metal",          "metal_full",       "metal"),
        ("Nu-Metal",       "nu_metal",         "nu_metal"),
        ("Surf Rock",      "surf_rock",        "surf_rock"),
        ("New Wave",       "new_wave",         "new_wave"),
    ]),
    ("Country", "#f59e0b", [
        ("Country",        "country_full",     "country"),
        ("Saloon",         "saloon_piano",     "saloon_piano"),
    ]),
    ("Blues & Jazz", "#6366f1", [
        ("Blues",          "blues_12bar_full", "blues_12bar_full"),
        ("Jazz",           "jazz_aaba_full",   "jazz_fusion"),
        ("Jazz Fusion",    "fusion_full",      "fusion_full"),
        ("Funk Fusion",    "funk_fusion_full", "funk_fusion_full"),
        ("Neo-Soul Chill", "neo_soul_full",    "neo_soul_full"),
        ("Bossa Nova",     "jazz_bossa_full",  "bossa_nova"),
        ("Hard Bop",       "jazz_hard_bop_full", "jazz_fusion"),
        ("Modal Jazz",     "jazz_modal_full",  "jazz_fusion"),
        ("Jazz Ballad",    "jazz_ballad_full", "jazz_fusion"),
    ]),
    ("Soul & Funk", "#a855f7", [
        ("Soul / Motown",  "soul_motown_full", "soul_motown_full"),
        ("Funk",           "funk_full_song",   "funk"),
        ("Disco",          "disco_full",       "disco"),
    ]),
    ("Hip-Hop & R&B", "#14b8a6", [
        ("Hip-Hop",        "hip_hop_full",     "hip_hop_90s"),
        ("90s Hip-Hop",    "hip_hop_90s",      "hip_hop_90s"),
        ("Trap",           "trap_dj",          "trap_dj"),
        ("2000s Rap",      "rap_2000s",        "rap_2000s"),
        ("90s R&B",        "rnb_90s",          "rnb_90s"),
    ]),
    ("Electronic", "#06b6d4", [
        ("EDM",            "edm_full_song",    "dance"),
        ("Dance",          "dance",            "dance"),
        ("Synthwave",      "synthwave",        "synthwave"),
    ]),
    ("Latin & World", "#22c55e", [
        ("Reggae",         "reggae_full",      "reggae_full"),
        ("Latin Pop",      "latin_pop",        "latin_pop"),
        ("Salsa",          "salsa",            "salsa"),
        ("Mambo",          "latin_mambo",      "latin_mambo"),
        ("Cumbia",         "latin_cumbia",     "latin_cumbia"),
        ("Reggaeton",      "reggaeton",        "reggaeton"),
        ("Flamenco",       "flamenco",         "flamenco"),
        ("Afrobeat",       "afrobeat",         "afrobeat"),
        ("Bhangra",        "bhangra",          "bhangra"),
        ("Bollywood",      "bollywood",        "bollywood"),
        ("Oud Ballad",     "oud_ballad",       "oud_ballad"),
        ("Gamelan",        "gamelan_ambient",  "gamelan_ambient"),
    ]),
    ("Cinematic & Classical", "#94a3b8", [
        ("Cinematic",      "cinematic_epic",   "cinematic_epic"),
        ("Heroic",         "cinematic_heroic", "cinematic_heroic"),
        ("Cinematic 6/8",  "cinematic_6_8",    "cinematic_6_8"),
        ("Holiday",        "holiday_cinematic", "holiday_cinematic"),
        ("Baroque",        "classical_baroque", "classical_baroque"),
        ("Waltz",          "classical_waltz",  "classical_waltz"),
        ("Romantic",       "classical_romantic", "classical_romantic"),
        ("Chiptune",       "game_chiptune",    "game_chiptune"),
        ("JRPG",           "game_jrpg",        "game_jrpg"),
        ("Adventure 6/8",  "game_adventure_6_8", "game_adventure_6_8"),
    ]),
]

# Presets intentionally NOT surfaced on the wheel (feature demos + a
# percussion-only layer that isn't a standalone song genre). They remain in
# STYLES so existing blocks still regenerate.
HIDDEN_PRESETS: frozenset[str] = frozenset({
    "pop_dynamic", "funk_dynamic", "rock_buildup", "jazz_trade_fours",
    "jazz_piano_full", "latin_percussion", "hip_hop_dj",
})


def genre_catalog() -> list[dict]:
    """The wheel-ready catalog: families (with colour + angle) each holding
    their genres, validated against STYLES. A genre's ``id`` is its song
    preset; ``section`` is the per-section feel preset."""
    from src.daw_integration.generic.styles import STYLES

    n = len(GENRE_FAMILIES)
    out: list[dict] = []
    for i, (family, color, genres) in enumerate(GENRE_FAMILIES):
        members = []
        for (name, song, section) in genres:
            if song not in STYLES:
                continue
            members.append({
                "id": song,
                "name": name,
                "section": section if section in STYLES else song,
            })
        if members:
            out.append({
                "family": family,
                "color": color,
                "angle": round(i * 360.0 / n, 2),   # wheel position, 12 o'clock = 0
                "genres": members,
            })
    return out


def section_feel(song_preset: str) -> str:
    """The lighter per-section preset for a song genre (falls back to itself)."""
    for _family, _color, genres in GENRE_FAMILIES:
        for (_name, song, section) in genres:
            if song == song_preset:
                return section
    return song_preset
