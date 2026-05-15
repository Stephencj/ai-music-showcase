"""Tests for the per-section pacing strategies.

The pacing registry shipped 2026-05-15 to give the random song
generator harmonic-rhythm variation per section — intro might
``ballad_4_2``, verse stays ``uniform_1``, the bridge tries
``with_secondary_doms``. Same seed must always pick the same
strategies (reproducibility).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

from src.composition.pacing import (
    PACING_REGISTRY,
    apply_pacing,
    pick_pacing,
)


class StrategyOutputTests(unittest.TestCase):
    """Each strategy emits a clean ``[(symbol, duration)]`` list."""

    def setUp(self):
        self.prog_major = ["I", "V", "vi", "IV"]
        self.prog_minor = ["i", "VII", "VI", "VII"]

    def test_uniform_1_is_identity_of_durations(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["uniform_1"], "C", "major")
        self.assertEqual(out, [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)])

    def test_uniform_2_doubles_all_durations(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["uniform_2"], "C", "major")
        self.assertEqual(out, [("I", 2.0), ("V", 2.0), ("vi", 2.0), ("IV", 2.0)])

    def test_stretch_tonic_extends_tonic_chords(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["stretch_tonic_2"], "C", "major")
        # I and vi are tonic-rest chords; V and IV are not.
        durations = {sym: dur for sym, dur in out}
        self.assertEqual(durations["I"], 2.0)
        self.assertEqual(durations["vi"], 2.0)
        self.assertEqual(durations["V"], 1.0)
        self.assertEqual(durations["IV"], 1.0)

    def test_short_long_subbar_pattern_repeats(self):
        out = apply_pacing(self.prog_major * 2,  # 8-chord input
                           PACING_REGISTRY["short_long_subbar"], "C", "major")
        durations = [d for _, d in out]
        self.assertEqual(durations, [0.5, 0.5, 1.0, 1.0] * 2)

    def test_ballad_4_2_first_chord_is_4_bars(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["ballad_4_2"], "C", "major")
        self.assertEqual(out[0], ("I", 4.0))
        for sym, dur in out[1:]:
            self.assertEqual(dur, 2.0)

    def test_cadence_accel_compresses_last_two_chords(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["cadence_accel"], "C", "major")
        durations = [d for _, d in out]
        # First 2 chords held 2 bars; last 2 compressed to 1.
        self.assertEqual(durations, [2.0, 2.0, 1.0, 1.0])

    def test_secondary_doms_inserts_V_of_next(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["with_secondary_doms"], "C", "major")
        # I → II7 → V → III7 → vi → I7 → IV (and IV held since no follower)
        syms = [s for s, _ in out]
        self.assertEqual(syms[0], "I")
        self.assertEqual(syms[1], "II7")   # V/V pulling into V
        self.assertEqual(syms[2], "V")
        self.assertEqual(syms[3], "III7")  # V/vi pulling into vi
        self.assertEqual(syms[4], "vi")
        self.assertEqual(syms[5], "I7")    # V/IV pulling into IV
        self.assertEqual(syms[6], "IV")
        # Every chord is 1 bar — the strategy's 2-bar grouping is
        # achieved by emitting two 1-bar entries per source chord.
        for _, d in out:
            self.assertEqual(d, 1.0)

    def test_secondary_doms_in_minor_key(self):
        out = apply_pacing(self.prog_minor,
                           PACING_REGISTRY["with_secondary_doms"], "A", "minor")
        # i → IV7 (V/VII) → VII → III7 (V/VI) → VI → IV7 (V/VII) → VII → held
        syms = [s for s, _ in out]
        self.assertEqual(syms[0], "i")
        self.assertEqual(syms[1], "IV7")
        self.assertEqual(syms[2], "VII")
        self.assertEqual(syms[3], "III7")
        self.assertEqual(syms[4], "VI")

    def test_chromatic_passing_inserts_diminished(self):
        out = apply_pacing(self.prog_major,
                           PACING_REGISTRY["with_chromatic_passing"],
                           "C", "major")
        # I → V (4th, skip), V → vi (adjacent, insert #V°), vi → IV (down, skip)
        syms = [s for s, _ in out]
        durations = [d for _, d in out]
        # V → vi: V should be 1.5 bars; #V° inserted at 0.5 bars; vi 2.0.
        idx_v = syms.index("V")
        self.assertEqual(syms[idx_v], "V")
        self.assertEqual(durations[idx_v], 1.5)
        self.assertEqual(syms[idx_v + 1], "#V°")
        self.assertEqual(durations[idx_v + 1], 0.5)


class PickPacingTests(unittest.TestCase):
    """Strategy picks must be deterministic from the RNG state."""

    class _Preset:
        """Stand-in for StylePreset — only the fields ``pick_pacing``
        reads. Lets tests run without instantiating the full dataclass."""
        def __init__(self, main, bridge=()):
            self.pacing_options = main
            self.bridge_pacing_options = bridge

    def test_seed_determinism(self):
        p = self._Preset(("uniform_1", "uniform_2", "stretch_tonic_2"))
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        self.assertEqual(
            pick_pacing(rng1, p, "verse").name,
            pick_pacing(rng2, p, "verse").name,
        )

    def test_bridge_uses_bridge_pool_when_set(self):
        # Force unambiguous pools so the test can't accidentally pick
        # uniform_1 from both.
        p = self._Preset(main=("uniform_1",), bridge=("ballad_4_2",))
        rng = np.random.default_rng(0)
        self.assertEqual(pick_pacing(rng, p, "bridge").name, "ballad_4_2")
        rng = np.random.default_rng(0)
        self.assertEqual(pick_pacing(rng, p, "verse").name, "uniform_1")

    def test_empty_pool_falls_back_to_uniform_1(self):
        p = self._Preset(main=(), bridge=())
        rng = np.random.default_rng(0)
        self.assertEqual(pick_pacing(rng, p, "verse").name, "uniform_1")

    def test_unknown_strategy_in_pool_falls_back_to_uniform_1(self):
        # Tolerate stale preset config without crashing — log-and-skip.
        p = self._Preset(main=("definitely_not_a_strategy",), bridge=())
        rng = np.random.default_rng(0)
        self.assertEqual(pick_pacing(rng, p, "verse").name, "uniform_1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
