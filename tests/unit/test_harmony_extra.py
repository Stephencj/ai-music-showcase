"""Tests for the "harmony" track type in MIDI Compose Extras.

Covers:
- ``add_harmony.voices`` truncates / pads / no-op'd shape.
- The new Extras type:
    - ``_default_track_for_type("harmony")`` returns the expected keys.
    - ``compose_midi`` with a harmony extra emits N separate harmony
      tracks named ``Melody Harm 1`` / ``Melody Harm 2`` etc.
    - An ``intervals`` CSV override bypasses the preset.
    - Widget keys for the harmony row exist (so @gr.render rebuilds
      preserve them).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic.midi_export import (
    MidiExporter,
    NoteEvent,
)


def _seed_melody() -> MidiExporter:
    m = MidiExporter(tempo=120, time_signature=(4, 4))
    mel = m._track_for("Melody", program=0)
    for beat, p in enumerate([60, 64, 67, 65]):
        mel.notes.append(NoteEvent(p, beat * 0.5, (beat + 1) * 0.5, 80))
    return m


def _harm_track_names(m: MidiExporter) -> list[str]:
    return [t.name for t in m.tracks if "Harm" in t.name]


# ---------------------------------------------------------------------------
# add_harmony voices kwarg
# ---------------------------------------------------------------------------

class AddHarmonyVoicesTests(unittest.TestCase):

    def test_voices_truncates_preset(self):
        """boston is natural 3-voice. voices=2 should drop to 2."""
        m = _seed_melody()
        m.add_harmony(
            source_track="Melody", style="boston", voices=2,
            key="C", scale_name="major", progression=["I"],
        )
        self.assertEqual(_harm_track_names(m),
                         ["Melody Harm 1", "Melody Harm 2"])

    def test_voices_pads_above_max(self):
        """journey is natural 1-voice. voices=3 should pad upward."""
        m = _seed_melody()
        m.add_harmony(
            source_track="Melody", style="journey", voices=3,
            key="C", scale_name="major", progression=["I"],
        )
        self.assertEqual(_harm_track_names(m),
                         ["Melody Harm 1", "Melody Harm 2", "Melody Harm 3"])

    def test_voices_none_preserves_preset(self):
        """No voices kwarg → preset's natural count emerges unchanged."""
        m = _seed_melody()
        m.add_harmony(
            source_track="Melody", style="queen",  # natural 2 voices
            key="C", scale_name="major", progression=["I"],
        )
        self.assertEqual(_harm_track_names(m),
                         ["Melody Harm 1", "Melody Harm 2"])

    def test_voices_equal_to_preset_no_change(self):
        m = _seed_melody()
        m.add_harmony(
            source_track="Melody", style="queen", voices=2,
            key="C", scale_name="major", progression=["I"],
        )
        self.assertEqual(_harm_track_names(m),
                         ["Melody Harm 1", "Melody Harm 2"])


# ---------------------------------------------------------------------------
# _default_track_for_type
# ---------------------------------------------------------------------------

class DefaultHarmonyTrackTests(unittest.TestCase):

    def test_default_harmony_track_has_expected_keys(self):
        d = app._default_track_for_type("harmony")
        for key in ("preset", "voices", "harmony_rule",
                    "intervals", "source_track", "program"):
            self.assertIn(key, d, f"missing key '{key}' in default")
        self.assertEqual(d["preset"], "queen")
        self.assertEqual(d["voices"], 2)
        self.assertEqual(d["harmony_rule"], "voice_leading_smooth")
        self.assertEqual(d["intervals"], "")
        self.assertEqual(d["source_track"], "Melody")

    def test_default_extra_track_harmony_includes_track_name(self):
        d = app._default_extra_track("harmony", name="Vocal Stack")
        self.assertEqual(d["type"], "harmony")
        self.assertEqual(d["track_name"], "Vocal Stack")
        self.assertEqual(d["voices"], 2)


# ---------------------------------------------------------------------------
# Widget keys present in the harmony row
# ---------------------------------------------------------------------------

