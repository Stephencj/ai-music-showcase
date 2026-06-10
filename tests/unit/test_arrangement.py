"""Tests for per-section arrangement (instruments enter/drop per section)."""
import unittest

import pretty_midi

import src.composition.builtins  # noqa: F401
from src.composition.song_composer import _plays_in_section, compose_song
from src.composition.instruments import INSTRUMENT_REGISTRY as REG
from src.daw_integration.generic.styles import STYLES


class TestArrangementMask(unittest.TestCase):
    def test_backing_vocals_chorus_only(self):
        bv = REG["vocal_harmony"]
        self.assertFalse(_plays_in_section(bv, "verse", True))
        self.assertFalse(_plays_in_section(bv, "intro", True))
        self.assertTrue(_plays_in_section(bv, "chorus", True))
        self.assertTrue(_plays_in_section(bv, "bridge", True))

    def test_drums_drop_in_intro_when_harmonic_present(self):
        dk = REG["drum_kit"]
        self.assertFalse(_plays_in_section(dk, "intro", True))
        self.assertTrue(_plays_in_section(dk, "intro", False))  # no harmony → keep drums
        self.assertTrue(_plays_in_section(dk, "verse", True))

    def test_core_instruments_always_play(self):
        for iid in ("piano", "electric_bass", "vocal_lead", "lead_guitar"):
            inst = REG[iid]
            for role in ("intro", "verse", "chorus", "bridge", "outro"):
                self.assertTrue(_plays_in_section(inst, role, True),
                                f"{iid} dropped in {role}")

    def test_none_instrument_always_plays(self):
        self.assertTrue(_plays_in_section(None, "intro", True))


class TestArrangementIntegration(unittest.TestCase):
    def test_intro_has_no_drums_but_verse_does(self):
        genre = "pop_full_song"
        out = compose_song(genre=genre, seed=5, skip_audio=True,
                           enabled_instruments=tuple(STYLES[genre].default_instruments))
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
        bar = 60.0 / STYLES[genre].tempo * 4
        rows = STYLES[genre].rhythm_variants["Full song"]
        intro = next(r for r in rows if r["label"] == "Intro")
        verse = next(r for r in rows if r["label"].startswith("Verse"))

        def drum_hits(row):
            # 50ms guard on the upper edge so the NEXT section's downbeat
            # (which can land a float-epsilon under the boundary) isn't
            # miscounted into this section.
            lo, hi = row["start_bar"] * bar, (row["end_bar"] + 1) * bar - 0.05
            return sum(1 for inst in pm.instruments if inst.is_drum
                       for n in inst.notes if lo <= n.start < hi)

        self.assertEqual(drum_hits(intro), 0, "intro should have no drums")
        self.assertGreater(drum_hits(verse), 0, "verse should have drums")


if __name__ == "__main__":
    unittest.main()
