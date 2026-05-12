"""Regression tests for the Melody Studio UI handler layer.

These exercise the plan ↔ dataframe round-trips, the loading/saving
flows, and the regenerate / preview entry points. Browser interaction
is out of scope (Gradio @gr.render is covered by the manual smoke).
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic import melody_plan as mp
from src.daw_integration.generic import blocks as block_store


def _reset_state():
    app._state.clear()
    app._state.update({
        "ai_wav_path": None, "midi_wav_path": None,
        "midi_path": None, "model": None,
    })


def _force_compose() -> None:
    """Run a deterministic compose so melody_load_from_compose has data."""
    app.compose_midi(
        style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
        bars=4, enable_chords=True, enable_bass=False,
        enable_melody=True, enable_drums=False,
        bass_pattern="root_fifth", drum_pattern="basic_rock",
        voicing="triad", swing=0.0, chord_rhythm="pulse_quarter",
        melody_style="motif", seed=42, progression_text="I V vi IV",
        extras=None,
        chord_octave=3, bass_octave=2, melody_octave=5,
        drum_grid_state=None, random_variation=False,
    )


class LoadFromComposeTests(unittest.TestCase):

    def setUp(self):
        _reset_state()

    def test_raises_when_no_compose_yet(self):
        with self.assertRaises(gr.Error) as cm:
            app.melody_load_from_compose()
        self.assertIn("Compose", str(cm.exception))

    def test_loads_melody_after_compose(self):
        _force_compose()
        plan = app.melody_load_from_compose()
        self.assertIsInstance(plan, mp.MelodyPlan)
        self.assertGreater(len(plan.notes), 0)
        self.assertEqual(plan.key, "C")
        self.assertEqual(plan.scale, "major")
        # Plan gets pinned to _state for subsequent UI actions
        self.assertIs(app._state.get("melody_plan"), plan)


class RenderViewsTests(unittest.TestCase):

    def setUp(self):
        _reset_state()
        _force_compose()
        self.plan = app.melody_load_from_compose()

    def test_returns_six_tuple(self):
        out = app.melody_render_views(self.plan)
        self.assertEqual(len(out), 6)

    def test_none_plan_returns_empty_views(self):
        header, note_rows, deg, pr, ov, hm = app.melody_render_views(None)
        self.assertIn("No plan", header)
        self.assertEqual(note_rows, [])
        self.assertEqual(deg["data"], [])
        self.assertEqual(pr["data"], [])

    def test_note_rows_match_plan_count(self):
        _, note_rows, _, _, _, _ = app.melody_render_views(self.plan)
        self.assertEqual(len(note_rows), len(self.plan.notes))

    def test_degree_grid_has_two_octaves(self):
        _, _, deg, _, _, _ = app.melody_render_views(self.plan)
        # C major (7 degrees) × 2 octaves = 14 rows
        self.assertEqual(len(deg["data"]), 14)

    def test_pianoroll_has_24_rows(self):
        _, _, _, pr, _, _ = app.melody_render_views(self.plan)
        # ±1 octave around the tonic
        self.assertEqual(len(pr["data"]), 24)


class NoteListRoundtripTests(unittest.TestCase):

    def test_roundtrip_preserves_notes(self):
        plan = mp.MelodyPlan(
            bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=0, beat=1.0, pitch=64, duration=1.0),
                mp.MelodyNote(bar=1, beat=2.0, pitch=67, duration=0.5),
            ],
        )
        rows = app._plan_to_note_rows(plan)
        self.assertEqual(len(rows), 3)
        rebuilt = app._note_rows_to_plan(rows, plan)
        self.assertEqual(len(rebuilt.notes), 3)
        # First note's fields preserved
        self.assertEqual(rebuilt.notes[0].pitch, 60)
        self.assertEqual(rebuilt.notes[1].pitch, 64)
        self.assertEqual(rebuilt.notes[2].duration, 0.5)

    def test_edit_pitch_propagates(self):
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0)],
        )
        rows = app._plan_to_note_rows(plan)
        rows[0][2] = 65  # change pitch to F
        new_plan = app._note_rows_to_plan(rows, plan)
        self.assertEqual(new_plan.notes[0].pitch, 65)

    def test_drop_row_removes_note(self):
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=0, beat=1.0, pitch=64, duration=1.0),
            ],
        )
        rows = app._plan_to_note_rows(plan)
        rows.pop(0)
        new_plan = app._note_rows_to_plan(rows, plan)
        self.assertEqual(len(new_plan.notes), 1)
        self.assertEqual(new_plan.notes[0].pitch, 64)


class DegreeGridRoundtripTests(unittest.TestCase):

    def test_grid_round_trip_in_scale_notes(self):
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=0.25),   # C → degree 1
                mp.MelodyNote(bar=0, beat=1.0, pitch=64, duration=0.25),   # E → degree 3
                mp.MelodyNote(bar=0, beat=2.0, pitch=67, duration=0.25),   # G → degree 5
            ],
        )
        rows, headers = app._plan_to_degree_grid(plan)
        # Re-derive plan from grid
        rebuilt = app._degree_grid_to_plan(rows, plan)
        # Same 3 pitches present (order may vary)
        pitches = sorted(n.pitch for n in rebuilt.notes)
        self.assertEqual(pitches, [60, 64, 67])

    def test_chromatic_notes_preserved_across_grid_toggle(self):
        # Eb (63) is chromatic in C major — grid can't represent it, but
        # the plan must not lose it.
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=0.25),
                mp.MelodyNote(bar=0, beat=1.0, pitch=63, duration=0.25),  # Eb
            ],
        )
        rows, _ = app._plan_to_degree_grid(plan)
        rebuilt = app._degree_grid_to_plan(rows, plan)
        pitches = sorted(n.pitch for n in rebuilt.notes)
        self.assertIn(63, pitches, "chromatic note dropped during grid round-trip")


# The old Dataframe-based override/harmony converters were retired when
# Section Overrides + Harmonies moved to a @gr.render row-based UI. The
# new dict-form converters and per-row keys are exercised by
# test_melody_studio_iter.py — see OverrideStateListTests,
# HarmonyStateListTests, and RowWidgetKeysTests there.


class RegenerateAndSaveTests(unittest.TestCase):

    def setUp(self):
        _reset_state()
        _force_compose()
        self.plan = app.melody_load_from_compose()

    def test_regenerate_full_when_blank_range(self):
        new_plan = app.melody_regenerate(self.plan, "", 7, "motif")
        self.assertEqual(new_plan.bars, self.plan.bars)

    def test_regenerate_partial_range_preserves_outside(self):
        new_plan = app.melody_regenerate(self.plan, "0:2", 7, "motif")
        # Notes in bars 2..N preserved
        outside_orig = sorted(
            (n.bar, n.beat, n.pitch)
            for n in self.plan.notes if n.bar >= 2
        )
        outside_new = sorted(
            (n.bar, n.beat, n.pitch)
            for n in new_plan.notes if n.bar >= 2
        )
        self.assertEqual(outside_orig, outside_new)

    def test_save_plan_writes_yaml_sibling(self):
        name = "_test_studio_save"
        msg = app.melody_save_plan(self.plan, name)
        yaml_path = block_store.BLOCKS_DIR / f"{name}_melody.yaml"
        try:
            self.assertTrue(yaml_path.exists())
            restored = mp.from_yaml(yaml_path)
            self.assertEqual(len(restored.notes), len(self.plan.notes))
        finally:
            if yaml_path.exists():
                yaml_path.unlink()

    def test_save_requires_name(self):
        with self.assertRaises(gr.Error):
            app.melody_save_plan(self.plan, "")
        with self.assertRaises(gr.Error):
            app.melody_save_plan(self.plan, "   ")


class PreviewTests(unittest.TestCase):

    def setUp(self):
        _reset_state()
        _force_compose()

    def test_preview_returns_wav_path(self):
        plan = app.melody_load_from_compose()
        wav_path = app.melody_preview(plan)
        self.assertTrue(wav_path.endswith(".wav"))
        self.assertTrue(Path(wav_path).exists())

    def test_preview_none_plan_raises(self):
        with self.assertRaises(gr.Error):
            app.melody_preview(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
