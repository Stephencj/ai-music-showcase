"""Regression tests for the Melody Studio iteration fixes.

Covers the three tracks landed in this session:

- **Track A** — row-based UI replaces the dataframes for Section
  Overrides and Harmonies. Every dynamically-rendered widget carries a
  stable ``key=`` so Gradio's ``@gr.render`` re-renders don't race with
  ``.change`` events (same fix as the earlier Extras-row bug).
- **Track B** — ``MidiExporter.add_harmony`` accepts the
  ``ProgressionPlan`` shape (``list[tuple[str, float]]``) used by the
  rest of the system post-fractional-pacing. Previously it indexed
  ``progression[idx]`` directly and silently no-op'd on tuple lists.
- **Track C** — the Studio preview can optionally layer the loaded
  block's non-melody tracks ("bed") under the rendered melody.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic import melody_plan as mp
from src.daw_integration.generic.midi_export import (
    MidiExporter,
    NoteEvent,
    Track,
)


def _reset_state():
    app._state.clear()
    app._state.update({
        "ai_wav_path": None, "midi_wav_path": None,
        "midi_path": None, "model": None,
    })


def _compose_simple():
    """Deterministic pop compose so the Studio handlers have data."""
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


# ---------------------------------------------------------------------------
# Track B — paced progression no longer breaks add_harmony
# ---------------------------------------------------------------------------

class HarmonyPacedProgressionTests(unittest.TestCase):
    """``add_harmony`` previously indexed ``progression[prog_idx]``, which
    returned tuples when the progression carried pacing. The harmony track
    silently came back empty. Now it uses ``chord_at_position`` like the
    melody / bass / lead generators do, so paced progressions work."""

    def test_paced_progression_produces_harmony(self):
        plan = mp.MelodyPlan(
            bars=4, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=0, beat=1.0, pitch=64, duration=1.0),
                mp.MelodyNote(bar=1, beat=0.0, pitch=67, duration=1.0),
                mp.MelodyNote(bar=2, beat=0.0, pitch=72, duration=1.0),
                mp.MelodyNote(bar=3, beat=0.0, pitch=67, duration=1.0),
            ],
            harmonies=[
                mp.HarmonyTag(start_bar=0, end_bar=4, preset="queen"),
            ],
        )
        paced = [("I", 0.5), ("V", 0.5), ("vi", 1.0), ("IV", 1.0), ("I", 1.0)]
        mel, harm = mp.render_melody_plan(plan, progression=paced)
        self.assertEqual(len(mel.notes), 5, "melody should be intact")
        self.assertIsNotNone(harm, "harmony track should not be None")
        self.assertGreater(
            len(harm.notes), 0,
            "harmony notes must be generated — this was the regression",
        )

    def test_legacy_list_str_progression_still_works(self):
        plan = mp.MelodyPlan(
            bars=2, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[
                mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0),
                mp.MelodyNote(bar=1, beat=0.0, pitch=64, duration=1.0),
            ],
            harmonies=[mp.HarmonyTag(start_bar=0, end_bar=2, preset="queen")],
        )
        mel, harm = mp.render_melody_plan(plan, progression=["I", "V"])
        self.assertEqual(len(mel.notes), 2)
        self.assertGreater(len(harm.notes), 0)

    def test_no_harmonies_returns_none(self):
        """Plans without any HarmonyTag should yield a None harmony track."""
        plan = mp.MelodyPlan(
            bars=1, time_signature=(4, 4), key="C", scale="major", tempo=120,
            notes=[mp.MelodyNote(bar=0, beat=0.0, pitch=60, duration=1.0)],
        )
        mel, harm = mp.render_melody_plan(plan)
        self.assertIsNone(harm)


# ---------------------------------------------------------------------------
# Track A — state-list ↔ dataclass round-trips
# ---------------------------------------------------------------------------

class OverrideStateListTests(unittest.TestCase):

    def test_dict_to_override_full(self):
        d = {
            "start_bar": 1, "end_bar": 4,
            "voicing": "ninth", "rhythm": "stabs_8th",
            "mode": "stack", "seed": 42,
        }
        ov = app._dict_to_override(d)
        self.assertEqual(ov.start_bar, 1)
        self.assertEqual(ov.end_bar, 4)
        self.assertEqual(ov.voicing, "ninth")
        self.assertEqual(ov.rhythm, "stabs_8th")
        self.assertEqual(ov.mode, "stack")
        self.assertEqual(ov.seed, 42)

    def test_dict_to_override_blank_voicing_becomes_none(self):
        d = {"start_bar": 0, "end_bar": 1, "voicing": "",
             "rhythm": "", "mode": "stack", "seed": None}
        ov = app._dict_to_override(d)
        self.assertIsNone(ov.voicing)
        self.assertIsNone(ov.rhythm)
        self.assertIsNone(ov.seed)

    def test_invalid_mode_falls_back_to_stack(self):
        d = {"start_bar": 0, "end_bar": 1, "voicing": "triad",
             "rhythm": "pad", "mode": "definitely_invalid", "seed": None}
        ov = app._dict_to_override(d)
        self.assertEqual(ov.mode, "stack")

    def test_roundtrip_via_override_to_dict(self):
        orig = mp.SectionOverride(
            start_bar=2, end_bar=5, voicing="quartal", rhythm="arpeggio_up",
            mode="decoration", seed=7,
        )
        d = app._override_to_dict(orig)
        back = app._dict_to_override(d)
        self.assertEqual(back.start_bar, orig.start_bar)
        self.assertEqual(back.end_bar, orig.end_bar)
        self.assertEqual(back.voicing, orig.voicing)
        self.assertEqual(back.rhythm, orig.rhythm)
        self.assertEqual(back.mode, orig.mode)
        self.assertEqual(back.seed, orig.seed)

    def test_sync_overrides_writes_to_plan(self):
        plan = mp.MelodyPlan(
            bars=4, time_signature=(4, 4), key="C", scale="major", tempo=120,
        )
        dicts = [
            {"start_bar": 0, "end_bar": 1, "voicing": "ninth",
             "rhythm": "stabs_8th", "mode": "stack", "seed": None},
            {"start_bar": 2, "end_bar": 3, "voicing": "triad",
             "rhythm": "pad", "mode": "replace", "seed": 7},
        ]
        result = app.melody_sync_overrides(plan, dicts)
        self.assertEqual(len(result.section_overrides), 2)
        self.assertEqual(result.section_overrides[0].voicing, "ninth")
        self.assertEqual(result.section_overrides[1].mode, "replace")

    def test_empty_state_list_clears_overrides(self):
        plan = mp.MelodyPlan(
            bars=4, time_signature=(4, 4), key="C", scale="major", tempo=120,
            section_overrides=[mp.SectionOverride(0, 1, "triad", "pad", "stack")],
        )
        result = app.melody_sync_overrides(plan, [])
        self.assertEqual(result.section_overrides, [])


class HarmonyStateListTests(unittest.TestCase):

    def test_dict_roundtrip_with_intervals(self):
        orig = mp.HarmonyTag(start_bar=0, end_bar=2, preset="queen",
                              intervals=[1, 2, 4])
        d = app._harmony_to_dict(orig)
        self.assertEqual(d["intervals"], "1,2,4")
        back = app._dict_to_harmony(d)
        self.assertEqual(back.preset, "queen")
        self.assertEqual(back.intervals, [1, 2, 4])

    def test_blank_intervals_becomes_none(self):
        d = {"start_bar": 0, "end_bar": 1, "preset": "abba", "intervals": ""}
        h = app._dict_to_harmony(d)
        self.assertIsNone(h.intervals)

    def test_default_preset_when_blank(self):
        d = {"start_bar": 0, "end_bar": 1, "preset": "", "intervals": ""}
        h = app._dict_to_harmony(d)
        self.assertEqual(h.preset, "queen")

    def test_sync_writes_to_plan(self):
        plan = mp.MelodyPlan(
            bars=4, time_signature=(4, 4), key="C", scale="major", tempo=120,
        )
        dicts = [
            {"start_bar": 0, "end_bar": 2, "preset": "queen", "intervals": ""},
            {"start_bar": 2, "end_bar": 4, "preset": "boston", "intervals": "1,2,3"},
        ]
        result = app.melody_sync_harmonies(plan, dicts)
        self.assertEqual(len(result.harmonies), 2)
        self.assertEqual(result.harmonies[1].preset, "boston")
        self.assertEqual(result.harmonies[1].intervals, [1, 2, 3])


class RowWidgetKeysTests(unittest.TestCase):
    """Every widget inside ``_render_override_row`` and
    ``_render_harmony_row`` carries a stable ``key=``. Same monkey-patch
    trick used for the Extras-row regression test."""

    def _capture_keys(self, render_fn, sample_dict, state_factory):
        captured: list[tuple[str, str | None]] = []
        orig = {
            "Dropdown": gr.Dropdown.__init__,
            "Number": gr.Number.__init__,
            "Slider": gr.Slider.__init__,
            "Textbox": gr.Textbox.__init__,
            "Button": gr.Button.__init__,
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
                state = state_factory()
                render_fn(0, sample_dict, state)
        finally:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", real)

        return captured

    def test_override_row_widgets_all_keyed(self):
        captured = self._capture_keys(
            app._render_override_row, app._default_override_dict(),
            lambda: gr.State([]),
        )
        missing = [name for name, key in captured
                   if name in ("Dropdown", "Number", "Slider", "Textbox")
                   and not key]
        self.assertEqual(missing, [],
                         f"missing keys: {missing}")
        keys = {key for _, key in captured if key}
        self.assertIn("override_0_voicing", keys)
        self.assertIn("override_0_rhythm", keys)
        self.assertIn("override_0_mode", keys)
        self.assertIn("override_0_start", keys)
        self.assertIn("override_0_end", keys)
        self.assertIn("override_0_seed", keys)

    def test_harmony_row_widgets_all_keyed(self):
        captured = self._capture_keys(
            app._render_harmony_row, app._default_harmony_dict(),
            lambda: gr.State([]),
        )
        missing = [name for name, key in captured
                   if name in ("Dropdown", "Number", "Slider", "Textbox")
                   and not key]
        self.assertEqual(missing, [], f"missing keys: {missing}")
        keys = {key for _, key in captured if key}
        self.assertIn("harmony_0_preset", keys)
        self.assertIn("harmony_0_intervals", keys)


# ---------------------------------------------------------------------------
# Track C — accompaniment-bed playback
# ---------------------------------------------------------------------------

class BedToggleTests(unittest.TestCase):

    def setUp(self):
        _reset_state()
        _compose_simple()

    def test_load_compose_pins_bed_tracks(self):
        app.melody_load_from_compose()
        bed = app._state.get("melody_bed_tracks")
        self.assertIsNotNone(bed)
        names = {t.name.lower() for t in bed}
        self.assertNotIn("melody", names,
                         "melody should be excluded from bed")
        # Pop preset emits Chords + Bass + Drums (we composed with all on)
        self.assertGreaterEqual(len(bed), 2)

    def test_pretty_midi_to_tracks_helper_skips_melody(self):
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        for name in ("Chords", "Melody", "Bass"):
            inst = pretty_midi.Instrument(program=0, is_drum=False, name=name)
            inst.notes.append(pretty_midi.Note(80, 60, 0.0, 1.0))
            pm.instruments.append(inst)
        tracks = mp.pretty_midi_to_tracks(pm, skip_melody=True)
        names = [t.name for t in tracks]
        self.assertIn("Chords", names)
        self.assertIn("Bass", names)
        self.assertNotIn("Melody", names)

    def test_preview_with_bed_differs_from_without(self):
        """The synthesized waveform must differ when bed is layered in."""
        import numpy as np
        import soundfile as sf
        plan = app.melody_load_from_compose()
        wav_off = app.melody_preview(plan, with_bed=False)
        a_off, _ = sf.read(wav_off)
        wav_on = app.melody_preview(plan, with_bed=True)
        a_on, _ = sf.read(wav_on)
        n = min(len(a_off), len(a_on))
        diff = float(np.abs(a_on[:n] - a_off[:n]).sum())
        self.assertGreater(diff, 100.0,
                           f"bed-on waveform should differ from bed-off; "
                           f"got abs-sum-diff {diff}")

    def test_preview_without_bed_works_without_bed_state(self):
        """Bed-off must still work even if bed_tracks is missing."""
        app._state.pop("melody_bed_tracks", None)
        plan = app.melody_load_from_compose()
        # melody_load_from_compose just repopulated bed; clear it again
        app._state.pop("melody_bed_tracks", None)
        wav = app.melody_preview(plan, with_bed=False)
        self.assertTrue(wav.endswith(".wav"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
