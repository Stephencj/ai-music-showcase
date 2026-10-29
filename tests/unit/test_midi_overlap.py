"""Same-pitch legato overlaps survive a MIDI round trip."""

import tempfile
import unittest
from pathlib import Path

import pretty_midi

from src.daw_integration.generic.midi_export import MidiExporter, NoteEvent


class SamePitchOverlapTest(unittest.TestCase):
    def test_a_repeated_pitch_overlapping_the_last_keeps_its_length(self):
        midi = MidiExporter(tempo=120)
        midi.add_notes([NoteEvent(pitch=60, start=0.0, end=2.06, velocity=80),     # legato into the next chord
                        NoteEvent(pitch=60, start=2.0, end=4.0, velocity=80),
                        NoteEvent(pitch=64, start=0.0, end=4.0, velocity=80)],
                       track_name="Strings", program=48)
        with tempfile.TemporaryDirectory() as td:
            path = midi.save(Path(td) / "x.mid")
            notes = sorted(pretty_midi.PrettyMIDI(str(path)).instruments[0].notes, key=lambda n: (n.pitch, n.start))
        c = [n for n in notes if n.pitch == 60]
        self.assertEqual(len(c), 2)
        self.assertAlmostEqual(c[0].end, 2.0, delta=0.01)            # the first lets go as the next starts
        self.assertAlmostEqual(c[1].end - c[1].start, 2.0, delta=0.01)   # and the next keeps its full length
        self.assertAlmostEqual([n for n in notes if n.pitch == 64][0].end, 4.0, delta=0.01)

    def test_stems_get_the_same_treatment(self):
        midi = MidiExporter(tempo=120)
        midi.add_notes([NoteEvent(pitch=60, start=0.0, end=2.06, velocity=80),
                        NoteEvent(pitch=60, start=2.0, end=4.0, velocity=80)], track_name="Strings", program=48)
        (_, pm), = list(midi.iter_single_track_pms())
        a, b = sorted(pm.instruments[0].notes, key=lambda n: n.start)
        self.assertLessEqual(a.end, b.start)


if __name__ == "__main__":
    unittest.main()
