"""Mix per-track stems into a stereo bus, then apply the master chain.

Per-family defaults set pan + relative gain. Drums and bass center, chords
slightly wide, melody/lead off-center, pad wide. Final mix is normalized
to ~-1 dBFS peak before the master chain — the master limiter then sets
final headroom.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .effects import (
    EffectChainLibrary,
    apply_chain,
    classify_family,
)
from .synth import RenderedStems, TrackStem

logger = logging.getLogger(__name__)


# Per-family mix defaults. ``pan`` ∈ [-1, 1] (-1=L, +1=R). ``gain_db`` is
# applied before panning. These are conservative starting points — users
# can later override.
@dataclass(frozen=True)
class MixDefaults:
    pan: float
    gain_db: float


_FAMILY_MIX: dict[str, MixDefaults] = {
    "drums": MixDefaults(pan=0.0, gain_db=0.0),
    "bass": MixDefaults(pan=0.0, gain_db=-1.0),
    "chords": MixDefaults(pan=-0.10, gain_db=-3.5),
    "pad": MixDefaults(pan=0.10, gain_db=-5.0),
    "melody": MixDefaults(pan=0.15, gain_db=-2.5),
    "lead": MixDefaults(pan=-0.15, gain_db=-2.5),
    "extra": MixDefaults(pan=0.0, gain_db=-3.0),
}


@dataclass
class ProcessedStem:
    """Stem after per-family effects + pan/gain, ready to sum."""
    name: str
    family: str
    audio: np.ndarray            # (2, N) stereo float32
    sample_rate: int


class Mixer:
    """Process stems through per-family effect chains, sum, master."""

    def __init__(
        self,
        library: Optional[EffectChainLibrary] = None,
        *,
        family_mix: Optional[dict[str, MixDefaults]] = None,
    ):
        self.library = library or EffectChainLibrary()
        self.family_mix = family_mix or _FAMILY_MIX

    # -- single-stem path --------------------------------------------------

    def process_stem(self, stem: TrackStem) -> ProcessedStem:
        family = classify_family(stem.name, stem.program, stem.is_drum)
        chain = self.library.for_family(family)
        mono_processed = apply_chain(chain, stem.audio, stem.sample_rate)

        # Pedalboard chains may emit stereo (Reverb etc.) — normalize shape.
        if mono_processed.ndim == 1:
            stereo = _mono_to_stereo(mono_processed)
        elif mono_processed.shape[0] == 2:
            stereo = mono_processed
        else:
            stereo = mono_processed.T  # (samples, 2) → (2, samples)

        defaults = self.family_mix.get(family, _FAMILY_MIX["extra"])
        stereo = _apply_gain_db(stereo, defaults.gain_db)
        stereo = _apply_pan(stereo, defaults.pan)

        return ProcessedStem(
            name=stem.name,
            family=family,
            audio=stereo.astype(np.float32, copy=False),
            sample_rate=stem.sample_rate,
        )

    # -- full mix ----------------------------------------------------------

    def mix(
        self,
        stems: RenderedStems,
        *,
        master_preset: str = "default",
    ) -> tuple[np.ndarray, list[ProcessedStem]]:
        """Process all stems, sum to a stereo bus, run the master chain.

        Returns ``(mix, processed_stems)`` where ``mix`` is shape
        ``(2, N)`` float32 at ``stems.sample_rate``.
        """
        processed = [self.process_stem(s) for s in stems.stems]

        if not processed:
            raise ValueError("No stems to mix.")

        n = max(p.audio.shape[1] for p in processed)
        bus = np.zeros((2, n), dtype=np.float32)
        for p in processed:
            audio = p.audio
            if audio.shape[1] < n:
                pad = np.zeros((2, n - audio.shape[1]), dtype=np.float32)
                audio = np.concatenate([audio, pad], axis=1)
            bus += audio

        # Pre-master normalization — gives the master chain a consistent
        # input level regardless of how many stems were summed.
        peak = float(np.max(np.abs(bus)))
        if peak > 0:
            bus *= 0.89 / peak  # ~-1 dBFS

        master = self.library.master(master_preset)
        mastered = apply_chain(master, bus, stems.sample_rate)
        if mastered.ndim == 1:
            mastered = _mono_to_stereo(mastered)
        elif mastered.shape[0] != 2 and mastered.shape[1] == 2:
            mastered = mastered.T

        return mastered.astype(np.float32, copy=False), processed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mono_to_stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono], axis=0)


def _apply_gain_db(stereo: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db == 0.0:
        return stereo
    return stereo * (10.0 ** (gain_db / 20.0))


def _apply_pan(stereo: np.ndarray, pan: float) -> np.ndarray:
    """Equal-power pan. ``pan`` ∈ [-1, 1]."""
    if pan == 0.0:
        return stereo
    pan = float(np.clip(pan, -1.0, 1.0))
    angle = (pan + 1.0) * (np.pi / 4.0)   # 0..π/2
    left_gain = float(np.cos(angle))
    right_gain = float(np.sin(angle))
    out = stereo.copy()
    out[0] *= left_gain * np.sqrt(2.0)
    out[1] *= right_gain * np.sqrt(2.0)
    return out
