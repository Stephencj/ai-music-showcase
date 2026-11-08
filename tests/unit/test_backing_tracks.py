"""Carol backing tracks: no lead, the guide melody's level, the count-in,
transposition, the timing JSON and the lyric alignment.

The lyric files are public-domain texts fetched into data/lyrics/ by
scripts/setup/fetch_carol_lyrics.py. These tests never contain lyric text:
they check counts (lines, syllables, notes) and times only."""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi  # noqa: E402

from src.composition import backing, christmas, lyrics  # noqa: E402
from src.composition.carols import CAROLS, carol  # noqa: E402
from src.composition.song_composer import compose_song  # noqa: E402
from src.daw_integration.generic.styles import STYLES  # noqa: E402

GENRES = tuple(christmas.STYLE_IDS)
SUNG = ("silent_night", "jingle_bells", "deck_the_halls", "good_king_wenceslas", "joy_to_the_world",
        "what_child_is_this", "the_first_noel")
NOT_SUNG = ("carol_of_the_bells", "angels_we_have_heard")


def compose(genre: str, tune: str, *, arrangement: str = "backing_track", key=None, seed: int = 4, length=None):
    """Plan + compose (no audio). Returns (plan, PrettyMIDI, timing)."""
    band = christmas.band_for(list(STYLES[genre].default_instruments), arrangement)
    plan = christmas.plan_song(genre, seed=seed, tune=tune, key=key, length_seconds=length,
                               arrangement=arrangement, instruments=band)
    out_dir = tempfile.mkdtemp(prefix="backing_")
    try:
        out = compose_song(genre=genre, sections=plan["sections"], seed=seed, key=plan["key"], scale=plan["scale"],
                           tempo=plan["tempo"], time_signature=plan["time_signature"], arrangement=arrangement,
                           enabled_instruments=tuple(band), output_dir=Path(out_dir), skip_audio=True)
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
        timing = backing.build_timing(plan, out["midi_path"])
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return plan, pm, timing


def _stem_target(name: str) -> float:
    from src.audio_processing.render.profiles import MIX_PROFILES as PROFILES
    for key, lufs in PROFILES["christmas"].stem_targets.items():
        if not key.startswith("family:") and key in name.lower():
            return float(lufs)
    raise AssertionError(f"no stem target for {name!r}")


