"""Tests for the transposable lick library + compiler."""
import unittest

from src.composition.licks import (
    LICKS,
    Lick,
    LickNote,
    chord_pitch_classes,
    licks_for,
    render_lick,
    snap_to_chord_tone,
)
from src.daw_integration.generic.midi_export import MidiExporter


class TestLickCompiler(unittest.TestCase):
    def test_strong_beats_land_on_chord_tones(self):
        """Strong-beat notes must be chord tones of the current chord; the
        same lick over I vs IV lands on each chord's tones."""
        lick = LICKS["rock"][0]  # rock_box_call_a
        for chord in ("I", "IV", "V"):
            m = MidiExporter(tempo=120)
            pitches = render_lick(
                m, lick, key="A", chord_symbol=chord, scale_type="minor",
                bar_start_beats=0.0, octave=4, track_name="Lead", program=29,
            )
            pcs = chord_pitch_classes(chord, "A", "minor")
            strong_idx = [i for i, n in enumerate(lick.notes) if n.strong]
            # Map emitted pitches back to the strong notes (rests skipped, but
            # this lick has no rests so indices align).
            strong_pitches = [pitches[i] for i in strong_idx]
            for p in strong_pitches:
                self.assertIn(p % 12, pcs,
                              f"strong note {p} not a chord tone of {chord} ({pcs})")

    def test_snap_to_nearest_chord_tone(self):
        # C major triad pitch classes {0,4,7}; pitch 62 (D) -> nearest is 60 or 64.
        self.assertIn(snap_to_chord_tone(62, {0, 4, 7}), (60, 64))
        # An already-chord-tone pitch is unchanged.
        self.assertEqual(snap_to_chord_tone(67, {0, 4, 7}), 67)

    def test_articulation_emits_bends(self):
        """A lick containing bend/vibrato marks produces pitch bends."""
        lick = LICKS["rock"][0]
        m = MidiExporter(tempo=120)
        render_lick(m, lick, key="A", chord_symbol="I", scale_type="minor",
                    bar_start_beats=0.0, track_name="Lead", program=29)
        bends = m.build().instruments[0].pitch_bends
        self.assertGreater(len(bends), 4)

    def test_bend_release_adds_down_ramp(self):
        lick = Lick("t", "rock", "call", [
            LickNote(0, 0.0, 1.0, articulation="bend_release_whole"),
        ])
        m = MidiExporter(tempo=120)
        render_lick(m, lick, key="A", chord_symbol="I", scale_type="minor",
                    bar_start_beats=0.0, track_name="Lead")
        bends = sorted(m.build().instruments[0].pitch_bends, key=lambda b: b.time)
        # Goes up then comes back down (a release) ending near neutral.
        self.assertGreater(max(b.pitch for b in bends), 1000)
        self.assertLessEqual(abs(bends[-1].pitch), 400)

    def test_bar_offset_places_notes_later(self):
        lick = LICKS["rock"][0]
        m = MidiExporter(tempo=120)
        render_lick(m, lick, key="A", chord_symbol="I", scale_type="minor",
                    bar_start_beats=4.0, track_name="Lead")
        starts = [n.start for n in m.build().instruments[0].notes]
        # bar 1 at 120bpm = 2.0s in; first note should be at/after that.
        self.assertGreaterEqual(min(starts), 2.0 - 1e-6)

    def test_licks_for_filters_by_role(self):
        calls = licks_for("rock", "call")
        self.assertTrue(calls)
        self.assertTrue(all(lk.role == "call" for lk in calls))
        self.assertTrue(any(lk.role == "turnaround" for lk in licks_for("rock")))


if __name__ == "__main__":
    unittest.main()
