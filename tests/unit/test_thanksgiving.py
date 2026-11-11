"""Thanksgiving on the seasonal engine (christmas.py): the public-domain
hymns, the four styles, no Christmas colours, the Christmas lessons (no rubs,
the lead under MIDI 88, bass roots, no blips), describe/revise and the
Thanksgiving playlist."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi  # noqa: E402

from src.composition import christmas  # noqa: E402
from src.composition.carols import CAROLS, bar_sums  # noqa: E402
from src.composition.hymns import HYMNS, hymn, hymn_catalog, raw_text  # noqa: E402
from src.composition.song_composer import _GENRE_TAG_MAP, _STRICT_GENRES, compose_song  # noqa: E402
from src.daw_integration.generic.midi_export import CHORD_FORMULAS, roman_to_semitone_offset  # noqa: E402
from src.daw_integration.generic.styles import STYLES  # noqa: E402

GENRES = christmas.season_styles("thanksgiving")
CHRISTMAS_COLOURS = ("sleigh_bells", "glockenspiel", "celesta")


def compose(genre: str, tune: str, seed: int = 3, length: float = 180):
    band = list(STYLES[genre].default_instruments)
    plan = christmas.plan_song(genre, seed=seed, tune=tune, length_seconds=length, instruments=band)
    out_dir = tempfile.mkdtemp(prefix="tg_")
    try:
        out = compose_song(genre=genre, sections=plan["sections"], seed=seed, key=plan["key"], scale=plan["scale"],
                           tempo=plan["tempo"], time_signature=plan["time_signature"],
                           enabled_instruments=tuple(band), output_dir=Path(out_dir), skip_audio=True)
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return plan, pm


class HymnTests(unittest.TestCase):

    def test_the_six_hymns(self):
        titles = {v["title"] for v in hymn_catalog().values()}
        for want in ("We Gather Together", "Come, Ye Thankful People, Come", "For the Beauty of the Earth",
                     "Now Thank We All Our God", "All Creatures of Our God and King", "Simple Gifts"):
            self.assertIn(want, titles)
        self.assertFalse(set(HYMNS) & set(CAROLS))

    def test_bars_add_up(self):
        for tid in HYMNS:
            t, raw = hymn(tid), raw_text(tid)
            for i, b in enumerate(bar_sums(raw["melody"])):
                self.assertAlmostEqual(b, t.pickup if (i == 0 and t.pickup) else t.beats, msg=f"{tid} bar {i + 1}")
            for i, b in enumerate(bar_sums(raw["chords"])):
                self.assertAlmostEqual(b, t.beats, msg=f"{tid} chord bar {i + 1}")

    def test_strong_beats_sit_on_our_chords(self):
        ext = {"maj": (2, 9, 11), "min": (2, 10), "7": (2, 9), "maj7": (2, 9), "min7": (2, 5)}
        for tid in HYMNS:
            t = hymn(tid)
            for n in t.melody:
                if n.start < 0:
                    continue
                if not ((n.start % t.beats == 0) or (t.beats == 4 and n.start % 2 == 0) or n.dur >= 1.5):
                    continue
                c = t.chord_at(n.start)
                off, q = roman_to_semitone_offset(c.symbol, t.scale)
                ok = {(off + i) % 12 for i in CHORD_FORMULAS.get(q, (0, 4, 7))} | {(off + i) % 12 for i in ext.get(q, ())}
                self.assertIn(n.pitch % 12, ok, f"{tid} bar {int(n.start // t.beats) + 1}: {n.pitch} over {c.symbol}")

    def test_public_domain_sources(self):
        for tid, info in hymn_catalog().items():
            self.assertIn("Public domain", info["source"], tid)
            years = [int(y) for y in re.findall(r"\b(1[0-9]{3})\b", info["source"])]
            self.assertTrue(years and max(years) < 1929, f"{tid}: {info['source']}")
        import src.composition.hymns as mod
        doc = mod.__doc__
        for src in ("openhymnal.org", "Wikipedia", "thesession.org", "our own"):
            self.assertIn(src, doc)                     # where each melody came from; harmony is ours


class StyleTests(unittest.TestCase):

    def test_four_styles_without_christmas_colours(self):
        from src.audio_processing.render.profiles import resolve_profile
        from src.composition.genres import genre_catalog
        self.assertEqual(len(GENRES), 4)
        wheel = {g["id"] for fam in genre_catalog() if fam["family"] == "Thanksgiving" for g in fam["genres"]}
        for g in GENRES:
            p = STYLES[g]
            self.assertEqual(p.sound, "sampled")
            self.assertIn(g, _STRICT_GENRES)
            self.assertEqual(_GENRE_TAG_MAP[g], ("christmas",))
            self.assertEqual(resolve_profile(g).name, "christmas")
            self.assertIn(g, wheel)
            self.assertEqual(set(p.default_instruments) & set(CHRISTMAS_COLOURS), set(), g)
        self.assertEqual(set(christmas.season_variants("thanksgiving")) & {"sleigh_bells", "celesta_ending"}, set())
        self.assertEqual(christmas.season_styles("christmas")[0], "christmas_swing_full")
        self.assertEqual(len(christmas.season_styles("christmas")), 6)

    def test_originals_get_autumn_titles(self):
        plan = christmas.plan_song("thanksgiving_piano_full", seed=12, tune="original")
        first = plan["tune_title"].split()[0]
        self.assertIn(first, christmas._AUTUMN_TITLE_WORDS[0])
        xmas = christmas.plan_song("christmas_jazz_trio_full", seed=12, tune="original")
        self.assertIn(xmas["tune_title"].split()[0], christmas._TITLE_WORDS[0])      # Christmas unchanged


class ArrangementTests(unittest.TestCase):

    def test_every_style_and_tune_keeps_the_christmas_lessons(self):
        for g in GENRES:
            for tune in list(HYMNS) + ["original"]:
                for seed in (3, 11):
                    plan, pm = compose(g, tune, seed=seed)
                    beat = 60.0 / plan["tempo"]
                    names = {i.name for i in pm.instruments if i.notes}
                    self.assertTrue(any(n.endswith("Melody") for n in names), (g, tune))
                    self.assertFalse(any(c.replace("_", " ").title() in names for c in CHRISTMAS_COLOURS), names)
                    mel = [n for i in pm.instruments if i.name.endswith("Melody") for n in i.notes]
                    self.assertLessEqual(max(n.pitch for n in mel), 88, (g, tune, seed))   # lead under MIDI 88
                    # No blips: nothing pitched shorter than 50 ms.
                    short = [(i.name, n.pitch, round(n.start, 2)) for i in pm.instruments if not i.is_drum
                             for n in i.notes if n.end - n.start < 0.05]
                    self.assertEqual(short, [], (g, tune, seed))
                    # No held half-step rubs against the tune.
                    rubs = 0
                    others = [i for i in pm.instruments if not i.is_drum and not i.name.endswith("Melody")]
                    for n in mel:
                        if n.end - n.start < 0.7 * beat:
                            continue
                        for i in others:
                            for m in i.notes:
                                ov = min(n.end, m.end) - max(n.start, m.start)
                                if ov >= 0.35 * beat and (max(n.pitch, m.pitch) - min(n.pitch, m.pitch)) % 12 == 1:
                                    rubs += 1
                    self.assertEqual(rubs, 0, (g, tune, seed))

    def test_bass_plays_the_roots(self):
        for g in GENRES:
            plan, pm = compose(g, "we_gather_together", seed=5)
            beats, bpm = plan["time_signature"][0], plan["tempo"]
            low = [n for i in pm.instruments if not i.is_drum and not i.name.endswith("Melody") for n in i.notes]
            hits = total = 0
            for sec in plan["sections"]:
                if sec["info"]["kind"] in ("intro", "count_in"):
                    continue
                tonic = christmas._tonic_pc(sec.get("key") or plan["key"])
                for sym, st, _d in sec["info"]["chords"]:
                    t0 = (sec["start_bar"] * beats + st) * 60.0 / bpm
                    root, _q = christmas.parse_symbol(sym, tonic, plan["scale"])
                    sounding = [n for n in low if n.start <= t0 + 0.12 and n.end > t0 + 0.12]
                    if not sounding or t0 > pm.get_end_time() * 0.85:   # the ritardando moves the clock
                        continue
                    total += 1
                    hits += min(sounding, key=lambda n: n.pitch).pitch % 12 == root
            self.assertGreater(hits / max(1, total), 0.85, (g, hits, total))


class DescribeTests(unittest.TestCase):

    def test_describe_and_revise(self):
        from src.composition.song_plan import engine_for, normalize_plan, rule_describe, rule_revise

        def describe(text):
            raw, _chips, notes = rule_describe(text)
            return normalize_plan(raw)[0]

        p = describe("cozy autumn piano, We Gather Together, about 3 minutes")
        self.assertEqual((p["genre"], p["tune"], p["length_seconds"]),
                         ("thanksgiving_piano_full", "we_gather_together", 180))
        self.assertEqual(describe("thanksgiving fireside folk guitar")["genre"], "thanksgiving_fireside_full")
        self.assertEqual(describe("harvest hymn with a choir, Now Thank We All Our God")["tune"],
                         "now_thank_we_all_our_god")
        self.assertEqual(engine_for("thanksgiving_hymn_full").id, "thanksgiving")
        self.assertEqual(engine_for("christmas_choir_full").id, "christmas")
        base = {"genre": "thanksgiving_piano_full", "tune": "simple_gifts"}
        raw, _ = rule_revise(base, "make it orchestral")
        new, _ = normalize_plan(raw, previous=base)
        self.assertEqual((new["genre"], new["tune"]), ("thanksgiving_strings_full", "simple_gifts"))
        raw, _ = rule_revise(base, "add sleigh bells")
        new, notes = normalize_plan(raw, previous=base)
        self.assertNotIn("sleigh_bells", new.get("arrangement", ""))
        self.assertNotIn("sleigh_bells", new.get("instruments", []))
        raw, _ = rule_revise(base, "warmer")
        self.assertIn("warmer", normalize_plan(raw, previous=base)[0].get("arrangement", ""))

    def test_tools(self):
        from src.serve import song_tools
        from src.serve.song_tools import ToolError
        self.assertEqual(song_tools._check_tune("thanksgiving_hymn_full", "Simple Gifts"), "simple_gifts")
        with self.assertRaises(ToolError):
            song_tools._check_tune("thanksgiving_hymn_full", "silent_night")
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="thanksgiving_piano_full", arrangement="sleigh_bells", wait=False)
        self.assertIn("thanksgiving", song_tools.describe_options())


class PlaylistTests(unittest.TestCase):

    def test_thanksgiving_running_order(self):
        from src.audio_processing.render.playlist import plan_mix
        tracks = plan_mix(total_minutes=62, seed=4, season="thanksgiving", originals=0.5)
        self.assertTrue(all(t.genre in GENRES for t in tracks))
        self.assertTrue(all(t.tune == "original" or t.tune in HYMNS for t in tracks))
        for a, b in zip(tracks, tracks[1:]):
            self.assertNotEqual(a.genre, b.genre)
        xmas = plan_mix(count=8, seed=4)
        self.assertTrue(all(t.genre.startswith("christmas_") for t in xmas))
        self.assertTrue(all(t.tune == "original" or t.tune in CAROLS for t in xmas))


if __name__ == "__main__":
    unittest.main(verbosity=2)
