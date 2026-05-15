"""Section-role normalization.

The rhythm_overrides UI stores free-text labels ("Verse 1", "Chorus 2",
"Pre-chorus", "Drop 1") — useful for humans but unstable as a key into
the TechniqueBank. ``role_for_label`` collapses each label to a
canonical role token.
"""

from __future__ import annotations

import re

# The five canonical roles. Techniques in the bank declare which roles
# they're eligible for using these tokens.
SECTION_ROLES: tuple[str, ...] = (
    "intro",
    "verse",
    "chorus",
    "bridge",
    "outro",
)


# Lowercase keyword fragments → role. First match wins, so order
# matters: more specific phrases ("pre-chorus") come BEFORE bare
# substrings ("chorus"), and high-signal terms ("outro", "intro",
# "bridge") come BEFORE generic groove/vamp tokens so a label like
# "Outro vamp" resolves to "outro" rather than "verse".
_ROLE_KEYWORDS: tuple[tuple[str, str], ...] = (
    # Most-specific compound forms first.
    ("pre-chorus",     "verse"),
    ("pre chorus",     "verse"),
    ("prechorus",      "verse"),
    ("middle 8",       "bridge"),
    ("middle-8",       "bridge"),
    # Outro family.
    ("outro",          "outro"),
    ("fade",           "outro"),
    ("coda",           "outro"),
    ("ending",         "outro"),
    ("tag",            "outro"),
    ("fill",           "outro"),
    # Intro family.
    ("intro",          "intro"),
    ("buildup",        "intro"),
    ("build up",       "intro"),
    ("build",          "intro"),
    # Bridge family.
    ("bridge",         "bridge"),
    ("break",          "bridge"),
    ("breakdown",      "bridge"),
    ("solo",           "bridge"),
    # Chorus family.
    ("chorus",         "chorus"),
    ("hook",           "chorus"),
    ("refrain",        "chorus"),
    ("drop",           "chorus"),
    ("lift",           "chorus"),
    # Generic groove tokens — last so the more-specific labels win.
    ("verse",          "verse"),
    ("vamp",           "verse"),
    ("groove",         "verse"),
)


def role_for_label(label: str) -> str:
    """Normalise a free-text section label into one of ``SECTION_ROLES``.

    Examples::

        role_for_label("Verse 1")    == "verse"
        role_for_label("Pre-chorus") == "verse"
        role_for_label("Chorus 2")   == "chorus"
        role_for_label("Drop 1")     == "chorus"
        role_for_label("Buildup")    == "intro"
        role_for_label("Bridge")     == "bridge"
        role_for_label("Outro vamp") == "outro"
        role_for_label("")           == "verse"   # safest default

    Unknown labels default to ``"verse"`` because that's the cell with
    the broadest technique catalogue — a random song will still come
    out musical even when the label is gibberish.
    """
    if not label:
        return "verse"
    lo = label.strip().lower()
    # Strip trailing index ("Verse 1" → "verse").
    lo = re.sub(r"\s+\d+$", "", lo)
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in lo:
            return role
    return "verse"
