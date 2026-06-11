"""Per-track producer mix layer — fader/mute/EQ/comp/FX in the render pipeline."""

import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.audio_processing.render.mix import _track_board, _apply_gain_db


class TrackBoardTests(unittest.TestCase):
    def test_empty_settings_make_empty_board(self):
        self.assertEqual(len(_track_board({})), 0)
        self.assertEqual(len(_track_board({"eq": {"low_db": 0}, "comp": {"ratio": 1}})), 0)

    def test_each_control_adds_a_plugin(self):
        import pedalboard as pdb
        b = _track_board({
            "eq": {"low_db": 3, "mid_db": -2, "high_db": 4},   # 3 filters
            "comp": {"ratio": 3},                               # 1 compressor
            "fx": {"reverb": 0.5, "delay": 0.3, "chorus": 0.2, "distortion": 0.4},  # 4 fx
        })
        self.assertEqual(len(b), 8)
        kinds = [type(p).__name__ for p in b]
        for want in ("Compressor", "Reverb", "Delay", "Chorus", "Distortion"):
            self.assertIn(want, kinds)
        # signal order: dynamics/tone before time-based fx (reverb last)
        self.assertEqual(kinds[-1], "Reverb")
        _ = pdb  # imported only to assert availability

    def test_board_processes_audio(self):
        b = _track_board({"fx": {"reverb": 0.6}, "eq": {"high_db": 6}})
        audio = np.random.randn(2, 4096).astype(np.float32) * 0.1
        out = np.asarray(b(audio, sample_rate=44100), dtype=np.float32)
        self.assertEqual(out.shape[0], 2)
        self.assertTrue(np.isfinite(out).all())

    def test_gain_db(self):
        a = np.ones((2, 10), dtype=np.float32)
        louder = _apply_gain_db(a, 6.0)
        self.assertAlmostEqual(float(louder[0, 0]), 10 ** (6 / 20), places=4)


if __name__ == "__main__":
    unittest.main()
