"""Per-preset section arrangement (feature B2).

Lets the UI ask for *which* sections to generate (intro/verse/chorus/
bridge/outro). We reuse the genre's natural arrangement (and bar lengths)
from ``song_composer._default_sections_for`` and just filter + renumber to
the chosen roles, so the result still iterates the exact section list
``compose_song`` already consumes.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("ai_music_studio.api.arrangement")

# Canonical musical order + sensible fallback bar-lengths for genres whose
# template doesn't define a given role.
SECTION_ORDER: tuple[str, ...] = ("intro", "verse", "chorus", "bridge", "outro")
_FALLBACK_BARS: dict[str, int] = {
    "intro": 4, "verse": 16, "chorus": 8, "bridge": 8, "outro": 4,
}


def _template_for(genre: str) -> list[dict]:
    try:
        from src.composition.song_composer import _default_sections_for
        return list(_default_sections_for(genre))
    except Exception:  # noqa: BLE001 — unknown genre / import hiccup → empty
        logger.warning("no section template for genre %r", genre)
        return []


def available_sections(genre: str) -> list[dict]:
    """Roles offerable in the UI for ``genre``: every canonical role, flagged
    with whether the genre's template defines it natively."""
    native = {s.get("role") for s in _template_for(genre)}
    return [{"role": r, "native": r in native} for r in SECTION_ORDER]


def build_sections(genre: str, roles: list[str]) -> list[dict]:
    """Contiguous ``{start_bar, end_bar, label, role}`` for the chosen roles
    in canonical order. Empty ``roles`` → the genre's full default
    arrangement. Bar-lengths/labels come from the template when present."""
    wanted = [r for r in SECTION_ORDER if r in set(roles)]
    template = _template_for(genre)

    if not wanted:
        # Full default arrangement (already contiguous) when nothing chosen.
        return template or _from_roles(list(SECTION_ORDER), {})

    by_role: dict[str, tuple[int, str]] = {}
    for s in template:
        r = s.get("role")
        if r and r not in by_role:
            bars = int(s["end_bar"]) - int(s["start_bar"]) + 1
            by_role[r] = (bars, s.get("label") or r.capitalize())
    return _from_roles(wanted, by_role)


def _from_roles(roles: list[str], by_role: dict[str, tuple[int, str]]) -> list[dict]:
    out: list[dict] = []
    cursor = 0
    for r in roles:
        bars, label = by_role.get(r, (_FALLBACK_BARS.get(r, 8), r.capitalize()))
        out.append({
            "start_bar": cursor,
            "end_bar": cursor + bars - 1,
            "label": label,
            "role": r,
        })
        cursor += bars
    return out
