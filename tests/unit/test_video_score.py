"""Scoring a video chapter by chapter (src/api/video_score.py)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

import src.composition  # noqa: F401
from src.api.video_score import (Chapter, choose_bars, compose_score, curate_hits, fit_to_length,
                                 gate_stops, plan_segments)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.chapters = [
            Chapter(start=0.0, card=3.0, roles=("verse",)),
            Chapter(start=13.1, card=3.2, roles=("verse", "chorus")),
            Chapter(start=40.0, card=3.2, roles=("bridge",), key="F"),
            Chapter(start=55.3, roles=("outro",)),
        ]
        self.plans = plan_segments(self.chapters, 60.0, 158.0)

    def test_every_chapter_is_whole_bars_and_lands_near_its_cut(self):
        from src.api.video_score import EARLY_SLACK, LATE_SLACK
        for p in self.plans:
            self.assertAlmostEqual(p.bars * 240.0 / p.tempo, p.end - p.start, places=6)
        for a, b in zip(self.plans, self.plans[1:]):
            self.assertAlmostEqual(a.end, b.start)                          # continuous music
        self.assertEqual(self.plans[0].start, 0.0)
        for p, ch in zip(self.plans[1:], self.chapters[1:]):
            self.assertTrue(-EARLY_SLACK - 0.03 <= p.start - ch.start <= LATE_SLACK + 0.03, (p.start, ch.start))
        self.assertLessEqual(self.plans[-1].end, 60.0 + 1e-6)              # the tail may ring out

    def test_slow_tempo_stays_steady(self):
        starts = [0.0, 13.1, 29.8, 45.1, 63.1, 80.6, 100.7]
        plans = plan_segments([Chapter(s) for s in starts], 120.0, 89.0)
        tempos = [p.tempo for p in plans]
        self.assertLessEqual(max(abs(a - b) for a, b in zip(tempos, tempos[1:])), 4.0)

    def test_the_tail_keeps_the_previous_tempo(self):
        plans = plan_segments([Chapter(0.0), Chapter(20.0), Chapter(40.0, roles=("outro",))], 46.1, 145.0)
        self.assertAlmostEqual(plans[-1].tempo, plans[-2].tempo)
        self.assertLessEqual(plans[-1].end, 46.1 + 1e-6)

    def test_tempos_stay_near_the_base_and_close_to_each_other(self):
        tempos = [p.tempo for p in self.plans]
        self.assertTrue(all(abs(t / 158.0 - 1) <= 0.08 for t in tempos), tempos)

    def test_sections_cover_the_chapter_title_card_first(self):
        p = self.plans[1]
        roles = [s["role"] for s in p.sections]
        self.assertEqual(roles, ["verse", "chorus"])                     # later chapters flow straight in
        first = self.plans[0]
        self.assertEqual(first.sections[0]["role"], "intro")             # only the opening gets an intro
        self.assertEqual(first.sections[0]["end_bar"] - first.sections[0]["start_bar"] + 1, 2)   # 3 s ≈ 2 bars
        self.assertEqual(p.sections[-1]["end_bar"], p.bars - 1)
        self.assertTrue(all(s.get("key") == "F" for s in self.plans[2].sections))

    def test_choose_bars_prefers_smooth_tempos(self):
        lengths = [12.0, 12.4, 11.8]
        bars = choose_bars(lengths, 158.0)
        tempos = [240 * n / l for n, l in zip(bars, lengths)]
        self.assertLess(max(abs(a - b) for a, b in zip(tempos, tempos[1:])), 12.0)


class CurateTest(unittest.TestCase):
    def test_curation(self):
        starts = [0.0, 20.0]
        hits = [0.0, 3.0, 6.5, 8.0, 12.0, 20.5, 24.0, 27.5]
        kept = curate_hits(hits, starts, min_gap=3.0)
        # 0.0/20.5 sit on chapter changes; 3.0 and 24.0 are each chapter's first
        # popup; 8.0 is too close to 6.5.
        self.assertEqual(kept, [6.5, 12.0, 27.5])

    def test_explicit_intro(self):
        plans = plan_segments([Chapter(0.0, card=3.0), Chapter(12.0, card=3.0, intro=True)], 24.0, 158.0)
        self.assertEqual(plans[1].sections[0]["role"], "intro")


class ComposeTest(unittest.TestCase):
    def test_groove_hits_land_on_the_next_beat_without_stopping_the_band(self):
        chapters = [Chapter(start=0.0, roles=("verse",)), Chapter(start=10.0, roles=("chorus",))]
        midi, plans, _ = compose_score(chapters, duration=20.0, hits=[14.2], curate=False)
        beat = 60.0 / plans[1].tempo
        grid = beat if beat <= 0.45 else beat / 2
        start = plans[1].start
        hit = start + np.ceil((14.2 - start - 0.03) / grid) * grid
        tracks = {t.name: t for t in midi.tracks}
        trumpet = [n.start for n in tracks["Trumpet"].notes]
        self.assertTrue(any(abs(t - hit) < 0.02 for t in trumpet))
        self.assertGreaterEqual(hit, 14.2 - 0.03)                         # never early
        drums_before = [n for n in tracks["Drum kit"].notes if hit - 2 * beat / 4 - 0.01 <= n.start < hit - 0.02]
        self.assertTrue(drums_before)                                     # the groove keeps going into it

    def test_a_strings_opening_plays_at_full_energy(self):
        chapters = [Chapter(start=0.0, roles=("verse",), card=6.0)]
        quiet, _, _ = compose_score(chapters, duration=16.0, hits=[], curate=False, arrangement="hits_only,soar",
                                    extra_instruments=["string_section"])
        loud, _, _ = compose_score(chapters, duration=16.0, hits=[], curate=False,
                                   arrangement="hits_only,soar,string_intro", extra_instruments=["string_section"])
        first = [n for n in {t.name: t for t in loud.tracks}["String Section"].notes if n.start < 0.05]
        self.assertTrue(first)
        self.assertGreaterEqual(min(n.velocity for n in first), 95)
        self.assertNotIn("String Section", {t.name for t in quiet.tracks if any(n.start < 0.05 for n in t.notes)})

    def test_a_chapter_can_carry_its_own_arrangement(self):
        chapters = [Chapter(start=0.0, roles=("verse",), arrangement="hits_only,calm"),
                    Chapter(start=10.0, roles=("verse",))]
        midi, plans, _ = compose_score(chapters, duration=20.0, hits=[], curate=False, arrangement="pocket_drums")
        kit = {t.name: t for t in midi.tracks}["Drum kit"].notes
        first = [n for n in kit if n.start < plans[1].start - 0.05]
        second = [n for n in kit if n.start >= plans[1].start]
        self.assertFalse([n for n in first if n.pitch == 46])                         # calm: no open hats
        self.assertTrue([n for n in second if n.pitch == 46])                         # pocket: an open hat a phrase

    def test_merged_score_lands_chapters_and_hits_in_video_time(self):
        chapters = [Chapter(start=0.0, card=3.0, roles=("verse",), lead="synth_lead"),
                    Chapter(start=10.0, card=3.0, roles=("chorus",), lead="lead_guitar")]
        midi, plans, _ = compose_score(chapters, duration=20.0, hits=[10.0, 14.2], hit_style="punch",
                                       curate=False)
        tracks = {t.name: t for t in midi.tracks}
        self.assertIn("Synth Lead", tracks)
        self.assertIn("Lead Guitar", tracks)
        guitar = [n.start for n in tracks["Lead Guitar"].notes]
        lead = [n.start for n in tracks["Synth Lead"].notes]
        ch2 = plans[1].start                                            # within the slack of 10.0
        self.assertTrue(abs(ch2 - 10.0) <= 0.55)
        self.assertTrue(guitar and min(guitar) >= ch2 - 0.02)            # the guitar takes chapter 2
        self.assertTrue(lead and max(lead) < ch2)
        crash = [n.start for n in tracks["Drum kit"].notes if n.pitch == 49]
        self.assertTrue(any(abs(t - 10.0) <= 60.0 / plans[1].tempo / 4 / 2 + 0.03 for t in crash))  # the hit
        step = 60.0 / plans[1].tempo / 4
        self.assertTrue(any(abs(t - 14.2) <= step / 2 + 0.01 for t in crash))   # a caption hit, snapped

    def test_gate_stops_silences_windows_with_short_fades(self):
        sr = 1000
        a = np.ones((2, 3000), dtype=np.float32)
        out = gate_stops(a, sr, [(1.0, 1.2)], fade_out=0.01, fade_in=0.01)
        self.assertEqual(float(out[:, 1000:1200].max()), 0.0)
        self.assertEqual(float(out[0, 980]), 1.0)                         # untouched before the fade
        self.assertTrue(0.0 < float(out[0, 995]) < 1.0)                    # fading out
        self.assertEqual(float(out[0, 1300]), 1.0)

    def test_explicit_sections_offset_and_stops(self):
        secs = [{"role": "intro", "bars": 1, "progression": ["iv7"]},
                {"role": "verse", "bars": 4, "progression": ["i7", "iv7", "i7", "VImaj7"]}]
        ch = [Chapter(start=0.0, key="Eb", sections=secs, intro=True)]
        plans = plan_segments(ch, 20.0, 89.0)
        self.assertEqual([s["role"] for s in plans[0].sections], ["intro", "verse"])
        self.assertEqual(plans[0].sections[1]["progression"], ["i7", "iv7", "i7", "VImaj7"])
        self.assertAlmostEqual(plans[0].tempo, 89.0)
        bar = 240 / 89.0
        midi, _, _ = compose_score(ch, duration=12.0, hits=[], genre="neo_soul_full", offset=-bar + 1.0,
                                   stops=[(5.0, 5.4)], curate=False)
        starts = [n.start for t in midi.tracks for n in t.notes]
        self.assertGreaterEqual(min(starts), 0.0)                          # the pickup is trimmed at 0
        self.assertFalse([s for s in starts if 5.0 + 0.01 <= s < 5.4 - 0.02])   # the band rests

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
