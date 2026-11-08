"""Christmas styles: presets, the public-domain carols (and the copyrighted
denylist), the form planner and its parts (no half-step rubs against the
tune), original tunes, the song-plan engine and its describe/revise rules,
the song tools, the stem levelling and the playlist mix."""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi  # noqa: E402

from src.composition import BANK, christmas  # noqa: E402
from src.composition.carols import (  # noqa: E402
    CAROLS, DENYLIST, bar_sums, carol, carol_catalog, raw_text,
)
from src.composition.song_composer import _GENRE_TAG_MAP, _STRICT_GENRES, compose_song  # noqa: E402
from src.daw_integration.generic.midi_export import CHORD_FORMULAS, roman_to_semitone_offset  # noqa: E402
from src.daw_integration.generic.styles import STYLES  # noqa: E402

GENRES = tuple(christmas.STYLE_IDS)


def compose(genre: str, tune: str, seed: int = 3, length: float = 150, arrangement: str = "",
            overrides: dict | None = None):
    band = christmas.band_for(list(STYLES[genre].default_instruments), arrangement)
    plan = christmas.plan_song(genre, seed=seed, tune=tune, length_seconds=length, arrangement=arrangement,
                               instruments=band)
    out_dir = tempfile.mkdtemp(prefix="xmas_")
    try:
        out = compose_song(genre=genre, sections=christmas.apply_overrides(plan["sections"], overrides), seed=seed, key=plan["key"], scale=plan["scale"],
                           tempo=plan["tempo"], time_signature=plan["time_signature"], arrangement=arrangement,
                           enabled_instruments=tuple(band), output_dir=Path(out_dir), skip_audio=True)
        pm = pretty_midi.PrettyMIDI(out["midi_path"])
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return plan, pm


def held_rubs(pm: pretty_midi.PrettyMIDI, tempo: float) -> list:
    """Held melody notes (3/4 beat+) a minor 2nd / 9th from a note another
    pitched part holds against them."""
    beat = 60.0 / tempo
    pitched = [i for i in pm.instruments if not i.is_drum and i.program not in (112, 113)]
    mel = [i for i in pitched if i.name.endswith("Melody")]
    others = [i for i in pitched if not i.name.endswith("Melody")]
    out = []
    for a in mel:
        for n in a.notes:
            if n.end - n.start < 0.7 * beat:
                continue
            for b in others:
                for m in b.notes:
                    if m.start >= n.end or m.end <= n.start:
                        continue
                    if min(n.end, m.end) - max(n.start, m.start) < 0.35 * beat:
                        continue
                    lo, hi = sorted((n.pitch, m.pitch))
                    if (hi - lo) % 12 == 1:
                        out.append((round(n.start, 2), a.name, n.pitch, b.name, m.pitch))
    return out


class PresetTests(unittest.TestCase):

    def test_six_sampled_strict_presets(self):
        self.assertEqual(len(GENRES), 6)
        from src.audio_processing.render.profiles import resolve_profile
        from src.composition.genres import genre_catalog
        wheel = {g["id"] for fam in genre_catalog() if fam["family"] == "Christmas" for g in fam["genres"]}
        for g in GENRES:
            p = STYLES[g]
            self.assertEqual(p.sound, "sampled", g)
            self.assertIn(g, _STRICT_GENRES)
            self.assertEqual(_GENRE_TAG_MAP[g], ("christmas",))
            self.assertEqual(resolve_profile(g).name, "christmas")
            self.assertIn(g, wheel)
            self.assertIn(g, christmas.STYLE_INFO)
            for inst in p.default_instruments:
                self.assertTrue(BANK.pick(inst, "verse", np.random.default_rng(0), preferred_tags=("christmas",),
                                          strict=True), (g, inst))

    def test_christmas_parts_never_leak_into_other_genres(self):
        rng = np.random.default_rng(0)
        for _ in range(50):
            t = BANK.pick("piano", "verse", rng, preferred_tags=("pop",))
            self.assertTrue(t is None or "christmas" not in t.tags, t)
            t = BANK.pick("chords", "chorus", rng)
            self.assertTrue(t is None or "christmas" not in t.tags, t)

    def test_new_sampled_instruments_are_mapped(self):
        from src.audio_processing.render import sampled
        ids = {i.id: i for i in sampled.SAMPLED_INSTRUMENTS}
        for sid, prog in (("grand_piano", 0), ("upright_bass", 32), ("harp", 46), ("glockenspiel", 9),
                          ("sleigh_bells", 112), ("shaker", 113), ("flute", 73), ("clarinet", 71), ("oboe", 68),
                          ("church_organ", 19), ("cello", 42), ("muted_trumpet", 59)):
            self.assertIn(prog, ids[sid].programs, sid)


