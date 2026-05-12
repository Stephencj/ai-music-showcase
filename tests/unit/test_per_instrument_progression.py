"""Regression tests for the per-instrument chord progression overrides.

Covers Track A from the per-instrument-progression plan:

- ``InstrumentProgression`` dataclass shape.
- ``sync_from_master``:
    * Clean instrument inherits master 1:1.
    * Master grows → tail mirrors cleanly, manual=False.
    * Master shrinks → instrument truncates.
    * Locked cell stays put when master changes that position; conflict
      index reported.
    * Locked cell whose symbol now matches the new master → no false
      positive (conflict list is empty).
- ``resolve_instrument_plan``:
    * ``None`` instrument → returns master plan as-is (regression guard
      so callers that haven't opted in keep working).
    * Override on cell 2 only → returned plan has the override's
      symbol on cell 2, master symbols elsewhere, master durations
      everywhere.
    * Instrument shorter than master → tail padded with master.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    ChordEvent,
    InstrumentProgression,
    expand_progression_plan,
    resolve_instrument_plan,
    sync_from_master,
)


def _master_events(text_plan, bars=4):
    """Convenience: take a list[str|(str,float)] master plan + bar
    count, return the expanded ChordEvent list."""
    return expand_progression_plan(text_plan, bars)


# ---------------------------------------------------------------------------
# InstrumentProgression dataclass
# ---------------------------------------------------------------------------

class InstrumentProgressionShapeTests(unittest.TestCase):

    def test_empty_defaults(self):
        ip = InstrumentProgression()
        self.assertEqual(ip.symbols, [])
        self.assertEqual(ip.manual, [])

    def test_explicit_construction(self):
        ip = InstrumentProgression(
            symbols=["I", "V", "vi", "IV"],
            manual=[False, True, False, False],
        )
        self.assertEqual(len(ip.symbols), 4)
        self.assertEqual(ip.manual[1], True)


# ---------------------------------------------------------------------------
# sync_from_master
# ---------------------------------------------------------------------------

class SyncFromMasterTests(unittest.TestCase):

    def test_clean_instrument_inherits_master(self):
        master = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression()
        updated, conflicts = sync_from_master(ip, master)
        self.assertEqual(updated.symbols, ["I", "V", "vi", "IV"])
        self.assertEqual(updated.manual, [False, False, False, False])
        self.assertEqual(conflicts, [])

    def test_master_grows_tail_mirrors_cleanly(self):
        master_short = _master_events(["I", "V"], bars=2)
        master_long = _master_events(["I", "V", "vi", "IV"], bars=4)
        ip = InstrumentProgression(
            symbols=["I", "V"], manual=[False, False],
        )
        ip, _ = sync_from_master(ip, master_short)
        ip, conflicts = sync_from_master(ip, master_long)
        self.assertEqual(ip.symbols, ["I", "V", "vi", "IV"])
        self.assertEqual(ip.manual, [False, False, False, False])
        self.assertEqual(conflicts, [])

    def test_master_shrinks_truncates(self):
        master_long = _master_events(["I", "V", "vi", "IV"], bars=4)
        master_short = _master_events(["I", "V"], bars=2)
        ip = InstrumentProgression()
        ip, _ = sync_from_master(ip, master_long)
        self.assertEqual(len(ip.symbols), 4)
        ip, conflicts = sync_from_master(ip, master_short)
        self.assertEqual(ip.symbols, ["I", "V"])
        self.assertEqual(ip.manual, [False, False])
        self.assertEqual(conflicts, [])

    def test_locked_cell_stays_put_and_reports_conflict(self):
        master_v1 = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression()
        ip, _ = sync_from_master(ip, master_v1)
        # User locks cell 2 to V/2.
        ip.symbols[2] = "V/2"
        ip.manual[2] = True
        # Master changes — cell 2's master symbol is now "iii", which
        # differs from V/2 → conflict.
        master_v2 = _master_events(["I", "V", "iii", "IV"])
        updated, conflicts = sync_from_master(ip, master_v2)
        self.assertEqual(updated.symbols, ["I", "V", "V/2", "IV"])
        self.assertEqual(updated.manual, [False, False, True, False])
        self.assertEqual(conflicts, [2])

    def test_locked_cell_matching_new_master_is_not_a_conflict(self):
        master_v1 = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression()
        ip, _ = sync_from_master(ip, master_v1)
        # User locks cell 2 to "iii".
        ip.symbols[2] = "iii"
        ip.manual[2] = True
        # Master happens to change cell 2 to "iii" too — same value as
        # the user picked. Should NOT register as a conflict.
        master_v2 = _master_events(["I", "V", "iii", "IV"])
        updated, conflicts = sync_from_master(ip, master_v2)
        self.assertEqual(updated.symbols, ["I", "V", "iii", "IV"])
        self.assertEqual(updated.manual[2], True)  # lock survives
        self.assertEqual(conflicts, [])

    def test_input_is_not_mutated(self):
        master = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression(
            symbols=["I", "V", "V/2", "IV"],
            manual=[False, False, True, False],
        )
        sync_from_master(ip, master)
        # Original lists untouched.
        self.assertEqual(ip.symbols, ["I", "V", "V/2", "IV"])
        self.assertEqual(ip.manual, [False, False, True, False])


# ---------------------------------------------------------------------------
# resolve_instrument_plan
# ---------------------------------------------------------------------------

class ResolveInstrumentPlanTests(unittest.TestCase):

    def test_none_returns_master_as_progression_plan(self):
        master = _master_events(["I", "V", "vi", "IV"])
        plan = resolve_instrument_plan(None, master)
        # Expected: [(symbol, duration_bars), …]
        self.assertEqual(len(plan), 4)
        for entry, ev in zip(plan, master):
            self.assertEqual(entry[0], ev.symbol)
            self.assertAlmostEqual(entry[1], ev.duration_bars)

    def test_empty_instrument_returns_master(self):
        master = _master_events(["I", "V", "vi", "IV"])
        plan = resolve_instrument_plan(InstrumentProgression(), master)
        self.assertEqual(len(plan), 4)
        self.assertEqual([entry[0] for entry in plan], ["I", "V", "vi", "IV"])

    def test_override_on_cell_2_only(self):
        master = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression(
            symbols=["I", "V", "V/2", "IV"],
            manual=[False, False, True, False],
        )
        plan = resolve_instrument_plan(ip, master)
        symbols = [entry[0] for entry in plan]
        self.assertEqual(symbols, ["I", "V", "V/2", "IV"])
        # Durations come from the master, not the instrument.
        durations = [entry[1] for entry in plan]
        for d, ev in zip(durations, master):
            self.assertAlmostEqual(d, ev.duration_bars)

    def test_instrument_shorter_than_master_tail_padded(self):
        master = _master_events(["I", "V", "vi", "IV"])
        ip = InstrumentProgression(
            symbols=["I", "V"],
            manual=[False, False],
        )
        plan = resolve_instrument_plan(ip, master)
        # Cells 0..1 from instrument, 2..3 from master tail.
        self.assertEqual([entry[0] for entry in plan], ["I", "V", "vi", "IV"])

    def test_durations_preserved_from_paced_master(self):
        # Master: I for 2 bars, V for 1, vi for 1, IV for 4
        master = _master_events([("I", 2.0), "V", "vi", ("IV", 4.0)], bars=8)
        ip = InstrumentProgression(
            symbols=["I", "V", "V/2", "IV"],
            manual=[False, False, True, False],
        )
        plan = resolve_instrument_plan(ip, master)
        durations = [entry[1] for entry in plan]
        # Master durations preserved: 2, 1, 1, 4.
        self.assertEqual(durations, [2.0, 1.0, 1.0, 4.0])


# ---------------------------------------------------------------------------
# compose_midi integration — overrides actually change generator output
# ---------------------------------------------------------------------------

class ComposeIntegrationTests(unittest.TestCase):
    """The most important test: compose_midi with a bass override
    produces different bass notes than the regression baseline."""

    def setUp(self):
        import app
        self.app = app
        app._state.clear()
        app._state.update({
            "ai_wav_path": None, "midi_wav_path": None,
            "midi_path": None, "model": None,
        })

    def _bass_pitches(self, midi_path: str) -> list[int]:
        """Return the bass track's note pitches in order. Looks for an
        instrument whose name contains 'bass' (case-insensitive)."""
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(midi_path)
        for inst in pm.instruments:
            if "bass" in (inst.name or "").lower():
                # Sorted by onset so leading vs trailing comparisons
                # are deterministic regardless of pretty_midi's order.
                notes = sorted(inst.notes, key=lambda n: n.start)
                return [n.pitch for n in notes]
        return []

    def _compose(self, *, bass_override=None):
        self.app.compose_midi(
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
        return self.app._state["midi_path"]

    def test_no_override_baseline(self):
        """Without overrides, bass plays the master progression roots
        (C-major: I=C, V=G, vi=A, IV=F → roots 36, 43, 45, 41 at
        octave 3 with bass_octave=3)."""
        path = self._compose()
        pitches = self._bass_pitches(path)
        self.assertTrue(pitches, "bass track should have notes")
        # First four bass roots should be tonic, dominant, submediant,
        # subdominant in *some* order proportional to durations. We
        # check the FIRST hit is the C tonic (pitch class 0).
        self.assertEqual(pitches[0] % 12, 0)

    def test_bass_override_changes_bass_only(self):
        """Override bar 2 (V) to ii in bass. Bass should hit D at bar 2;
        chords + melody should be untouched since they use the master."""
        # 4 cells: I V vi IV; override cell 1 (V) → ii.
        override = {
            "symbols": ["I", "ii", "vi", "IV"],
            "manual": [False, True, False, False],
        }
        path = self._compose(bass_override=override)
        pitches = self._bass_pitches(path)
        self.assertTrue(pitches)
        # Find the bass note at bar 2 (start = 1 bar in seconds at 120bpm/4
        # = 2 seconds). Bar 2 root should be D (pitch class 2), not G
        # (pitch class 7) as it would be on the master.
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(path)
        bass = next(
            i for i in pm.instruments if "bass" in (i.name or "").lower()
        )
        bar2_notes = [n for n in bass.notes if 1.99 < n.start < 3.01]
        self.assertTrue(bar2_notes, "expected bass notes inside bar 2")
        # All bar-2 bass roots should be D (pc 2). Previously they'd be G.
        pcs = [n.pitch % 12 for n in bar2_notes]
        self.assertEqual(set(pcs), {2},
                         f"bar-2 bass pitch classes should be {{D=2}}; got {pcs}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
