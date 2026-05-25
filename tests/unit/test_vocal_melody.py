"""Tests for composing a vocal melody FROM lyrics (step 3 of the workflow:
generate instrumental → write lyrics → write melody to lyrics).

Pure-logic: no audio, no block IO. Validates the note-plan shape the renderer
(``apply_melody_plan``) and the word-aligner depend on."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.vocal_melody import build_scale, melody_plan_from_lyrics  # noqa: E402


SECTIONS = [
    {"role": "intro", "start_bar": 0, "end_bar": 3},
    {"role": "verse", "start_bar": 4, "end_bar": 19},
    {"role": "chorus", "start_bar": 20, "end_bar": 35},
    {"role": "outro", "start_bar": 36, "end_bar": 39},
]


class BuildScaleTests(unittest.TestCase):
    def test_major_is_in_key_and_singable(self):
        scale = build_scale("F#", "major")
        self.assertTrue(scale)
        self.assertTrue(all(53 <= m for m in scale))
        # F# major pitch classes only (6,8,10,11,1,3,5)
        self.assertTrue(set(m % 12 for m in scale).issubset({6, 8, 10, 11, 1, 3, 5}))

    def test_minor_scale(self):
        scale = build_scale("A", "minor")
        self.assertTrue(set(m % 12 for m in scale).issubset({9, 11, 0, 2, 4, 5, 7}))

    def test_unknown_scale_falls_back_to_major(self):
        self.assertEqual(build_scale("C", "klingon"), build_scale("C", "major"))


class MelodyFromLyricsTests(unittest.TestCase):
    def _plan(self, syls, key="F#", scale="major"):
        lines = [f"line {i}" for i in range(len(syls))]
        return melody_plan_from_lyrics(
            lines=lines, syllables_per_line=syls, sections=SECTIONS,
            chords_per_bar=["F#", "C#", "B", "F#"] * 10, key=key, scale=scale,
            tempo=104.0, beats_per_bar=4)

    def test_one_note_per_syllable(self):
        syls = [2, 4, 12, 15, 7, 6, 12, 12]
        plan = self._plan(syls)
        self.assertEqual(len(plan["lead"]), sum(syls))

    def test_all_notes_in_key(self):
        # in-key by pitch class (octave may shift in the singable-register pass)
        pcs = {m % 12 for m in build_scale("F#", "major")}
        plan = self._plan([8, 8, 8, 8])
        self.assertTrue(all(m % 12 in pcs for m, _, _ in plan["lead"]))

    def test_notes_strictly_time_ordered(self):
        plan = self._plan([6, 9, 11, 7, 5, 8])
        starts = [s for _, s, _ in plan["lead"]]
        self.assertTrue(all(starts[i] < starts[i + 1] for i in range(len(starts) - 1)))

    def test_notes_within_song_bars(self):
        plan = self._plan([6, 9, 11, 7])
        end_beat = (SECTIONS[-1]["end_bar"] + 1) * 4
        self.assertLess(max(s for _, s, _ in plan["lead"]), end_beat)

    def test_harmony_only_for_chorus(self):
        # one syllable per line, lines land across sections incl the chorus
        plan = self._plan([5, 5, 5, 5])
        self.assertTrue(plan["harmony"], "chorus section should stack harmony")
        # no harmony when there's no chorus section
        only_verse = melody_plan_from_lyrics(
            lines=["a", "b"], syllables_per_line=[6, 6],
            sections=[{"role": "verse", "start_bar": 0, "end_bar": 7}],
            chords_per_bar=["C"] * 8, key="C", scale="major", tempo=120, beats_per_bar=4)
        self.assertEqual(only_verse["harmony"], [])

    def test_tempo_passthrough_and_durations_positive(self):
        plan = self._plan([4, 4, 4, 4])
        self.assertEqual(plan["tempo"], 104.0)
        self.assertTrue(all(d > 0 for _, _, d in plan["lead"]))

    def test_zero_syllable_lines_skipped(self):
        plan = self._plan([0, 5, 0, 5])
        self.assertEqual(len(plan["lead"]), 10)

    def test_different_key(self):
        pcs = {m % 12 for m in build_scale("C", "major")}
        plan = self._plan([8, 8, 8, 8], key="C", scale="major")
        self.assertTrue(all(m % 12 in pcs for m, _, _ in plan["lead"]))


class RefitTests(unittest.TestCase):
    """_refit must hit the target count exactly, preserve time order, and not
    drop/overlap (so one note per syllable survives monophonic reduction)."""

    def _ordered_nonoverlap(self, notes):
        for i in range(len(notes) - 1):
            if notes[i][1] + notes[i][2] > notes[i + 1][1] + 1e-6:
                return False
            if notes[i + 1][1] < notes[i][1]:
                return False
        return True

    def test_merge_down_to_target(self):
        from src.composition.vocal_melody import _refit
        notes = [[60, 0.0, 0.5], [62, 0.5, 0.5], [64, 1.0, 0.5], [65, 1.5, 0.5]]
        out = _refit(notes, 2)
        self.assertEqual(len(out), 2)
        self.assertTrue(self._ordered_nonoverlap(out))

    def test_split_up_to_target(self):
        from src.composition.vocal_melody import _refit
        out = _refit([[60, 0.0, 2.0]], 4)
        self.assertEqual(len(out), 4)
        self.assertTrue(self._ordered_nonoverlap(out))
        self.assertTrue(all(p == 60 for p, _, _ in out))   # split repeats the pitch

    def test_exact_passthrough(self):
        from src.composition.vocal_melody import _refit
        notes = [[60, 0.0, 0.5], [62, 0.5, 0.5]]
        self.assertEqual(_refit(notes, 2), notes)

    def test_empty_and_zero(self):
        from src.composition.vocal_melody import _refit
        self.assertEqual(_refit([], 5), [])
        self.assertEqual(_refit([[60, 0.0, 1.0]], 0), [])


if __name__ == "__main__":
    unittest.main()
