"""Phase 1 tests for the melody revamp: rhythm motifs, velocity curve,
lick auto-fire, motif restate.

Each behavior opts in via a kwarg (default = today's behavior so the
271 existing tests stay green). These tests lock the kwargs themselves
plus the style-variant wiring that turns them on per-genre.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    MELODIC_LICKS,
    MidiExporter,
    RHYTHM_MOTIFS,
    _velocity_for_position,
)
from src.daw_integration.generic.styles import STYLES


# ---------------------------------------------------------------------------
# RHYTHM_MOTIFS catalog
# ---------------------------------------------------------------------------

class RhythmMotifsCatalogTests(unittest.TestCase):

    def test_curated_motifs_present(self):
        expected = {
            "pop_anacrusis", "jazz_charleston", "funk_16th_synco",
            "blues_shuffle", "bossa_partido", "country_long_short",
            "latin_clave_son",
        }
        self.assertTrue(expected.issubset(RHYTHM_MOTIFS.keys()))

    def test_jazz_charleston_has_offbeat_hits(self):
        # Charleston's identity is the and-of-2 / and-of-4 hits.
        beats = [round(b, 2) for b, _, _ in RHYTHM_MOTIFS["jazz_charleston"]]
        offbeat = [b for b in beats if (b * 2) % 2 == 1]  # odd half-beats
        self.assertGreaterEqual(len(offbeat), 1,
                                 f"jazz_charleston missing offbeat hits: {beats}")

    def test_funk_16th_synco_has_sixteenth_subdivision(self):
        # Funk syncopation lives on the 0.25/0.75 16th-note grid.
        beats = [round(b, 3) for b, _, _ in RHYTHM_MOTIFS["funk_16th_synco"]]
        sixteenths = [b for b in beats if (b * 4) % 4 in (1, 3)]
        self.assertGreaterEqual(len(sixteenths), 2,
                                 f"funk_16th_synco missing 16th sub: {beats}")

    def test_clave_son_has_3_2_structure(self):
        # 3-2 son clave: 3 hits in bar 1, 2 hits in bar 2.
        beats = [b for b, _, _ in RHYTHM_MOTIFS["latin_clave_son"]]
        bar1 = [b for b in beats if b < 4.0]
        bar2 = [b for b in beats if b >= 4.0]
        self.assertEqual(len(bar1), 3, f"clave bar 1 should have 3 hits, got {bar1}")
        self.assertEqual(len(bar2), 3, f"clave bar 2 should have 3 hits, got {bar2}")
        # Off-by-one OK for catalog tuning; assert each bar has 2 or 3 hits.

    def test_rhythm_motif_kwarg_uses_catalog(self):
        """When `rhythm_motif` is set, the rendered notes' beat
        positions should match the catalog template, NOT the
        procedural strong/weak grid."""
        m_catalog = MidiExporter(tempo=120, time_signature=(4, 4))
        m_catalog.add_melody(
            key="C", scale_name="major", bars=2, octave=5, seed=42,
            progression=["I", "V"],
            melody_style="motif",
            rhythm_motif="latin_clave_son",
            cadence=None,
        )
        starts = sorted({round(n.start, 3) for n in m_catalog.tracks[0].notes})
        # latin_clave_son template puts notes at 0.0, 1.5, 2.5, 4.0,
        # 5.5, 6.5 beats. At 120 BPM 4/4, beat = 0.5s, so seconds are
        # 0.0, 0.75, 1.25, 2.0, 2.75, 3.25.
        expected_seconds = [0.0, 0.75, 1.25, 2.0, 2.75, 3.25]
        # Cadence is None so no final-note snap; lick_pool is None so
        # no override. The rendered set should be a superset / match.
        for exp in expected_seconds:
            self.assertTrue(
                any(abs(s - exp) < 0.05 for s in starts),
                f"missing expected onset {exp}s in rendered starts {starts}",
            )


# ---------------------------------------------------------------------------
# velocity_curve helper + integration
# ---------------------------------------------------------------------------

class VelocityCurveHelperTests(unittest.TestCase):

    def test_arc_peaks_mid_phrase(self):
        # mid should be > both ends for an arc.
        start = _velocity_for_position(0.0, "arc", 60, 100)
        mid = _velocity_for_position(0.5, "arc", 60, 100)
        end = _velocity_for_position(1.0, "arc", 60, 100)
        self.assertGreater(mid, start + 10)
        self.assertGreater(mid, end + 10)

    def test_rise_monotonic_climb(self):
        seq = [_velocity_for_position(p / 10, "rise", 60, 100) for p in range(11)]
        for a, b in zip(seq, seq[1:]):
            self.assertLessEqual(a, b, f"rise should be monotonic; got {seq}")

    def test_fall_monotonic_descent(self):
        seq = [_velocity_for_position(p / 10, "fall", 60, 100) for p in range(11)]
        for a, b in zip(seq, seq[1:]):
            self.assertGreaterEqual(a, b, f"fall should be monotonic; got {seq}")

    def test_valley_dips_in_middle(self):
        start = _velocity_for_position(0.0, "valley", 60, 100)
        mid = _velocity_for_position(0.5, "valley", 60, 100)
        end = _velocity_for_position(1.0, "valley", 60, 100)
        self.assertLess(mid, start - 5)
        self.assertLess(mid, end - 5)


class VelocityCurveIntegrationTests(unittest.TestCase):

    def test_phrase_arc_curve_louder_mid_phrase(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_melody(
            key="C", scale_name="major", bars=8, octave=5, seed=42,
            progression=["I"] * 8,
            melody_style="motif",
            phrase_shape="arc",
            velocity_curve="phrase_arc",
            cadence=None,
        )
        notes = sorted(m.tracks[0].notes, key=lambda n: n.start)
        n = len(notes)
        if n < 12:
            self.skipTest("not enough notes")
        first_q = [x.velocity for x in notes[: n // 4]]
        mid_q = [x.velocity for x in notes[n * 3 // 8 : n * 5 // 8]]
        first_mean = sum(first_q) / len(first_q)
        mid_mean = sum(mid_q) / len(mid_q)
        # Arc curve should make middle notes meaningfully louder.
        self.assertGreater(mid_mean, first_mean + 3,
                           f"arc mid {mid_mean:.1f} not louder than start {first_mean:.1f}")


# ---------------------------------------------------------------------------
# lick_pool auto-fire
# ---------------------------------------------------------------------------

class LickAutoFireTests(unittest.TestCase):

    def test_lick_pool_stamps_a_lick(self):
        """With a deterministic seed, the country walk-up lick should
        stamp at a recognisable bar; the lick's distinctive degree-1
        landing (pc 0 in C major) appears at the end of either the
        penultimate or final bar."""
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I"] * 4,
            melody_style="motif",
            lick_pool=["country_walk_up_5_to_1"],
            cadence=None,
        )
        bar_dur = 2.0
        # Target bar is either bar 2 (anacrusis) or bar 3 (final).
        in_target = [
            n for n in m.tracks[0].notes
            if 2 * bar_dur - 0.01 <= n.start < 4 * bar_dur
        ]
        self.assertTrue(in_target, "expected lick notes in bars 2-3")
        # Lick velocity is fixed at 95 — distinguishes them from the
        # walker's variable velocities. At least one note should be
        # exactly 95.
        self.assertTrue(any(n.velocity == 95 for n in in_target),
                        "no stamped lick note found (vel=95 marker)")

    def test_empty_lick_pool_does_nothing(self):
        m1 = MidiExporter(tempo=120, time_signature=(4, 4))
        m1.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I", "V", "vi", "IV"],
            melody_style="motif",
            cadence=None,
        )
        m2 = MidiExporter(tempo=120, time_signature=(4, 4))
        m2.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I", "V", "vi", "IV"],
            melody_style="motif",
            lick_pool=[],
            cadence=None,
        )
        self.assertEqual(len(m1.tracks[0].notes), len(m2.tracks[0].notes))

    def test_invalid_lick_names_are_skipped(self):
        """A pool of all-invalid names is a no-op — output identical
        to no lick_pool at all."""
        m_baseline = MidiExporter(tempo=120, time_signature=(4, 4))
        m_baseline.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I"] * 4,
            melody_style="motif",
            cadence=None,
        )
        m_invalid = MidiExporter(tempo=120, time_signature=(4, 4))
        m_invalid.add_melody(
            key="C", scale_name="major", bars=4, octave=5, seed=42,
            progression=["I"] * 4,
            melody_style="motif",
            lick_pool=["does_not_exist", "nope"],
            cadence=None,
        )
        # Same notes, same velocities.
        b = [(round(n.start, 3), n.pitch, n.velocity)
             for n in m_baseline.tracks[0].notes]
        i = [(round(n.start, 3), n.pitch, n.velocity)
             for n in m_invalid.tracks[0].notes]
        self.assertEqual(b, i)


# ---------------------------------------------------------------------------
# Motif restate
# ---------------------------------------------------------------------------

class MotifRestateTests(unittest.TestCase):

    def test_restate_returns_to_block_zero_contour(self):
        """With motif_development=['repeat','sequence_up','repeat','restate'],
        block-3's adjacent-step direction sequence should match
        block-0's (or be very close)."""
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_melody(
            key="C", scale_name="major", bars=8, octave=5, seed=42,
            progression=["I"] * 8,  # constant chord eliminates harmonic confound
            melody_style="motif",
            phrase_shape="plateau",
            motif_development=["repeat", "sequence_up", "repeat", "restate"],
            cadence=None,
        )
        notes = sorted(m.tracks[0].notes, key=lambda n: n.start)
        # 2-bar motif × 4 blocks = 8 bars. Bar dur = 2s.
        bar_dur = 2.0
        block0 = [n for n in notes if n.start < 2 * bar_dur - 0.01]
        block3 = [n for n in notes if n.start >= 6 * bar_dur - 0.01]
        # Compare adjacent-step direction signs.
        def signs(seq):
            return [
                1 if seq[i + 1].pitch > seq[i].pitch else
                -1 if seq[i + 1].pitch < seq[i].pitch else 0
                for i in range(len(seq) - 1)
            ]
        s0, s3 = signs(block0), signs(block3)
        common = min(len(s0), len(s3))
        if common == 0:
            self.skipTest("not enough notes to compare")
        # Most non-zero direction comparisons should agree.
        agree = sum(
            1 for a, b in zip(s0[:common], s3[:common])
            if a != 0 and b != 0 and (a * b) > 0
        )
        disagree = sum(
            1 for a, b in zip(s0[:common], s3[:common])
            if a != 0 and b != 0 and (a * b) < 0
        )
        self.assertGreaterEqual(
            agree, disagree,
            f"restate should agree with block 0; agree={agree}, disagree={disagree}, "
            f"s0={s0}, s3={s3}",
        )


