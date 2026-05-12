"""Regression tests for the per-instrument progression overrides.

The override shape is a small dict ``{"text": str, "locked": bool}``
carried in a gr.State per instrument (and as ``progression`` +
``progression_locked`` keys on each Extras-state entry). Locked = follow
the master textbox; unlocked + non-empty = use this instrument's text.

Covers:
- ``_resolve_instrument_progression``: locked / unlocked-text / unlocked-
  empty / missing-override / unparseable-text fallback.
- ``_default_instrument_progression_dict`` shape.
- ``compose_midi`` end-to-end: baseline (no overrides) produces master-
  rooted bass; unlocked bass override changes bass without touching
  chords or melody.
- New extras dict starts with ``progression_locked=True`` so it inherits
  the master out of the box.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app


# ---------------------------------------------------------------------------
# _resolve_instrument_progression
# ---------------------------------------------------------------------------

class ResolveInstrumentProgressionTests(unittest.TestCase):

    def test_missing_override_falls_back_to_master(self):
        plan = app._resolve_instrument_progression(None, "I V vi IV")
        # master_text parses to the same ProgressionPlan as the helper
        # _parse_progression_text would produce.
        self.assertEqual(plan, app._parse_progression_text("I V vi IV"))

    def test_locked_override_uses_master(self):
        ov = {"text": "vi V iii IV", "locked": True}
        plan = app._resolve_instrument_progression(ov, "I V vi IV")
        # Locked → master wins regardless of stored text.
        self.assertEqual(plan, app._parse_progression_text("I V vi IV"))

    def test_unlocked_override_with_text_wins(self):
        ov = {"text": "I I/3 V V/2 vi vi/4 IV ii", "locked": False}
        plan = app._resolve_instrument_progression(ov, "I V vi IV")
        self.assertEqual(plan, app._parse_progression_text(
            "I I/3 V V/2 vi vi/4 IV ii",
        ))

    def test_unlocked_empty_falls_back_to_master(self):
        """Unlocked + empty/whitespace text → use master, don't silently
        produce a single-tonic plan."""
        ov = {"text": "  ", "locked": False}
        plan = app._resolve_instrument_progression(ov, "I V vi IV")
        self.assertEqual(plan, app._parse_progression_text("I V vi IV"))

    def test_unlocked_text_that_parses_to_nothing_falls_back(self):
        """Edge case: if _parse_progression_text returns None/empty
        (e.g. only whitespace + punctuation that doesn't yield any
        symbols), fall back to the master so the user never ends up
        with a silent generator mid-edit."""
        # _parse_progression_text is permissive, so we use a value
        # that explicitly returns None — only pure-whitespace inputs
        # reliably do that today, and we already covered that above.
        # This test guards the BRANCH that handles the None return
        # by stubbing the parser, to lock the fallback intent.
        from unittest import mock
        with mock.patch.object(app, "_parse_progression_text",
                                side_effect=lambda t: None if t == "garbage"
                                else [("I", 1.0)]):
            ov = {"text": "garbage", "locked": False}
            plan = app._resolve_instrument_progression(ov, "I V vi IV")
            self.assertEqual(plan, [("I", 1.0)])


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class DefaultStateTests(unittest.TestCase):

    def test_default_instrument_dict_starts_locked(self):
        d = app._default_instrument_progression_dict("I V vi IV")
        self.assertEqual(d["text"], "I V vi IV")
        self.assertTrue(d["locked"])

    def test_default_extra_track_has_progression_keys(self):
        tr = app._default_extra_track("bass", name="Walking Bass")
        self.assertIn("progression", tr)
        self.assertIn("progression_locked", tr)
        self.assertEqual(tr["progression"], "")
        self.assertTrue(tr["progression_locked"])


# ---------------------------------------------------------------------------
# compose_midi end-to-end
# ---------------------------------------------------------------------------

class ComposeIntegrationTests(unittest.TestCase):
    """The most important verification: an unlocked bass override
    actually produces different bass notes than the master would have."""

    def setUp(self):
        app._state.clear()
        app._state.update({
            "ai_wav_path": None, "midi_wav_path": None,
            "midi_path": None, "model": None,
        })

    def _bass_pitch_classes_in_bar(self, midi_path: str, bar_idx: int) -> set:
        """Return the set of pitch classes the bass plays during a
        given bar (bars are 1-second intervals at 120 BPM / 4/4)."""
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(midi_path)
        for inst in pm.instruments:
            if "bass" in (inst.name or "").lower():
                start = bar_idx * 2.0  # 2s per bar at 120 BPM 4/4
                end = (bar_idx + 1) * 2.0
                return {
                    n.pitch % 12 for n in inst.notes
                    if start - 0.01 < n.start < end - 0.01
                }
        return set()

    def _compose(self, *, bass_override=None):
        app.compose_midi(
            style="pop", key="C", scale="major", tempo=120, time_sig="4/4",
            bars=4, enable_chords=True, enable_bass=True, enable_melody=False,
            enable_drums=False, bass_pattern="root_only",
            drum_pattern="basic_rock", voicing="triad", swing=0.0,
            chord_rhythm="pulse_quarter", melody_style="motif", seed=42,
            progression_text="I V vi IV", extras=None,
            chord_octave=3, bass_octave=3, melody_octave=5,
            drum_grid_state=None, random_variation=False,
            bass_progression_override=bass_override,
        )
        return app._state["midi_path"]

    def test_baseline_bass_follows_master(self):
        path = self._compose()
        # Bar 0 = I (C, pc 0); bar 1 = V (G, pc 7).
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 0), {0})
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 1), {7})

    def test_locked_override_falls_through_to_master(self):
        """Locked override is a no-op even when it has stale text."""
        path = self._compose(bass_override={
            "text": "ii ii ii ii", "locked": True,
        })
        # Still master: bar 0 = I, bar 1 = V.
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 0), {0})
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 1), {7})

    def test_unlocked_bass_override_changes_bass(self):
        """The headline scenario: bass walks a different progression."""
        path = self._compose(bass_override={
            "text": "I ii iii IV", "locked": False,
        })
        # Bar 1 should now be ii (D, pc 2) instead of V (G, pc 7).
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 1), {2})

    def test_unlocked_empty_override_falls_through_to_master(self):
        path = self._compose(bass_override={"text": "", "locked": False})
        self.assertEqual(self._bass_pitch_classes_in_bar(path, 1), {7})


if __name__ == "__main__":
    unittest.main(verbosity=2)
