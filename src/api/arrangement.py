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
SECTION_ORDER: tuple[str, ...] = (
    "intro", "buildup", "verse", "prechorus", "chorus", "drop",
    "bridge", "breakdown", "solo", "outro")
_FALLBACK_BARS: dict[str, int] = {
    "intro": 4, "buildup": 4, "verse": 16, "prechorus": 4, "chorus": 8,
    "drop": 8, "bridge": 8, "breakdown": 8, "solo": 8, "outro": 4,
}
# Display labels where the capitalised role isn't right.
_ROLE_LABELS: dict[str, str] = {"prechorus": "Pre-chorus"}


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


def build_sections(genre: str, roles: list[str],
                   section_presets: dict[str, str] | None = None,
                   section_overrides: dict[str, dict] | None = None) -> list[dict]:
    """Contiguous ``{start_bar, end_bar, label, role}`` for the chosen roles
    in canonical order. Empty ``roles`` → the genre's full default
    arrangement. Bar-lengths/labels come from the template when present.

    ``section_presets`` (optional) maps a role → preset id, attaching a
    ``preset_id`` to every section of that role so ``compose_song`` renders it
    in that preset's feel (multi-preset songs). Roles absent from the map use
    the song genre."""
    wanted = [r for r in SECTION_ORDER if r in set(roles)]
    template = _template_for(genre)
    template_roles = {s.get("role") for s in template}

    # Keep the genre's FULL arrangement — with its repeated verses/choruses,
    # i.e. its real (~3-minute) length — when nothing is chosen OR the caller
    # kept exactly the genre's native sections (the generate UI's default
    # selects every native role). Collapsing to one-of-each-role here is what
    # silently halved a "full song" (pop_full_song 80 → 48 bars) and starved
    # the vocal line/lyric of phrases. A strict subset still builds a reduced
    # custom arrangement below.
    if template and (not wanted or set(wanted) == template_roles):
        secs = [dict(s) for s in template]
    elif not wanted:
        # No template (unknown genre) and nothing chosen → generic sketch.
        secs = _from_roles(list(SECTION_ORDER), {})
    else:
        by_role: dict[str, tuple[int, str]] = {}
        for s in template:
            r = s.get("role")
            if r and r not in by_role:
                bars = int(s["end_bar"]) - int(s["start_bar"]) + 1
                by_role[r] = (bars, s.get("label") or r.capitalize())
        secs = _from_roles(wanted, by_role)

    _attach_presets(secs, genre, section_presets)
    _attach_overrides(secs, section_overrides)
    return secs


def _attach_presets(secs: list[dict], genre: str,
                    section_presets: dict[str, str] | None) -> list[dict]:
    """Tag each section with a ``preset_id`` from the role→preset map. A value
    equal to the song genre (or empty/unknown) is dropped so the section just
    inherits the global preset."""
    sp = section_presets or {}
    for s in secs:
        pid = (sp.get(s.get("role")) or "").strip()
        if pid and pid != genre:
            s["preset_id"] = pid
    return secs


def _attach_overrides(secs: list[dict],
                      section_overrides: dict[str, dict] | None) -> list[dict]:
    """Apply per-role playing-style overrides onto each section: ``knobs``
    (merged into the section's knobs), ``energy`` (the section's level), and
    ``feature_lead`` (force the solo/lead into it)."""
    ov = section_overrides or {}
    for s in secs:
        o = ov.get(s.get("role"))
        if not isinstance(o, dict):
            continue
        if isinstance(o.get("knobs"), dict) and o["knobs"]:
            s["knobs"] = dict(o["knobs"])
        if o.get("energy") is not None:
            try:
                s["energy"] = max(0.4, min(1.5, float(o["energy"])))
            except (TypeError, ValueError):
                pass
        if o.get("feature_lead"):
            s["feature_lead"] = True
        # Per-section key / mode / tempo (full flexibility).
        if o.get("key"):
            s["key"] = str(o["key"])
        if o.get("scale"):
            s["scale"] = str(o["scale"])
        if o.get("tempo") is not None:
            try:
                s["tempo"] = max(40.0, min(260.0, float(o["tempo"])))
            except (TypeError, ValueError):
                pass
    return secs


def _from_roles(roles: list[str], by_role: dict[str, tuple[int, str]]) -> list[dict]:
    out: list[dict] = []
    cursor = 0
    for r in roles:
        bars, label = by_role.get(
            r, (_FALLBACK_BARS.get(r, 8), _ROLE_LABELS.get(r, r.capitalize())))
        out.append({
            "start_bar": cursor,
            "end_bar": cursor + bars - 1,
            "label": label,
            "role": r,
        })
        cursor += bars
    return out
