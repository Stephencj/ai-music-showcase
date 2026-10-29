"""Scoring a video chapter by chapter (src/api/video_score.py)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

import src.composition  # noqa: F401
from src.api.video_score import Chapter, choose_bars, compose_score, fit_to_length, plan_segments


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.chapters = [
            Chapter(start=0.0, card=3.0, roles=("verse",)),
            Chapter(start=13.1, card=3.2, roles=("verse", "chorus")),
            Chapter(start=40.0, card=3.2, roles=("bridge",), key="F"),
            Chapter(start=55.3, roles=("outro",)),
        ]
        self.plans = plan_segments(self.chapters, 60.0, 158.0)

    def test_every_chapter_is_whole_bars_ending_on_the_next_chapter(self):
        for p in self.plans:
            self.assertAlmostEqual(p.bars * 240.0 / p.tempo, p.end - p.start, places=6)
        self.assertEqual([round(p.start, 3) for p in self.plans], [0.0, 13.1, 40.0, 55.3])
        self.assertAlmostEqual(self.plans[-1].end, 60.0)

    def test_tempos_stay_near_the_base_and_close_to_each_other(self):
        tempos = [p.tempo for p in self.plans]
        self.assertTrue(all(abs(t / 158.0 - 1) <= 0.08 for t in tempos), tempos)

    def test_sections_cover_the_chapter_title_card_first(self):
        p = self.plans[1]
        roles = [s["role"] for s in p.sections]
        self.assertEqual(roles, ["intro", "verse", "chorus"])
        self.assertEqual(p.sections[0]["end_bar"] - p.sections[0]["start_bar"] + 1, 2)   # 3.2 s ≈ 2 bars
        self.assertEqual(p.sections[-1]["end_bar"], p.bars - 1)
        self.assertTrue(all(s.get("key") == "F" for s in self.plans[2].sections))

    def test_choose_bars_prefers_smooth_tempos(self):
        lengths = [12.0, 12.4, 11.8]
        bars = choose_bars(lengths, 158.0)
        tempos = [240 * n / l for n, l in zip(bars, lengths)]
        self.assertLess(max(abs(a - b) for a, b in zip(tempos, tempos[1:])), 12.0)


class ComposeTest(unittest.TestCase):
    def test_merged_score_lands_chapters_and_hits_in_video_time(self):
        chapters = [Chapter(start=0.0, card=3.0, roles=("verse",), lead="synth_lead"),
                    Chapter(start=10.0, card=3.0, roles=("chorus",), lead="lead_guitar")]
        midi, plans = compose_score(chapters, duration=20.0, hits=[10.0, 14.2])
        tracks = {t.name: t for t in midi.tracks}
        self.assertIn("Synth Lead", tracks)
        self.assertIn("Lead Guitar", tracks)
        guitar = [n.start for n in tracks["Lead Guitar"].notes]
        lead = [n.start for n in tracks["Synth Lead"].notes]
        self.assertTrue(guitar and min(guitar) >= 10.0 - 0.02)          # the guitar takes chapter 2
        self.assertTrue(lead and max(lead) < 10.0)
        crash = [n.start for n in tracks["Drum kit"].notes if n.pitch == 49]
        self.assertTrue(any(abs(t - 10.0) < 0.02 for t in crash))       # the chapter's opening hit
        step = 60.0 / plans[1].tempo / 4
        self.assertTrue(any(abs(t - 14.2) <= step / 2 + 0.01 for t in crash))   # a caption hit, snapped

    def test_fit_to_length(self):
        sr = 1000
        a = np.ones((2, 1500), dtype=np.float32)
        out = fit_to_length(a, sr, 2.0, fade=0.1)
        self.assertEqual(out.shape, (2, 2000))
        self.assertEqual(float(out[0, -1]), 0.0)
        self.assertEqual(float(out[0, 1700]), 0.0)                       # padded
        self.assertEqual(fit_to_length(np.ones((2, 3000), dtype=np.float32), sr, 2.0).shape, (2, 2000))


if __name__ == "__main__":
    unittest.main()
