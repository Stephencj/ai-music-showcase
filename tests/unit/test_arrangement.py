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


class TestPreChorus(unittest.TestCase):
    def test_prechorus_is_a_selectable_role(self):
        from src.api.arrangement import available_sections
        roles = [s["role"] for s in available_sections("pop")]
        self.assertIn("prechorus", roles)
        # ordered between verse and chorus
        self.assertLess(roles.index("verse"), roles.index("prechorus"))
        self.assertLess(roles.index("prechorus"), roles.index("chorus"))

    def test_pop_full_song_prechorus_is_native_and_tagged(self):
        # pop_full_song's template defines a "Pre-chorus" — it must surface as a
        # native, distinctly-tagged (role=prechorus) section so it's both
        # selectable and independently controllable, not collapsed to a verse.
        from src.api.arrangement import available_sections, build_sections
        native = {s["role"] for s in available_sections("pop_full_song") if s["native"]}
        self.assertIn("prechorus", native)
        secs = build_sections("pop_full_song", [])   # full default arrangement
        labels = [s["label"] for s in secs if s["role"] == "prechorus"]
        self.assertEqual(labels, ["Pre-chorus"])

    def test_prechorus_section_is_not_empty(self):
        # A pre-chorus maps to a canonical role for technique selection, so it
        # must compose actual notes (never render empty).
        from src.api.arrangement import build_sections
        secs = build_sections("pop", ["verse", "prechorus", "chorus"])
        pc = next(s for s in secs if s["role"] == "prechorus")
        self.assertEqual(pc["label"], "Pre-chorus")
        out = compose_song(genre="pop", sections=secs, seed=5, skip_audio=True,
                           enabled_instruments=("drum_kit", "electric_bass", "piano"))
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
        bar = 60.0 / STYLES["pop"].tempo * 4
        lo, hi = pc["start_bar"] * bar, (pc["end_bar"] + 1) * bar - 0.05
        n = sum(1 for inst in pm.instruments for nt in inst.notes if lo <= nt.start < hi)
        self.assertGreater(n, 0, "pre-chorus rendered empty")


if __name__ == "__main__":
    unittest.main()
