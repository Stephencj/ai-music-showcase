"""'Explain this song' theory breakdown."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.explain import (
    explain_spec, _function, _key_relation, _name_progression, _devices,
)


class FunctionTests(unittest.TestCase):
    def test_functions(self):
        self.assertEqual(_function("I"), "tonic")
        self.assertEqual(_function("V7"), "dominant")
        self.assertEqual(_function("IV"), "predominant (subdominant)")
        self.assertIn("Neapolitan", _function("bII7"))


class KeyRelationTests(unittest.TestCase):
    def test_home_key(self):
        self.assertIn("home key", _key_relation("C", "major", "C", "major"))

    def test_relative_degree_shares_signature(self):
        # A minor is the vi of C major and keeps the signature.
        rel = _key_relation("A", "minor", "C", "major")
        self.assertIn("vi", rel)
        self.assertIn("same key signature", rel)

    def test_dorian_is_the_ii(self):
        self.assertIn("ii", _key_relation("D", "dorian", "C", "major"))

    def test_parallel_mode_is_flagged(self):
        # Same root, different mode → parallel / modal interchange.
        rel = _key_relation("C", "dorian", "C", "major")
        self.assertIn("parallel", rel)


class DeviceTests(unittest.TestCase):
    def test_named_progressions(self):
        self.assertIn("Axis", _name_progression(["I", "V", "vi", "IV"]) or "")
        self.assertIn("jazz", _name_progression(["ii7", "V7", "I"]) or "")

    def test_devices(self):
        self.assertTrue(any("tritone" in d for d in _devices(["I", "bII7", "I"], "major")))
        self.assertTrue(any("Dorian IV" in d for d in _devices(["i7", "IV7"], "dorian")))


class ExplainSpecTests(unittest.TestCase):
    def test_shape(self):
        spec = {
            "genre": "pop_full_song", "key": "C", "scale": "major", "tempo": 120,
            "sections": [{"start_bar": 0, "end_bar": 3, "label": "Verse", "role": "verse"}],
            "progression": [
                {"root_pc": 0, "quality": "maj", "symbol": "I", "start_bar": 0, "end_bar": 1},
                {"root_pc": 7, "quality": "maj", "symbol": "V", "start_bar": 1, "end_bar": 2},
            ],
        }
        e = explain_spec(spec)
        self.assertEqual(e["key"], "C major")
        self.assertEqual(len(e["sections"]), 1)
        sec = e["sections"][0]
        self.assertTrue(sec["chords"])
        self.assertEqual(sec["chords"][0]["function"], "tonic")
        self.assertEqual(sec["feel"], "Pop (Full song)")  # no preset → song genre


if __name__ == "__main__":
    unittest.main()
