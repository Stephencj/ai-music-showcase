"""Integration: blues and country full-songs grow articulated lead parts."""
import unittest

import pretty_midi

import src.composition.builtins  # noqa: F401  (populates BANK)
from src.composition.licks import LICKS
from src.composition.song_composer import compose_song
from src.daw_integration.generic.midi_export import SCALES
from src.daw_integration.generic.styles import STYLES


def _lead(genre, seed=4):
    enabled = tuple(STYLES[genre].default_instruments)
    out = compose_song(genre=genre, seed=seed, enabled_instruments=enabled,
                       skip_audio=True)
    pm = pretty_midi.PrettyMIDI(out["midi_path"])
    return {i.name: i for i in pm.instruments}


class TestGenreLeads(unittest.TestCase):
    def test_lick_libraries_present(self):
        for g in ("rock", "blues", "country"):
            self.assertTrue(LICKS.get(g), f"no licks for {g}")
        self.assertIn("mixolydian_blues", SCALES)

    def test_blues_lead_plays_with_bends(self):
        by_name = _lead("blues_12bar_full")
        self.assertIn("Lead Guitar", by_name, sorted(by_name))
        lead = by_name["Lead Guitar"]
        self.assertGreater(len(lead.notes), 40)
        self.assertGreater(len(lead.pitch_bends), 30, "blues lead has no bends")

    def test_country_lead_has_double_stops(self):
        by_name = _lead("country_full", seed=11)
        self.assertIn("Lead Guitar", by_name, sorted(by_name))
        self.assertGreater(len(by_name["Lead Guitar"].notes), 40)
        # The sixth double-stops render on a sibling track.
        self.assertIn("Lead Guitar (dbl)", by_name,
                      "no double-stop sibling track for country")
        self.assertGreater(len(by_name["Lead Guitar (dbl)"].notes), 0)

    def test_country_uses_lead_techniques(self):
        enabled = tuple(STYLES["country_full"].default_instruments)
        out = compose_song(genre="country_full", seed=11,
                           enabled_instruments=enabled, skip_audio=True)
        picks = {s["technique"] for s in out["selections"]
                 if s.get("instrument") == "lead_guitar"}
        self.assertTrue(any("country" in p for p in picks),
                        f"no country lead technique fired; got {picks}")


if __name__ == "__main__":
    unittest.main()
