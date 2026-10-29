"""Neo-Soul Chill: strict techniques, the laid-back pocket, phrase stops."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pretty_midi

import src.composition  # noqa: F401
from src.api.arrangement import build_sections
from src.composition.song_composer import compose_song
from src.daw_integration.generic.styles import STYLES

GENRE = "neo_soul_full"


def compose(seed=7, sections=None):
    td = tempfile.TemporaryDirectory()
    secs = sections or build_sections(GENRE, [], None, None)
    res = compose_song(genre=GENRE, sections=secs, seed=seed,
                       enabled_instruments=tuple(STYLES[GENRE].default_instruments),
                       lead_voice="guitar_clean", output_dir=Path(td.name), skip_audio=True)
    pm = pretty_midi.PrettyMIDI(res["midi_path"])
    td.cleanup()
    return res, {i.name: i for i in pm.instruments}


class NeoSoulTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, cls.tracks = compose()
        cls.bar = 4 * 60.0 / STYLES[GENRE].tempo

    def test_strict_neo_soul_techniques(self):
        names = {s["technique"] for s in self.res["selections"]}
        self.assertTrue(names and all(n.startswith("neo_soul_") for n in names), names)

    def test_band(self):
        self.assertEqual(set(self.tracks), {"Drum kit", "Electric Bass", "Electric Piano", "Synth Lead"})

    def test_backbeat_sits_behind_the_grid(self):
        step = self.bar / 16
        snares = [n.start for n in self.tracks["Drum kit"].notes if n.pitch == 38 and n.velocity > 80]
        late = [((t / step) - round(t / step)) * step for t in snares]
        self.assertGreater(float(np.median(late)), 0.005)

    def test_phrase_end_stop_in_the_verse(self):
        # The verse is bars 2-9; its bar 3 (song bar 5) ends with an 8th of silence.
        a, b = 5 * self.bar + 14 * self.bar / 16, 6 * self.bar
        for name, track in self.tracks.items():
            self.assertFalse([n for n in track.notes if a + 0.012 <= n.start < b - 0.015], name)

    def test_same_seed_same_song(self):
        _, again = compose()
        a = [(n.pitch, round(n.start, 4)) for t in self.tracks.values() for n in t.notes]
        b = [(n.pitch, round(n.start, 4)) for t in again.values() for n in t.notes]
        self.assertEqual(a, b)

    def test_clean_guitar_voice(self):
        from src.audio_processing.render.lead_voices import LEAD_VOICES
        v = LEAD_VOICES["guitar_clean"]
        self.assertTrue(all(l.drive_db == 0 and l.chorus > 0 for l in v.layers))


if __name__ == "__main__":
    unittest.main()
