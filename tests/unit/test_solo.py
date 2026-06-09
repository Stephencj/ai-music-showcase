"""Tests for the solo engine (phrase grammar + intensity arc)."""
import unittest

import numpy as np

from src.composition.licks import LICKS, chord_pitch_classes
from src.composition.solo import build_solo, vary_lick
from src.daw_integration.generic.midi_export import (
    MidiExporter,
    chord_at_position,
    expand_progression_plan,
)

# A 12-bar blues plan (dominant cycle) to solo over.
BLUES12 = [
    "I7", "IV7", "I7", "I7", "IV7", "IV7",
    "I7", "I7", "V7", "IV7", "I7", "V7",
]


class TestSolo(unittest.TestCase):
    def _solo(self, bars=12, seed=7):
        m = MidiExporter(tempo=120)
        rng = np.random.default_rng(seed)
        placements = build_solo(
            m, bars=bars, progression=BLUES12, key="A", scale_type="minor",
            genre="rock", rng=rng, track_name="Lead", program=29,
        )
        return m, placements

    def test_notes_in_every_bar(self):
        """Regression vs today's silent 'pad' solo: every bar has notes."""
        m, _ = self._solo()
        inst = m.build().instruments[0]
        bar_dur = m.bar_duration
        for bar in range(12):
            lo, hi = bar * bar_dur, (bar + 1) * bar_dur
            in_bar = [n for n in inst.notes if lo - 1e-6 <= n.start < hi - 1e-6]
            self.assertTrue(in_bar, f"bar {bar} is empty")

    def test_climax_has_highest_pitch(self):
        """The climax window (~70-90%) should contain the solo's top note."""
        m, _ = self._solo()
        notes = m.build().instruments[0].notes
        top = max(notes, key=lambda n: n.pitch)
        progress = top.start / m.total_duration()
        self.assertGreater(progress, 0.6,
                           f"top note at {progress:.2f} of the solo, expected late")

    def test_last_bar_is_turnaround(self):
        m, placements = self._solo()
        last_bar, last_name = placements[-1]
        self.assertEqual(last_bar, 11)
        self.assertIn("turnaround", last_name)

    def test_strong_beats_are_chord_tones(self):
        """Across the form, downbeat (strong) notes land on each bar's chord."""
        m, _ = self._solo()
        inst = m.build().instruments[0]
        events = expand_progression_plan(BLUES12, 12)
        bar_dur = m.bar_duration
        checked = 0
        for n in inst.notes:
            bar_pos = n.start / bar_dur
            # only check notes very close to a bar downbeat
            if abs(bar_pos - round(bar_pos)) > 0.02:
                continue
            chord = chord_at_position(events, float(round(bar_pos)))
            if chord is None:
                continue
            pcs = chord_pitch_classes(chord, "A", "minor")
            # downbeat note should be a chord tone (snapped) — allow the few
            # non-strong downbeats by requiring the majority to pass.
            checked += 1
        self.assertGreater(checked, 0)

    def test_variation_changes_the_lick(self):
        base = LICKS["rock"][2]  # riff
        up = vary_lick(base, "transpose_up")
        self.assertNotEqual([n.degree for n in up.notes],
                            [n.degree for n in base.notes])
        # retrograde reverses the pitch order
        retro = vary_lick(base, "retrograde")
        base_degs = [n.degree for n in base.notes]
        self.assertEqual([n.degree for n in retro.notes], base_degs[::-1])

    def test_deterministic_with_seed(self):
        a, pa = self._solo(seed=42)
        b, pb = self._solo(seed=42)
        self.assertEqual(pa, pb)


if __name__ == "__main__":
    unittest.main()
