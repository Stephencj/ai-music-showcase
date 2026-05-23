"""AI vocals — sing the generated melody/harmony MIDI with lyrics.

Pluggable engines behind one interface:
  - ``RoughEngine``  : macOS ``say`` TTS pitch-corrected to the MIDI notes
                       (the MVP "rough demo" — local, near-zero deps).
  - (later) studio   : a DiffSinger-class local SVS for real singing.

See ``render_lead_vocal`` for the top-level entry point.
"""

from .engine import RoughEngine, VocalEngine  # noqa: F401
from .render import render_lead_vocal  # noqa: F401


def studio_available() -> bool:
    """True if the DiffSinger voicebank is present (lazy import)."""
    try:
        from .studio import available
        return available()
    except Exception:  # noqa: BLE001
        return False


def get_engine(name: str, voice: str = ""):
    """Resolve an engine by name, falling back to rough."""
    if name == "studio":
        from .studio import StudioEngine
        return StudioEngine(speaker=voice or "tiger_fresh")
    return RoughEngine(voice)


__all__ = ["RoughEngine", "VocalEngine", "render_lead_vocal", "studio_available", "get_engine"]