class CarolTests(unittest.TestCase):

    def test_bars_add_up(self):
        for tid in CAROLS:
            t, raw = carol(tid), raw_text(tid)
            mel, ch = bar_sums(raw["melody"]), bar_sums(raw["chords"])
            for i, b in enumerate(mel):
                want = t.pickup if (i == 0 and t.pickup) else t.beats
                self.assertAlmostEqual(b, want, msg=f"{tid} melody bar {i + 1}")
            for i, b in enumerate(ch):
                self.assertAlmostEqual(b, t.beats, msg=f"{tid} chord bar {i + 1}")
            self.assertEqual(len(ch), t.bars)
            self.assertEqual(len(mel) - (1 if t.pickup else 0), t.bars, tid)

    def test_strong_beats_sit_on_the_chords(self):
        """Every strong-beat or long melody note is a chord tone or a gentle
        tension of the chord written under it (catches encoding slips)."""
        ext = {"maj": (2, 9, 11), "min": (2, 10), "7": (2, 9), "maj7": (2, 9), "min7": (2, 5)}
        for tid in CAROLS:
            t = carol(tid)
            for n in t.melody:
                if n.start < 0:
                    continue
                strong = (n.start % t.beats == 0) or (t.beats == 4 and n.start % 2 == 0) or n.dur >= 1.5
                if not strong:
                    continue
                c = t.chord_at(n.start)
                off, q = roman_to_semitone_offset(c.symbol, t.scale)
                root = (t.tonic_pc + off) % 12
                ok = {(root + i) % 12 for i in CHORD_FORMULAS.get(q, (0, 4, 7))}
                ok |= {(root + i) % 12 for i in ext.get(q, ())}
                self.assertIn(n.pitch % 12, ok, f"{tid} bar {int(n.start // t.beats) + 1}: {n.pitch} over {c.symbol}")

    def test_every_carol_is_public_domain(self):
        for tid, info in carol_catalog().items():
            self.assertIn("Public domain", info["source"], tid)
            years = [int(y) for y in re.findall(r"\b(1[0-9]{3})\b", info["source"])]
            self.assertTrue(years and max(years) < 1929, f"{tid}: {info['source']}")

    def test_denylist_blocks_modern_songs(self):
        for must in ("all i want for christmas", "let it snow", "have yourself a merry little christmas",
                     "white christmas", "rudolph", "frosty", "sleigh ride", "christmas time is here"):
            self.assertIn(must, DENYLIST)
        for tid, info in carol_catalog().items():
            for bad in DENYLIST:
                self.assertNotIn(bad, tid.replace("_", " "), tid)
                self.assertNotIn(bad, info["title"].lower(), tid)
        self.assertEqual(christmas.denied_song("play White Christmas please"), "white christmas")
        titles = {f"{a} {b}".lower() for a in christmas._TITLE_WORDS[0] for b in christmas._TITLE_WORDS[1] + ("Waltz",)}
        for bad in DENYLIST:
            self.assertFalse(any(bad in t for t in titles), bad)               # original tunes' names too
        self.assertIsNone(carol("white_christmas"))


class OriginalTuneTests(unittest.TestCase):

    def test_original_tunes_are_aaba_and_fit_their_chords(self):
        for seed in (1, 2, 3, 40):
            for beats in (3, 4):
                t = christmas.original_tune(seed, beats, plain=False)
                self.assertEqual(t.bars, 32)
                self.assertTrue(t.melody)
                self.assertLessEqual(max(n.start + n.dur for n in t.melody), 32 * beats + 1e-6)
                for n in t.melody:
                    if n.start % beats == 0 or n.dur >= 2:
                        c = t.chord_at(n.start)
                        root, q = christmas.parse_symbol(c.symbol, 0, "major")
                        self.assertTrue(christmas.fits(n.pitch, root, q), (seed, beats, n, c.symbol))
        a, b = christmas.original_tune(1, 4), christmas.original_tune(2, 4)
        self.assertNotEqual([n.pitch for n in a.melody], [n.pitch for n in b.melody])
        self.assertEqual(christmas.original_tune(1, 4), christmas.original_tune(1, 4))

    def test_original_harmony_uses_the_christmas_idioms(self):
        syms = set()
        for seed in range(30):
            syms |= {c.symbol for c in christmas.original_tune(seed, 4).chords}
        for want in ("ii7", "V7", "VI7", "#idim", "iv7", "Vsus4", "II7"):
            self.assertIn(want, syms)


