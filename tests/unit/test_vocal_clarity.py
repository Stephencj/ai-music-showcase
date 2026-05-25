"""Tests for the vocal-intelligibility toolkit shipped 2026-05-24:

  * ``apply_clarity`` levers (register fold, inter-word gap, de-melisma) and
    the density guard that neutralises clarity on fast/dense (rap) lines.
  * the editable phonetic layer (``to_phonetic`` / ``parse_phonetic`` →
    ``align_words_to_notes(pron=...)``).
  * the splice-repair word locator (``unclear_word_indices``).

All pure-logic (no audio render / no ASR), so they're deterministic and fast —
the render-quality claims are measured separately by ``tools.clarity_bench``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.vocals.lyrics import (  # noqa: E402
    align_words_to_notes, apply_clarity, parse_phonetic, to_phonetic,
)
from src.models.vocals.render import section_time_ranges  # noqa: E402
from src.models.vocals.repair import unclear_word_indices  # noqa: E402


def _seg(text, notes, start):
    return {"text": text, "notes": list(notes), "start": start}


class ClarityTransformTests(unittest.TestCase):
    def test_register_fold_caps_high_notes(self):
        segs = [_seg("hi", [(73, 0.4)], 0.0)]              # C#5, above ceiling 71
        out = apply_clarity(segs, register="fold", min_word_gap=0.0)
        self.assertEqual(out[0]["notes"][0][0], 61)        # folded down an octave
        # a note already under the ceiling is untouched
        segs = [_seg("lo", [(60, 0.4)], 0.0)]
        out = apply_clarity(segs, register="fold", min_word_gap=0.0)
        self.assertEqual(out[0]["notes"][0][0], 60)

    def test_register_shift_preserves_contour(self):
        segs = [_seg("a", [(73, 0.4)], 0.0), _seg("b", [(69, 0.4)], 0.4)]
        out = apply_clarity(segs, register="shift", min_word_gap=0.0, demelisma=False)
        # whole line drops one octave so the 73 peak clears ceiling 71; the
        # interval between the two notes is preserved (contour intact)
        self.assertEqual(out[0]["notes"][0][0], 61)
        self.assertEqual(out[1]["notes"][0][0], 57)

    def test_inter_word_gap_trims_tail_not_onset(self):
        segs = [_seg("one", [(60, 0.4)], 0.0), _seg("two", [(60, 0.4)], 0.4)]
        out = apply_clarity(segs, register="off", min_word_gap=0.10, demelisma=False)
        self.assertAlmostEqual(out[0]["notes"][0][1], 0.30, places=6)  # 0.10 trimmed
        self.assertEqual(out[1]["start"], 0.4)                          # onset unmoved
        self.assertEqual(out[1]["notes"][0][1], 0.4)                    # last word kept

    def test_gap_never_shortens_below_floor(self):
        segs = [_seg("x", [(60, 0.12)], 0.0), _seg("y", [(60, 0.12)], 0.12)]
        out = apply_clarity(segs, register="off", min_word_gap=0.10, demelisma=False)
        self.assertGreaterEqual(out[0]["notes"][0][1], 0.08)

    def test_demelisma_merges_same_pitch_within_word(self):
        segs = [_seg("baby", [(60, 0.3), (60, 0.3), (62, 0.3)], 0.0)]
        out = apply_clarity(segs, register="off", min_word_gap=0.0, demelisma=True)
        self.assertEqual(out[0]["notes"], [(60, 0.6), (62, 0.3)])

    def test_density_guard_neutralises_clarity_on_fast_lines(self):
        # 0.15 s notes < min_sustain (0.18) → only the (harmless) register cap
        fast = [_seg("go", [(60, 0.15)], i * 0.15) for i in range(5)]
        out = apply_clarity(fast)            # defaults (gap + demelisma on)
        self.assertEqual([s["notes"] for s in out], [s["notes"] for s in fast])

    def test_does_not_mutate_input(self):
        segs = [_seg("hi", [(73, 0.4)], 0.0)]
        apply_clarity(segs)
        self.assertEqual(segs[0]["notes"], [(73, 0.4)])


class PhoneticLayerTests(unittest.TestCase):
    def test_to_phonetic_one_group_per_word(self):
        ph = to_phonetic("forever baby")
        self.assertEqual(ph.count("["), 2)
        self.assertRegex(ph, r"^\[[a-z ]+\] \[[a-z ]+\]$")

    def test_parse_round_trip(self):
        ph = to_phonetic("hello world")
        pron = parse_phonetic(ph)
        self.assertEqual(len(pron), 2)
        self.assertTrue(all(isinstance(p, list) and p for p in pron))

    def test_pron_attaches_to_segments(self):
        notes = [(60, 0.0, 0.4), (62, 0.4, 0.8), (64, 0.8, 1.2)]
        segs = align_words_to_notes("forever", notes, pron=[["f", "er", "eh", "v", "er"]])
        self.assertEqual(segs[0]["phonemes"], ["f", "er", "eh", "v", "er"])

    def test_pron_ignored_on_word_count_mismatch(self):
        notes = [(60, 0.0, 0.4), (62, 0.4, 0.8)]
        # two words, only one pron group → guard skips the override (no desync)
        segs = align_words_to_notes("hi there", notes, pron=[["hh", "ay"]])
        self.assertNotIn("phonemes", segs[0])


class SectionEngineRangeTests(unittest.TestCase):
    def test_inclusive_end_bar_to_open_time_range(self):
        # 104 bpm, 4/4 → barlen = 4*60/104 = 2.3077 s. "Intro 0–3" is 4 bars.
        ranges = section_time_ranges([(0, 3, "rough"), (4, 19, "studio")], 104.0, 4)
        self.assertEqual(len(ranges), 2)
        self.assertAlmostEqual(ranges[0][0], 0.0, places=4)
        self.assertAlmostEqual(ranges[0][1], 4 * (4 * 60 / 104), places=4)   # 0..bar4
        self.assertEqual(ranges[0][2], "rough")
        # verse starts exactly where intro ends (contiguous, no gap/overlap)
        self.assertAlmostEqual(ranges[1][0], ranges[0][1], places=6)
        self.assertAlmostEqual(ranges[1][1], 20 * (4 * 60 / 104), places=4)  # ..bar20

    def test_three_four_meter(self):
        ranges = section_time_ranges([(0, 1, "studio")], 120.0, 3)  # barlen=1.5s, 2 bars
        self.assertAlmostEqual(ranges[0][1], 3.0, places=6)

    def test_empty(self):
        self.assertEqual(section_time_ranges([], 120.0, 4), [])


class RepairLocatorTests(unittest.TestCase):
    def test_flags_substitutions_and_deletions(self):
        ref = ["broke", "my", "heart", "baby", "now"]
        heard = "broke my hard now"          # heart→hard (sub), baby dropped (del)
        idxs = unclear_word_indices(ref, heard)
        self.assertIn(2, idxs)               # heart
        self.assertIn(3, idxs)               # baby
        self.assertNotIn(0, idxs)            # broke matched
        self.assertNotIn(1, idxs)            # my matched

    def test_perfect_transcript_flags_nothing(self):
        ref = ["clear", "as", "day"]
        self.assertEqual(unclear_word_indices(ref, "clear as day"), [])


if __name__ == "__main__":
    unittest.main()
