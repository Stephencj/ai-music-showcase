"""Tests for the rule-based natural-language → song-plan parser.

Pins the prompt → SongPlan mapping: genre detection, multi-preset
(genre-bound-to-section) binding, key/scale/tempo/swing extraction, and
instrument recognition. The plan must stay shaped like the Generate form so
the frontend can apply it directly.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.nl_parser import parse_prompt
from src.daw_integration.generic.styles import STYLES
from src.composition.instruments import INSTRUMENT_REGISTRY


class NlParserTests(unittest.TestCase):
    def test_plan_shape_and_valid_ids(self):
        p = parse_prompt("a funk song")
        for k in ("genre", "key", "scale", "tempo", "swing", "sections",
                  "section_presets", "instruments", "understood", "notes"):
            self.assertIn(k, p)
        self.assertIn(p["genre"], STYLES)
        self.assertEqual(p["sections"], [])
        self.assertIsInstance(p["section_presets"], dict)

    def test_empty_prompt_defaults(self):
        p = parse_prompt("")
        self.assertEqual(p["genre"], "pop_full_song")
        self.assertEqual(p["section_presets"], {})
        self.assertIsNone(p["key"])
        self.assertIsNone(p["tempo"])

    def test_global_genre(self):
        self.assertEqual(parse_prompt("make some funky music")["genre"], "funk_full_song")
        self.assertEqual(parse_prompt("a country tune")["genre"], "country_full")
        self.assertEqual(parse_prompt("90s boom bap")["genre"], "hip_hop_90s")

    def test_multi_preset_binding(self):
        p = parse_prompt("a pop song with a funky verse and a hip-hop chorus")
        self.assertEqual(p["genre"], "pop_full_song")
        self.assertEqual(p["section_presets"].get("verse"), "funk_full_song")
        self.assertEqual(p["section_presets"].get("chorus"), "hip_hop_full")
        # every section preset id is a real style
        for pid in p["section_presets"].values():
            self.assertIn(pid, STYLES)

    def test_section_genre_promotes_to_global_when_no_unbound(self):
        # No standalone global genre → the chorus's genre becomes the song's,
        # and the now-redundant chorus override is dropped.
        p = parse_prompt("jazzy verse, funky chorus")
        self.assertEqual(p["genre"], "funk_full_song")
        self.assertNotIn("chorus", p["section_presets"])
        self.assertEqual(p["section_presets"].get("verse"), "jazz_aaba_full")

    def test_key_minor_major(self):
        self.assertEqual(parse_prompt("in G minor")["key"], "G")
        self.assertEqual(parse_prompt("in G minor")["scale"], "minor")
        self.assertEqual(parse_prompt("Bb major please")["key"], "Bb")
        self.assertEqual(parse_prompt("a tune in F# minor")["scale"], "minor")
        self.assertEqual(parse_prompt("key of C")["key"], "C")

    def test_key_m_shorthand(self):
        p = parse_prompt("something in Gm")
        self.assertEqual(p["key"], "G")
        self.assertEqual(p["scale"], "minor")

    def test_no_false_key_from_article_a(self):
        # The article "a" must not be read as the key of A.
        self.assertIsNone(parse_prompt("a big funk jam")["key"])

    def test_tempo_explicit_and_words(self):
        self.assertEqual(parse_prompt("funk at 128 bpm")["tempo"], 128.0)
        self.assertEqual(parse_prompt("a slow ballad")["tempo"], 70.0)
        self.assertEqual(parse_prompt("upbeat pop")["tempo"], 124.0)

    def test_swing(self):
        self.assertAlmostEqual(parse_prompt("a shuffle blues")["swing"], 0.33)
        self.assertEqual(parse_prompt("straight eighths rock")["swing"], 0.0)

    def test_instruments(self):
        p = parse_prompt("add 808s, horns and a fiddle")
        self.assertIn("bass_808", p["instruments"])
        self.assertIn("brass_section", p["instruments"])
        self.assertIn("violin", p["instruments"])
        for iid in p["instruments"]:
            self.assertIn(iid, INSTRUMENT_REGISTRY)

    def test_style_hints_noted_not_applied(self):
        p = parse_prompt("a rock song with a guitar solo in the bridge")
        self.assertTrue(p["notes"])  # solo is surfaced as a note
        self.assertEqual(p["section_presets"], {})  # but not turned into a preset

    def test_understood_always_has_genre(self):
        p = parse_prompt("anything")
        self.assertTrue(any(u.startswith("Genre:") for u in p["understood"]))


if __name__ == "__main__":
    unittest.main()
