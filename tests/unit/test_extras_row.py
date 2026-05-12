"""Regression tests for the Extra Tracks row UI.

Two layers covered:

1. The pure-Python mutation logic (the ``_set`` closure pattern each row
   uses to update ``extras_state``). The closure captures the row's
   ``idx``; multiple rows must not stomp on each other.
2. The fact that every dynamically-created widget carries a stable
   ``key=`` so Gradio's ``@gr.render`` can preserve the live component
   instance across state-triggered re-renders. Without the keys the
   ``.change`` event would race with the widget-rebuild and the user's
   selection would silently fail to commit — that was the actual bug
   Stephen reported as "Extras isn't allowing me to adjust voicing".

We build the app and inspect the generated row to confirm the keys are
in place; we also exercise the data flow end-to-end (mutate dict →
``_render_extras`` → MIDI reflects the change).
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import gradio as gr

import app
from src.daw_integration.generic.midi_export import MidiExporter


def _make_set(idx):
    """Re-creation of the closure pattern used inside _render_extra_track_row.
    Each row's lambdas capture an instance of this for their own idx."""
    def _set(state, **kv):
        out = list(state)
        out[idx] = {**out[idx], **kv}
        return out
    return _set


class SetClosureTests(unittest.TestCase):
    """The row's ``_set`` writes back to the right slot regardless of the
    other rows' values. This pins the closure-per-row contract."""

    def test_mutates_only_target_index(self):
        a = app._default_extra_track("chord", "A")
        b = app._default_extra_track("chord", "B")
        c = app._default_extra_track("chord", "C")
        state = [a, b, c]
        mutated = _make_set(1)(state, voicing="seventh")
        self.assertEqual(mutated[0], a)
        self.assertEqual(mutated[2], c)
        self.assertEqual(mutated[1]["voicing"], "seventh")
        # Original state untouched (mutation built a new list)
        self.assertEqual(state[1]["voicing"], "triad")

    def test_independent_per_row_closures(self):
        # Verifies the late-binding gotcha is avoided: each _make_set call
        # captures its own idx, so mutating row 1 doesn't accidentally
        # write to row 0.
        a = app._default_extra_track("chord", "A")
        b = app._default_extra_track("chord", "B")
        state = [a, b]
        set0 = _make_set(0)
        set1 = _make_set(1)
        s1 = set0(state, voicing="seventh")
        s2 = set1(s1, voicing="ninth")
        self.assertEqual(s2[0]["voicing"], "seventh")
        self.assertEqual(s2[1]["voicing"], "ninth")

    def test_multiple_field_writes_per_call(self):
        a = app._default_extra_track("chord", "A")
        mutated = _make_set(0)([a], voicing="sus4", octave=4, program=48)
        self.assertEqual(mutated[0]["voicing"], "sus4")
        self.assertEqual(mutated[0]["octave"], 4)
        self.assertEqual(mutated[0]["program"], 48)


class ExtraTypesAcceptAllFields(unittest.TestCase):
    """Render every extra-track type and confirm _render_extras reads back
    every field the row exposes (voicing/rhythm/octave/program for chord,
    pattern/octave/program for bass, etc.)."""

    def _render(self, extras):
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        app._render_extras(
            midi, extras, key="C", scale="major", bars=4, swing=0.0,
            progression=[("I", 1.0)], seed=42,
        )
        return midi

    def test_chord_voicing_changes_output(self):
        triad = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 3, "program": 0,
        }])
        seventh = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "seventh", "chord_rhythm": "pad",
            "octave": 3, "program": 0,
        }])
        # Same beat-0 hit produces different pitch counts: triad=3, seventh=4
        triad_pcs = {n.pitch % 12 for n in triad.tracks[0].notes
                     if abs(n.start) < 0.01}
        seventh_pcs = {n.pitch % 12 for n in seventh.tracks[0].notes
                       if abs(n.start) < 0.01}
        self.assertEqual(len(triad_pcs), 3, f"triad pcs: {triad_pcs}")
        self.assertEqual(len(seventh_pcs), 4, f"seventh pcs: {seventh_pcs}")

    def test_chord_rhythm_changes_output(self):
        pad = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 3, "program": 0,
        }])
        pulse = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pulse_quarter",
            "octave": 3, "program": 0,
        }])
        self.assertLess(len(pad.tracks[0].notes), len(pulse.tracks[0].notes),
                        "pulse_quarter should produce more hits than pad")

    def test_chord_octave_changes_output(self):
        low = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 3, "program": 0,
        }])
        high = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 5, "program": 0,
        }])
        # Octave 5 root = MIDI 72, octave 3 root = 48 → 24 semitones higher
        low_root = min(n.pitch for n in low.tracks[0].notes)
        high_root = min(n.pitch for n in high.tracks[0].notes)
        self.assertEqual(high_root - low_root, 24)

    def test_chord_program_changes_output(self):
        a = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 3, "program": 0,
        }])
        b = self._render([{
            "type": "chord", "track_name": "X",
            "voicing": "triad", "chord_rhythm": "pad",
            "octave": 3, "program": 48,  # String Ensemble
        }])
        self.assertEqual(a.tracks[0].program, 0)
        self.assertEqual(b.tracks[0].program, 48)

    def test_bass_pattern_changes_output(self):
        root = self._render([{
            "type": "bass", "track_name": "X",
            "pattern": "root", "octave": 2, "program": 33,
        }])
        walking = self._render([{
            "type": "bass", "track_name": "X",
            "pattern": "walking", "octave": 2, "program": 33,
        }])
        # walking has 4 notes per bar, root has 1
        self.assertGreater(len(walking.tracks[0].notes),
                           len(root.tracks[0].notes) * 2)

    def test_melody_style_changes_output(self):
        motif = self._render([{
            "type": "melody", "track_name": "X",
            "melody_style": "motif", "octave": 5, "program": 0,
            "density": 1.0,
        }])
        chord_tone = self._render([{
            "type": "melody", "track_name": "X",
            "melody_style": "chord_tone", "octave": 5, "program": 0,
            "density": 1.0,
        }])
        # Two distinct styles → different note sequences (high probability).
        # Compare pitch sequences.
        motif_seq = [n.pitch for n in motif.tracks[0].notes]
        ct_seq = [n.pitch for n in chord_tone.tracks[0].notes]
        self.assertNotEqual(motif_seq, ct_seq)


