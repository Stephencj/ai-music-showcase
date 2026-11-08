"""SFZ dialect details the newer libraries rely on: an #include in the middle
of a line (Salamander), Windows backslash sample paths (Shinyguitar), a
typo'd group define (Swirly Drums' ``$HTQTRGRPP`` → ``15P``) and a CC
crossfade given only its low end (``xfout_locc100=0``)."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from src.audio_processing.render.sfz import Note, SampleCache, SfzRenderer, load_sfz


class SfzCompatTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = Path(td.name)
        (self.root / "s").mkdir()
        t = np.arange(4410) / 44100
        sf.write(self.root / "s" / "a.wav", np.stack([np.sin(2 * np.pi * 440 * t)] * 2, axis=1) * 0.5, 44100)

    def _load(self, text, **files):
        for name, body in files.items():
            (self.root / name).write_text(body)
        (self.root / "i.sfz").write_text(text)
        return load_sfz(self.root / "i.sfz")

    def test_midline_include(self):
        inst = self._load('<group> #include "vel.txt" lovel=1 hivel=64 #include "reg.txt"\n',
                          **{"vel.txt": "#define $V a\n", "reg.txt": "<region> sample=s/$V.wav key=60\n"})
        self.assertEqual(len(inst.regions), 1)
        self.assertEqual((inst.regions[0].lovel, inst.regions[0].hivel, inst.regions[0].lokey), (1, 64, 60))
        self.assertTrue(inst.regions[0].sample_path.exists())

    def test_backslash_paths_and_typo_group(self):
        inst = self._load("<region> sample=s\\a.wav key=60 group=16 off_by=15P\n")
        r = inst.regions[0]
        self.assertTrue(r.sample_path.exists())
        self.assertEqual((r.group, r.off_by), (16, 15))

    def test_one_sided_cc_crossfade_plays_at_its_end(self):
        inst = self._load("<control> set_cc100=0\n<region> sample=s/a.wav key=60 xfout_locc100=0\n")
        audio = SfzRenderer(inst, 44100, cache=SampleCache()).render([Note(60, 0.0, 0.1, 100)])
        self.assertGreater(float(np.abs(audio).max()), 0.01)


if __name__ == "__main__":
    unittest.main()
