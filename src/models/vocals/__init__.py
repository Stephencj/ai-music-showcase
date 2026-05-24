"""AI vocals — sing the generated melody/harmony MIDI with lyrics.

Pluggable engines behind one interface:
  - ``RoughEngine``  : macOS ``say`` TTS pitch-corrected to the MIDI notes
                       (the MVP "rough demo" — local, near-zero deps).
  - (later) studio   : a DiffSinger-class local SVS for real singing.

See ``render_lead_vocal`` for the top-level entry point.
"""

from .engine import RoughEngine, VocalEngine  # noqa: F401
from .render import render_lead_vocal, render_vocals  # noqa: F401


def studio_available() -> bool:
    """True if the DiffSinger voicebank is present (lazy import)."""
    try:
        from .studio import available
        return available()
    except Exception:  # noqa: BLE001
        return False


_STUDIO_ENGINE = None  # cached: compiled ONNX sessions reused across jobs


def get_engine(name: str, voice: str = ""):
    """Resolve an engine by name, falling back to rough. The studio engine
    is cached (the ONNX models are costly to compile); we just swap the
    speaker per call."""
    if name == "studio":
        global _STUDIO_ENGINE
        from .studio import StudioEngine
        if _STUDIO_ENGINE is None:
            _STUDIO_ENGINE = StudioEngine(speaker=voice or "tiger_fresh")
        else:
            _STUDIO_ENGINE.set_speaker(voice or "tiger_fresh")
        return _STUDIO_ENGINE
    return RoughEngine(voice)


__all__ = ["RoughEngine", "VocalEngine", "render_lead_vocal", "studio_available", "get_engine"]
