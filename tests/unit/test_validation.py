"""Regression tests for the key-safety audit module.

Covers:
  - classify_note: chord_tone / in_scale / approach_tone / out_of_key buckets
  - suggest_alternatives: returns nearest in-scale pitches
  - audit_track / audit_midi: skips chord pads and drum tracks
  - apply_suggestion: rewrites the correct note, no-ops on missing match

These pin the behaviour that the Compose-tab Key-safety panel relies on so
future generator changes can't silently regress the audit. Run with::

    python -m unittest discover tests/
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    MidiExporter, NoteEvent, Track,
)
from src.daw_integration.generic import validation as v


def _melody(notes, time_sig=(4, 4), tempo=120.0):
    """Build a single-track MidiExporter populated with the given notes."""
    midi = MidiExporter(tempo=tempo, time_signature=time_sig)
    t = Track(name="Melody", program=0)
    t.notes.extend(notes)
    midi.tracks.append(t)
    return midi


class ClassifyNoteTests(unittest.TestCase):

    def test_chord_tone(self):
        # C major triad members on I chord in C major
        for pitch in (60, 64, 67):  # C, E, G
            self.assertEqual(
                v.classify_note(pitch, "I", "C", "major",
                                duration_beats=1.0, is_strong_beat=True),
                "chord_tone",
            )

    def test_in_scale_non_chord_tone(self):
        # D and A are in C major but not in the C-major triad
        for pitch in (62, 69):
            self.assertEqual(
                v.classify_note(pitch, "I", "C", "major",
                                duration_beats=1.0, is_strong_beat=True),
                "in_scale",
            )

    def test_long_chromatic_is_out_of_key(self):
        # Eb in C major, long duration, strong beat → out_of_key
        self.assertEqual(
            v.classify_note(63, "I", "C", "major",
                            duration_beats=2.0, is_strong_beat=True),
            "out_of_key",
        )

    def test_short_weak_chromatic_is_approach_tone(self):
        # C# in C major, short weak-beat neighbour of D → approach_tone
        self.assertEqual(
            v.classify_note(61, "I", "C", "major",
                            duration_beats=0.2, is_strong_beat=False),
            "approach_tone",
        )

    def test_status_is_pitch_class_based(self):
        # Octave doesn't change the verdict
        for octv in range(2, 7):
            pitch = 12 * (octv + 1)  # C in this octave
            self.assertEqual(
                v.classify_note(pitch, "I", "C", "major",
                                duration_beats=1.0, is_strong_beat=True),
                "chord_tone",
            )


class SuggestAlternativesTests(unittest.TestCase):

    def test_returns_in_scale_only(self):
        alts = v.suggest_alternatives(63, "C", "major")  # Eb → should suggest in-scale
        for p in alts:
            self.assertIn(p % 12, {0, 2, 4, 5, 7, 9, 11},
                          f"pitch {p} not in C major")

    def test_returns_sorted_by_distance(self):
        alts = v.suggest_alternatives(63, "C", "major")
        # D (62) and E (64) are both ±1 → should be among the top two
        self.assertIn(62, alts[:2])
        self.assertIn(64, alts[:2])

    def test_excludes_self(self):
        alts = v.suggest_alternatives(60, "C", "major")
        self.assertNotIn(60, alts)

    def test_limit(self):
        alts = v.suggest_alternatives(60, "C", "major", max_n=3)
        self.assertEqual(len(alts), 3)


class AuditMidiTests(unittest.TestCase):

    def test_clean_melody_has_no_issues(self):
        midi = _melody([
            NoteEvent(60, 0.0, 0.5),   # C
            NoteEvent(64, 0.5, 1.0),   # E
            NoteEvent(67, 1.0, 1.5),   # G
        ])
        self.assertEqual(v.audit_midi(midi, ["I"], "major", "C"), [])

    def test_long_chromatic_flagged(self):
        midi = _melody([
            NoteEvent(60, 0.0, 0.5),
            NoteEvent(63, 0.5, 1.5),   # Eb long → out_of_key
            NoteEvent(67, 1.5, 2.0),
        ])
        issues = v.audit_midi(midi, ["I"], "major", "C")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].status, "out_of_key")
        self.assertEqual(issues[0].pitch, 63)
        self.assertEqual(issues[0].pitch_name, "D#4")
        self.assertEqual(issues[0].bar_idx, 0)
        self.assertGreaterEqual(len(issues[0].suggested_alternatives), 1)

    def test_short_chromatic_flagged_as_approach(self):
        midi = _melody([
            NoteEvent(60, 0.0, 0.5),
            NoteEvent(61, 0.5, 0.6),   # C# very short, weak beat
            NoteEvent(62, 0.6, 1.0),
        ])
        issues = v.audit_midi(midi, ["I"], "major", "C")
        statuses = {i.status for i in issues}
        self.assertIn("approach_tone", statuses)

    def test_chord_track_skipped(self):
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        chords = Track(name="Chords", program=0)
        # Polyphonic stacks @ same start time → recognised as chord track
        for t in [0.0, 1.0, 2.0]:
            chords.notes.extend([
                NoteEvent(60, t, t + 0.9),
                NoteEvent(64, t, t + 0.9),
                NoteEvent(67, t, t + 0.9),
            ])
        midi.tracks.append(chords)
        self.assertEqual(v.audit_midi(midi, ["I"], "major", "C"), [])

    def test_drum_track_skipped(self):
        midi = MidiExporter(tempo=120, time_signature=(4, 4))
        drums = Track(name="Drums", program=0, is_drum=True, channel=9)
        # Out-of-key-looking pitches on a drum channel should still be skipped
        drums.notes.extend([NoteEvent(63, 0.0, 0.1), NoteEvent(61, 0.5, 0.6)])
        midi.tracks.append(drums)
        self.assertEqual(v.audit_midi(midi, ["I"], "major", "C"), [])

    def test_handles_empty_progression(self):
        midi = _melody([NoteEvent(60, 0.0, 0.5)])
        # None progression should not crash
        issues = v.audit_midi(midi, None, "major", "C")
        self.assertEqual(issues, [])

    def test_chord_changes_per_bar(self):
        # Same Eb pitch at different bar positions takes different chord context
        # In C major: I=C, V=G. Eb (63) is out_of_key for both chords.
        midi = _melody([
            NoteEvent(63, 0.0, 0.5),   # bar 0, chord I
            NoteEvent(63, 2.0, 2.5),   # bar 1, chord V
        ])
        issues = v.audit_midi(midi, ["I", "V"], "major", "C")
        self.assertEqual(len(issues), 2)
        self.assertEqual(issues[0].chord_symbol, "I")
        self.assertEqual(issues[1].chord_symbol, "V")


class ApplySuggestionTests(unittest.TestCase):

    def test_apply_rewrites_correct_note(self):
        midi = _melody([
            NoteEvent(60, 0.0, 0.5),
            NoteEvent(63, 0.5, 1.5),
            NoteEvent(67, 1.5, 2.0),
        ])
        issues = v.audit_midi(midi, ["I"], "major", "C")
        self.assertEqual(len(issues), 1)
        ok = v.apply_suggestion(midi, issues[0], 62)  # snap Eb → D
        self.assertTrue(ok)
        self.assertEqual([n.pitch for n in midi.tracks[0].notes],
                         [60, 62, 67])

    def test_apply_returns_false_when_note_gone(self):
        midi = _melody([NoteEvent(60, 0.0, 0.5)])
        issues = v.audit_midi(midi, ["I"], "major", "C")
        # Forge an issue that doesn't match anything in the midi
        from src.daw_integration.generic.validation import NoteIssue
        bogus = NoteIssue(
            track_name="Melody", bar_idx=99, beat=0.0, pitch=99,
            pitch_name="D#9", status="out_of_key", chord_symbol="I",
            suggested_alternatives=[],
        )
        self.assertFalse(v.apply_suggestion(midi, bogus, 60))


if __name__ == "__main__":
    unittest.main(verbosity=2)
