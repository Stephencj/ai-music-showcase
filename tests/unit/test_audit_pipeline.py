"""Integration tests for the Compose-tab key-safety audit pipeline.

Tests the app-level glue (not the validation core itself — that's covered
by ``test_validation.py``). Specifically pins:
  - compose_midi returns the 5-tuple the click handler expects
  - audit rows have the right shape for the Dataframe component
  - get_suggestions_for_row handles every edge case without raising
  - play_flagged_bar / apply_audit_suggestion give clear errors when
    called before Compose or when there are no issues
  - apply_audit_suggestion's empty-string autofill kicks in when the
    user clicks Apply before the dropdown auto-populates
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic.midi_export import (
    MidiExporter, NoteEvent, Track,
)
from src.daw_integration.generic import validation as v


def _reset_state():
    app._state.clear()
    app._state.update({
        "ai_wav_path": None, "midi_wav_path": None,
        "midi_path": None, "model": None,
    })


class ComposeReturnsAuditTuple(unittest.TestCase):

    def setUp(self):
        _reset_state()

    def test_compose_returns_5_tuple(self):
        result = app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
            enable_drums=False, bass_pattern="root_fifth",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        # (wav_path, mid_path, info, audit_rows, suggestion_update)
        self.assertEqual(len(result), 5)
        wav, mid, info, rows, sugg = result
        self.assertTrue(wav.endswith(".wav"))
        self.assertTrue(mid.endswith(".mid"))
        self.assertIn("BPM", info)
        self.assertIsInstance(rows, list)

    def test_compose_seeds_suggestion_dropdown_on_issues(self):
        # bootsy_slap bass produces out-of-key notes in C major → audit
        # should populate suggestion dropdown for row 1.
        result = app.compose_midi(
            style="custom", key="C", scale="major", tempo=120,
            time_sig="4/4", bars=4,
            enable_chords=False, enable_bass=True,
            enable_melody=False, enable_drums=False,
            bass_pattern="bootsy_slap", drum_pattern="basic_rock",
            voicing="triad", swing=0.0, chord_rhythm="pad",
            melody_style="motif", seed=42,
            progression_text="I V vi IV", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        _, _, _, rows, sugg_update = result
        self.assertGreater(len(rows), 0,
                           "bootsy_slap in C major should produce issues")
        # sugg_update is the Gradio update dict
        self.assertIn("choices", sugg_update)
        self.assertGreater(len(sugg_update["choices"]), 0)

    def test_compose_returns_empty_audit_when_clean(self):
        # Pop preset stays in scale → 0 issues
        _, _, _, rows, sugg_update = app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
            enable_drums=False, bass_pattern="root_fifth",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        self.assertEqual(rows, [])
        self.assertEqual(sugg_update["choices"], [])

    def test_audit_row_shape(self):
        _, _, _, rows, _ = app.compose_midi(
            style="custom", key="C", scale="major", tempo=120,
            time_sig="4/4", bars=4,
            enable_chords=False, enable_bass=True,
            enable_melody=False, enable_drums=False,
            bass_pattern="bootsy_slap", drum_pattern="basic_rock",
            voicing="triad", swing=0.0, chord_rhythm="pad",
            melody_style="motif", seed=42,
            progression_text="I V vi IV", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        for row in rows:
            # AUDIT_COLUMNS has 8 entries
            self.assertEqual(len(row), len(app.AUDIT_COLUMNS))
            # First column is 1-based row number (int)
            self.assertIsInstance(row[0], int)
            self.assertGreaterEqual(row[0], 1)


class AuditActionErrorHandling(unittest.TestCase):

    def setUp(self):
        _reset_state()

    def test_play_before_compose_raises_clearly(self):
        with self.assertRaises(gr.Error) as cm:
            app.play_flagged_bar(1)
        msg = str(cm.exception)
        self.assertIn("Compose", msg)
        self.assertIn("nothing to audit", msg.lower())

    def test_apply_before_compose_raises_clearly(self):
        with self.assertRaises(gr.Error) as cm:
            app.apply_audit_suggestion(1, "C4")
        msg = str(cm.exception)
        self.assertIn("Compose", msg)
        self.assertIn("nothing to audit", msg.lower())

    def test_play_with_no_issues_says_so(self):
        # Compose successfully but with zero issues
        app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
            enable_drums=False, bass_pattern="root_fifth",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        with self.assertRaises(gr.Error) as cm:
            app.play_flagged_bar(1)
        msg = str(cm.exception)
        # Must NOT misdiagnose as "nothing composed yet" — they DID compose.
        self.assertNotIn("nothing to audit", msg.lower())
        self.assertIn("No flagged notes", msg)

    def test_apply_with_no_issues_says_so(self):
        app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=True,
            enable_drums=False, bass_pattern="root_fifth",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="", extras=None,
            chord_octave=3, bass_octave=2, melody_octave=5,
            drum_grid_state=None,
        )
        with self.assertRaises(gr.Error) as cm:
            app.apply_audit_suggestion(1, "C4")
        msg = str(cm.exception)
        self.assertNotIn("nothing to audit", msg.lower())
        self.assertIn("No flagged notes", msg)

    def test_invalid_row_index_raises_clear_message(self):
        # Force an issue so the "no issues" guard doesn't fire first
        _force_one_issue()
        with self.assertRaises(gr.Error) as cm:
            app.play_flagged_bar(99)
        self.assertIn("99", str(cm.exception))


class GetSuggestionsForRowTests(unittest.TestCase):

    def setUp(self):
        _reset_state()

    def test_empty_issues_returns_empty_choices(self):
        result = app.get_suggestions_for_row(1)
        # Gradio update dict has __type__ == 'update'
        self.assertEqual(result.get("choices"), [])

    def test_invalid_row_returns_empty_choices(self):
        _force_one_issue()
        for bad in (-1, 0, 99, "abc", None):
            with self.subTest(row=bad):
                result = app.get_suggestions_for_row(bad)
                self.assertEqual(result.get("choices"), [])

    def test_valid_row_returns_alt_names(self):
        _force_one_issue()
        result = app.get_suggestions_for_row(1)
        choices = result.get("choices")
        self.assertGreater(len(choices), 0)
        # Each choice should look like a note name (e.g. "D4")
        for c in choices:
            self.assertRegex(c, r"^[A-G][#b]?-?\d+$")


class ApplyAutofillTests(unittest.TestCase):

    def setUp(self):
        _reset_state()

    def test_empty_suggestion_autofills_first(self):
        _force_one_issue()
        first_sugg = app._state["audit_issues"][0].alt_names()[0]
        before_pitch = app._state["last_midi"].tracks[0].notes[1].pitch
        out = app.apply_audit_suggestion(1, "")  # empty text → autofill
        self.assertIn(first_sugg, out[2])  # info string mentions target
        after_pitch = app._state["last_midi"].tracks[0].notes[1].pitch
        self.assertNotEqual(before_pitch, after_pitch)

    def test_apply_returns_5_tuple(self):
        _force_one_issue()
        out = app.apply_audit_suggestion(1, "")
        self.assertEqual(len(out), 5)
        # 5th element is the next-suggestion update for the dropdown
        self.assertIn("__type__", out[4])


def _force_one_issue():
    """Pin an MidiExporter into _state that has exactly one flagged note,
    so the apply/play/get-suggestions handlers have something to act on."""
    midi = MidiExporter(tempo=120, time_signature=(4, 4))
    mel = Track(name="Melody", program=0)
    mel.notes.extend([
        NoteEvent(60, 0.0, 0.5),
        NoteEvent(63, 0.5, 1.5),     # Eb long → out_of_key
        NoteEvent(67, 1.5, 2.0),
    ])
    midi.tracks.append(mel)
    app._state["last_midi"] = midi
    app._state["audit_context"] = {
        "key": "C", "scale": "major",
        "progression": ["I"], "swing": 0.0,
    }
    app._state["audit_issues"] = v.audit_midi(midi, ["I"], "major", "C")


if __name__ == "__main__":
    unittest.main(verbosity=2)
