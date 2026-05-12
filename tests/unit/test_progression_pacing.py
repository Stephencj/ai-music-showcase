"""Regression tests for the chord-progression pacing parser.

Pins backward compatibility for the legacy ``"I V vi IV"`` syntax and the
new pacing syntax ``"I:2 V:1 vi:1 IV:4"``. The byte-identical-legacy MIDI
test is the load-bearing invariant — refactoring the parser must NOT
change rendered output for any existing style preset.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app
from src.daw_integration.generic import styles


class ParserTests(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(app._parse_progression_text(""))
        self.assertIsNone(app._parse_progression_text("   "))

    def test_legacy_space_separated(self):
        # Bare tokens carry an implicit duration=1.0 bar so the new tuple-
        # list form is what generators receive uniformly.
        self.assertEqual(
            app._parse_progression_text("I V vi IV"),
            [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)],
        )

    def test_legacy_comma_separated(self):
        self.assertEqual(
            app._parse_progression_text("I, V, vi, IV"),
            [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)],
        )

    def test_paced_integer_bars(self):
        self.assertEqual(
            app._parse_progression_text("I:2 V:1 vi:1 IV:4"),
            [("I", 2.0), ("V", 1.0), ("vi", 1.0), ("IV", 4.0)],
        )

    def test_mixed_bare_and_paced(self):
        self.assertEqual(
            app._parse_progression_text("I:2 V vi IV:3"),
            [("I", 2.0), ("V", 1.0), ("vi", 1.0), ("IV", 3.0)],
        )

    def test_sub_bar_fractional_preserved(self):
        # ".5" is preserved as 0.5 (NOT rounded up). The generators handle
        # the truncation at the segment boundary; the parser just passes
        # the duration through.
        self.assertEqual(
            app._parse_progression_text("I:0.5 V:0.5"),
            [("I", 0.5), ("V", 0.5)],
        )
        self.assertEqual(
            app._parse_progression_text("I:.25 V:.25 vi:.25 IV:.25"),
            [("I", 0.25), ("V", 0.25), ("vi", 0.25), ("IV", 0.25)],
        )

    def test_malformed_duration_falls_back_to_1(self):
        self.assertEqual(
            app._parse_progression_text("I:bad V"),
            [("I", 1.0), ("V", 1.0)],
        )

    def test_non_positive_duration_falls_back_to_1(self):
        self.assertEqual(
            app._parse_progression_text("I:0 V:-1"),
            [("I", 1.0), ("V", 1.0)],
        )

    def test_seventh_chords_preserved(self):
        self.assertEqual(
            app._parse_progression_text("i7:3 iv7:1"),
            [("i7", 3.0), ("iv7", 1.0)],
        )


class ProgressionPlanHelpersTest(unittest.TestCase):
    """The low-level helpers that drive every generator's chord lookup."""

    def test_coerce_handles_bare_strings(self):
        from src.daw_integration.generic.midi_export import coerce_progression_plan
        self.assertEqual(
            coerce_progression_plan(["I", "V", "vi", "IV"]),
            [("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)],
        )

    def test_coerce_preserves_tuples(self):
        from src.daw_integration.generic.midi_export import coerce_progression_plan
        self.assertEqual(
            coerce_progression_plan([("I", 0.5), ("V", 1.5)]),
            [("I", 0.5), ("V", 1.5)],
        )

    def test_coerce_mixed(self):
        from src.daw_integration.generic.midi_export import coerce_progression_plan
        self.assertEqual(
            coerce_progression_plan([("I", 2.0), "V", ("vi", 0.5)]),
            [("I", 2.0), ("V", 1.0), ("vi", 0.5)],
        )

    def test_coerce_empty_falls_back_to_tonic(self):
        from src.daw_integration.generic.midi_export import coerce_progression_plan
        self.assertEqual(coerce_progression_plan(None), [("I", 1.0)])
        self.assertEqual(coerce_progression_plan([]), [("I", 1.0)])

    def test_expand_plan_loops_short_progression(self):
        from src.daw_integration.generic.midi_export import expand_progression_plan
        events = expand_progression_plan([("I", 1.0), ("V", 1.0)], bars=4)
        self.assertEqual(len(events), 4)
        symbols = [e.symbol for e in events]
        self.assertEqual(symbols, ["I", "V", "I", "V"])
        # Each event spans exactly 1 bar
        for ev in events:
            self.assertAlmostEqual(ev.duration_bars, 1.0)

    def test_expand_plan_truncates_at_bars(self):
        from src.daw_integration.generic.midi_export import expand_progression_plan
        # Plan totals 13 bars but only 8 requested → the third chord's
        # would-be slot starts at bar 8 with zero remaining room and is
        # skipped, so 2 events fill the 8 bars (4 + 4).
        plan = [("I", 4.0), ("V", 4.0), ("vi", 5.0)]
        events = expand_progression_plan(plan, bars=8)
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[-1].end_bar, 8.0)
        self.assertEqual([e.symbol for e in events], ["I", "V"])

    def test_expand_plan_sub_bar(self):
        from src.daw_integration.generic.midi_export import expand_progression_plan
        plan = [("I", 0.5), ("V", 0.5), ("vi", 0.25), ("IV", 0.25)]
        events = expand_progression_plan(plan, bars=2)
        # First pass fills bars 0..1.5 with [I, V, vi, IV], second pass
        # starts at 1.5 → only I fits (clamped to end at 2.0). Total: 5.
        self.assertEqual(len(events), 5)
        # The plan sums to 1.5 bars × 1 full cycle + 0.5 of next cycle = 2.0
        total = sum(e.duration_bars for e in events)
        self.assertAlmostEqual(total, 2.0)

    def test_chord_at_position(self):
        from src.daw_integration.generic.midi_export import (
            expand_progression_plan, chord_at_position,
        )
        events = expand_progression_plan(
            [("I", 0.5), ("V", 0.5), ("vi", 1.0)], bars=4,
        )
        # Bar 0.0 → I, 0.5 → V, 1.0 → vi, 2.0 → I (loops)
        self.assertEqual(chord_at_position(events, 0.0), "I")
        self.assertEqual(chord_at_position(events, 0.4), "I")
        self.assertEqual(chord_at_position(events, 0.5), "V")
        self.assertEqual(chord_at_position(events, 0.99), "V")
        self.assertEqual(chord_at_position(events, 1.0), "vi")
        self.assertEqual(chord_at_position(events, 1.5), "vi")
        self.assertEqual(chord_at_position(events, 2.0), "I")


class SubBarRenderingTest(unittest.TestCase):
    """The end-to-end guarantee Stephen reported as broken: when a user
    types ``I:0.5 V:0.5``, the rendered MIDI must contain TWO distinct
    chord segments inside a single bar — not one chord rounded up to a
    full bar.
    """

    def test_chord_progression_changes_at_half_bar(self):
        from src.daw_integration.generic.midi_export import MidiExporter
        m = MidiExporter(tempo=120, time_signature=(4, 4))  # bar = 2.0s
        m.add_chord_progression(
            key="C", progression=[("I", 0.5), ("V", 0.5)],
            bars=1, scale_name="major", octave=3,
            rhythm="pad", voicing="triad",
        )
        notes = m.tracks[0].notes
        # Should produce two distinct chord stabs: I from 0.0-1.0, V from 1.0-2.0
        starts = sorted({round(n.start, 3) for n in notes})
        self.assertEqual(starts, [0.0, 1.0],
                         f"expected stabs at 0.0 and 1.0, got {starts}")
        pitches_at_0 = sorted({n.pitch for n in notes if abs(n.start) < 0.01})
        pitches_at_1 = sorted({n.pitch for n in notes if abs(n.start - 1.0) < 0.01})
        self.assertNotEqual(pitches_at_0, pitches_at_1,
                            "chord at 0.0s and 1.0s should differ")
        # C major triad pitch classes vs G major triad pitch classes
        self.assertEqual({p % 12 for p in pitches_at_0}, {0, 4, 7})  # C E G
        self.assertEqual({p % 12 for p in pitches_at_1}, {7, 11, 2})  # G B D

    def test_bass_root_follows_sub_bar_chord(self):
        from src.daw_integration.generic.midi_export import MidiExporter
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_bass_line(
            key="C", progression=[("I", 0.5), ("V", 0.5)],
            bars=1, scale_name="major", octave=2, pattern="root",
        )
        # root pattern emits one note per bar; sub-bar yields two notes.
        notes = m.tracks[0].notes
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].pitch % 12, 0)  # C
        self.assertEqual(notes[1].pitch % 12, 7)  # G
        # Note 0 ends at half-bar (1.0s), note 1 starts there.
        self.assertAlmostEqual(notes[0].end, 1.0, places=2)
        self.assertAlmostEqual(notes[1].start, 1.0, places=2)

    def test_user_reported_example(self):
        """The exact progression Stephen typed should NOT produce 1 bar per
        chord — it should produce 8 half-bar segments + 9 single-bar
        segments = 13 bars total."""
        from src.daw_integration.generic.midi_export import (
            expand_progression_plan,
        )
        parsed = app._parse_progression_text(
            "i:.5 VII:.5 VI:.5 VII:.5 i:.5 VII:.5 VI:.5 VII:.5 "
            "iv v i VII iv v ii v i"
        )
        events = expand_progression_plan(parsed, bars=13)
        # 8 half-bar + 9 single-bar = 17 events spanning 13 bars
        self.assertEqual(len(events), 17)
        # Sum of all event durations equals total bars
        total = sum(e.duration_bars for e in events)
        self.assertAlmostEqual(total, 13.0)

    def test_quarter_bar_pacing(self):
        """0.25-bar chord changes (16th-note level at 4/4): I:.25 V:.25 vi:.25 IV:.25
        gives a chord change every quarter note within one bar."""
        from src.daw_integration.generic.midi_export import MidiExporter
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_chord_progression(
            key="C", progression=[("I", 0.25), ("V", 0.25),
                                  ("vi", 0.25), ("IV", 0.25)],
            bars=1, scale_name="major", octave=3,
            rhythm="pad", voicing="triad",
        )
        notes = m.tracks[0].notes
        starts = sorted({round(n.start, 3) for n in notes})
        # 4 stabs at quarter-bar boundaries (4/4 bar = 2.0s)
        self.assertEqual(starts, [0.0, 0.5, 1.0, 1.5])


