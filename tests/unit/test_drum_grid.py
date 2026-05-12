"""Regression tests for the drum-grid editor helpers.

Pins the round-trip between a named drum pattern, the (drum_name → levels)
grid representation the UI Dataframe edits, and the rendered MIDI events.
Future catalog additions or grid-size changes should not break these.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    drum_pattern_to_grid, grid_step_labels, GRID_DRUM_ROWS,
    grid_subdivs_for_meter,
    DRUM_PATTERNS_BY_METER, MidiExporter, GM_DRUMS,
)


class DrumPatternToGridTests(unittest.TestCase):
    """The grid editor always uses the finest practical subdivision (16ths
    for x/4 meters, eighth-relative 16ths for x/8 compound meters) so it
    can edit every hit any built-in pattern emits — including patterns
    stored at a coarser native ``"8th"`` resolution."""

    def test_basic_rock_kick_and_snare_positions(self):
        # 4/4 grid is always 16ths → 16 steps per bar regardless of native grid
        grid = drum_pattern_to_grid("basic_rock", (4, 4), bars=1)
        self.assertEqual(len(grid["kick"]), 16)
        # Kick on beats 1 and 3 → 16th-grid steps 0 and 8
        self.assertGreater(grid["kick"][0], 0)
        self.assertGreater(grid["kick"][8], 0)
        # Snare on beats 2 and 4 → 16th-grid steps 4 and 12
        self.assertGreater(grid["snare"][4], 0)
        self.assertGreater(grid["snare"][12], 0)

    def test_funk_is_16th_grid(self):
        grid = drum_pattern_to_grid("funk", (4, 4), bars=1)
        # funk is "16th" → 16 steps per bar (matches grid resolution)
        self.assertEqual(len(grid["kick"]), 16)
        # funk has ghost-note (level 1) snare hits
        self.assertIn(1, grid["snare"])

    def test_subdivs_per_meter(self):
        # x/4 meters use 4 subdivisions per pulse (16ths)
        self.assertEqual(grid_subdivs_for_meter((4, 4)), 4)
        self.assertEqual(grid_subdivs_for_meter((3, 4)), 4)
        self.assertEqual(grid_subdivs_for_meter((5, 4)), 4)
        # x/8 meters use 2 subdivisions per eighth pulse (still 16ths in absolute terms)
        self.assertEqual(grid_subdivs_for_meter((6, 8)), 2)
        self.assertEqual(grid_subdivs_for_meter((12, 8)), 2)
        self.assertEqual(grid_subdivs_for_meter((7, 8)), 2)

    def test_compound_meter_grid_size(self):
        # 6/8 → 6 eighth pulses × 2 subdivisions = 12 steps per bar
        grid = drum_pattern_to_grid("compound_6_8", (6, 8), bars=1)
        self.assertEqual(len(grid["kick"]), 12)
        # 12/8 → 24 steps
        grid12 = drum_pattern_to_grid("bembe", (12, 8), bars=1)
        self.assertEqual(len(grid12["kick"]), 24)

    def test_unknown_pattern_returns_empty_template(self):
        grid = drum_pattern_to_grid("does_not_exist", (4, 4), bars=1)
        self.assertEqual(set(grid.keys()), set(GRID_DRUM_ROWS))
        for row in grid.values():
            self.assertEqual(set(row), {0})

    def test_all_meters_round_trip(self):
        # Smoke-check every (meter, pattern) combo: load → render → > 0 hits
        for time_sig, patterns in DRUM_PATTERNS_BY_METER.items():
            for pattern_name in patterns:
                with self.subTest(time_sig=time_sig, pattern=pattern_name):
                    grid = drum_pattern_to_grid(pattern_name, time_sig, bars=1)
                    midi = MidiExporter(tempo=120, time_signature=time_sig)
                    midi.add_drum_grid(grid, bars=1)
                    n_hits = sum(len(t.notes) for t in midi.tracks)
                    self.assertGreater(
                        n_hits, 0,
                        f"{pattern_name} @ {time_sig} produced 0 hits",
                    )

    def test_grid_levels_clamp_to_3(self):
        """Velocity multipliers above 0.85 bucket into accent (level 3)."""
        grid = drum_pattern_to_grid("basic_rock", (4, 4), bars=1)
        for row in grid.values():
            for level in row:
                self.assertIn(level, {0, 1, 2, 3})


class GridStepLabelsTests(unittest.TestCase):

    def test_4_4_16th_grid_labels(self):
        labels = grid_step_labels((4, 4), bars=1, steps_per_bar=16)
        self.assertEqual(len(labels), 16)
        # Each beat starts with "bar.beat" and intermediate steps are e/&/a
        self.assertEqual(labels[0], "1.1")
        self.assertEqual(labels[1], "e")
        self.assertEqual(labels[2], "&")
        self.assertEqual(labels[3], "a")
        self.assertEqual(labels[4], "1.2")

    def test_compound_meter_labels_are_eighth_relative(self):
        # 6/8 → 12 steps per bar, 2 subdivisions per eighth pulse → uses
        # the EIGHTH template (e.g. "1.1 & 1.2 & ...").
        labels = grid_step_labels((6, 8), bars=1, steps_per_bar=12)
        self.assertEqual(len(labels), 12)
        self.assertEqual(labels[0], "1.1")
        self.assertEqual(labels[1], "&")
        self.assertEqual(labels[2], "1.2")

    def test_multibar_labels_prefix_with_bar_number(self):
        labels = grid_step_labels((4, 4), bars=2, steps_per_bar=16)
        self.assertEqual(len(labels), 32)
        self.assertEqual(labels[0], "1.1")
        self.assertEqual(labels[16], "2.1")


class AddDrumGridTests(unittest.TestCase):

    def test_levels_map_to_velocities(self):
        # Synthetic 16-step (4/4 16ths) grid: accent kick on beat 1,
        # ghost snare on beat 2.
        grid = {d: [0] * 16 for d in GRID_DRUM_ROWS}
        grid["kick"][0] = 3   # accent — beat 1
        grid["snare"][4] = 1  # ghost — beat 2
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        midi.add_drum_grid(grid, bars=1, base_velocity=90)
        notes = midi.tracks[0].notes
        kicks = [n for n in notes if n.pitch == GM_DRUMS["kick"]]
        snares = [n for n in notes if n.pitch == GM_DRUMS["snare"]]
        self.assertEqual(len(kicks), 1)
        self.assertEqual(len(snares), 1)
        # Accent velocity > normal > ghost
        self.assertGreater(kicks[0].velocity, snares[0].velocity)
        # Ghost should be substantially quieter
        self.assertLess(snares[0].velocity, 60)

    def test_silent_grid_produces_no_notes(self):
        grid = {d: [0] * 16 for d in GRID_DRUM_ROWS}
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        midi.add_drum_grid(grid, bars=1)
        self.assertEqual(midi.tracks[0].notes, [])

    def test_unknown_drum_row_ignored(self):
        grid = {"made_up_drum": [3] * 16}
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        midi.add_drum_grid(grid, bars=1)
        self.assertEqual(midi.tracks[0].notes, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
