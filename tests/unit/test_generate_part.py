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


class ArrangementTests(unittest.TestCase):
    def _arr(self, **kw):
        kw.setdefault("output", "midi")
        return service.generate_arrangement(GeneratePartRequest(**kw))

    def test_multi_track_arrangement(self):
        r = self._arr(key="G", scale="major", tempo=110, bars=8,
                      progression=["I", "V", "vi", "IV"], genre="pop_full_song", seed=5)
        names = {t["track"] for t in r["tracks"]}
        self.assertEqual(names, {"Chords", "Bass", "Drums", "Melody"})
        self.assertGreater(r["n_notes"], 0)
        self.assertEqual(r["n_notes"], sum(t["n_notes"] for t in r["tracks"]))
        # the saved MIDI really has multiple instruments
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(str(service.part_file(r["part_id"], "part.mid")))
        self.assertGreaterEqual(len([i for i in pm.instruments if i.notes]), 4)

    def test_parts_subset(self):
        r = self._arr(key="C", bars=4, progression=["I", "V"], parts=["bass", "drums"])
        self.assertEqual({t["track"] for t in r["tracks"]}, {"Bass", "Drums"})


class PartOptionsTests(unittest.TestCase):
    def test_shape_has_all_targets_and_defaults(self):
        po = service.part_options()
        for t in ("chords", "bass", "drums", "melody", "lead"):
            self.assertIn(t, po)
            for mod in po[t].values():
                self.assertTrue(mod["options"], "modifier has options")
                self.assertIn(mod["default"], mod["options"], "default is a valid option")

    def test_chords_and_melody_have_two_modifiers(self):
        po = service.part_options()
        self.assertEqual(set(po["chords"].keys()), {"voicing", "rhythm"})
        self.assertEqual(set(po["melody"].keys()), {"style", "phrase_shape"})
        self.assertEqual(set(po["bass"].keys()), {"pattern"})

    def test_modifiers_are_accepted_by_generate(self):
        r = _gen(target="chords", key="C", bars=2, progression=["I", "V"],
                 voicing="seventh", chord_rhythm="charleston")
        self.assertGreater(r["n_notes"], 0)
        r = _gen(target="melody", key="C", bars=4, progression=["I", "V", "vi", "IV"],
                 melody_style="blues", phrase_shape="rise", seed=1)
        self.assertGreater(r["n_notes"], 0)

    def test_octave_shifts_register(self):
        lo = _gen(target="chords", bars=2, progression=["I", "V"], octave=2)
        hi = _gen(target="chords", bars=2, progression=["I", "V"], octave=4)
        self.assertLess(min(p for p, _, _ in lo["notes"]), min(p for p, _, _ in hi["notes"]))

    def test_note_density_changes_count(self):
        sparse = _gen(target="melody", bars=4, progression=["I", "IV", "V", "I"],
                      seed=1, note_density=0.4)
        dense = _gen(target="melody", bars=4, progression=["I", "IV", "V", "I"],
                     seed=1, note_density=0.95)
        self.assertLess(sparse["n_notes"], dense["n_notes"])
        # drums honor density too
        self.assertLess(_gen(target="drums", bars=2, seed=1, note_density=0.5)["n_notes"],
                        _gen(target="drums", bars=2, seed=1, note_density=1.0)["n_notes"])


if __name__ == "__main__":
    unittest.main()
