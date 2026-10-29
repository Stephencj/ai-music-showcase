"""Built-in synth lead: pitch, glide, legato phrasing."""

import unittest

import numpy as np

from src.audio_processing.render.sfz import Note
from src.audio_processing.render.synth_lead import LeadPatch, render_lead

SR = 44100


def f0(audio, start, end):
    m = audio.mean(axis=0)[int(start * SR):int(end * SR)]
    m = m * np.hanning(len(m))
    spec = np.abs(np.fft.rfft(m, n=1 << 18))
    freqs = np.fft.rfftfreq(1 << 18, 1 / SR)
    keep = freqs > 100
    return float(freqs[keep][np.argmax(spec[keep])])


class SynthLeadTest(unittest.TestCase):
    def test_pitch(self):
        out = render_lead([Note(69, 0.0, 0.5, 100)], SR)
        self.assertAlmostEqual(f0(out, 0.05, 0.25), 440.0, delta=2.0)
        self.assertFalse(np.isnan(out).any())
        self.assertLess(float(np.abs(out).max()), 1.0)

    def test_legato_glides_to_the_new_pitch(self):
        out = render_lead([Note(69, 0.0, 0.3, 100), Note(72, 0.3, 0.8, 100)], SR)
        self.assertAlmostEqual(f0(out, 0.36, 0.56), 523.25, delta=3.0)   # after the glide, before vibrato

    def test_legato_does_not_retrigger_the_attack(self):
        legato = render_lead([Note(69, 0.0, 0.3, 100), Note(72, 0.3, 0.8, 100)], SR)
        detached = render_lead([Note(69, 0.0, 0.2, 100), Note(72, 0.3, 0.8, 100)], SR)
        at = int(0.3 * SR)
        window = slice(at, at + int(0.0005 * SR))
        # A retriggered note restarts from silence; a legato one keeps sounding.
        self.assertGreater(np.abs(legato[:, window]).mean(), 3 * np.abs(detached[:, window]).mean())

    def test_release_and_silence(self):
        out = render_lead([Note(60, 0.0, 0.2, 100)], SR, patch=LeadPatch(release=0.1))
        self.assertLess(float(np.abs(out[:, int(0.6 * SR):]).max()), 1e-3)
        self.assertEqual(render_lead([], SR).shape, (2, 0))


if __name__ == "__main__":
    unittest.main()
