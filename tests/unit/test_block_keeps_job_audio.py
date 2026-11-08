"""Saving a generation as a block keeps the generation's own mix (sampled
instruments, mix, loudness) instead of re-rendering the MIDI on the General
MIDI soundfont."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pretty_midi
import soundfile as sf

from src.daw_integration.generic import blocks


def _pm():
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=0.0, end=1.0))
    pm.instruments.append(inst)
    return pm


class BlockKeepsJobAudioTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        p = mock.patch.object(blocks, "BLOCKS_DIR", self.dir / "blocks")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.td.cleanup)
        # A distinctive "real mix": 2 s of a 1 kHz tone, stereo.
        t = np.arange(44100 * 2) / 44100
        tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype("float32")
        self.mix = self.dir / "mix.wav"
        sf.write(self.mix, np.stack([tone, tone], axis=1), 44100)

    def test_audio_source_is_kept_and_midi_is_not_re_rendered(self):
        with mock.patch.object(blocks, "_write_block_wav") as render:
            blocks.save_block("Kept", _pm(), tempo=120, time_signature=(4, 4), bars=1,
                              audio_source=self.mix)
        render.assert_not_called()
        wav = blocks._wav_path("Kept")
        data, sr = sf.read(wav)
        self.assertEqual(sr, 44100)
        self.assertAlmostEqual(len(data) / sr, 2.0, places=2)      # the mix, not the 1 s MIDI
        self.assertTrue(blocks._preview_path("Kept").exists())

    def test_mp3_source_is_converted(self):
        mp3 = self.dir / "mix.mp3"
        self.assertTrue(blocks.write_preview_mp3(self.mix, mp3))
        with mock.patch.object(blocks, "_write_block_wav") as render:
            blocks.save_block("FromMp3", _pm(), tempo=120, time_signature=(4, 4), bars=1,
                              audio_source=mp3)
        render.assert_not_called()
        data, sr = sf.read(blocks._wav_path("FromMp3"))
        self.assertGreater(len(data) / sr, 1.9)

    def test_missing_source_falls_back_to_rendering(self):
        with mock.patch.object(blocks, "_write_block_wav", return_value=False) as render:
            blocks.save_block("Fallback", _pm(), tempo=120, time_signature=(4, 4), bars=1,
                              audio_source=self.dir / "nope.wav")
        render.assert_called_once()


if __name__ == "__main__":
    unittest.main()
