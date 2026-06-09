"""Tests for per-chord voicing variety (the 'mostly 7 chords' fix)."""
import unittest

from src.composition.harmony import harmony_profile
from src.daw_integration.generic.midi_export import (
    MidiExporter,
    _chord_function,
    _voicing_for_chord,
)
import numpy as np


def _chord_track_pitch_sigs(voicing, *, variety, family="diatonic_color", seed=7):
    """Return the set of distinct chord-voicing 'shapes' (interval patterns
    above the root) produced across a progression — a proxy for voicing
    variety independent of transposition."""
    m = MidiExporter(tempo=100)
    m.add_chord_progression(
        key="C", progression=["I", "V", "vi", "IV", "I", "V", "vi", "IV"],
        bars=8, voicing=voicing, rhythm="pad",
        voicing_variety=variety, voicing_family=family, seed=seed,
    )
    track = m.tracks[0]
    # group notes by onset → chord; shape = sorted intervals from the lowest note
    by_start = {}
    for n in track.notes:
        by_start.setdefault(round(n.start, 3), []).append(n.pitch)
    shapes = set()
    for pitches in by_start.values():
        lo = min(pitches)
        shapes.add(tuple(sorted(p - lo for p in pitches)))
    return shapes


class TestVoicingVariety(unittest.TestCase):
    def test_uniform_when_variety_zero(self):
        """variety=0 → backward-compatible single voicing shape family."""
        shapes = _chord_track_pitch_sigs("seventh", variety=0.0)
        # All chords use the same voicing recipe; shapes vary only by chord
        # quality (maj7 vs dom7 vs m7), so at most a few — and crucially the
        # same as the legacy path. Assert it's small/stable.
        self.assertLessEqual(len(shapes), 3)

    def test_variety_produces_more_shapes(self):
        few = _chord_track_pitch_sigs("seventh", variety=0.0)
        many = _chord_track_pitch_sigs("seventh", variety=0.8)
        self.assertGreater(len(many), len(few),
                           "voicing variety did not add distinct voicings")

    def test_deterministic_under_seed(self):
        a = _chord_track_pitch_sigs("ninth", variety=0.6, family="jazz", seed=3)
        b = _chord_track_pitch_sigs("ninth", variety=0.6, family="jazz", seed=3)
        self.assertEqual(a, b)

    def test_chord_function_mapping(self):
        self.assertEqual(_chord_function(0), "tonic")
        self.assertEqual(_chord_function(4), "dominant")
        self.assertEqual(_chord_function(3), "predominant")
        self.assertEqual(_chord_function(5), "submediant")
        self.assertEqual(_chord_function(None), "other")

    def test_non_diatonic_keeps_base_voicing(self):
        rng = np.random.default_rng(1)
        # root_degree None (non-diatonic) → always the base voicing.
        for _ in range(20):
            self.assertEqual(
                _voicing_for_chord(None, "7", "ninth", "jazz", 1.0, rng),
                "ninth",
            )

    def test_profiles_genre_keyed(self):
        self.assertEqual(harmony_profile("jazz_aaba_full").voicing_family, "jazz")
        self.assertEqual(harmony_profile("rock_anthem_full").voicing_family, "rock")
        self.assertEqual(harmony_profile("classical_baroque").voicing_family, "classical")
        self.assertEqual(harmony_profile("pop_full_song").voicing_family, "diatonic_color")
        self.assertGreater(harmony_profile("jazz").voicing_variety,
                           harmony_profile("rock").voicing_variety)


if __name__ == "__main__":
    unittest.main()
