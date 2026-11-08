"""Integrated loudness (ITU-R BS.1770 / EBU R128, in LUFS) and normalising to it.

Background music for a video sits far below a mastered track (about −23 to
−28 LUFS against −12 to −14), so a score can be rendered at a set loudness.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter


def _k_weighting(sample_rate: int):
    """The two BS.1770 pre-filters (high shelf + high pass) for ``sample_rate``."""
    # High shelf (head effect).
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / sample_rate)
    vh = 10 ** (g / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    b1 = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a1 = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    # High pass (RLB).
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sample_rate)
    a0 = 1 + k / q + k * k
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return (b1, a1), (b2, a2)


def integrated_lufs(audio: np.ndarray, sample_rate: int) -> float:
    """Integrated loudness of ``(channels, N)`` audio, gated per BS.1770."""
    x = np.atleast_2d(np.asarray(audio, dtype=np.float64))
    (b1, a1), (b2, a2) = _k_weighting(sample_rate)
    y = lfilter(b2, a2, lfilter(b1, a1, x, axis=1), axis=1)
    block, hop = int(0.4 * sample_rate), int(0.1 * sample_rate)
    if y.shape[1] < block:
        return -70.0
    starts = range(0, y.shape[1] - block + 1, hop)
    power = np.array([np.sum(np.mean(y[:, s:s + block] ** 2, axis=1)) for s in starts])
    loud = -0.691 + 10 * np.log10(power + 1e-12)
    gated = power[loud > -70.0]
    if not gated.size:
        return -70.0
    relative = -0.691 + 10 * np.log10(gated.mean()) - 10.0
    final = power[(loud > -70.0) & (loud > relative)]
    return float(-0.691 + 10 * np.log10(final.mean() + 1e-12))


def normalize(audio: np.ndarray, sample_rate: int, target_lufs: float, *, peak_ceiling_db: float = -1.0) -> tuple[np.ndarray, float]:
    """Scale to ``target_lufs`` (never pushing peaks past the ceiling). Returns (audio, gain dB)."""
    gain_db = target_lufs - integrated_lufs(audio, sample_rate)
    peak = float(np.abs(audio).max()) or 1.0
    max_gain_db = peak_ceiling_db - 20 * math.log10(peak)
    gain_db = min(gain_db, max_gain_db)
    return (audio * (10 ** (gain_db / 20))).astype(audio.dtype), gain_db


def level(audio: np.ndarray, sample_rate: int, target_lufs: float, *, peak_ceiling_db: float = -1.0,
          max_limit_db: float = 4.0) -> tuple[np.ndarray, float]:
    """Like :func:`normalize`, but when the peaks would stop the mix short of
    ``target_lufs`` (a peaky piano), a gentle look-ahead-free limiter takes up
    to ``max_limit_db`` off the loudest transients so the mix still reaches
    the target. Returns (audio, gain dB)."""
    out, gain = normalize(audio, sample_rate, target_lufs, peak_ceiling_db=peak_ceiling_db)
    short = target_lufs - integrated_lufs(out, sample_rate)
    if short <= 0.2:
        return out, gain
    import pedalboard as pdb
    push = min(short + 0.3, max_limit_db)
    board = pdb.Pedalboard([pdb.Gain(gain_db=push),
                            pdb.Limiter(threshold_db=peak_ceiling_db - 0.3, release_ms=150.0)])
    limited = np.asarray(board(out.astype(np.float32), sample_rate=sample_rate), dtype=np.float32)
    final, extra = normalize(limited, sample_rate, target_lufs, peak_ceiling_db=peak_ceiling_db)
    return final.astype(audio.dtype), gain + push + extra