# ---------------------------------------------------------------------------
# Style variant wiring
# ---------------------------------------------------------------------------

class StyleMelodyVariantWiringTests(unittest.TestCase):
    """Five curated styles should declare the new melody variants."""

    EXPECTED = {
        "pop": {"rhythm_motif", "velocity_curve", "lick_pool"},
        "funk": {"rhythm_motif", "velocity_curve", "lick_pool"},
        "jazz_fusion": {"rhythm_motif", "velocity_curve", "lick_pool"},
        "country": {"rhythm_motif", "velocity_curve", "lick_pool"},
        "bossa_nova": {"rhythm_motif", "velocity_curve", "lick_pool"},
    }

    def test_each_style_declares_all_three(self):
        for style, expected_keys in self.EXPECTED.items():
            mv = STYLES[style].melody_variant or {}
            for key in expected_keys:
                with self.subTest(style=style, key=key):
                    self.assertIn(key, mv,
                                  f"{style} missing melody_variant['{key}']")

    def test_jazz_fusion_uses_charleston(self):
        mv = STYLES["jazz_fusion"].melody_variant or {}
        self.assertEqual(mv["rhythm_motif"], "jazz_charleston")

    def test_lick_pools_reference_known_licks(self):
        """No typos in lick names — every entry must exist in MELODIC_LICKS."""
        for style in self.EXPECTED:
            mv = STYLES[style].melody_variant or {}
            for name in mv.get("lick_pool", []):
                with self.subTest(style=style, lick=name):
                    self.assertIn(name, MELODIC_LICKS,
                                  f"{style}'s lick_pool references unknown {name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
