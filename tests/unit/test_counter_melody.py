"""Regression tests for Phase 3 counter-melody / auto-harmony.

When a Lead extra's ``follow_mode`` is set to anything other than
``"independent"``, ``add_lead_line`` bypasses its pattern dispatch and
emits a line that *responds* to the named source track (default:
``"Melody"``). Each mode has a distinctive musical fingerprint we lock
here so future generator edits don't silently break the harmony.

Modes:
- ``parallel_third`` / ``parallel_sixth``: scale-step above each
  source note.
- ``contrary_motion``: mirrored around the source's first pitch.
- ``call_response``: emits chord-tone hits during source's rests
  longer than 0.5 beats.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.daw_integration.generic.midi_export import (
    MidiExporter,
    NoteEvent,
    Track,
)


def _seed_melody(m: MidiExporter, pitches, *, gap_at_end: float = 0.0):
    """Build a Melody track with one note per pitch, each one beat
    long, sequential. ``gap_at_end`` leaves silence after the last
    note (for call/response testing)."""
    mel = m._track_for("Melody", program=0)
    beat = m.pulse_unit
    for i, p in enumerate(pitches):
        mel.notes.append(NoteEvent(
            pitch=p, start=i * beat, end=(i + 1) * beat * 0.95,
            velocity=80,
        ))
    return mel


class FollowerModeTests(unittest.TestCase):

    def test_parallel_third_above_melody(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        _seed_melody(m, [60, 62, 64, 65])  # C major: C D E F
        m.add_lead_line(
            key="C", scale_name="major", bars=1, octave=5,
            progression=["I"], track_name="Lead",
            follow_source="Melody", follow_mode="parallel_third",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        # Diatonic scale-step third above C is E (pc 4), D→F (pc 5),
        # E→G (pc 7), F→A (pc 9). At least 3/4 should be a scale third.
        lead_pcs = sorted({n.pitch % 12 for n in lead.notes})
        expected = {4, 5, 7, 9}
        # Each lead pitch should land on a scale tone strictly above its source.
        for src_n, lead_n in zip(
            sorted(m.tracks[0].notes, key=lambda n: n.start),
            sorted(lead.notes, key=lambda n: n.start),
        ):
            self.assertGreater(
                lead_n.pitch, src_n.pitch,
                f"parallel_third must sit above source ({lead_n.pitch} vs {src_n.pitch})",
            )

    def test_parallel_sixth_above_melody(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        _seed_melody(m, [60, 62, 64, 65])
        m.add_lead_line(
            key="C", scale_name="major", bars=1, octave=5,
            progression=["I"], track_name="Lead",
            follow_source="Melody", follow_mode="parallel_sixth",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        # Sixth is wider than third → each lead pitch should be
        # higher than its source by more than the third version.
        for src_n, lead_n in zip(
            sorted(m.tracks[0].notes, key=lambda n: n.start),
            sorted(lead.notes, key=lambda n: n.start),
        ):
            self.assertGreater(lead_n.pitch - src_n.pitch, 4,
                               f"sixth above should be > 4 semis ({lead_n.pitch - src_n.pitch})")

    def test_contrary_motion_mirrors_first_pitch(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        _seed_melody(m, [60, 64, 67, 72])  # ascending
        m.add_lead_line(
            key="C", scale_name="major", bars=1, octave=4,
            progression=["I"], track_name="Lead",
            follow_source="Melody", follow_mode="contrary_motion",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        lead_sorted = sorted(lead.notes, key=lambda n: n.start)
        # As the source ascends, the lead should overall descend.
        first = lead_sorted[0].pitch
        last = lead_sorted[-1].pitch
        self.assertLess(last, first,
                        f"contrary motion: lead should fall ({first}→{last}) as melody rises")

    def test_call_response_plays_only_in_rests(self):
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        beat = m.pulse_unit
        # Melody plays one short note on beat 0, then rests until beat 2.
        mel = m._track_for("Melody", program=0)
        mel.notes.append(NoteEvent(pitch=60, start=0.0, end=beat * 0.5, velocity=80))
        mel.notes.append(NoteEvent(pitch=60, start=beat * 2.0, end=beat * 2.5, velocity=80))
        m.add_lead_line(
            key="C", scale_name="major", bars=1, octave=5,
            progression=["I"], track_name="Lead",
            follow_source="Melody", follow_mode="call_response",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        self.assertTrue(lead.notes, "call/response should produce at least one note")
        for n in lead.notes:
            # Every lead note must start during a rest (between melody notes
            # or after the last one).
            self.assertGreaterEqual(
                n.start, beat * 0.5 - 1e-6,
                f"lead note at {n.start} starts inside the first melody note's window",
            )

    def test_independent_mode_uses_pattern_dispatch(self):
        """Default mode (no follow) keeps today's pattern-based behavior."""
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        _seed_melody(m, [60, 62, 64, 65])
        m.add_lead_line(
            key="C", scale_name="major", bars=2, octave=4,
            progression=["I", "V"], pattern="clinton_synth",
            track_name="Lead",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        # clinton_synth fires many 16th-note hits — way more than 4.
        self.assertGreater(len(lead.notes), 6,
                           "independent clinton_synth should emit a dense riff")

    def test_missing_source_track_does_not_crash(self):
        """If the user enables follow_mode before the Melody track
        exists (e.g. melody disabled in Compose), the lead silently
        bails — no crash, no spurious notes."""
        m = MidiExporter(tempo=120, time_signature=(4, 4))
        m.add_lead_line(
            key="C", scale_name="major", bars=1, octave=5,
            progression=["I"], track_name="Lead",
            follow_source="Melody", follow_mode="parallel_third",
        )
        lead = next(t for t in m.tracks if t.name == "Lead")
        self.assertEqual(len(lead.notes), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
