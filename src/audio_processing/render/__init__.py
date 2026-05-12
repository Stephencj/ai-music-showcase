"""High-quality MIDI → audio render pipeline.

Public entry points:

- :func:`render_to_audio` — orchestrate synthesis + effects + mix + master.
- :class:`FluidSynthRenderer` — render per-track stems via pyfluidsynth.
- :class:`EffectChainLibrary` — per-family pedalboard effect chains.
- :class:`Mixer` — sum stems with pan/gain into a stereo master.
- :func:`resolve_soundfont` — find a usable .sf2/.sf3 with fallbacks.

Typical use::

    from src.daw_integration.generic.midi_export import MidiExporter
    from src.audio_processing.render import render_to_audio

    midi = MidiExporter(...)  # build composition
    result = render_to_audio(
        midi,
        output_dir=Path("data/outputs/renders/song"),
        with_stems=True,
        master_preset="default",
    )
    print(result.mix_path, result.stem_paths)
"""

from .pipeline import RenderResult, render_to_audio
from .synth import FluidSynthRenderer
from .effects import EffectChainLibrary, MASTER_PRESETS
from .mix import Mixer
from .soundfont_resolver import (
    DEFAULT_SOUNDFONT_DIR,
    SoundfontNotFoundError,
    resolve_soundfont,
)

__all__ = [
    "DEFAULT_SOUNDFONT_DIR",
    "EffectChainLibrary",
    "FluidSynthRenderer",
    "MASTER_PRESETS",
    "Mixer",
    "RenderResult",
    "SoundfontNotFoundError",
    "render_to_audio",
    "resolve_soundfont",
]
