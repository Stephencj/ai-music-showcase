"""Sanity tests for the named instrument registry.

The registry is the source of truth for the UI's six family
checkboxgroups and for ``compose_song`` / ``compose_midi``
per-instrument MIDI routing — so any drift between the helpers
and the registry shows up immediately as a broken UI or wrong
GM patches.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.instruments import (
    FAMILIES,
    FAMILY_LABELS,
    INSTRUMENT_REGISTRY,
    expand_selection,
    instruments_for_family,
    role_of,
)


class RegistryShapeTests(unittest.TestCase):

    def test_every_family_has_a_label(self):
        for family in FAMILIES:
            self.assertIn(family, FAMILY_LABELS)

    def test_every_family_has_at_least_one_instrument(self):
        for family in FAMILIES:
            self.assertGreaterEqual(
                len(instruments_for_family(family)), 1,
                f"family {family!r} has no instruments",
            )

    def test_every_instrument_belongs_to_a_known_family(self):
        valid = set(FAMILIES)
        for inst_id, inst in INSTRUMENT_REGISTRY.items():
            self.assertIn(
                inst.family, valid,
                f"{inst_id!r} declares unknown family {inst.family!r}",
            )

    def test_every_instrument_role_is_one_of_the_four_buckets(self):
        valid = {"chords", "bass", "melody", "drums"}
        for inst_id, inst in INSTRUMENT_REGISTRY.items():
            self.assertIn(inst.role, valid,
                          f"{inst_id!r} has bad role {inst.role!r}")

    def test_track_name_matches_label(self):
        for inst in INSTRUMENT_REGISTRY.values():
            self.assertEqual(inst.track_name, inst.label)

    def test_default_octave_present_for_pitched_instruments(self):
        for inst_id, inst in INSTRUMENT_REGISTRY.items():
            if inst.is_drum:
                self.assertIsNone(
                    inst.default_octave,
                    f"{inst_id}: drum instruments should have "
                    f"default_octave=None (got {inst.default_octave})",
                )
            else:
                self.assertIsNotNone(
                    inst.default_octave,
                    f"{inst_id}: pitched instrument missing default_octave",
                )
                self.assertGreaterEqual(inst.default_octave, 1)
                self.assertLessEqual(inst.default_octave, 6)


class SectionCompositeTests(unittest.TestCase):

    def test_every_section_member_is_in_the_registry(self):
        for inst in INSTRUMENT_REGISTRY.values():
            if not inst.is_section:
                continue
            for m in inst.members:
                self.assertIn(
                    m, INSTRUMENT_REGISTRY,
                    f"{inst.id} declares unknown member {m!r}",
                )

    def test_expand_keeps_section_when_no_members_selected(self):
        out = expand_selection(["brass_section"])
        self.assertEqual([i.id for i in out], ["brass_section"])

    def test_expand_drops_section_when_a_member_is_selected(self):
        # If trumpet is ticked individually, the composite is dropped.
        out = expand_selection(["brass_section", "trumpet"])
        self.assertEqual([i.id for i in out], ["trumpet"])

    def test_a_bass_member_keeps_its_section(self):
        # The contrabass plays a bass line under the string section's pad.
        ids = [i.id for i in expand_selection(["string_section", "contrabass"])]
        self.assertEqual(ids, ["string_section", "contrabass"])
        ids = [i.id for i in expand_selection(["string_section", "violin"])]
        self.assertEqual(ids, ["violin"])

    def test_expand_ignores_unknown_ids(self):
        out = expand_selection(["piano", "no_such_inst"])
        self.assertEqual([i.id for i in out], ["piano"])

    def test_expand_dedupes(self):
        out = expand_selection(["piano", "piano"])
        self.assertEqual([i.id for i in out], ["piano"])


class RoleOfTests(unittest.TestCase):

    def test_piano_is_chords_role(self):
        self.assertEqual(role_of("piano"), "chords")

    def test_drum_kit_is_drums_role(self):
        self.assertEqual(role_of("drum_kit"), "drums")

    def test_trumpet_is_melody_role(self):
        self.assertEqual(role_of("trumpet"), "melody")

    def test_unknown_id_returns_none(self):
        self.assertIsNone(role_of("not_a_real_id"))


if __name__ == "__main__":
    unittest.main()