class PlanTests(unittest.TestCase):

    def test_sections_are_contiguous_and_carry_their_chords(self):
        for g in GENRES:
            for tune in ("silent_night", "the_first_noel", "original"):
                plan = christmas.plan_song(g, seed=5, tune=tune, length_seconds=180)
                beats = plan["time_signature"][0]
                bar = 0
                for s in plan["sections"]:
                    self.assertEqual(s["start_bar"], bar)
                    bars = s["end_bar"] - s["start_bar"] + 1
                    self.assertAlmostEqual(sum(d for _s, _st, d in s["info"]["chords"]), bars * beats, msg=s["label"])
                    self.assertAlmostEqual(sum(d for _s, d in s["progression"]), bars)
                    self.assertTrue(s["progression_exact"])
                    bar += bars
                self.assertEqual(plan["sections"][0]["role"], "intro")
                self.assertEqual(plan["sections"][-1]["role"], "outro")
                self.assertTrue(plan["sections"][-1]["tempo_points"])        # the ritardando

    def test_length_picks_the_number_of_passes(self):
        short = christmas.plan_song("christmas_jazz_trio_full", seed=1, tune="silent_night", tempo=76,
                                    length_seconds=120)
        long = christmas.plan_song("christmas_jazz_trio_full", seed=1, tune="silent_night", tempo=76,
                                   length_seconds=300)
        self.assertLess(short["seconds"], long["seconds"])
        for p, want in ((short, 120), (long, 300)):
            self.assertLess(abs(p["seconds"] - want), 50, p["seconds"])

    def test_meter_key_and_lift(self):
        p = christmas.plan_song("christmas_choir_full", seed=2, tune="silent_night", key="D")
        self.assertEqual(p["time_signature"], (3, 4))
        self.assertEqual(p["key"], "D")
        lifted = christmas.plan_song("christmas_pop_full", seed=2, tune="jingle_bells", key="C",
                                     arrangement="key_change", length_seconds=200)
        self.assertEqual(lifted["final_key"], "Db")
        before = [s for s in lifted["sections"] if not s.get("key")][-1]
        self.assertIn(before["info"]["chords"][-1][0], ("bVI7",))          # the pivot into the new key
        flat = christmas.plan_song("christmas_pop_full", seed=2, tune="jingle_bells", key="C",
                                   arrangement="no_key_change", length_seconds=200)
        self.assertEqual(flat["final_key"], "C")
        minor = christmas.plan_song("christmas_fireside_full", seed=4, tune="what_child_is_this")
        self.assertEqual(minor["scale"], "minor")

    def test_tempo_map_and_meter_reach_the_midi(self):
        plan, pm = compose("christmas_jazz_trio_full", "silent_night", seed=4)
        ts = pm.time_signature_changes[0]
        self.assertEqual((ts.numerator, ts.denominator), (3, 4))
        _times, tempi = pm.get_tempo_changes()
        self.assertLess(min(tempi), plan["tempo"] * 0.75)                  # it slows into the ending


