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
    def test_lead_techniques_registered(self):
        for name in ("rock_lead_riff_verse", "rock_lead_riff_chorus",
                     "rock_guitar_solo"):
            self.assertIsNotNone(BANK.get(name), f"{name} not registered")
        solo = BANK.get("rock_guitar_solo")
        self.assertIn("lead_guitar", solo.instruments)
        self.assertIn("bridge", solo.section_roles)  # "Solo" label -> bridge role

    def test_lead_guitar_plays_with_bends(self):
        by_name = _compose()
        self.assertIn("Lead Guitar", by_name,
                      f"no Lead Guitar track; got {sorted(by_name)}")
        lead = by_name["Lead Guitar"]
        self.assertGreater(len(lead.notes), 20, "lead guitar barely plays")
        # Bends survive the MIDI round-trip (articulation rendered + serialized).
        self.assertGreater(len(lead.pitch_bends), 10, "no bends on the lead")

    def test_solo_section_is_not_silent(self):
        """The solo section (bars 72-87 of rock_anthem_full) must contain
        lead-guitar notes — the old behaviour rendered a silent pad there."""
        lead = _compose()["Lead Guitar"]
        lo, hi = 72 * _BAR_DUR, 88 * _BAR_DUR
        in_solo = [n for n in lead.notes if lo <= n.start < hi]
        self.assertTrue(in_solo, "solo section has no lead-guitar notes")

    def test_deterministic(self):
        self.assertEqual(
            {n: len(i.notes) for n, i in _compose(5).items()},
            {n: len(i.notes) for n, i in _compose(5).items()},
        )


if __name__ == "__main__":
    unittest.main()
