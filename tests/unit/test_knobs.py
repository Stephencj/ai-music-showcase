"""Tests for the generation feel-knobs (resolution + effect on compose_song)."""
import unittest

import pretty_midi

import src.composition.builtins  # noqa: F401
from src.composition.knobs import KNOB_KEYS, default_knobs, resolve_knobs
from src.composition.song_composer import (
    _default_sections_for,
    _lead_guitar_section_plan,
    compose_song,
)
from src.daw_integration.generic.midi_export import GM_DRUMS
from src.daw_integration.generic.styles import STYLES

ROCK = "rock_anthem_full"
_TOMS = {GM_DRUMS["tom_low"], GM_DRUMS["tom_mid"], GM_DRUMS["tom_high"]}


def _compose(knobs=None, seed=7, genre=ROCK):
    out = compose_song(genre=genre, seed=seed,
                       enabled_instruments=tuple(STYLES[genre].default_instruments),
                       skip_audio=True, knobs=knobs)
    return pretty_midi.PrettyMIDI(out["midi_path"])


def _sig(pm):
    return sorted((i.name, len(i.notes)) for i in pm.instruments)


class TestKnobResolution(unittest.TestCase):
    def test_none_equals_default(self):
        self.assertEqual(resolve_knobs("pop_full_song", None),
                         default_knobs("pop_full_song"))

    def test_override_and_clamp(self):
        k = resolve_knobs("pop_full_song", {"voicing_variety": 5.0, "dynamics": -1})
        self.assertEqual(k["voicing_variety"], 1.0)   # clamped to 1
        self.assertEqual(k["dynamics"], 0.0)          # clamped to 0
        self.assertIn("lead_amount", k)

    def test_unknown_keys_ignored(self):
        k = resolve_knobs("pop_full_song", {"nonsense": 1.0})
        self.assertNotIn("nonsense", k)

    def test_all_keys_present(self):
        k = default_knobs("jazz_aaba_full")
        for key in KNOB_KEYS:
            self.assertIn(key, k)


class TestKnobsBackwardCompat(unittest.TestCase):
    def test_knobs_none_is_identical(self):
        self.assertEqual(_sig(_compose(None)), _sig(_compose()))


class TestKnobEffects(unittest.TestCase):
    def test_drum_fill_knob_changes_fill_count(self):
        """More drum_fill -> more tom-fill hits (some patterns use toms
        natively, so compare counts rather than asserting zero)."""
        def toms(knob):
            pm = _compose({"drum_fill": knob})
            return sum(1 for inst in pm.instruments if inst.is_drum
                       for n in inst.notes if n.pitch in _TOMS)
        self.assertGreater(toms(2.0), toms(0.0))

    def test_voicing_variety_knob_changes_shape_count(self):
        """More voicing_variety -> more distinct chord voicings (pop's
        diatonic-colour palette shows it clearly; rock power chords don't)."""
        def shapes(knob):
            pm = _compose({"voicing_variety": knob}, genre="pop_full_song")
            inst = next(i for i in pm.instruments if i.name == "Piano")
            by_start = {}
            for n in inst.notes:
                by_start.setdefault(round(n.start, 2), []).append(n.pitch)
            return len({tuple(sorted(p - min(v) for p in v))
                        for v in by_start.values() if len(v) > 1})
        self.assertGreater(shapes(1.0), shapes(0.0))

    def test_lead_amount_zero_drops_lead(self):
        secs = _default_sections_for(ROCK)
        plan = _lead_guitar_section_plan(secs, 7, resolve_knobs(ROCK, {
            "lead_amount": 0.0, "lead_intro": 1.0, "lead_outro": 1.0,
        }))
        self.assertEqual(plan, set(), "lead_amount=0 should mean no lead")

    def test_lead_intro_outro_can_be_forced(self):
        secs = _default_sections_for(ROCK)
        plan = _lead_guitar_section_plan(secs, 7, resolve_knobs(ROCK, {
            "lead_intro": 1.0, "lead_outro": 1.0,
        }))
        roles = {secs[i]["role"] for i in plan}
        self.assertIn("intro", roles)
        self.assertIn("outro", roles)

    def test_lead_fill_renders_only_a_pickup(self):
        """With lead featured nowhere but fills forced, the lead plays only a
        few notes (a 1-bar turnaround), not a full section."""
        # lead_amount 0 removes featured play; lead_fills 1 forces fills.
        pm = _compose({"lead_amount": 0.0, "lead_intro": 0.0, "lead_outro": 0.0,
                       "lead_fills": 1.0})
        lead = next((i for i in pm.instruments if i.name == "Lead Guitar"), None)
        self.assertIsNotNone(lead, "fills should still create a Lead Guitar track")
        # Fills are ~1 bar each across a handful of sections — far fewer notes
        # than a featured lead (which had 700+ notes earlier).
        self.assertLess(len(lead.notes), 120)
        self.assertGreater(len(lead.notes), 0)


if __name__ == "__main__":
    unittest.main()
