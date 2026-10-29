"""Integrated loudness (BS.1770) and normalising to a target."""

import unittest

import numpy as np

from src.audio_processing.render.loudness import integrated_lufs, normalize


class LoudnessTest(unittest.TestCase):
    sr = 48000

    def tone(self, dbfs, seconds=10, hz=997):
        t = np.arange(self.sr * seconds) / self.sr
        return np.vstack([np.sin(2 * np.pi * hz * t) * 10 ** (dbfs / 20)] * 2).astype(np.float32)

    def test_ebu_reference_tone(self):
        # EBU Tech 3341: a stereo 1 kHz sine at −23 dBFS reads −23 LUFS.
        self.assertAlmostEqual(integrated_lufs(self.tone(-23), self.sr), -23.0, delta=0.15)

    def test_gating_ignores_silence(self):
        quiet = np.concatenate([self.tone(-23, 5), np.zeros((2, self.sr * 5), np.float32)], axis=1)
        self.assertAlmostEqual(integrated_lufs(quiet, self.sr), -23.0, delta=0.2)

    def test_normalize_to_background_level(self):
        out, gain = normalize(self.tone(-10), self.sr, -25.0)
        self.assertAlmostEqual(integrated_lufs(out, self.sr), -25.0, delta=0.15)
        self.assertLess(gain, -14.0)

    def test_normalize_respects_the_peak_ceiling(self):
        out, _ = normalize(self.tone(-30), self.sr, -5.0, peak_ceiling_db=-1.0)
        self.assertLessEqual(20 * np.log10(np.abs(out).max()), -1.0 + 1e-3)


if __name__ == "__main__":
    unittest.main()
