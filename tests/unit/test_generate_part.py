"""Tests for the host-agnostic /generate-part brain (VST/DAW bridge Phase 0).

Generates ONE part (MIDI note-list) from musical context. Uses output='midi'
so there's no soundfont render in the unit path."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.api import service  # noqa: E402
from src.api.schemas import GeneratePartRequest  # noqa: E402


def _gen(**kw):
    kw.setdefault("output", "midi")
    return service.generate_part(GeneratePartRequest(**kw))


class GeneratePartTests(unittest.TestCase):
    def test_each_target_produces_notes(self):
        for target in ("chords", "bass", "melody", "drums"):
            r = _gen(target=target, key="C", tempo=100, bars=4,
                     progression=["I", "V", "vi", "IV"], seed=7)
            self.assertGreater(r["n_notes"], 0, f"{target}: no notes")
            self.assertEqual(r["target"], target)
            for pitch, start, dur in r["notes"]:
                self.assertTrue(0 <= pitch <= 127)
                self.assertGreaterEqual(start, 0.0)
                self.assertGreater(dur, 0.0)

    def test_notes_within_requested_bars(self):
        r = _gen(target="melody", key="C", tempo=120, bars=4,
                 progression=["I", "V", "vi", "IV"], seed=1)
        total_beats = 4 * 4  # bars * beats_per_bar
        self.assertTrue(all(s < total_beats + 0.5 for _, s, _ in r["notes"]))

    def test_chords_are_stacked_triads(self):
        r = _gen(target="chords", key="C", scale="major", bars=2, progression=["I", "V"])
        # several notes share the downbeat (a chord), not a single line
        starts = [round(s, 3) for _, s, _ in r["notes"]]
        self.assertGreater(len(starts) - len(set(starts)), 0)

    def test_progression_cycles_to_cover_bars(self):
        # 2-chord progression over 8 bars must still fill the span
        r = _gen(target="bass", key="C", bars=8, progression=["I", "V"])
        self.assertEqual(len(r["progression"]), 8)
        self.assertGreater(r["n_notes"], 0)

    def test_default_progression_major_minor(self):
        self.assertEqual(service._default_progression("major"), ["I", "V", "vi", "IV"])
        self.assertEqual(service._default_progression("minor"), ["i", "VI", "III", "VII"])

    def test_empty_progression_uses_default(self):
        r = _gen(target="chords", key="A", scale="minor", bars=4, progression=[])
        self.assertEqual(r["progression"][0], "i")

    def test_unknown_target_raises(self):
        with self.assertRaises(ValueError):
            _gen(target="kazoo", bars=2)

    def test_genre_style_defaults_apply(self):
        # a known full-song genre should resolve without error and produce notes
        r = _gen(target="melody", key="C", bars=4, genre="pop_full_song",
                 progression=["I", "V", "vi", "IV"], seed=2)
        self.assertGreater(r["n_notes"], 0)

    def test_midi_artifact_written_and_servable(self):
        r = _gen(target="bass", key="C", bars=2, progression=["I", "V"])
        self.assertIsNotNone(service.part_file(r["part_id"], "part.mid"))
        self.assertIsNone(service.part_file(r["part_id"], "../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
