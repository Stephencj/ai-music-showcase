"""Tests for the vocal family + lead/harmony technique pack.

Shipped 2026-05-15 to restore the melody line that the per-instrument
iteration round had inadvertently dropped for chord-only instrument
selections, and to give vocals first-class idiomatic treatment with
phrasing techniques (ballad sustain / pop chorus belt / R&B melisma /
jazz crooner / country twang / rock belt / gospel lift / etc).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi

from src.composition import BANK
from src.composition.instruments import (
    FAMILIES, FAMILY_LABELS, INSTRUMENT_REGISTRY, instruments_for_family,
)
from src.composition.song_composer import compose_song


LEAD_NAMES = {
    "vocal_lead_ballad_sustain",
    "vocal_lead_intimate_verse",
    "vocal_lead_jazz_crooner",
    "vocal_lead_country_twang",
    "vocal_lead_hooky_motif",
    "vocal_lead_pop_chorus_belt",
    "vocal_lead_rnb_melisma",
    "vocal_lead_gospel_lift",
    "vocal_lead_rock_belt",
}
HARMONY_NAMES = {
    "vocal_harmony_oohs_pad",
    "vocal_harmony_aahs_chorus",
    "vocal_harmony_doowop_block",
    "vocal_harmony_gospel_stack",
    "vocal_harmony_motown_charleston",
}


class VocalFamilyShapeTests(unittest.TestCase):

    def test_vocal_family_present(self):
        self.assertIn("vocal", FAMILIES)
        self.assertEqual(FAMILY_LABELS["vocal"], "Vocals")

    def test_vocal_lead_instrument(self):
        inst = INSTRUMENT_REGISTRY["vocal_lead"]
        self.assertEqual(inst.family, "vocal")
        self.assertEqual(inst.role, "melody")
        self.assertEqual(inst.program, 53)  # GM Voice Oohs
        self.assertEqual(inst.default_octave, 5)

    def test_vocal_harmony_instrument(self):
        inst = INSTRUMENT_REGISTRY["vocal_harmony"]
        self.assertEqual(inst.family, "vocal")
        self.assertEqual(inst.role, "chords")
        self.assertEqual(inst.program, 52)  # GM Choir Aahs
        self.assertEqual(inst.voicing_role, "pad")

    def test_vocal_family_has_two_instruments(self):
        ids = [i.id for i in instruments_for_family("vocal")]
        self.assertEqual(set(ids), {"vocal_lead", "vocal_harmony"})


class VocalTechniqueRegistrationTests(unittest.TestCase):

    def test_all_lead_techniques_register(self):
        registered = {t.name for t in BANK.all_techniques()
                      if "vocal_lead" in t.instruments}
        for name in LEAD_NAMES:
            self.assertIn(name, registered,
                          f"lead vocal technique {name} not registered")

    def test_all_harmony_techniques_register(self):
        registered = {t.name for t in BANK.all_techniques()
                      if "vocal_harmony" in t.instruments}
        for name in HARMONY_NAMES:
            self.assertIn(name, registered,
                          f"harmony vocal technique {name} not registered")

    def test_lead_techniques_target_vocal_lead_only(self):
        for tech in BANK.all_techniques():
            if tech.name not in LEAD_NAMES:
                continue
            self.assertEqual(tech.instruments, ("vocal_lead",),
                             f"{tech.name}: instruments={tech.instruments}")

    def test_every_vocal_technique_carries_vocal_tag(self):
        for tech in BANK.all_techniques():
            if tech.name in LEAD_NAMES | HARMONY_NAMES:
                self.assertIn("vocal", tech.tags,
                              f"{tech.name}: missing 'vocal' tag")


class VocalRenderingTests(unittest.TestCase):

    def test_compose_with_vocal_lead_produces_lead_track(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=[
                    "drum_kit", "electric_bass", "piano", "vocal_lead",
                ],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        names = {i.name: i for i in pm.instruments}
        self.assertIn("Lead Vocal", names)
        self.assertEqual(names["Lead Vocal"].program, 53)
        self.assertGreater(len(names["Lead Vocal"].notes), 0)

    def test_compose_with_vocal_harmony_routes_to_choir_aahs(self):
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="soul_motown_full", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=[
                    "drum_kit", "electric_bass", "piano",
                    "vocal_lead", "vocal_harmony",
                ],
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        names = {i.name: i for i in pm.instruments}
        self.assertIn("Backing Vocals", names)
        self.assertEqual(names["Backing Vocals"].program, 52)

    def test_pop_full_song_no_longer_silent(self):
        """Regression guard: pop_full_song with its preset default
        instruments must produce at least one melody-role MIDI track."""
        from src.daw_integration.generic.styles import STYLES
        defaults = STYLES["pop_full_song"].default_instruments
        with tempfile.TemporaryDirectory() as td:
            out = compose_song(
                genre="pop_full_song", seed=42, skip_audio=True,
                output_dir=Path(td),
                enabled_instruments=defaults,
            )
            pm = pretty_midi.PrettyMIDI(out["midi_path"])
        # Find a track named "Lead Vocal" — guaranteed by the preset
        # update — or one of the melody-program ranges.
        names = {i.name for i in pm.instruments}
        self.assertTrue(
            "Lead Vocal" in names,
            f"pop_full_song should now produce a Lead Vocal track; got tracks={names}",
        )


class VocalPresetDefaultsTests(unittest.TestCase):
    """Each vocal-friendly preset auto-fills the Vocals accordion."""

    VOCAL_LEAD_PRESETS = (
        "pop_full_song", "rock_anthem_full", "ballad_full",
        "country_full", "soul_motown_full", "disco_full",
        "reggae_full", "hip_hop_full", "funk_full_song",
        "jazz_aaba_full", "jazz_bossa_full", "jazz_piano_full",
    )
    VOCAL_HARMONY_PRESETS = (
        "soul_motown_full", "disco_full", "reggae_full", "ballad_full",
    )

    def test_lead_presets_include_vocal_lead(self):
        from src.daw_integration.generic.styles import STYLES
        for k in self.VOCAL_LEAD_PRESETS:
            self.assertIn(
                "vocal_lead", STYLES[k].default_instruments,
                f"{k}: missing vocal_lead in default_instruments",
            )

    def test_harmony_presets_include_vocal_harmony(self):
        from src.daw_integration.generic.styles import STYLES
        for k in self.VOCAL_HARMONY_PRESETS:
            self.assertIn(
                "vocal_harmony", STYLES[k].default_instruments,
                f"{k}: missing vocal_harmony in default_instruments",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
