"""Regression tests for the multi-variation StylePreset progression API.

Pins two contracts:

1. Every preset exposes a non-empty ``progression_variants`` list whose
   first entry is named "Default" and whose plan equals the legacy
   ``progression`` field. This guarantees code that still reads
   ``style.progression`` continues to behave identically.
2. Every variation's plan parses cleanly through ``coerce_progression_plan``
   and expands to a non-empty event list at the preset's natural bar count.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app
from src.daw_integration.generic.styles import STYLES
from src.daw_integration.generic.midi_export import (
    coerce_progression_plan,
    expand_progression_plan,
)


class VariantContractTests(unittest.TestCase):

    def test_every_preset_has_at_least_one_variant(self):
        for name, p in STYLES.items():
            with self.subTest(preset=name):
                self.assertTrue(p.progression_variants,
                                f"{name} has empty variants")

    def test_first_variant_is_default_matching_legacy_progression(self):
        for name, p in STYLES.items():
            with self.subTest(preset=name):
                first_name, first_plan = p.progression_variants[0]
                self.assertEqual(first_name, "Default")
                self.assertEqual(first_plan, p.progression,
                                 f"{name}: variant 0 plan diverges from .progression")

    def test_every_variant_plan_is_parseable(self):
        for name, p in STYLES.items():
            for vname, plan in p.progression_variants:
                with self.subTest(preset=name, variant=vname):
                    coerced = coerce_progression_plan(plan)
                    self.assertTrue(coerced, f"empty coerced plan")
                    events = expand_progression_plan(coerced, bars=8)
                    self.assertTrue(events, f"expanded to 0 events at 8 bars")

    def test_named_variants_present_on_curated_presets(self):
        """The 12 curated presets should expose >1 variant."""
        curated = {
            "pop", "funk", "rock", "metal", "dance", "disco",
            "jazz_fusion", "country", "boy_band",
            "latin_pop", "salsa", "bossa_nova",
        }
        for name in curated:
            with self.subTest(preset=name):
                self.assertGreater(
                    len(STYLES[name].progression_variants), 1,
                    f"{name} should have ≥2 variants (curated)",
                )


class SerializerTests(unittest.TestCase):

    def test_bare_strings_roundtrip(self):
        plan = ["I", "V", "vi", "IV"]
        self.assertEqual(app._progression_plan_to_text(plan), "I V vi IV")

    def test_integer_duration_renders_colon(self):
        plan = [("I", 2.0), ("V", 1.0), ("vi", 1.0), ("IV", 4.0)]
        self.assertEqual(app._progression_plan_to_text(plan), "I:2 V vi IV:4")

    def test_fractional_duration_renders_decimal(self):
        plan = [("I", 0.5), ("V", 0.25)]
        self.assertEqual(app._progression_plan_to_text(plan), "I:0.5 V:0.25")

    def test_empty_plan_returns_empty_string(self):
        self.assertEqual(app._progression_plan_to_text([]), "")
        self.assertEqual(app._progression_plan_to_text(None), "")

    def test_parser_serializer_roundtrip(self):
        """The serializer normalizes ":1" durations to bare symbols. So
        parse → serialize is not byte-identical, but parse → serialize →
        parse should produce the same plan (semantic equivalence)."""
        for raw in ("I V vi IV",
                    "I:2 V vi IV:4",
                    "I:0.5 V:0.5 vi:1 IV:1"):
            parsed = app._parse_progression_text(raw)
            text = app._progression_plan_to_text(parsed)
            reparsed = app._parse_progression_text(text)
            self.assertEqual(parsed, reparsed,
                             f"semantic roundtrip failed for {raw!r}")


class RandomVariationComposeTests(unittest.TestCase):
    """Compose with random_variation=True must pick a real variant — not
    fall back to the textbox or to None."""

    def test_random_variation_uses_preset_variant(self):
        # Use a preset with multiple variants
        result = app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=False,
            enable_melody=False, enable_drums=False,
            bass_pattern="root_fifth", drum_pattern="basic_rock",
            voicing="triad", swing=0.0, chord_rhythm="pad",
            melody_style="motif", seed=42,
            progression_text="DELIBERATELY_GARBAGE",  # should be ignored
            extras=None, chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
            random_variation=True,
        )
        # If random_variation honoured the preset, the textbox garbage was
        # ignored and we got a valid render.
        self.assertEqual(len(result), 5)
        midi = app._state.get("last_midi")
        self.assertIsNotNone(midi)
        # At least one chord note rendered
        chord_track = next(t for t in midi.tracks)
        self.assertGreater(len(chord_track.notes), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
