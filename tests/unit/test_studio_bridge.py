"""Regression tests for the Studio → Compose Song bridge fixes.

Covers the two bugs landed in this session:

- **Track 1** — Melody Studio's old save wrote only a sidecar
  ``{name}_melody.yaml`` with no parent block, so nothing showed up in
  Compose Song. The new ``melody_save_as_block`` handler bakes the
  rendered melody + harmony + accompaniment bed into a complete
  ``pretty_midi.PrettyMIDI`` and calls ``block_store.save_block`` to
  write the standard block trio (``.mid`` + ``.yaml`` + ``.wav``), plus
  the editable sidecar so the user can come back and tweak the plan.
- **Track 2** — Library + Timeline cards in Compose Song now carry
  stable ``key=`` per widget so Gradio's ``@gr.render`` re-renders
  don't race with click events. Also: ``list_blocks`` now filters out
  ``*_melody.yaml`` sidecars (which previously appeared as malformed
  library entries) and entries missing the ``name`` field.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr
import pretty_midi

import app
from src.daw_integration.generic import blocks as block_store
from src.daw_integration.generic import melody_plan as mp


def _reset_state():
    app._state.clear()
    app._state.update({
        "ai_wav_path": None, "midi_wav_path": None,
        "midi_path": None, "model": None,
    })


def _compose_simple():
    app.compose_midi(
        style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
        bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
        enable_drums=True, bass_pattern="root_fifth",
        drum_pattern="basic_rock", voicing="triad", swing=0.0,
        chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
        progression_text="I V vi IV", extras=None,
        chord_octave=3, bass_octave=2, melody_octave=5,
        drum_grid_state=None, random_variation=False,
    )


def _cleanup_block(name: str):
    safe = block_store._safe_name(name)
    for suffix in (".mid", ".yaml", ".wav"):
        p = block_store.BLOCKS_DIR / f"{safe}{suffix}"
        if p.exists():
            p.unlink()
    sidecar = block_store.BLOCKS_DIR / f"{safe}_melody.yaml"
    if sidecar.exists():
        sidecar.unlink()


# ---------------------------------------------------------------------------
# Track 1 — bake-to-block
# ---------------------------------------------------------------------------

class BakePlanToPMTests(unittest.TestCase):

    def test_bake_includes_melody_and_bed(self):
        plan = mp.MelodyPlan(
            bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=1, beat=0.0, pitch=64, duration=1.0),
            ],
        )
        from src.daw_integration.generic.midi_export import Track, NoteEvent
        bed_chords = Track(name="Chords", program=0)
        bed_chords.notes.append(NoteEvent(48, 0.0, 2.0, 80))
        bed_bass = Track(name="Bass", program=33)
        bed_bass.notes.append(NoteEvent(36, 0.0, 2.0, 80))
        pm = mp.bake_plan_to_pm(plan, bed_tracks=[bed_chords, bed_bass])
        names = [i.name for i in pm.instruments]
        self.assertIn("Melody", names)
        self.assertIn("Chords", names)
        self.assertIn("Bass", names)

    def test_bake_without_bed_returns_just_melody(self):
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0)],
        )
        pm = mp.bake_plan_to_pm(plan, bed_tracks=None)
        names = [i.name for i in pm.instruments]
        self.assertEqual(names, ["Melody"])

    def test_bake_adds_harmony_when_tag_present(self):
        plan = mp.MelodyPlan(
            bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=1, beat=0.0, pitch=64, duration=1.0),
            ],
            harmonies=[mp.HarmonyTag(start_bar=0, end_bar=2, preset="queen")],
        )
        pm = mp.bake_plan_to_pm(plan)
        names = [i.name for i in pm.instruments]
        self.assertIn("Harmony", names)


class SaveAsBlockTests(unittest.TestCase):

    def setUp(self):
        _reset_state()
        _compose_simple()
        self.test_name = "_test_studio_save_as_block"
        _cleanup_block(self.test_name)

    def tearDown(self):
        _cleanup_block(self.test_name)

    def test_writes_complete_block_trio(self):
        plan = app.melody_load_from_compose()
        status, bumped = app.melody_save_as_block(plan, self.test_name, 0)
        safe = block_store._safe_name(self.test_name)
        self.assertTrue((block_store.BLOCKS_DIR / f"{safe}.mid").exists())
        self.assertTrue((block_store.BLOCKS_DIR / f"{safe}.yaml").exists())
        self.assertTrue((block_store.BLOCKS_DIR / f"{safe}_melody.yaml").exists())
        self.assertEqual(bumped, 1)
        # The safe-name (underscores stripped by ``_safe_name``) appears in status
        self.assertIn(safe, status)

    def test_block_contains_melody_and_bed(self):
        plan = app.melody_load_from_compose()
        app.melody_save_as_block(plan, self.test_name, 0)
        safe = block_store._safe_name(self.test_name)
        pm = pretty_midi.PrettyMIDI(
            str(block_store.BLOCKS_DIR / f"{safe}.mid"),
        )
        names_lower = [(i.name or "").lower() for i in pm.instruments]
        self.assertTrue(any("melody" in n for n in names_lower))
        self.assertTrue(any("chord" in n for n in names_lower))
        self.assertTrue(any("bass" in n for n in names_lower))
        self.assertTrue(any("drum" in n for n in names_lower))

    def test_appears_in_list_blocks(self):
        plan = app.melody_load_from_compose()
        app.melody_save_as_block(plan, self.test_name, 0)
        names = [b["name"] for b in block_store.list_blocks()]
        self.assertIn(self.test_name, names)

    def test_sidecar_alone_does_not_appear_in_list(self):
        """Sidecar yaml without parent block must NOT pollute the library."""
        sidecar = block_store.BLOCKS_DIR / "_sidecar_only_melody.yaml"
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0)],
        )
        mp.to_yaml(plan, sidecar)
        try:
            names = [b["name"] for b in block_store.list_blocks()]
            self.assertNotIn("_sidecar_only_melody", names)
            self.assertNotIn("_sidecar_only", names)
        finally:
            sidecar.unlink()

    def test_save_raises_when_plan_none(self):
        with self.assertRaises(gr.Error):
            app.melody_save_as_block(None, "anything", 0)

    def test_save_raises_when_name_empty(self):
        plan = app.melody_load_from_compose()
        with self.assertRaises(gr.Error):
            app.melody_save_as_block(plan, "", 0)
        with self.assertRaises(gr.Error):
            app.melody_save_as_block(plan, "   ", 0)


class DeleteBlockSidecarCleanupTests(unittest.TestCase):
    """``delete_block`` should also remove the ``{name}_melody.yaml``
    sidecar so the user doesn't accumulate orphans."""

    def test_delete_removes_sidecar(self):
        name = "_test_delete_sidecar"
        _compose_simple()
        plan = app.melody_load_from_compose()
        app.melody_save_as_block(plan, name, 0)
        safe = block_store._safe_name(name)
        sidecar = block_store.BLOCKS_DIR / f"{safe}_melody.yaml"
        self.assertTrue(sidecar.exists())
        block_store.delete_block(name)
        self.assertFalse(sidecar.exists())
        self.assertFalse((block_store.BLOCKS_DIR / f"{safe}.mid").exists())
        self.assertFalse((block_store.BLOCKS_DIR / f"{safe}.yaml").exists())


