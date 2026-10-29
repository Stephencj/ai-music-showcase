"""Synthesised brush sounds for a brush kit.

No free (CC0) brush-kit samples are available, so the two sounds that make
brushes brushes are synthesised and laid over the real kit's kick and soft
hi-hat foot: the *tap* (wires striking the head: a short band-passed noise
burst with a hint of drum body) and the *swish* (wires sweeping the head
through the beat: soft band-passed noise that swells and fades).

Drum-track notes on key 25 are taps and on key 24 swishes (both below the
kit's keymap); velocity sets the level.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from scipy.signal import butter, sosfilt

from .sfz import Note

BRUSH_SWISH = 24
BRUSH_TAP = 25


def _band(x: np.ndarray, lo: float, hi: float, sr: int, order: int = 2) -> np.ndarray:
    sos = butter(order, [lo / (sr / 2), min(hi / (sr / 2), 0.99)], btype="band", output="sos")
    return sosfilt(sos, x)


def render_brushes(notes: Iterable[Note], sample_rate: int = 44100, *, seed: int = 3,
                   tail: float = 0.5) -> np.ndarray:
    notes = [n for n in notes if n.pitch in (BRUSH_SWISH, BRUSH_TAP)]
    if not notes:
        return np.zeros((2, 0), dtype=np.float32)
    sr = sample_rate
    rng = np.random.default_rng(seed)
    total = int((max(n.end for n in notes) + tail) * sr)
    out = np.zeros((2, total))
    for n in notes:
        start = int(n.start * sr)
        if start >= total:
            continue
        vel = (n.velocity / 127.0) ** 1.4
        if n.pitch == BRUSH_TAP:
            length = min(int(0.16 * sr), total - start)
            t = np.arange(length) / sr
            env = (1 - np.exp(-t / 0.0015)) * np.exp(-t / 0.032)
            for ch in range(2):
                noise = _band(rng.standard_normal(length), 1800, 7500, sr)
                body = 0.35 * np.sin(2 * math.pi * 205 * t) * np.exp(-t / 0.035)
                out[ch, start:start + length] += (noise * 0.9 + body) * env * vel * 0.55
        else:
            length = min(max(int((n.end - n.start) * sr), int(0.1 * sr)), total - start)
            t = np.linspace(0.0, 1.0, length, endpoint=False)
            env = np.sin(math.pi * t) ** 1.5 * (0.85 + 0.15 * np.sin(2 * math.pi * 4.5 * t * (length / sr)))
            for ch, pan in enumerate((0.9, 1.1)):
                noise = _band(rng.standard_normal(length), 2500, 9000, sr)
                out[ch, start:start + length] += noise * env * vel * 0.16 * pan
    return out.astype(np.float32)
