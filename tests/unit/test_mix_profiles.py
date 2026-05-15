"""Tests for the genre-aware mix profile system."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.audio_processing.render.effects import VALID_FAMILIES, classify_family
from src.audio_processing.render.mix import MixDefaults, _FAMILY_MIX
from src.audio_processing.render.profiles import (
    MIX_PROFILES,
    apply_profile_to_family_mix,
    resolve_profile,
)


class ProfileRegistryTests(unittest.TestCase):

    def test_six_profiles_registered(self):
        self.assertEqual(
            set(MIX_PROFILES.keys()),
            {"pop", "rock", "jazz", "ballad", "edm", "cinematic"},
        )

    def test_each_profile_has_a_label(self):
        for name, profile in MIX_PROFILES.items():
            self.assertTrue(profile.label,
                            f"{name}: missing label")

    def test_each_profile_master_preset_resolves(self):
        from src.audio_processing.render.effects import MASTER_PRESETS
        for name, profile in MIX_PROFILES.items():
            self.assertIn(profile.master_preset, MASTER_PRESETS,
                          f"{name}: unknown master {profile.master_preset}")


class ResolveProfileTests(unittest.TestCase):

    def test_full_song_presets_resolve(self):
        cases = {
            "pop_full_song":      "pop",
            "rock_anthem_full":   "rock",
            "ballad_full":        "ballad",
            "edm_full_song":      "edm",
            "jazz_aaba_full":     "jazz",
            "cinematic_epic":     "cinematic",
        }
        for style, expected in cases.items():
            self.assertEqual(
                resolve_profile(style).name, expected,
                f"{style} should resolve to {expected}",
            )

    def test_unknown_preset_falls_back_to_pop(self):
        self.assertEqual(resolve_profile("no_such_genre").name, "pop")

    def test_none_falls_back_to_pop(self):
        self.assertEqual(resolve_profile(None).name, "pop")


class ApplyProfileTests(unittest.TestCase):

    def test_pop_profile_overrides_lead_vocal_gain(self):
        merged = apply_profile_to_family_mix(MIX_PROFILES["pop"], _FAMILY_MIX)
        # pop sets lead_vocal gain to -2 dB (instead of base -3 dB).
        self.assertEqual(merged["lead_vocal"].gain_db, -2.0)
        # Base entries that pop doesn't override stay unchanged.
        self.assertEqual(merged["bass"].gain_db, _FAMILY_MIX["bass"].gain_db)

    def test_edm_profile_drives_bass_gain_up(self):
        merged = apply_profile_to_family_mix(MIX_PROFILES["edm"], _FAMILY_MIX)
        self.assertEqual(merged["bass"].gain_db, -2.0)

    def test_ballad_profile_softens_drums(self):
        merged = apply_profile_to_family_mix(MIX_PROFILES["ballad"], _FAMILY_MIX)
        self.assertEqual(merged["drums"].gain_db, -5.0)


class FamilyClassificationTests(unittest.TestCase):

    def test_lead_vocal_track_classifies(self):
        self.assertEqual(
            classify_family("Lead Vocal", program=53, is_drum=False),
            "lead_vocal",
        )

    def test_backing_vocal_track_classifies(self):
        self.assertEqual(
            classify_family("Backing Vocals", program=52, is_drum=False),
            "bvocal",
        )

    def test_brass_section_classifies(self):
        self.assertEqual(
            classify_family("Brass Section", program=61, is_drum=False),
            "brass",
        )

    def test_trumpet_classifies(self):
        self.assertEqual(
            classify_family("Trumpet", program=56, is_drum=False),
            "brass",
        )

    def test_violin_classifies(self):
        self.assertEqual(
            classify_family("Violin", program=40, is_drum=False),
            "strings",
        )

    def test_flute_classifies(self):
        self.assertEqual(
            classify_family("Flute", program=73, is_drum=False),
            "woodwind",
        )

    def test_drum_kit_classifies(self):
        self.assertEqual(
            classify_family("Drum kit", program=0, is_drum=True),
            "drums",
        )

    def test_all_new_families_in_valid_families(self):
        for family in ("brass", "woodwind", "strings",
                       "lead_vocal", "bvocal"):
            self.assertIn(family, VALID_FAMILIES,
                          f"{family} missing from VALID_FAMILIES")


class FamilyMixDefaultsTests(unittest.TestCase):
    """Industry-anchored gain table: lead vocal at -3 dB, drums tight,
    pad far back. These thresholds enforce the load-bearing invariants
    of the mix; trip them and audio output sounds out of balance."""

    def test_lead_vocal_at_minus_3_db(self):
        self.assertEqual(_FAMILY_MIX["lead_vocal"].gain_db, -3.0)

    def test_drums_above_strings_above_pad(self):
        # Drum prominence > strings prominence > pad prominence.
        self.assertGreater(
            _FAMILY_MIX["drums"].gain_db,
            _FAMILY_MIX["strings"].gain_db,
        )
        self.assertGreater(
            _FAMILY_MIX["strings"].gain_db,
            _FAMILY_MIX["pad"].gain_db,
        )

    def test_lead_vocal_louder_than_chords(self):
        # The single most important invariant — vocal must sit on top
        # of the comp instruments.
        self.assertGreater(
            _FAMILY_MIX["lead_vocal"].gain_db,
            _FAMILY_MIX["chords"].gain_db,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