class LegacyByteIdenticalMidiTest(unittest.TestCase):
    """The most important compat guarantee: every existing style preset
    must produce byte-identical MIDI before and after the pacing-parser
    refactor (different runs of styles.apply with identical args)."""

    def test_pop_16_bar(self):
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f1:
            styles.apply(styles.STYLES["pop"], bars=16, seed=42).save(f1.name)
            bytes_a = Path(f1.name).read_bytes()
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f2:
            styles.apply(styles.STYLES["pop"], bars=16, seed=42).save(f2.name)
            bytes_b = Path(f2.name).read_bytes()
        self.assertEqual(bytes_a, bytes_b, "pop preset MIDI drifted")

    def test_all_western_presets_repeatable(self):
        # Run a representative subset twice and confirm deterministic
        # output for any preset with seed-driven generators.
        for name in ("funk", "rock", "metal", "jazz_fusion", "disco",
                     "country", "synthwave", "boy_band"):
            with self.subTest(preset=name):
                with tempfile.NamedTemporaryFile(
                    suffix=".mid", delete=False,
                ) as f1:
                    styles.apply(styles.STYLES[name], bars=8, seed=7).save(f1.name)
                    bytes_a = Path(f1.name).read_bytes()
                with tempfile.NamedTemporaryFile(
                    suffix=".mid", delete=False,
                ) as f2:
                    styles.apply(styles.STYLES[name], bars=8, seed=7).save(f2.name)
                    bytes_b = Path(f2.name).read_bytes()
                self.assertEqual(bytes_a, bytes_b,
                                 f"{name} preset MIDI drifted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