class BackingArrangementTests(unittest.TestCase):

    def test_no_lead_in_any_style(self):
        for genre in GENRES:
            with self.subTest(genre=genre):
                plan, pm, _t = compose(genre, "deck_the_halls", length=60)
                names = [i.name for i in pm.instruments]
                self.assertFalse([n for n in names if "melody" in n.lower()], names)
                self.assertTrue(plan["backing"])
                # Every part still plays (the full arrangement).
                pitched = [i for i in pm.instruments if not i.is_drum and i.notes]
                self.assertGreaterEqual(len(pitched), 2, names)

    def test_full_song_still_has_its_melody(self):
        _plan, pm, _t = compose("christmas_jazz_trio_full", "silent_night", arrangement="", length=60)
        self.assertTrue(any(i.name.endswith("Melody") for i in pm.instruments))
        self.assertFalse(any(i.name == christmas.COUNT_IN_TRACK for i in pm.instruments))

    def test_guide_melody_is_quiet(self):
        plan, pm, timing = compose("christmas_orchestral_full", "the_first_noel", arrangement="guide_melody",
                                   length=60)
        self.assertTrue(plan["guide"])
        self.assertEqual(timing["variant"], "guide_melody")
        guides = [i for i in pm.instruments if i.name.startswith("Guide Melody")]
        self.assertTrue(guides, [i.name for i in pm.instruments])
        self.assertFalse([i for i in pm.instruments if i.name.endswith(" Melody") and i not in guides])
        # Levelled well under the band: below every other stem the profile sets.
        _full_plan, full, _ = compose("christmas_orchestral_full", "the_first_noel", arrangement="", length=60)
        guide_lufs = _stem_target(guides[0].name)
        others = [_stem_target(i.name) for i in pm.instruments
                  if i not in guides and i.name != christmas.COUNT_IN_TRACK and _has_target(i.name)]
        self.assertTrue(others)
        self.assertLess(guide_lufs, min(others))
        self.assertLessEqual(guide_lufs - _stem_target("Flute Melody"), -12.0)
        # And softer as played, too.
        full_vel = [n.velocity for i in full.instruments if i.name.endswith(" Melody") for n in i.notes]
        guide_vel = [n.velocity for i in guides for n in i.notes]
        self.assertLess(sum(guide_vel) / len(guide_vel), sum(full_vel) / len(full_vel))

    def test_count_in_is_one_bar_of_recorded_hihat(self):
        for genre, tune in (("christmas_jazz_trio_full", "silent_night"), ("christmas_pop_full", "jingle_bells"),
                            ("christmas_choir_full", "carol_of_the_bells")):
            with self.subTest(genre=genre):
                plan, pm, timing = compose(genre, tune, length=60)
                beats = plan["time_signature"][0]
                ci = [i for i in pm.instruments if i.name == christmas.COUNT_IN_TRACK]
                self.assertEqual(len(ci), 1)
                self.assertTrue(ci[0].is_drum)
                self.assertEqual(ci[0].program, 0)                 # the sampled / GM kit, never a synth
                notes = sorted(ci[0].notes, key=lambda n: n.start)
                self.assertEqual(len(notes), beats)
                self.assertTrue(all(n.pitch == 42 for n in notes))  # closed hi-hat
                bar0 = timing["bars"][0]
                for n, t in zip(notes, bar0["beats"]):
                    self.assertAlmostEqual(n.start, t, delta=0.01)
                self.assertEqual(timing["count_in"]["clicks"], bar0["beats"])
                # Nothing else sounds in the count-in bar.
                first_other = min(n.start for i in pm.instruments if i.name != christmas.COUNT_IN_TRACK
                                  for n in i.notes)
                self.assertGreaterEqual(first_other, bar0["end"] - 0.05)
                self.assertEqual(plan["sections"][0]["info"]["kind"], "count_in")
                self.assertEqual(plan["sections"][1]["label"], "Intro")
                self.assertEqual(plan["sections"][-1]["label"], "Outro")

    def test_one_verse_per_pass_and_no_key_change(self):
        for tune in SUNG:
            with self.subTest(tune=tune):
                plan = christmas.plan_song("christmas_orchestral_full", seed=9, tune=tune,
                                           arrangement="backing_track,key_change" if tune == "joy_to_the_world"
                                           else "backing_track")
                passes = [s for s in plan["sections"] if s["info"]["kind"] in ("pass1", "pass2", "var", "final")]
                self.assertEqual(len(passes), min(lyrics.verse_count(tune), 4))
                self.assertEqual(plan["times"], 1)
                if tune != "joy_to_the_world":
                    self.assertEqual(plan["final_key"], plan["key"])

    def test_transposition(self):
        t = carol("silent_night")
        for key, v7 in (("C", "G7"), ("G", "D7"), ("Bb", "F7"), ("D", "A7")):
            with self.subTest(key=key):
                plan, pm, timing = compose("christmas_fireside_full", "silent_night", key=key, length=60,
                                           arrangement="guide_melody,plain_harmony")
                self.assertEqual(timing["key"], key)
                syms = [c["symbol"] for c in timing["chords"]]
                self.assertIn(key, syms)
                self.assertIn(v7, syms)
                shift = backing.sounding_shift(t, key)
                self.assertEqual(timing["transpose"], shift)
                # The guide plays the tune in the key (any octave).
                want = {(n.pitch + shift) % 12 for n in t.melody}
                got = {n.pitch % 12 for i in pm.instruments if i.name.startswith("Guide Melody") for n in i.notes}
                self.assertTrue(got and got <= want, (key, got - want))
                self.assertEqual({p % 12 for p, _s, _e in timing["melody"]}, want)
                # The bass roots follow the key.
                bass = [i for i in pm.instruments if "Bass" in i.name or "Cello" in i.name]
                if bass:
                    pcs = {n.pitch % 12 for n in bass[0].notes}
                    self.assertIn(backing.key_pc(key), pcs)

    def test_minor_carol_keys(self):
        t = carol("what_child_is_this")
        keys = backing.resolve_keys(t, [])
        labels = [k for k, _ in keys]
        self.assertEqual(labels[:5], ["Am", "Bm", "Dm", "Em", "Gm"])
        self.assertEqual(backing.resolve_keys(t, ["G"])[0][1], "G")         # "G" for a minor carol = G minor
        self.assertEqual(backing.chord_name("V7", "E", "minor"), "B7")
        self.assertEqual(backing.chord_name("i", "G", "minor"), "Gm")

    def test_voice_presets_fit_the_range(self):
        for tid in CAROLS:
            t = carol(tid)
            lo, hi = backing.written_range(t)
            for voice in backing.VOICE_PRESETS:
                with self.subTest(carol=tid, voice=voice):
                    key = backing.voice_key(t, voice)
                    rlo, rhi = backing.VOICE_RANGES[voice]
                    # The melody fits (an octave either way is the singer's choice).
                    shift = (backing.key_pc(key) - t.tonic_pc) % 12
                    fits = [max(0, rlo - (lo + s)) + max(0, (hi + s) - rhi) for s in (shift - 12, shift, shift + 12)]
                    self.assertLessEqual(min(fits), max(0, (hi - lo) - (rhi - rlo)), (key, fits))
        sn = carol("silent_night")
        self.assertNotEqual(backing.voice_key(sn, "low"), backing.voice_key(sn, "high"))


