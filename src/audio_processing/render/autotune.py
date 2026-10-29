"""Per-sample fine tuning for sampled leads.

Some libraries' samples sit a few cents off their nominal pitch (a plucked
guitar string starts sharp; one trumpet note is 18 cents high). Two such
instruments in unison beat against each other and sound sour. Each sample's
pitch is measured once (YIN over 80–450 ms after its attack) against the
pitch its region says it is, and the renderer corrects every note by it.
Measurements are cached in ``<instruments>/.tuning.json``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MAX_CORRECTION = 35.0      # cents; anything bigger is a detection error, not tuning


class SampleTuner:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = Path(cache_path)
        self._lock = threading.Lock()
        try:
            self._cache: dict[str, float] = json.loads(self.cache_path.read_text())
        except Exception:
            self._cache = {}
        self._dirty = False

    def cents(self, path: Path, sample, keycenter: int) -> float:
        """How sharp (positive) the sample sounds versus ``keycenter``."""
        key = f"{path}|{keycenter}"
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        value = self._measure(sample, keycenter)
        with self._lock:
            self._cache[key] = value
            self._dirty = True
        return value

    @staticmethod
    def _measure(sample, keycenter: int) -> float:
        try:
            import librosa
            mono = sample.data.mean(axis=0)
            sr = sample.sample_rate
            peak = float(np.abs(mono).max())
            if peak <= 0:
                return 0.0
            onset = int(np.argmax(np.abs(mono) > 0.1 * peak))
            seg = mono[onset + int(0.08 * sr): onset + int(0.45 * sr)]
            if len(seg) < 4096:
                return 0.0
            target = librosa.midi_to_hz(keycenter)
            f = librosa.yin(seg, fmin=target * 2 ** (-5 / 12), fmax=target * 2 ** (5 / 12), sr=sr, frame_length=4096)
            c = float(np.median(1200 * np.log2(f / target)))
            return c if abs(c) <= MAX_CORRECTION else 0.0
        except Exception:
            logger.debug("autotune: measure failed", exc_info=True)
            return 0.0

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            try:
                self.cache_path.write_text(json.dumps(self._cache))
                self._dirty = False
            except OSError:
                logger.warning("autotune: can't write %s", self.cache_path)
