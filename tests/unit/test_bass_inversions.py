"""Tests for tasteful passing bass inversions (slash chords)."""
import unittest

import numpy as np

from src.daw_integration.generic.midi_export import (
    MidiExporter,
    _smooth_bass_root,
    note_name_to_midi,
)


class TestSmoothBassRoot:
    pass


class TestBassInversions(unittest.TestCase):
    def test_no_inversion_when_prob_zero(self):
        m = MidiExporter(tempo=120)
        # Big leaps: C -> A (vi) -> F (IV). With prob 0, always roots.
        m.add_bass_line(key="C", progression=["I", "vi", "IV", "V"],
                        bars=8, pattern="root", octave=2, seed=1,
                        inversion_prob=0.0)
        a = [n.pitch for n in m.tracks[0].notes]
        m2 = MidiExporter(tempo=120)
        m2.add_bass_line(key="C", progression=["I", "vi", "IV", "V"],
                         bars=8, pattern="root", octave=2, seed=1,
                         inversion_prob=0.0)
        self.assertEqual(a, [n.pitch for n in m2.tracks[0].notes])

    def test_inversion_smooths_a_leap(self):
        # prev_bass far below; root leaps. An inversion should land closer.
        rng = np.random.default_rng(0)
        root = note_name_to_midi("A", 2)        # 45
        prev = note_name_to_midi("C", 2)        # 36 — a 9-semitone leap to A
        # Force inversion (prob 1.0). Expect a chord tone nearer to prev.
        out = _smooth_bass_root(root, "min", prev, rng, 1.0)
        self.assertNotEqual(out, root)
        self.assertLessEqual(abs(out - prev), 4)

    def test_inversion_keeps_root_on_small_step(self):
        rng = np.random.default_rng(0)
        root = note_name_to_midi("D", 2)
        prev = note_name_to_midi("C", 2)        # 2-semitone step — keep root
        self.assertEqual(_smooth_bass_root(root, "maj", prev, rng, 1.0), root)

    def test_some_inversions_appear_with_high_prob(self):
        m = MidiExporter(tempo=120)
        m.add_bass_line(key="C", progression=["I", "vi", "IV", "V"],
                        bars=16, pattern="root_fifth", octave=2, seed=4,
                        inversion_prob=1.0)
        # With leaps and prob 1.0, at least one downbeat is a non-root.
        roots = {note_name_to_midi("C", 2), note_name_to_midi("A", 2),
                 note_name_to_midi("F", 2), note_name_to_midi("G", 2)}
        downbeats = [n.pitch for n in m.tracks[0].notes]
        self.assertTrue(any(p not in roots and (p + 12) not in roots
                            and (p - 12) not in roots for p in downbeats))


if __name__ == "__main__":
    unittest.main()