def _has_target(name: str) -> bool:
    try:
        _stem_target(name)
        return True
    except AssertionError:
        return False


class TimingJsonTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.plan, cls.pm, cls.timing = compose("christmas_jazz_trio_full", "silent_night", key="G")

    def test_schema(self):
        tm = self.timing
        for k in ("schema", "tune", "title", "style", "variant", "key", "scale", "transpose", "tempo",
                  "time_signature", "duration", "count_in", "bars", "sections", "chords", "phrases", "melody",
                  "lyrics"):
            self.assertIn(k, tm)
        self.assertEqual(tm["schema"], backing.SCHEMA)
        self.assertEqual(tm["variant"], "backing_track")
        json.dumps(tm)                                          # serialisable
        doc = (PROJECT_ROOT / "docs" / "backing_tracks.md").read_text()
        for k in ("count_in", "bars", "sections", "chords", "phrases", "lyrics", "syllables", "chars"):
            self.assertIn(f'"{k}"', doc)

    def test_bars_beats_sections_and_chords_are_contiguous(self):
        tm = self.timing
        beats = tm["time_signature"][0]
        self.assertEqual(len(tm["bars"]), self.plan["bars"])
        for a, b in zip(tm["bars"], tm["bars"][1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=3)
            self.assertEqual(len(a["beats"]), beats)
            self.assertTrue(all(x < y for x, y in zip(a["beats"], a["beats"][1:])))
        for a, b in zip(tm["sections"], tm["sections"][1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=3)
        ch = tm["chords"]
        self.assertAlmostEqual(ch[0]["start"], tm["count_in"]["end"], places=3)   # chords start after the count-in
        for a, b in zip(ch, ch[1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=3)
            self.assertTrue(re.fullmatch(r"[A-G][b#]?(m|maj7|m7|7|6|m6|dim7|\+|sus[24])?", a["symbol"]), a)
        self.assertAlmostEqual(ch[-1]["end"], tm["bars"][-1]["end"], places=3)
        # The ritardando: the last bars are slower.
        lens = [b["end"] - b["start"] for b in tm["bars"]]
        self.assertGreater(lens[-1], lens[2] * 1.2)

    def test_lyric_lines_follow_the_melody(self):
        tm = self.timing
        lyr = lyrics.load("silent_night")
        self.assertTrue(tm["lyrics"]["available"])
        self.assertEqual(tm["lyrics"]["file"], "data/lyrics/silent_night.txt")
        lines = tm["lyrics"]["lines"]
        passes = [s for s in self.plan["sections"] if s["info"]["kind"] in ("pass1", "pass2", "var", "final")]
        per_pass = [len(lyr.verses[i].lines) for i in range(len(passes))]
        self.assertEqual(len(lines), sum(per_pass))
        last_end = 0.0
        for ln in lines:
            n_syl = len(lyr.syllables(ln["line"]))
            self.assertEqual(len(ln["syllables"]), n_syl)
            self.assertEqual([s["i"] for s in ln["syllables"]], list(range(n_syl)))
            width = len(lyr.text_lines[ln["line"]])
            for s in ln["syllables"]:
                self.assertLess(s["start"], s["end"])
                self.assertTrue(0 <= s["chars"][0] < s["chars"][1] <= width)
            starts = [s["start"] for s in ln["syllables"]]
            self.assertEqual(starts, sorted(starts))
            self.assertGreaterEqual(ln["start"], last_end - 1e-3)
            last_end = ln["end"]
            # Each line is sung inside its pass's section (a pickup may lead in).
            sec = tm["sections"][ln["section"]]
            self.assertGreaterEqual(ln["start"], sec["start"] - 1.6)
            self.assertLessEqual(ln["end"], sec["end"] + 0.01)
        self.assertGreater(lines[0]["start"], tm["count_in"]["end"])

    def test_chords_only_without_lyrics(self):
        _plan, _pm, tm = compose("christmas_choir_full", "angels_we_have_heard", length=60)
        self.assertFalse(tm["lyrics"]["available"])
        self.assertEqual(tm["lyrics"]["lines"], [])
        self.assertTrue(tm["phrases"])
        self.assertTrue(all(p["line"] is None for p in tm["phrases"]))
        self.assertTrue(tm["chords"])

    def test_karaoke_payload(self):
        k = backing.karaoke_payload(self.timing)
        self.assertTrue(k["has_lead"])
        self.assertEqual(len(k["notes"]), len(self.timing["melody"]))
        lyr = lyrics.load("silent_night")
        n_words = sum(len(lyrics.line_words(lyr.text_lines[ln["line"]])) for ln in self.timing["lyrics"]["lines"])
        self.assertEqual(len(k["words"]), n_words)
        starts = [w["start"] for w in k["words"]]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(all(w["end"] > w["start"] for w in k["words"]))
        # Rebuilt from a saved block's spec, the same timing.
        spec = {"plan_args": {"genre": "christmas_jazz_trio_full", "seed": 4, "tune": "silent_night", "key": "G",
                              "tempo": None, "length_seconds": None, "arrangement": "backing_track",
                              "instruments": christmas.band_for(
                                  list(STYLES["christmas_jazz_trio_full"].default_instruments), "backing_track")}}
        again = backing.timing_for_spec(spec, self.pm)
        self.assertEqual(again["lyrics"]["lines"], self.timing["lyrics"]["lines"])
        self.assertIsNone(backing.timing_for_spec({"plan_args": {**spec["plan_args"], "arrangement": ""}}, self.pm))


class LyricsTests(unittest.TestCase):

    def test_files_and_sources(self):
        sources = (PROJECT_ROOT / "data" / "lyrics" / "SOURCES.md").read_text()
        for tid in SUNG:
            with self.subTest(carol=tid):
                p = lyrics.lyrics_path(tid)
                self.assertTrue(p.is_file(), p)
                head = [ln for ln in p.read_text().splitlines() if ln.startswith("#")]
                src = [ln for ln in head if ln.startswith("# source: https://")]
                self.assertEqual(len(src), 1)
                self.assertTrue(any(ln.startswith("# public domain: ") for ln in head))
                self.assertIn(f"`{tid}`", sources)
                self.assertIn(src[0][len("# source: "):].split("?")[0], sources.replace("%3F", "?"))
                self.assertGreaterEqual(len(lyrics.load(tid).verses), 2)
        for tid in NOT_SUNG:
            self.assertFalse(lyrics.lyrics_path(tid).exists())
            self.assertIn(f"`{tid}`", sources)

    def test_syllable_rules(self):
        # Ordinary words (no lyric text): counts and spans that cover the word.
        cases = {"glorious": 3, "nation": 2, "little": 2, "comes": 1, "praises": 2, "heavenly": 3, "people": 2,
                 "lying": 2, "the": 1, "fire": 1, "precious": 2, "everlasting": 4, "o'er": 1, "table": 2}
        for w, n in cases.items():
            spans = lyrics.word_syllables(w)
            self.assertEqual(len(spans), n, (w, spans))
            self.assertEqual(spans[0][0], 0)
            self.assertEqual(spans[-1][1], len(w))
            self.assertTrue(all(a < b for a, b in spans))
            self.assertTrue(all(x[1] == y[0] for x, y in zip(spans, spans[1:])))

    def test_every_verse_aligns_within_the_melisma_rules(self):
        for tid in SUNG:
            t = carol(tid)
            lyr = lyrics.load(tid)
            notes = len(t.melody)
            for p, lines in enumerate(lyrics.align_passes(t, lyr)):
                with self.subTest(carol=tid, verse=p + 1):
                    self.assertTrue(lines)
                    # The lines cover the tune's notes in order, once.
                    self.assertEqual(lines[0].notes[0], 0)
                    self.assertEqual(lines[-1].notes[1], notes)
                    for a, b in zip(lines, lines[1:]):
                        self.assertEqual(a.notes[1], b.notes[0])
                    for lt in lines:
                        n_notes = lt.notes[1] - lt.notes[0]
                        n_syl = len(lyr.syllables(lt.line))
                        # One slot per syllable; notes - syllables = melismas - splits.
                        self.assertEqual(len(lt.syllables), n_syl)
                        self.assertEqual(n_notes - n_syl, lt.melismas - lt.splits)
                        self.assertLessEqual(lt.melismas, lyrics.MAX_MELISMAS)
                        self.assertLessEqual(lt.splits, lyrics.MAX_SPLITS)
                        used = [i for s in lt.syllables for i in s.notes]
                        self.assertEqual(sorted(set(used)), list(range(*lt.notes)))
                        self.assertTrue(all(s.notes for s in lt.syllables))
                        st = [s.start for s in lt.syllables]
                        self.assertEqual(st, sorted(st))
                    # Melismas stay the exception: at least two syllables per three notes.
                    syl = sum(len(lt.syllables) for lt in lines)
                    self.assertGreaterEqual(syl, notes * 2 / 3 - 1)

    def test_phrase_boundaries_end_on_held_notes(self):
        # The lines end where the music breathes: on a note of at least a
        # beat (most of them longer), the same boundaries for every verse.
        for tid in SUNG:
            t = carol(tid)
            passes = lyrics.align_passes(t, lyrics.load(tid))
            with self.subTest(carol=tid):
                bounds = {tuple(lt.notes for lt in p) for p in passes if len(p) == len(passes[0])}
                self.assertEqual(len(bounds), 1)
                held = 0
                for lt in passes[0]:
                    last = t.melody[lt.notes[1] - 1]
                    nxt = t.melody[lt.notes[1]].start if lt.notes[1] < len(t.melody) else last.start + last.dur
                    held += (nxt - last.start) >= 1.0 - 1e-6
                self.assertGreaterEqual(held, len(passes[0]) - 1)


class PlanAndToolsTests(unittest.TestCase):

    def test_variants_catalogued_and_exclusive(self):
        from src.composition import song_plan as sp
        eng = sp.engine_for("christmas_orchestral_full")
        self.assertIn("backing_track", eng.arrangement_variants)
        self.assertIn("guide_melody", eng.arrangement_variants)
        self.assertIn(("backing_track", "guide_melody"), eng.exclusive)

    def test_describe_and_revise(self):
        from src.composition import song_plan as sp
        raw, chips, _notes = sp.rule_describe("Silent Night backing track in G")
        plan, _n = sp.normalize_plan(raw)
        self.assertEqual((plan["genre"], plan["tune"], plan["key"], plan["arrangement"]),
                         ("christmas_orchestral_full", "silent_night", "G", "backing_track"))
        raw, _c, _n = sp.rule_describe("jazz trio What Child Is This, no melody, with a guide melody, low voice")
        plan, _n = sp.normalize_plan(raw)
        self.assertEqual(plan["arrangement"], "guide_melody")
        self.assertEqual(plan["key"], backing.voice_key(carol("what_child_is_this"), "low"))
        p = {"genre": "christmas_fireside_full", "tune": "joy_to_the_world", "key": "D", "arrangement": "warmer"}
        new, fired = sp.rule_revise(p, "lower key")
        self.assertEqual(new["key"], "C")
        new, _f = sp.rule_revise(p, "higher key")
        self.assertEqual(new["key"], "E")
        new, _f = sp.rule_revise(p, "make it a backing track")
        new, _n = sp.normalize_plan(new, p)
        self.assertEqual(sp.split_variants(new["arrangement"]), ["warmer", "backing_track"])
        new2, _f = sp.rule_revise(new, "keep the melody quiet as a guide")
        new2, _n = sp.normalize_plan(new2, new)
        self.assertEqual(sp.split_variants(new2["arrangement"]), ["warmer", "guide_melody"])
        # No key set on a carol: "lower key" goes to its low-voice key.
        new, _f = sp.rule_revise({"genre": "christmas_choir_full", "tune": "silent_night"}, "lower key please")
        self.assertEqual(new["key"], backing.voice_key(carol("silent_night"), "low"))

    def test_chips_show_the_carol(self):
        from src.composition import song_plan as sp
        chips = sp.plan_chips({"genre": "christmas_jazz_trio_full", "tune": "silent_night", "length_seconds": 180})
        self.assertIn("Silent Night", chips)
        self.assertIn("About 3:00", chips)
        self.assertIn("Original tune", sp.plan_chips({"genre": "christmas_pop_full", "tune": "original"}))

    def test_tool_validation(self):
        from src.serve import song_tools as st
        with self.assertRaises(st.ToolError):
            st.backing_tracks(tune="original", wait=False)
        with self.assertRaises(st.ToolError):
            st.backing_tracks(tune="silent_night", genre="funk_fusion_full", wait=False)
        with self.assertRaises(st.ToolError):
            st.backing_tracks(tune="silent_night", keys=["H#"], wait=False)
        with self.assertRaises(st.ToolError):
            st.backing_tracks(tune="White Christmas", wait=False)
        self.assertIn("backing_tracks", st.TOOLS_BY_NAME)
        opts = st.describe_options()["christmas"]
        self.assertIn("backing_tracks", opts)
        self.assertTrue(opts["lyrics"]["silent_night"])
        self.assertFalse(opts["lyrics"]["carol_of_the_bells"])

    def test_request_schema(self):
        from src.api.schemas import BackingTracksRequest, GenerateRequest
        r = BackingTracksRequest(tune="silent_night")
        self.assertEqual(r.keys, [])
        g = GenerateRequest(genre="christmas_pop_full", tune="jingle_bells", length_seconds=120,
                            arrangement="backing_track")
        self.assertEqual((g.tune, g.length_seconds), ("jingle_bells", 120))


if __name__ == "__main__":
    unittest.main()