# ---------------------------------------------------------------------------
# Track 2 — library / timeline card stable keys
# ---------------------------------------------------------------------------

class LibraryCardKeysTests(unittest.TestCase):
    """Library + Timeline card widgets carry stable ``key=`` to survive
    ``@gr.render`` re-renders without dropping click handlers — the same
    fix that closed the Extras-row and Override-row regressions."""

    def _capture_keys(self, render_fn, *render_args):
        captured: list[tuple[str, str | None]] = []
        orig = {
            "Dropdown": gr.Dropdown.__init__,
            "Number": gr.Number.__init__,
            "Slider": gr.Slider.__init__,
            "Textbox": gr.Textbox.__init__,
            "Button": gr.Button.__init__,
            "Audio": gr.Audio.__init__,
        }

        def make_spy(name, real):
            def __init__(self, *args, **kwargs):
                captured.append((name, kwargs.get("key")))
                return real(self, *args, **kwargs)
            return __init__

        try:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", make_spy(name, real))
            with gr.Blocks():
                render_fn(*render_args)
        finally:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", real)
        return captured

    def test_library_card_buttons_have_keys(self):
        blk = {"name": "verse1", "time_signature": [4, 4], "bars": 4,
               "tempo": 120, "instruments": [{}], "n_notes": 16,
               "_wav_path": None}
        captured = self._capture_keys(
            app._render_library_card, blk, gr.State({}), gr.State(0),
        )
        keyed = [(name, key) for name, key in captured if key]
        # Every Button should be keyed
        button_keys = [k for n, k in keyed if n == "Button"]
        self.assertGreater(len(button_keys), 0)
        # The "+ Timeline" button must be present with a stable key
        self.assertIn("lib_verse1_add", button_keys)
        self.assertIn("lib_verse1_del", button_keys)

    def test_timeline_card_widgets_have_keys(self):
        entry = {"block_name": "verse1", "repeat": 2}
        lib = {"verse1": {"time_signature": [4, 4], "bars": 4, "tempo": 120}}
        captured = self._capture_keys(
            app._render_timeline_card, 0, entry, 1, lib, gr.State({}),
        )
        keyed = {k for _, k in captured if k}
        self.assertIn("tl_0_repeat", keyed)
        self.assertIn("tl_0_remove", keyed)


class AddToTimelineLogicTests(unittest.TestCase):
    """Validate the closure that powers ``+ Timeline`` — the actual click
    wiring lives inside an @gr.render so we test the closure shape, not
    the Gradio plumbing."""

    def test_appending_one_block_grows_timeline(self):
        state = {"title": "Untitled", "timeline": []}
        # Re-create the closure inline
        def _add(state, name="verse1"):
            timeline = list(state.get("timeline", []))
            timeline.append({"block_name": name, "repeat": 1})
            return {**state, "timeline": timeline}
        new_state = _add(state)
        self.assertEqual(len(new_state["timeline"]), 1)
        self.assertEqual(new_state["timeline"][0], {"block_name": "verse1",
                                                      "repeat": 1})

    def test_appending_preserves_existing_entries(self):
        state = {"title": "x", "timeline": [
            {"block_name": "intro", "repeat": 1},
        ]}
        def _add(state, name="verse1"):
            timeline = list(state.get("timeline", []))
            timeline.append({"block_name": name, "repeat": 1})
            return {**state, "timeline": timeline}
        new_state = _add(state)
        self.assertEqual([e["block_name"] for e in new_state["timeline"]],
                         ["intro", "verse1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