class ArrangementTests(unittest.TestCase):

    def test_every_part_plays_and_no_held_rubs(self):
        for g in GENRES:
            for tune in list(CAROLS) + ["original"]:
                plan, pm = compose(g, tune, seed=3, length=150)
                names = {i.name for i in pm.instruments if i.notes}
                self.assertTrue(any(n.endswith("Melody") for n in names), (g, tune))
                self.assertEqual(held_rubs(pm, plan["tempo"]), [], (g, tune))
                for inst in STYLES[g].default_instruments:
                    label = {"drum_kit": ("Drum kit", "Brushes")}.get(inst)
                    from src.composition.instruments import INSTRUMENT_REGISTRY
                    label = label or (INSTRUMENT_REGISTRY[inst].label,)
                    self.assertTrue(any(n.startswith(lb) for n in names for lb in label), (g, tune, inst, names))

    def test_variants_change_the_parts(self):
        _p, plain = compose("christmas_orchestral_full", "jingle_bells")
        _p, warm = compose("christmas_orchestral_full", "jingle_bells", arrangement="warmer")
        def count(pm, name):
            return sum(len(i.notes) for i in pm.instruments if i.name.startswith(name))
        self.assertGreater(count(plain, "Glockenspiel"), 0)
        self.assertEqual(count(warm, "Glockenspiel"), 0)
        _p, calm = compose("christmas_swing_full", "jingle_bells", arrangement="less_busy")
        _p, busy = compose("christmas_swing_full", "jingle_bells")
        comp = lambda pm: sum(len(i.notes) for i in pm.instruments if i.name == "Piano")  # noqa: E731
        self.assertLess(comp(calm), comp(busy))
        _p, bells = compose("christmas_jazz_trio_full", "jingle_bells", arrangement="sleigh_bells")
        self.assertGreater(count(bells, "Sleigh Bells"), 0)
        plan, strings = compose("christmas_swing_full", "silent_night", arrangement="strings_ending")
        hold = plan["sections"][-1]
        bar_s = plan["time_signature"][0] * 60 / plan["tempo"]
        t_hold = (hold["start_bar"] * plan["time_signature"][0] + hold["info"]["hold_from"]) * 60 / plan["tempo"]
        last = {i.name for i in strings.instruments for n in i.notes if n.start >= t_hold - 0.05 and not i.is_drum}
        self.assertTrue(last and all("String" in n or "Harp" in n for n in last), last)
        plan, orch = compose("christmas_orchestral_full", "the_first_noel")
        hold = plan["sections"][-1]
        t_hold = (hold["start_bar"] * plan["time_signature"][0] + hold["info"]["hold_from"]) * 60 / plan["tempo"]
        last = {i.name for i in orch.instruments for n in i.notes if n.start >= t_hold - 0.05 and not i.is_drum}
        self.assertTrue(last and all("String" in n or "Harp" in n for n in last), last)   # ends on the strings
        self.assertGreater(bar_s, 0)

    def test_catalog_matches_the_variants_the_code_reads(self):
        src = Path(christmas.__file__).read_text()
        used = set(re.findall(r'"([a-z_]+)" (?:not )?in (?:sec\.|self\.)?var\b', src))
        used |= set(re.findall(r'return "([a-z_]+)" in self\.var', src))
        used |= set(christmas.ARRANGEMENT_INSTRUMENTS)               # variants that bring a player
        self.assertEqual(set(christmas.ARRANGEMENT_VARIANTS) - used, set(), "catalogued variant no code reads")
        self.assertEqual(used - set(christmas.ARRANGEMENT_VARIANTS), set(), "variant read but not catalogued")

    def test_timeline_silences_the_choir_in_a_section(self):
        # The Timeline's Choir lane rests a section with an instrument mask
        # that leaves out "choir": its pad and the tune it sings go quiet there.
        g = "christmas_choir_full"
        mask = [i for i in STYLES[g].default_instruments if i != "choir"]
        plan, full = compose(g, "silent_night")
        _p, rest = compose(g, "silent_night", overrides={"chorus": {"instruments": mask}})
        beat = 60 / plan["tempo"]
        def choir_in(pm, sec):
            # (a beat in from each end: pickups and early attacks of its neighbours)
            a = (sec["start_bar"] * plan["time_signature"][0] + 1) * beat
            b = ((sec["end_bar"] + 1) * plan["time_signature"][0] - 1) * beat
            return sum(1 for i in pm.instruments if i.name.startswith("Choir") for n in i.notes if a <= n.start < b)
        for sec in plan["sections"]:
            if sec["role"] == "chorus":
                self.assertGreater(choir_in(full, sec), 0)
                self.assertEqual(choir_in(rest, sec), 0)
            elif sec["role"] == "outro":                                       # still sings the Amen
                self.assertEqual(choir_in(rest, sec), choir_in(full, sec))
                self.assertGreater(choir_in(rest, sec), 0)


