"""Tests for vocal pitch-correction (Auto-Tune to the composed melody / key).

``retune_f0`` is pure (no audio) and gets the bulk of the coverage; one WORLD
round-trip on a harmonic signal confirms the full path actually moves pitch to
the target (a pure sine is degenerate for WORLD, so we use a sawtooth)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.vocals.autotune import (  # noqa: E402
    _hz_to_midi, _midi_to_hz, autotune, retune_f0,
)


class RetuneF0Tests(unittest.TestCase):
    def test_unvoiced_frames_pass_through(self):
        f0 = np.array([0.0, 200.0, 0.0])
        t = np.array([0.0, 0.1, 0.2])
        out = retune_f0(f0, t, targets=[(60, 0.0, 1.0)], mode="hard")
        self.assertEqual(out[0], 0.0)
        self.assertEqual(out[2], 0.0)

    def test_hard_snap_to_guide_note(self):
        out = retune_f0(np.array([200.0, 210.0]), np.array([0.1, 0.2]),
                        targets=[(60, 0.0, 1.0)], mode="hard")
        self.assertAlmostEqual(out[0], _midi_to_hz(60), places=1)
        self.assertAlmostEqual(out[1], _midi_to_hz(60), places=1)

    def test_rest_frames_left_alone(self):
        # t=0.5 is past the only note (a rest) → untouched
        out = retune_f0(np.array([330.0]), np.array([0.5]),
                        targets=[(60, 0.0, 0.25)], mode="hard")
        self.assertEqual(out[0], 330.0)

    def test_snap_to_key(self):
        # 263 Hz is just above C4 (261.6); nearest C-major note is C4
        out = retune_f0(np.array([263.0]), np.array([0.0]),
                        key="C", scale="major", mode="hard")
        self.assertAlmostEqual(out[0], _midi_to_hz(60), places=1)

    def test_natural_blend_is_between(self):
        out = retune_f0(np.array([200.0]), np.array([0.0]),
                        targets=[(60, 0.0, 1.0)], mode="natural", strength=0.5)
        self.assertGreater(out[0], 200.0)
        self.assertLess(out[0], _midi_to_hz(60))

    def test_midi_hz_roundtrip(self):
        self.assertAlmostEqual(_hz_to_midi(_midi_to_hz(69)), 69.0, places=6)
        self.assertAlmostEqual(_midi_to_hz(69), 440.0, places=3)


class AutotuneRoundTripTests(unittest.TestCase):
    def test_harmonic_signal_snaps_to_target(self):
        from scipy import signal as sps
        import pyworld as pw
        sr = 22050
        dur = 1.2
        x = (0.3 * sps.sawtooth(2 * np.pi * 220.0 * np.arange(int(sr * dur)) / sr)
             ).astype(np.float32)
        y = autotune(x, sr, targets=[(60, 0.0, dur)], mode="hard")  # → C4 261.6
        f0, _ = pw.harvest(y.astype(np.float64), sr, frame_period=5.0)
        voiced = f0[f0 > 0]
        self.assertGreater(len(voiced), 0)
        self.assertAlmostEqual(float(np.median(voiced)), _midi_to_hz(60), delta=8.0)


if __name__ == "__main__":
    unittest.main()
