"""Timeline support for Christmas songs: who plays in each section (so a part
the form leaves out shows as resting) and moving the tune off a part that is
silenced or removed (section_overrides[role]["lead"])."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi  # noqa: E402

from src.composition import christmas  # noqa: E402
from src.composition.song_composer import compose_song  # noqa: E402
from src.composition.song_plan import normalize_plan  # noqa: E402
from src.daw_integration.generic.styles import STYLES  # noqa: E402

CHOIR = "christmas_choir_full"


def plan(genre=CHOIR, tune="silent_night", seed=5, length=150, band=None):
    band = band or list(STYLES[genre].default_instruments)
    return band, christmas.plan_song(genre, seed=seed, tune=tune, length_seconds=length, instruments=band)


def compose(genre, band, p, secs):
    d = tempfile.mkdtemp(prefix="xmas_move_")
    try:
        out = compose_song(genre=genre, sections=secs, seed=5, key=p["key"], scale=p["scale"], tempo=p["tempo"],
                           time_signature=p["time_signature"], enabled_instruments=tuple(band),
                           output_dir=Path(d), skip_audio=True)
        return out, pretty_midi.PrettyMIDI(out["midi_path"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def span(pm, secs, i, p):
    """Seconds where section i sounds (planned tempo; the outro's ritardando
    only stretches its end)."""
    bar_s = p["time_signature"][0] * 60.0 / p["tempo"]
    return secs[i]["start_bar"] * bar_s, (secs[i]["end_bar"] + 1) * bar_s


def notes_in(pm, track, a, b):
    return [n for t in pm.instruments if t.name == track for n in t.notes if a - 1e-3 <= n.start < b - 0.05]


class SectionPlaysTests(unittest.TestCase):

    def test_plays_reports_who_the_form_leaves_out(self):
        band, p = plan()
        out, _pm = compose(CHOIR, band, p, p["sections"])
        plays = out["section_plays"]
        self.assertEqual(len(plays), len(p["sections"]))
        intro = next(i for i, s in enumerate(p["sections"]) if s["role"] == "intro")
        # The choir doesn't sing the intro (the organ has it); it does sing the
        # last pass and the ending.
        self.assertNotIn("choir", plays[intro])
        self.assertIn("organ_church", plays[intro])
        for i, s in enumerate(p["sections"]):
            if s["role"] in ("chorus", "outro"):
                self.assertIn("choir", plays[i], s["label"])

    def test_a_masked_part_is_not_reported_playing(self):
        band, p = plan()
        secs = christmas.apply_overrides(p["sections"], {"outro": {"instruments": ["organ_church", "string_section"]}})
        out, _pm = compose(CHOIR, band, p, secs)
        outro = next(i for i, s in enumerate(secs) if s["role"] == "outro")
        self.assertNotIn("choir", out["section_plays"][outro])

    def test_every_style_reports_plays(self):
        for genre in christmas.STYLE_IDS:
            with self.subTest(genre=genre):
                band, p = plan(genre, tune="jingle_bells", length=60)
                out, pm = compose(genre, band, p, p["sections"])
                plays = out["section_plays"]
                self.assertEqual(len(plays), len(p["sections"]))
                self.assertTrue(all(set(x) <= set(band) for x in plays))
                self.assertTrue(all(plays[1:]), "every section but the intro has someone playing")


class MelodyMoveTests(unittest.TestCase):

    def test_section_tune_reports_melody_and_options(self):
        _band, p = plan()
        tunes = [christmas.section_tune(s) for s in p["sections"]]
        chorus = [t for s, t in zip(p["sections"], tunes) if s["role"] == "chorus"]
        self.assertTrue(chorus and all(t["melody"] == "choir" for t in chorus))
        self.assertTrue(all({"choir", "organ_church", "string_section"} <= set(t["melody_options"]) for t in chorus))
        interlude = [t for s, t in zip(p["sections"], tunes) if s["info"].get("kind") == "interlude"]
        self.assertTrue(all(t["melody"] is None for t in interlude))

    def test_move_the_tune_off_a_silenced_choir_to_the_organ(self):
        band, p = plan()
        ov = {"chorus": {"instruments": ["organ_church", "string_section"], "lead": "organ_church"}}
        secs = christmas.apply_overrides(p["sections"], ov)
        out, pm = compose(CHOIR, band, p, secs)
        lo, hi = christmas.PLAYABLE["organ_church"]
        chorus = [i for i, s in enumerate(secs) if s["role"] == "chorus"]
        self.assertTrue(chorus)
        for i in chorus:
            self.assertEqual(christmas.section_tune(secs[i])["melody"], "organ_church")
            self.assertEqual(christmas.section_tune(secs[i])["melody_default"], "choir")
            self.assertNotIn("choir", out["section_plays"][i])
            a, b = span(pm, secs, i, p)
            tune = notes_in(pm, "Organ (Church) Melody", a, b)
            # The whole tune is there, audible, in the organ's range.
            self.assertGreaterEqual(len(tune), len(secs[i]["info"]["melody"]) - 2, secs[i]["label"])
            self.assertTrue(all(n.velocity >= 40 for n in tune))
            self.assertTrue(all(lo <= n.pitch <= hi for n in tune), sorted({n.pitch for n in tune}))
            self.assertFalse(notes_in(pm, "Choir Melody", a, b))
            self.assertFalse(notes_in(pm, "Choir", a, b))
        # The ending keeps the choir on the tune.
        outro = next(i for i, s in enumerate(secs) if s["role"] == "outro")
        a, b = span(pm, secs, outro, p)
        self.assertTrue(notes_in(pm, "Choir Melody", a, b))

    def test_moved_tune_stays_in_range_for_every_option(self):
        from src.composition.instruments import INSTRUMENT_REGISTRY
        for genre in christmas.STYLE_IDS:
            band, p = plan(genre, tune="joy_to_the_world", length=60)
            for target in christmas.melody_options(p["sections"][-1]["info"]):
                with self.subTest(genre=genre, target=target):
                    secs = christmas.apply_overrides(p["sections"], {"outro": {"lead": target}})
                    self.assertEqual(christmas.section_tune(secs[-1])["melody"], target)
                    out, pm = compose(genre, band, p, secs)
                    self.assertIn(target, out["section_plays"][-1])
                    a = span(pm, secs, len(secs) - 1, p)[0]
                    track = f"{INSTRUMENT_REGISTRY[target].label} Melody"
                    tune = notes_in(pm, track, a, 1e9)
                    self.assertGreaterEqual(len(tune), 3, f"{genre}: no tune in the outro on {target}")
                    lo, hi = christmas.PLAYABLE[target]
                    self.assertTrue(all(lo <= n.pitch <= hi for n in tune), sorted({n.pitch for n in tune}))

    def test_a_lead_that_cannot_carry_the_tune_is_ignored(self):
        _band, p = plan()
        for bad in ("upright_bass", "trumpet", "nonsense"):          # no melody register / not in the band
            secs = christmas.apply_overrides(p["sections"], {"chorus": {"lead": bad}})
            self.assertTrue(all(s["info"]["lead"] == "choir" for s in secs if s["role"] == "chorus"))
        # The interlude (role bridge) has no tune: a lead there changes nothing.
        secs = christmas.apply_overrides(p["sections"], {"bridge": {"lead": "string_section"}})
        for a, b in zip(p["sections"], secs):
            if a["info"].get("kind") == "interlude":
                self.assertEqual(b["info"]["lead"], "")

    def test_the_pickup_follows_the_moved_tune(self):
        band, p = plan(tune="joy_to_the_world")
        secs = christmas.apply_overrides(p["sections"], {"chorus": {"lead": "string_section"}})
        for a, b in zip(secs, secs[1:]):
            if a["info"].get("tail_lead"):
                self.assertEqual(a["info"]["tail_lead"], b["info"]["lead"])
        # The plan itself is untouched.
        self.assertTrue(all(s["info"]["lead"] == "choir" for s in p["sections"] if s["role"] == "chorus"))

    def test_normalize_plan_keeps_lead(self):
        out, _notes = normalize_plan({"genre": CHOIR, "section_overrides": {
            "chorus": {"instruments": ["organ_church"], "lead": "organ_church"},
            "outro": {"lead": "not_an_instrument"}}})
        self.assertEqual(out["section_overrides"]["chorus"]["lead"], "organ_church")
        self.assertNotIn("outro", out.get("section_overrides", {}))


if __name__ == "__main__":
    unittest.main()