class SongPlanTests(unittest.TestCase):

    def test_engine_and_guide(self):
        from src.composition import song_plan as sp
        for g in GENRES:
            eng = sp.engine_for(g)
            self.assertEqual(eng.id, "christmas")
            self.assertTrue(eng.tunes)
        self.assertEqual(set(sp.engine_for(GENRES[0]).arrangement_variants), set(christmas.ARRANGEMENT_VARIANTS))
        guide = sp.system_prompt()
        for g in GENRES:
            self.assertIn(g, guide)
        for tid in CAROLS:
            self.assertIn(tid, guide)
        self.assertIn("White Christmas", guide)

    def test_describe_and_revise_rules(self):
        from src.composition.song_plan import normalize_plan, rule_describe, rule_revise

        def describe(text):
            raw, _chips, notes = rule_describe(text)
            plan, n2 = normalize_plan(raw)
            return plan, notes + n2

        plan, _ = describe("cozy jazz trio Christmas, Silent Night, background")
        self.assertEqual(plan["genre"], "christmas_jazz_trio_full")
        self.assertEqual(plan["tune"], "silent_night")
        self.assertEqual(plan["target_lufs"], -16.0)
        plan2, _ = describe("big band christmas swing, jingle bells, 3 minutes")
        self.assertEqual((plan2["genre"], plan2["tune"], plan2["length_seconds"]),
                         ("christmas_swing_full", "jingle_bells", 180))
        plan3, notes = describe("a christmas pop song like All I Want for Christmas")
        self.assertEqual(plan3["genre"], "christmas_pop_full")
        self.assertEqual(plan3["tune"], "original")
        self.assertTrue(any("copyrighted" in n for n in notes))
        for genre_words, want in (("orchestral", "christmas_orchestral_full"), ("acoustic fireside", "christmas_fireside_full"),
                                  ("church choir", "christmas_choir_full"), ("pop anthem", "christmas_pop_full")):
            self.assertEqual(describe(f"{genre_words} christmas")[0]["genre"], want)

        base = {"genre": "christmas_jazz_trio_full", "tune": "silent_night"}
        for feedback, want in (("add sleigh bells", "sleigh_bells"), ("warmer", "warmer"), ("less busy", "less_busy"),
                               ("end on the celesta", "celesta_ending"), ("no key change", "no_key_change")):
            raw, _fired = rule_revise(base, feedback)
            new, _n = normalize_plan(raw, previous=base)
            self.assertIn(want, new.get("arrangement", ""), feedback)
            self.assertEqual(new["genre"], base["genre"], feedback)
            self.assertEqual(new["tune"], "silent_night")
        raw, _ = rule_revise(base, "add sleigh bells")
        self.assertIn("sleigh_bells", normalize_plan(raw, previous=base)[0]["instruments"])
        raw, _ = rule_revise(base, "make it orchestral")
        new, _ = normalize_plan(raw, previous=base)
        self.assertEqual((new["genre"], new["tune"]), ("christmas_orchestral_full", "silent_night"))
        # Funk Fusion feedback doesn't pick up Christmas variants (and vice versa).
        funk = {"genre": "funk_fusion_full"}
        raw, _ = rule_revise(funk, "less busy and warmer")
        self.assertNotIn("warmer", normalize_plan(raw, previous=funk)[0].get("arrangement", ""))


class SongToolsTests(unittest.TestCase):

    def test_options_and_validation(self):
        from src.serve import song_tools
        from src.serve.song_tools import ToolError
        opts = song_tools.describe_options()
        self.assertIn("christmas", opts)
        self.assertEqual(set(opts["christmas"]["tunes"]["carols"]), set(CAROLS))
        self.assertIn("christmas_mix", song_tools.TOOLS_BY_NAME)
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="christmas_pop_full", tune="White Christmas", wait=False)
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="christmas_pop_full", tune="silent nite", wait=False)
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="funk_fusion_full", tune="silent_night", wait=False)
        with self.assertRaises(ToolError):
            song_tools.generate_song(genre="christmas_pop_full", arrangement="hits_only", wait=False)
        with self.assertRaises(ToolError):
            song_tools.christmas_mix(wait=False)
        styles = {s["name"]: s for s in song_tools.list_styles("christmas")}
        self.assertEqual(set(styles), set(GENRES))
        self.assertTrue(all(s["arrangement_variants"] for s in styles.values()))