class WidgetKeysPresentTests(unittest.TestCase):
    """Verify that every dynamic widget in the extras row carries a
    ``key=`` so Gradio's ``@gr.render`` doesn't blow it away during
    re-renders triggered by the very state mutations the widgets emit.

    We can't easily introspect widgets created inside @gr.render after
    construction (they're created lazily), so we monkey-patch the gr.*
    constructors to capture which keys get used during a single row
    render.
    """

    def test_every_chord_row_widget_has_a_key(self):
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
            # Render a chord-type row inside a fresh Blocks context so
            # gradio doesn't complain about missing parents.
            with gr.Blocks():
                state = gr.State([app._default_extra_track("chord", "X")])
                app._render_extra_track_row(0, {"type": "chord",
                                                 "track_name": "X",
                                                 "voicing": "triad",
                                                 "chord_rhythm": "pad",
                                                 "octave": 3,
                                                 "program": 0}, state)
        finally:
            for name, real in orig.items():
                setattr(getattr(gr, name), "__init__", real)

        # Filter out Markdown (no widget) and check each constructed
        # widget had a key. Buttons may not — they don't carry state.
        missing = [name for name, key in captured
                   if name in ("Dropdown", "Number", "Slider", "Textbox")
                   and not key]
        self.assertEqual(missing, [],
                         f"missing key= on widgets: {missing}")

        # Spot-check well-known keys
        keys = {key for _, key in captured if key}
        self.assertIn("extra_0_voicing", keys)
        self.assertIn("extra_0_rhythm", keys)
        self.assertIn("extra_0_octave", keys)
        self.assertIn("extra_0_program", keys)
        self.assertIn("extra_0_name", keys)

    def test_row_keys_are_unique_per_index(self):
        """Adding a second row produces different keys so widgets don't
        collide. Same monkey-patch trick as above, two rows in sequence."""
        captured: list[str] = []
        orig = gr.Dropdown.__init__

        def __init__(self, *args, **kwargs):
            if kwargs.get("key"):
                captured.append(kwargs["key"])
            return orig(self, *args, **kwargs)

        try:
            gr.Dropdown.__init__ = __init__
            with gr.Blocks():
                state = gr.State([])
                row0 = {"type": "chord", "track_name": "A",
                        "voicing": "triad", "chord_rhythm": "pad",
                        "octave": 3, "program": 0}
                row1 = {"type": "chord", "track_name": "B",
                        "voicing": "triad", "chord_rhythm": "pad",
                        "octave": 3, "program": 0}
                app._render_extra_track_row(0, row0, state)
                app._render_extra_track_row(1, row1, state)
        finally:
            gr.Dropdown.__init__ = orig

        row0_keys = [k for k in captured if k.startswith("extra_0_")]
        row1_keys = [k for k in captured if k.startswith("extra_1_")]
        self.assertTrue(row0_keys)
        self.assertTrue(row1_keys)
        self.assertFalse(set(row0_keys) & set(row1_keys),
                         "row 0 and row 1 keys must not overlap")


if __name__ == "__main__":
    unittest.main(verbosity=2)
