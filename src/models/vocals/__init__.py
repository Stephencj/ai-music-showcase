"""AI vocals — sing the generated melody/harmony MIDI with lyrics.

Pluggable engines behind one interface:
  - ``RoughEngine``  : macOS ``say`` TTS pitch-corrected to the MIDI notes
                       (the MVP "rough demo" — local, near-zero deps).
  - (later) studio   : a DiffSinger-class local SVS for real singing.

See ``render_lead_vocal`` for the top-level entry point.
"""

from .engine import RoughEngine, VocalEngine  # noqa: F401
from .render import render_lead_vocal  # noqa: F401

__all__ = ["RoughEngine", "VocalEngine", "render_lead_vocal"]
