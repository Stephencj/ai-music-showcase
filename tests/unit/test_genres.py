"""Genre catalog: the consolidated, de-duplicated view used by the genre wheel.

Pins that every catalog id resolves to a real preset, the feature-demo presets
are hidden, and the catalog covers all the full-song templates (so no song
genre silently disappears from the picker).
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.composition.genres import genre_catalog, section_feel, HIDDEN_PRESETS
from src.daw_integration.generic.styles import STYLES


class GenreCatalogTests(unittest.TestCase):
    def test_all_ids_are_real_presets(self):
        for fam in genre_catalog():
            self.assertTrue(fam["family"])
            self.assertTrue(fam["color"].startswith("#"))
            for g in fam["genres"]:
                self.assertIn(g["id"], STYLES, f"{g['name']} song preset missing")
                self.assertIn(g["section"], STYLES, f"{g['name']} section preset missing")

    def test_demos_are_hidden(self):
        ids = {g["id"] for fam in genre_catalog() for g in fam["genres"]}
        for demo in ("pop_dynamic", "funk_dynamic", "rock_buildup", "jazz_trade_fours"):
            self.assertIn(demo, HIDDEN_PRESETS)
            self.assertNotIn(demo, ids)

    def test_full_song_templates_are_covered(self):
        # Every full-song preset (that isn't a hidden demo) should be the SONG
        # preset of some genre, so the wheel can generate it.
        song_ids = {g["id"] for fam in genre_catalog() for g in fam["genres"]}
        for key, p in STYLES.items():
            if p.rhythm_variants and key not in HIDDEN_PRESETS:
                self.assertIn(key, song_ids, f"full-song preset {key} not on the wheel")

    def test_no_duplicate_song_ids(self):
        ids = [g["id"] for fam in genre_catalog() for g in fam["genres"]]
        self.assertEqual(len(ids), len(set(ids)), "a song preset is listed twice")

    def test_section_feel_falls_back_to_self(self):
        self.assertEqual(section_feel("pop_full_song"), "pop")
        self.assertEqual(section_feel("salsa"), "salsa")
        self.assertEqual(section_feel("not_a_preset"), "not_a_preset")


if __name__ == "__main__":
    unittest.main()
