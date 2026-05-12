"""Regression tests for the Melody plan headless engine.

Covers:
  - Dataclass YAML round-trip (notes / overrides / harmonies preserved).
  - Plain ``render_melody_plan`` produces a passthrough melody when no
    overrides are present (one rendered note per ``MelodyNote``).
  - Each ``SectionOverride.mode`` (stack / replace / decoration) produces
    the expected note-count shape relative to the underlying melody.
  - ``regenerate_bars`` preserves notes outside the range and replaces
    notes inside it.
  - ``melody_plan_from_track`` is the inverse of the plain render path
    (modulo bar inference).
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.melody_plan import (
    HarmonyTag,
    MelodyNote,
    MelodyPlan,
    SectionOverride,
    from_yaml,
    melody_plan_from_track,
    regenerate_bars,
    render_melody_plan,
    to_yaml,
)
from src.daw_integration.generic.midi_export import (
    NoteEvent,
    Track,
)


def _simple_plan() -> MelodyPlan:
    """A 2-bar C-major plan with 4 notes per bar — used by several tests."""
    return MelodyPlan(
        bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
        notes=[
            MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
            MelodyNote(bar=0, beat=1.0, pitch=64, duration=1.0),
            MelodyNote(bar=0, beat=2.0, pitch=67, duration=1.0),
            MelodyNote(bar=0, beat=3.0, pitch=60, duration=1.0),
            MelodyNote(bar=1, beat=0.0, pitch=62, duration=1.0),
            MelodyNote(bar=1, beat=1.0, pitch=65, duration=1.0),
            MelodyNote(bar=1, beat=2.0, pitch=69, duration=1.0),
            MelodyNote(bar=1, beat=3.0, pitch=62, duration=1.0),
        ],
    )


class YamlRoundtripTests(unittest.TestCase):

    def test_simple_plan_roundtrips(self):
        plan = _simple_plan()
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        to_yaml(plan, path)
        restored = from_yaml(path)
        self.assertEqual(restored.bars, plan.bars)
        self.assertEqual(restored.time_signature, plan.time_signature)
        self.assertEqual(restored.key, plan.key)
        self.assertEqual(restored.scale, plan.scale)
        self.assertEqual(restored.notes, plan.notes)
        Path(path).unlink()

    def test_overrides_and_harmonies_roundtrip(self):
        plan = _simple_plan()
        plan.section_overrides = [
            SectionOverride(start_bar=0, end_bar=1, voicing="ninth",
                            rhythm="stabs_8th", mode="stack", seed=42),
            SectionOverride(start_bar=1, end_bar=2, voicing="sus4_add9",
                            rhythm="arpeggio_up", mode="replace"),
        ]
        plan.harmonies = [
            HarmonyTag(start_bar=0, end_bar=2, preset="queen",
                       intervals=[2, 4]),
        ]
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            path = f.name
        to_yaml(plan, path)
        restored = from_yaml(path)
        self.assertEqual(restored.section_overrides, plan.section_overrides)
        self.assertEqual(restored.harmonies, plan.harmonies)
        Path(path).unlink()


class PassthroughRenderTests(unittest.TestCase):

    def test_no_override_emits_one_note_per_plan_note(self):
        plan = _simple_plan()
        mel, harm = render_melody_plan(plan, progression=["I", "V"])
        self.assertEqual(len(mel.notes), len(plan.notes))
        self.assertIsNone(harm)

    def test_velocity_preserved(self):
        plan = MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0,
                              velocity=42)],
        )
        mel, _ = render_melody_plan(plan)
        self.assertEqual(mel.notes[0].velocity, 42)

    def test_bar_beat_to_seconds_conversion(self):
        # At 120 BPM in 4/4 each bar = 2.0s, each beat = 0.5s
        plan = MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[MelodyNote(bar=0, beat=2.0, pitch=60, duration=1.0)],
        )
        mel, _ = render_melody_plan(plan)
        self.assertAlmostEqual(mel.notes[0].start, 1.0, places=3)


class StackModeTests(unittest.TestCase):

    def test_stack_multiplies_notes_via_rhythm(self):
        plan = MelodyPlan(
            bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                MelodyNote(bar=0, beat=0.0, pitch=60, duration=4.0),
                MelodyNote(bar=1, beat=0.0, pitch=60, duration=4.0),
            ],
            section_overrides=[
                SectionOverride(start_bar=0, end_bar=1, voicing="triad",
                                rhythm="stabs_8th", mode="stack"),
            ],
        )
        mel, _ = render_melody_plan(plan, progression=["I", "I"])
        bar0 = [n for n in mel.notes if n.start < 2.0]
        bar1 = [n for n in mel.notes if n.start >= 2.0]
        # Bar 0 has stack mode: 8 rhythm hits × ≥3 stack pitches = ≥24
        self.assertGreater(len(bar0), len(bar1) * 8,
                           "stack should fire rhythm × voicing")
        # Bar 1 is pass-through (no override) → 1 note
        self.assertEqual(len(bar1), 1)

    def test_stack_uses_melody_pitch_as_bass(self):
        plan = MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[MelodyNote(bar=0, beat=0.0, pitch=60, duration=4.0)],
            section_overrides=[
                SectionOverride(start_bar=0, end_bar=1, voicing="triad",
                                rhythm="pad", mode="stack"),
            ],
        )
        mel, _ = render_melody_plan(plan)
        pitches = sorted({n.pitch for n in mel.notes})
        self.assertIn(60, pitches, "melody-note pitch should be in the stack")
        self.assertGreater(len(pitches), 1, "stack should add voicing pitches")


class ReplaceModeTests(unittest.TestCase):

    def test_replace_discards_melody_pitch(self):
        # Use a melody pitch not in the chord (high B = 71). Replace should
        # discard it and emit only chord-tone pitches.
        plan = MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[MelodyNote(bar=0, beat=0.0, pitch=71, duration=4.0)],
            section_overrides=[
                SectionOverride(start_bar=0, end_bar=1, voicing="triad",
                                rhythm="pulse_quarter", mode="replace"),
            ],
        )
        mel, _ = render_melody_plan(plan, progression=["I"])
        # pulse_quarter × triad (3 pitches) = 12 hits
        self.assertEqual(len(mel.notes), 4 * 3)
        # B (71) should be absent from the replaced output (chord = C, E, G)
        pitch_classes = {n.pitch % 12 for n in mel.notes}
        self.assertNotIn(71 % 12, {0, 4, 7})  # sanity: B isn't C/E/G
        # The output's pitch classes should be the C-major triad
        self.assertTrue(pitch_classes.issubset({0, 4, 7}),
                        f"replace produced non-chord pitches: {pitch_classes}")


class DecorationModeTests(unittest.TestCase):

    def test_decoration_preserves_melody_and_adds_notes(self):
        plan = MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                MelodyNote(bar=0, beat=0.0, pitch=60, duration=2.0),
                MelodyNote(bar=0, beat=2.0, pitch=64, duration=2.0),
            ],
            section_overrides=[
                SectionOverride(start_bar=0, end_bar=1, voicing="triad",
                                rhythm="stabs_8th", mode="decoration"),
            ],
        )
        mel, _ = render_melody_plan(plan, progression=["I"])
        # Melody pitches should appear in the output
        pitches = [n.pitch for n in mel.notes]
        self.assertIn(60, pitches)
        self.assertIn(64, pitches)
        # Decoration adds ornaments → total notes > 2
        self.assertGreater(len(mel.notes), 2)


class RegenerateBarsTests(unittest.TestCase):

    def test_outside_range_notes_preserved(self):
        plan = _simple_plan()
        new = regenerate_bars(plan, start_bar=1, end_bar=2, seed=7)
        bar0_originals = [n for n in plan.notes if n.bar == 0]
        bar0_new = [n for n in new.notes if n.bar == 0]
        self.assertEqual(bar0_new, bar0_originals)

    def test_inside_range_notes_replaced(self):
        plan = _simple_plan()
        new = regenerate_bars(plan, start_bar=1, end_bar=2, seed=7,
                              progression=["V"])
        bar1_originals = [n for n in plan.notes if n.bar == 1]
        bar1_new = [n for n in new.notes if n.bar == 1]
        # New bar 1 should not equal the originals (probability 1 with seed)
        self.assertNotEqual(bar1_new, bar1_originals)

    def test_total_bars_unchanged(self):
        plan = _simple_plan()
        new = regenerate_bars(plan, start_bar=0, end_bar=1, seed=7)
        self.assertEqual(new.bars, plan.bars)


class FromTrackTests(unittest.TestCase):

    def test_basic_conversion(self):
        track = Track(name="Melody", program=0)
        # 120 BPM 4/4 → bar = 2s, beat = 0.5s
        track.notes.extend([
            NoteEvent(60, 0.0, 0.5, 80),
            NoteEvent(64, 0.5, 1.0, 80),
            NoteEvent(67, 2.0, 2.5, 80),   # bar 1
        ])
        plan = melody_plan_from_track(
            track, key="C", scale="major",
            time_signature=(4, 4), tempo=120,
        )
        self.assertEqual(plan.bars, 2)
        self.assertEqual(plan.notes[0].bar, 0)
        self.assertAlmostEqual(plan.notes[0].beat, 0.0, places=2)
        self.assertEqual(plan.notes[2].bar, 1)
        self.assertAlmostEqual(plan.notes[2].beat, 0.0, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