class HarmonyRowKeysTests(unittest.TestCase):
    """Row-stable keys keep widgets alive across @gr.render rebuilds —
    same guarantee every other extras row provides."""

    def _capture_keys(self, render_fn, *args):
        captured: list[tuple[str, str | None]] = []
        orig = {
            "Dropdown": gr.Dropdown.__init__,
            "Number": gr.Number.__init__,
            "Slider": gr.Slider.__init__,
            "Textbox": gr.Textbox.__init__,
            "Button": gr.Button.__init__,
            "Radio": gr.Radio.__init__,
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
                render_fn(*args)
        finally:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", real)
        return captured

    def test_harmony_row_has_voices_preset_rule_intervals_keys(self):
        tr = app._default_extra_track("harmony")
        captured = self._capture_keys(
            app._render_extra_track_row, 0, tr, gr.State([]),
        )
        keys = {k for _, k in captured if k}
        for expected in (
            "extra_0_voices", "extra_0_preset", "extra_0_harmony_rule",
            "extra_0_intervals", "extra_0_source", "extra_0_program",
        ):
            self.assertIn(expected, keys, f"missing widget key {expected!r}")


# ---------------------------------------------------------------------------
# compose_midi end-to-end with a harmony extra
# ---------------------------------------------------------------------------

class ComposeWithHarmonyExtraTests(unittest.TestCase):

    def setUp(self):
        app._state.clear()
        app._state.update({
            "ai_wav_path": None, "midi_wav_path": None,
            "midi_path": None, "model": None,
        })

    def _compose_with_extra(self, extra: dict):
        app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
            enable_drums=False, bass_pattern="root_only",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="I V vi IV", extras=[extra],
            chord_octave=3, bass_octave=3, melody_octave=5,
            drum_grid_state=None, random_variation=False,
        )
        import pretty_midi
        return pretty_midi.PrettyMIDI(app._state["midi_path"])

    def test_harmony_extra_emits_two_voices_for_queen(self):
        pm = self._compose_with_extra({
            "type": "harmony",
            "track_name": "Vocals",
            "preset": "queen",
            "voices": 2,
            "harmony_rule": "voice_leading_smooth",
            "intervals": "",
            "source_track": "Melody",
            "program": 53,
        })
        names = [i.name for i in pm.instruments]
        self.assertIn("Melody Harm 1", names)
        self.assertIn("Melody Harm 2", names)

    def test_harmony_extra_three_voices_via_pad(self):
        pm = self._compose_with_extra({
            "type": "harmony",
            "track_name": "Trio",
            "preset": "journey",
            "voices": 3,
            "harmony_rule": "voice_leading_smooth",
            "intervals": "",
            "source_track": "Melody",
            "program": 0,
        })
        names = [i.name for i in pm.instruments]
        self.assertIn("Melody Harm 1", names)
        self.assertIn("Melody Harm 2", names)
        self.assertIn("Melody Harm 3", names)

    def test_intervals_override_emits_voices(self):
        """When intervals='1,3' is set, the preset is bypassed and
        two voices are emitted at those intervals. The exact pitch
        offsets depend on the voice-leading smoothing pass; here we
        just verify the override actually reaches add_harmony (two
        Harm tracks land instead of queen's natural 2 above the melody)."""
        pm = self._compose_with_extra({
            "type": "harmony",
            "track_name": "Override",
            "preset": "queen",
            "voices": 2,
            "harmony_rule": "voice_leading_smooth",
            "intervals": "1,3",
            "source_track": "Melody",
            "program": 0,
        })
        names = [i.name for i in pm.instruments]
        self.assertIn("Melody Harm 1", names)
        self.assertIn("Melody Harm 2", names)
        # Both should be above the melody on average since both
        # interval indices are positive.
        melody = next(i for i in pm.instruments if i.name == "Melody")
        for hi in (1, 2):
            h = next(i for i in pm.instruments
                     if i.name == f"Melody Harm {hi}")
            offsets = [
                hn.pitch - mn.pitch
                for hn in h.notes
                for mn in melody.notes
                if abs(mn.start - hn.start) < 0.05
            ]
            avg = sum(offsets) / len(offsets) if offsets else 0
            self.assertGreater(
                avg, 0,
                f"Harm {hi} expected above melody (positive interval); avg={avg:.1f}",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