class StemTargetTests(unittest.TestCase):

    def test_stems_are_levelled_to_their_targets(self):
        from src.audio_processing.render.loudness import integrated_lufs
        from src.audio_processing.render.mix import Mixer
        from src.audio_processing.render.synth import TrackStem
        sr = 44100
        t = np.arange(sr * 4) / sr
        tone = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        mixer = Mixer(stem_targets={"melody": -18.0, "family:drums": -30.0})
        out = mixer.process_stem(TrackStem(name="Flute Melody", program=73, is_drum=False,
                                           audio=np.stack([tone, tone]), sample_rate=sr))
        self.assertAlmostEqual(integrated_lufs(out.audio, sr), -18.0, delta=0.6)
        plain = Mixer().process_stem(TrackStem(name="Flute", program=73, is_drum=False,
                                               audio=np.stack([tone, tone]), sample_rate=sr))
        self.assertGreater(abs(integrated_lufs(plain.audio, sr) + 18.0), 1.0)


class PlaylistTests(unittest.TestCase):

    def test_running_order_is_varied(self):
        from src.audio_processing.render.playlist import plan_mix
        tracks = plan_mix(total_minutes=60, seed=7)
        self.assertGreaterEqual(len(tracks), 15)
        for a, b in zip(tracks, tracks[1:]):
            self.assertNotEqual(a.genre, b.genre)
            self.assertNotEqual(a.key, b.key)
        carols = [t.tune for t in tracks if t.tune != "original"]
        first = carols[: len(CAROLS)]
        self.assertEqual(len(first), len(set(first)))                      # no repeat before every carol played
        self.assertTrue(any(t.tune == "original" for t in tracks))
        self.assertEqual(len({t.seed for t in tracks}), len(tracks))
        self.assertEqual(len(plan_mix(count=5, seed=1)), 5)
        self.assertEqual([t.genre for t in plan_mix(count=4, seed=3)], [t.genre for t in plan_mix(count=4, seed=3)])

    def test_render_mix_crossfades_at_one_loudness(self):
        import soundfile as sf

        from src.api import service
        from src.audio_processing.render import playlist
        sr = 44100
        made = []

        def fake_generation(req, progress, job_id):
            d = service.API_OUT / job_id
            d.mkdir(parents=True, exist_ok=True)
            n = len(made)
            t = np.arange(int(sr * 12)) / sr
            amp = 0.05 if n % 2 else 0.4                                   # very different levels
            x = (amp * np.sin(2 * np.pi * (220 + 110 * n) * t)).astype(np.float32)
            wav = d / "mix.wav"
            sf.write(str(wav), np.stack([x, x]).T, sr)
            made.append(job_id)
            return {"_paths": {"audio_wav": str(wav)}, "tune_title": f"Song {n + 1}", "key": "C", "tempo": 100,
                    "seed": n, "tune": "original"}

        out = Path(tempfile.mkdtemp(prefix="mix_"))
        orig = service.run_generation
        service.run_generation = fake_generation
        try:
            tracks = playlist.plan_mix(count=3, seed=2)
            res = playlist.render_mix(tracks, name="t", out_dir=out, crossfade=2.0, target_lufs=-16.0,
                                      formats=("wav",))
            audio, rate = sf.read(res.files["wav"], always_2d=True)
            self.assertEqual(rate, sr)
            self.assertAlmostEqual(len(audio) / sr, 3 * 12 - 2 * 2.0, delta=0.1)   # two crossfades
            from src.audio_processing.render.loudness import integrated_lufs
            self.assertAlmostEqual(integrated_lufs(audio.T.astype(np.float32), sr), -16.0, delta=1.0)
            self.assertLessEqual(float(np.abs(audio).max()), 10 ** (-1 / 20) + 1e-3)
            starts = [t["start"] for t in res.tracks]
            self.assertEqual(starts, sorted(starts))
            self.assertAlmostEqual(starts[1], 10.0, delta=0.1)
            self.assertTrue(Path(res.files["tracklist"]).exists())
            self.assertIn("0:10 Song 2", playlist.chapters(res.tracks))
            self.assertFalse(any((service.API_OUT / j).exists() for j in made))    # per-song renders cleaned
        finally:
            service.run_generation = orig
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
