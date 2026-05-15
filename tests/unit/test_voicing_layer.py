"""Unit tests for the stratified per-instrument voicing layer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.instruments import INSTRUMENT_REGISTRY
from src.composition.voicing_layer import (
    LAYER_ROLES,
    LAYERED_VOICING_MAP,
    assign_layered_voicings,
    effective_voicing,
)


class EffectiveVoicingTests(unittest.TestCase):

    def test_none_role_passes_through(self):
        self.assertEqual(effective_voicing(None, "ninth"), "ninth")
        self.assertEqual(effective_voicing("", "seventh"), "seventh")

    def test_mid_comp_maps_ninth_to_rootless(self):
        self.assertEqual(effective_voicing("mid_comp", "ninth"), "rootless")

    def test_mid_comp_maps_seventh_to_shell(self):
        self.assertEqual(effective_voicing("mid_comp", "seventh"), "shell")

    def test_pad_keeps_ninth(self):
        self.assertEqual(effective_voicing("pad", "ninth"), "ninth")

    def test_pad_warms_triad_to_seventh(self):
        self.assertEqual(effective_voicing("pad", "triad"), "seventh")

    def test_top_thins_ninth_to_shell(self):
        self.assertEqual(effective_voicing("top", "ninth"), "shell")

    def test_top_thins_triad_to_open5(self):
        self.assertEqual(effective_voicing("top", "triad"), "open5")

    def test_unmapped_voicing_passes_through(self):
        # Exotic voicings the technique picked deliberately stay intact.
        self.assertEqual(effective_voicing("pad", "quartal"), "quartal")
        self.assertEqual(effective_voicing("mid_comp", "drop2"), "drop2")
        self.assertEqual(effective_voicing("top", "quintal"), "quintal")

    def test_unknown_role_passes_through(self):
        # Tolerate stale data — log-and-skip rather than crash.
        self.assertEqual(effective_voicing("not_a_role", "ninth"), "ninth")


class AssignLayeredVoicingsTests(unittest.TestCase):

    def test_empty_list_returns_empty_dict(self):
        self.assertEqual(assign_layered_voicings([]), {})

    def test_solo_instrument_returns_empty_dict(self):
        piano = INSTRUMENT_REGISTRY["piano"]
        self.assertEqual(assign_layered_voicings([piano]), {})

    def test_three_instruments_get_three_distinct_roles(self):
        # piano (octave 3) → mid_comp; brass_section pinned to pad;
        # woodwind_section pinned to top.
        insts = [INSTRUMENT_REGISTRY[k] for k in
                 ("piano", "brass_section", "woodwind_section")]
        out = assign_layered_voicings(insts)
        self.assertEqual(out["piano"], "mid_comp")
        self.assertEqual(out["brass_section"], "pad")
        self.assertEqual(out["woodwind_section"], "top")

    def test_pinned_role_overrides_register_default(self):
        # synth_pad is pinned to "pad" even when picked with two
        # higher-octave instruments that would otherwise outrank it.
        insts = [INSTRUMENT_REGISTRY[k] for k in
                 ("synth_pad", "viola", "woodwind_section")]
        out = assign_layered_voicings(insts)
        self.assertEqual(out["synth_pad"], "pad")

    def test_assignment_is_deterministic(self):
        insts = [INSTRUMENT_REGISTRY[k] for k in
                 ("piano", "organ_hammond", "brass_section")]
        a = assign_layered_voicings(list(insts))
        b = assign_layered_voicings(list(reversed(insts)))
        self.assertEqual(a, b)

    def test_two_instruments_low_and_high(self):
        insts = [INSTRUMENT_REGISTRY[k] for k in ("piano", "violin")]
        out = assign_layered_voicings(insts)
        self.assertEqual(out["piano"], "mid_comp")
        # violin sits at octave 5 — it should land on "top".
        self.assertEqual(out["violin"], "top")

    def test_layer_roles_constant_matches_map_keys(self):
        self.assertEqual(set(LAYER_ROLES), set(LAYERED_VOICING_MAP.keys()))


class InstrumentPinnedRoleTests(unittest.TestCase):

    def test_section_composites_carry_canonical_roles(self):
        self.assertEqual(INSTRUMENT_REGISTRY["brass_section"].voicing_role, "pad")
        self.assertEqual(INSTRUMENT_REGISTRY["string_section"].voicing_role, "pad")
        self.assertEqual(INSTRUMENT_REGISTRY["woodwind_section"].voicing_role, "top")
        self.assertEqual(INSTRUMENT_REGISTRY["synth_pad"].voicing_role, "pad")

    def test_non_pinned_instruments_have_no_role(self):
        for inst_id in ("piano", "organ_hammond", "electric_guitar_clean",
                        "viola", "trumpet"):
            self.assertIsNone(INSTRUMENT_REGISTRY[inst_id].voicing_role,
                              f"{inst_id} should not have a pinned voicing_role")


if __name__ == "__main__":
    unittest.main(verbosity=2)
