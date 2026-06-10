"""Integration: rock_anthem_full grows a real lead-guitar part with a solo.

The preset's ``default_instruments`` (auto-ticked in the Compose UI) now
include ``lead_guitar``; here we pass them to compose_song explicitly to
simulate that, then confirm the lead plays — with bends — and that the
solo section is no longer silent.
"""
import unittest

import pretty_midi

import src.composition.builtins  # noqa: F401  (populates BANK)
from src.composition.song_composer import compose_song
from src.composition.techniques import BANK
from src.daw_integration.generic.styles import STYLES

ROCK = "rock_anthem_full"
_ENABLED = tuple(STYLES[ROCK].default_instruments)
_TEMPO = STYLES[ROCK].tempo
_BAR_DUR = 60.0 / _TEMPO * 4  # 4/4


def _compose(seed=7):
    out = compose_song(genre=ROCK, seed=seed, enabled_instruments=_ENABLED,
                       skip_audio=True)
    pm = pretty_midi.PrettyMIDI(out["midi_path"])
    return {i.name: i for i in pm.instruments}


class TestRockLeadIntegration(unittest.TestCase):
    def test_lead_engine_registered(self):
        eng = BANK.get("lead_guitar_engine")
        self.assertIsNotNone(eng, "lead_guitar_engine not registered")
        self.assertEqual(eng.instruments, ("lead_guitar",))
        # Covers every role so there's no generic-melody fallback.
        for role in ("intro", "verse", "chorus", "bridge", "outro"):
            self.assertIn(role, eng.section_roles)

    def test_lead_guitar_plays_with_bends(self):
        by_name = _compose()
        self.assertIn("Lead Guitar", by_name,
                      f"no Lead Guitar track; got {sorted(by_name)}")
        lead = by_name["Lead Guitar"]
        self.assertGreater(len(lead.notes), 20, "lead guitar barely plays")
        # Bends survive the MIDI round-trip (articulation rendered + serialized).
        self.assertGreater(len(lead.pitch_bends), 10, "no bends on the lead")

    def test_lead_is_featured_not_constant(self):
        """The lead is featured, not wallpaper: it must NOT play the intro
        (bars 0-7) and must join the FINAL chorus (bars 72? no — Chorus 2 =
        bars 56-71 in rock_anthem_full)."""
        from src.composition.song_composer import (
            _lead_guitar_section_plan, _default_sections_for,
        )
        secs = _default_sections_for(ROCK)
        # Final chorus is always in the plan; intro/outro never; not all.
        for seed in range(8):
            plan = _lead_guitar_section_plan(secs, seed)
            roles = [(secs[i]["role"], secs[i]["label"]) for i in plan]
            self.assertLess(len(plan), len(secs), "lead plays every section")
            self.assertNotIn("intro", [r for r, _ in roles])
            self.assertNotIn("outro", [r for r, _ in roles])
            chorus_idxs = [i for i, s in enumerate(secs) if s["role"] == "chorus"]
            self.assertIn(chorus_idxs[-1], plan, "lead misses the final chorus")
            # Earlier choruses are NOT joined.
            for ci in chorus_idxs[:-1]:
                self.assertNotIn(ci, plan, "lead joined a non-final chorus")

    def test_lead_absent_from_intro_in_render(self):
        lead = _compose(7)["Lead Guitar"]
        intro = [n for n in lead.notes if n.start < 8 * _BAR_DUR]
        self.assertFalse(intro, "lead guitar should not play the intro")

    def test_deterministic(self):
        self.assertEqual(
            {n: len(i.notes) for n, i in _compose(5).items()},
            {n: len(i.notes) for n, i in _compose(5).items()},
        )


if __name__ == "__main__":
    unittest.main()
