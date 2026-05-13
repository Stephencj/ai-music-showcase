"""Tests for the HQ block audio pipeline (Phase 2).

Verifies:
- ``save_block`` writes a 44.1 kHz stereo WAV (was 22 kHz mono).
- ``ensure_preview_wav`` does the same lazily.
- The graceful fallback fires (and still writes SOME .wav) when the
  HQ pipeline raises — block save is never blocked by a preview
  failure.
- ``rerender_block_wav`` replaces an existing WAV with a fresh HQ
  render.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pretty_midi
import soundfile as sf

from src.daw_integration.generic import blocks as block_store


def _tiny_pm() -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, name="Melody")
    for beat, p in enumerate([60, 64, 67, 72]):
        inst.notes.append(pretty_midi.Note(
            velocity=80, pitch=p, start=beat * 0.5, end=(beat + 1) * 0.5,
        ))
    pm.instruments.append(inst)
    return pm


class SaveBlockHQTests(unittest.TestCase):
    """save_block writes a 44.1 kHz stereo preview by default."""

    def setUp(self):
        self.original_dir = block_store.BLOCKS_DIR
        self.tmpdir = Path(__file__).parent / f"_tmp_hq_{id(self)}"
        self.tmpdir.mkdir(exist_ok=True)
        block_store.BLOCKS_DIR = self.tmpdir

    def tearDown(self):
        block_store.BLOCKS_DIR = self.original_dir
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_sample_rate_is_44100(self):
        self.assertEqual(block_store._DEFAULT_PREVIEW_SR, 44100)

    def test_save_block_writes_44100_stereo_wav(self):
        pm = _tiny_pm()
        block_store.save_block(
            "test_hq", pm, tempo=120.0, time_signature=(4, 4), bars=1,
        )
        wav = self.tmpdir / "test_hq.wav"
        self.assertTrue(wav.exists())
        info = sf.info(str(wav))
        self.assertEqual(info.samplerate, 44100)
        self.assertEqual(info.channels, 2)

    def test_ensure_preview_wav_writes_44100_stereo(self):
        pm = _tiny_pm()
        # Save WITHOUT writing wav, so ensure_preview_wav has to do it.
        block_store.save_block(
            "test_lazy", pm, tempo=120.0, time_signature=(4, 4), bars=1,
            write_wav=False,
        )
        result = block_store.ensure_preview_wav("test_lazy")
        self.assertIsNotNone(result)
        info = sf.info(str(result))
        self.assertEqual(info.samplerate, 44100)
        self.assertEqual(info.channels, 2)

    def test_save_block_falls_back_when_hq_raises(self):
        """If the HQ path fails (e.g. missing soundfont in CI), block
        save still produces SOME .wav via the pretty_midi fallback."""
        pm = _tiny_pm()
        with mock.patch.object(
            block_store, "_write_block_wav_hq", return_value=False,
        ):
            block_store.save_block(
                "test_fallback", pm, tempo=120.0,
                time_signature=(4, 4), bars=1,
            )
        wav = self.tmpdir / "test_fallback.wav"
        self.assertTrue(wav.exists(), "fallback should still write a .wav")
        info = sf.info(str(wav))
        # Fallback is 22050 mono.
        self.assertEqual(info.samplerate, 22050)
        self.assertEqual(info.channels, 1)

    def test_rerender_block_wav_replaces_existing(self):
        """Even if a 22 kHz mono .wav already exists, rerender_block_wav
        overwrites it with a fresh HQ render."""
        pm = _tiny_pm()
        # Save with WRITE_WAV but force the fallback path (low-quality).
        with mock.patch.object(
            block_store, "_write_block_wav_hq", return_value=False,
        ):
            block_store.save_block(
                "test_rerender", pm, tempo=120.0,
                time_signature=(4, 4), bars=1,
            )
        wav = self.tmpdir / "test_rerender.wav"
        before = sf.info(str(wav))
        self.assertEqual(before.samplerate, 22050)
        # Now force a fresh HQ re-render — should overwrite.
        result = block_store.rerender_block_wav("test_rerender")
        self.assertEqual(result, wav)
        after = sf.info(str(wav))
        self.assertEqual(after.samplerate, 44100)
        self.assertEqual(after.channels, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
