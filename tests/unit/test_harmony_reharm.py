"""Tests for reharmonization pacing strategies + genre-driven selection."""
import unittest

import numpy as np

from src.composition.harmony import harmony_profile
from src.composition.pacing import (
    PACING_REGISTRY,
    apply_pacing,
    pick_pacing,
)
from src.daw_integration.generic.midi_export import roman_to_semitone_offset


def _apply(name, prog, key="C", scale="major"):
    return apply_pacing(prog, PACING_REGISTRY[name], key, scale)


class TestReharm(unittest.TestCase):
    def test_tritone_sub_replaces_dominant(self):
        out = _apply("with_tritone_sub", ["I", "V", "vi", "IV"])
        syms = [s for s, _ in out]
        self.assertIn("bII7", syms)
        self.assertNotIn("V", syms)

    def test_borrowed_minor_iv_in_major(self):
        out = _apply("with_borrowed_chords", ["I", "IV", "V", "I"])
        syms = [s for s, _ in out]
        self.assertIn("iv", syms)        # IV -> borrowed minor iv

    def test_borrowed_major_iv_in_minor(self):
        out = _apply("with_borrowed_chords", ["i", "iv", "v", "i"], scale="minor")
        syms = [s for s, _ in out]
        self.assertIn("IV", syms)

    def test_reharm_output_is_parseable(self):
        for strat in ("with_tritone_sub", "with_borrowed_chords"):
            out = _apply(strat, ["I", "IV", "V", "vi"])
            for sym, dur in out:
                # roman_to_semitone_offset never raises; should give a valid pc.
                off, qual = roman_to_semitone_offset(sym, "major")
                self.assertIsInstance(off, int)
                self.assertGreater(dur, 0)

    def test_durations_positive_and_present(self):
        out = _apply("with_tritone_sub", ["I", "V"])
        self.assertTrue(all(d > 0 for _, d in out))
        self.assertEqual(len(out), 2)

    def test_jazz_reharms_more_than_pop(self):
        """Over many seeds, a jazz profile picks reharm strategies in
        verse/chorus far more often than pop (which has none/sparse)."""
        class _P:  # minimal preset stub
            pacing_options = ("uniform_1",)
            bridge_pacing_options = ()
        jazz = harmony_profile("jazz_aaba_full")
        pop = harmony_profile("pop_full_song")
        reharm_names = {
            "with_secondary_doms", "with_tritone_sub", "with_borrowed_chords",
            "with_chromatic_passing",
        }

        def count(prof):
            n = 0
            for s in range(200):
                rng = np.random.default_rng(s)
                pick = pick_pacing(rng, _P(), "chorus",
                                   reharm=prof.reharm, reharm_prob=prof.reharm_prob)
                if pick.name in reharm_names:
                    n += 1
            return n

        self.assertGreater(count(jazz), count(pop))

    def test_intro_never_reharms(self):
        class _P:
            pacing_options = ("uniform_1",)
            bridge_pacing_options = ()
        prof = harmony_profile("jazz_aaba_full")
        for s in range(50):
            rng = np.random.default_rng(s)
            pick = pick_pacing(rng, _P(), "intro",
                               reharm=prof.reharm, reharm_prob=prof.reharm_prob)
            self.assertEqual(pick.name, "uniform_1")


if __name__ == "__main__":
    unittest.main()
