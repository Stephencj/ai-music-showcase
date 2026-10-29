"""SFZ sample player: parsing, region choice, pitch, envelopes, chokes.

Builds tiny instruments from generated sine samples in a temp dir, so the
tests never need the downloaded libraries.
"""

import os
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from src.audio_processing.render.sfz import (
    Note,
    SfzRenderer,
    _file_loop,
    load_sfz,
    note_number,
)

SR = 44100


def _sine(path: Path, hz: float, seconds: float = 1.0, amp: float = 0.5) -> None:
    t = np.arange(int(SR * seconds)) / SR
    sf.write(str(path), (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32), SR)


def _f0(audio: np.ndarray, start: float = 0.05, length: float = 0.5) -> float:
    m = audio.mean(axis=0)[int(start * SR):int((start + length) * SR)]
    m = m * np.hanning(len(m))
    spec = np.abs(np.fft.rfft(m, n=1 << 18))
    freqs = np.fft.rfftfreq(1 << 18, 1 / SR)
    return float(freqs[np.argmax(spec)])


class Lib:
    def __init__(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def sample(self, name: str, hz: float, seconds: float = 1.0, amp: float = 0.5) -> str:
        _sine(self.dir / name, hz, seconds, amp)
        return name

    def sfz(self, text: str, name: str = "inst.sfz") -> Path:
        p = self.dir / name
        p.write_text(text)
        return p

    def close(self) -> None:
        self._td.cleanup()


class NoteNumberTest(unittest.TestCase):
    def test_names_and_numbers(self):
        self.assertEqual(note_number("c4"), 60)
        self.assertEqual(note_number("a4"), 69)
        self.assertEqual(note_number("c#4"), 61)
        self.assertEqual(note_number("eb3"), 51)
        self.assertEqual(note_number("c-1"), 0)
        self.assertEqual(note_number("72"), 72)
        self.assertIsNone(note_number("nope"))


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.lib = Lib()

    def tearDown(self):
        self.lib.close()

    def test_inheritance_define_include_and_spaces_in_sample_names(self):
        self.lib.sample("low a.wav", 220.0)
        (self.lib.dir / "maps").mkdir()
        (self.lib.dir / "maps" / "map.sfz").write_text(
            "<region> sample=low a.wav lokey=$LO hikey=c5 pitch_keycenter=a3\n"
        )
        path = self.lib.sfz(
            "// comment\n#define $LO 50\n"
            "<control> set_cc7=100\n"
            "<global> ampeg_release=0.5 volume=-3\n"
            "<group> volume=-6 /* block\ncomment */\n"
            '#include "maps/map.sfz"\n'
        )
        inst = load_sfz(path)
        self.assertEqual(len(inst.regions), 1)
        r = inst.regions[0]
        self.assertEqual(r.sample_path.name, "low a.wav")
        self.assertEqual((r.lokey, r.hikey, r.keycenter), (50, 72, 57))
        self.assertEqual(r.op["volume"], "-6")          # group overrides global
        self.assertEqual(r.op["ampeg_release"], "0.5")  # global inherited
        self.assertEqual(inst.cc_defaults[7], 100.0)

    def test_new_global_resets_group_opcodes(self):
        self.lib.sample("s.wav", 220.0)
        inst = load_sfz(self.lib.sfz(
            "<global> volume=-1 <group> tune=50 <region> sample=s.wav\n"
            "<global> <region> sample=s.wav\n"
        ))
        self.assertEqual(inst.regions[0].op.get("tune"), "50")
        self.assertNotIn("tune", inst.regions[1].op)
        self.assertNotIn("volume", inst.regions[1].op)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.lib = Lib()

    def tearDown(self):
        self.lib.close()

    def render(self, sfz_text: str, notes, **kw):
        inst = load_sfz(self.lib.sfz(sfz_text))
        return SfzRenderer(inst, SR).render(notes, **kw)

    def test_pitch_follows_keycenter(self):
        self.lib.sample("a.wav", 220.0)
        out = self.render("<region> sample=a.wav pitch_keycenter=57 lokey=0 hikey=127",
                          [Note(69, 0.0, 0.6, 100)])
        self.assertAlmostEqual(_f0(out), 440.0, delta=3.0)

    def test_transpose_and_tune(self):
        self.lib.sample("a.wav", 220.0)
        out = self.render("<region> sample=a.wav pitch_keycenter=57 transpose=12 tune=0",
                          [Note(57, 0.0, 0.6, 100)])
        self.assertAlmostEqual(_f0(out), 440.0, delta=3.0)

    def test_velocity_layers(self):
        self.lib.sample("soft.wav", 220.0)
        self.lib.sample("loud.wav", 330.0)
        text = ("<group> pitch_keycenter=57 lokey=57 hikey=57 amp_veltrack=0\n"
                "<region> sample=soft.wav hivel=63\n<region> sample=loud.wav lovel=64\n")
        self.assertAlmostEqual(_f0(self.render(text, [Note(57, 0, 0.5, 40)])), 220.0, delta=3.0)
        self.assertAlmostEqual(_f0(self.render(text, [Note(57, 0, 0.5, 120)])), 330.0, delta=3.0)

    def test_round_robin_cycles(self):
        self.lib.sample("rr1.wav", 220.0)
        self.lib.sample("rr2.wav", 330.0)
        inst = load_sfz(self.lib.sfz(
            "<group> key=60 pitch_keycenter=60 seq_length=2 loop_mode=one_shot\n"
            "<region> sample=rr1.wav seq_position=1\n<region> sample=rr2.wav seq_position=2\n"))
        r = SfzRenderer(inst, SR)
        out = r.render([Note(60, 0.0, 0.1, 100), Note(60, 1.5, 1.6, 100)], tail_seconds=0.5)
        self.assertAlmostEqual(_f0(out, 0.1, 0.5), 220.0, delta=3.0)
        self.assertAlmostEqual(_f0(out, 1.6, 0.5), 330.0, delta=3.0)

    def test_velocity_curve_and_veltrack(self):
        self.lib.sample("a.wav", 220.0)
        text = "<region> sample=a.wav key=60"
        soft = self.render(text, [Note(60, 0, 0.5, 32)])
        loud = self.render(text, [Note(60, 0, 0.5, 127)])
        ratio = np.abs(loud).max() / np.abs(soft).max()
        self.assertAlmostEqual(ratio, (127 / 32) ** 2, delta=1.0)

    def test_cc_fader_and_locc_condition(self):
        self.lib.sample("a.wav", 220.0)
        on = self.render("<control> set_cc101=127 <region> sample=a.wav key=60 "
                         "amplitude_oncc101=100 locc101=1", [Note(60, 0, 0.5, 127)])
        off = self.render("<control> set_cc101=0 <region> sample=a.wav key=60 "
                          "amplitude_oncc101=100 locc101=1", [Note(60, 0, 0.5, 127)])
        self.assertGreater(np.abs(on).max(), 0.3)
        self.assertEqual(float(np.abs(off).max()), 0.0)

    def test_release_and_note_length(self):
        self.lib.sample("a.wav", 220.0, seconds=3.0)
        out = self.render("<region> sample=a.wav key=60 ampeg_release=0.1",
                          [Note(60, 0.0, 0.5, 127)], tail_seconds=1.0)
        level = np.abs(out).max(axis=0)
        self.assertGreater(level[int(0.45 * SR):int(0.5 * SR)].max(), 0.3)
        self.assertLess(level[int(0.7 * SR):].max(), 1e-3)

    def test_one_shot_ignores_note_off(self):
        self.lib.sample("a.wav", 220.0, seconds=1.0)
        out = self.render("<region> sample=a.wav key=60 loop_mode=one_shot",
                          [Note(60, 0.0, 0.05, 127)], tail_seconds=1.0)
        self.assertGreater(np.abs(out[:, int(0.8 * SR):int(0.9 * SR)]).max(), 0.3)

    def test_loop_sustains_past_sample_end(self):
        self.lib.sample("a.wav", 220.0, seconds=0.5)
        text = ("<region> sample=a.wav key=60 loop_mode=loop_continuous "
                f"loop_start={int(0.1 * SR)} loop_end={int(0.1 * SR) + 200 * 5 - 1}")
        out = self.render(text, [Note(60, 0.0, 2.0, 127)])
        self.assertGreater(np.abs(out[:, int(1.5 * SR):int(1.9 * SR)]).max(), 0.3)

    def test_choke_group(self):
        self.lib.sample("open.wav", 3000.0, seconds=3.0)
        self.lib.sample("closed.wav", 5000.0, seconds=0.2)
        text = ("<global> loop_mode=one_shot\n"
                "<region> sample=open.wav key=46 group=1 off_by=2\n"
                "<region> sample=closed.wav key=42 group=2\n")
        out = self.render(text, [Note(46, 0.0, 0.1, 127), Note(42, 0.5, 0.6, 127)], tail_seconds=0.5)
        self.assertGreater(np.abs(out[:, int(0.2 * SR):int(0.4 * SR)]).max(), 0.3)
        self.assertLess(np.abs(out[:, int(1.0 * SR):int(2.5 * SR)]).max(), 1e-3)

    def test_release_trigger_plays_on_note_off(self):
        self.lib.sample("body.wav", 220.0, seconds=2.0)
        self.lib.sample("noise.wav", 990.0, seconds=0.3)
        text = ("<region> sample=body.wav key=60 ampeg_release=0.01\n"
                "<region> sample=noise.wav key=60 trigger=release\n")
        out = self.render(text, [Note(60, 0.0, 1.0, 100)], tail_seconds=0.5)
        self.assertAlmostEqual(_f0(out, 1.05, 0.2), 990.0, delta=5.0)

    def test_keyswitch_default(self):
        self.lib.sample("a.wav", 220.0)
        self.lib.sample("b.wav", 330.0)
        text = ("<group> sw_lokey=24 sw_hikey=25 sw_default=25 key=60 pitch_keycenter=60\n"
                "<region> sample=a.wav sw_last=24\n<region> sample=b.wav sw_last=25\n")
        self.assertAlmostEqual(_f0(self.render(text, [Note(60, 0, 0.5, 100)])), 330.0, delta=3.0)

    def test_missing_sample_is_skipped(self):
        out = self.render("<region> sample=nope.wav key=60", [Note(60, 0, 0.5, 100)])
        self.assertEqual(float(np.abs(out).max()), 0.0)


class LoopPointsTest(unittest.TestCase):
    def test_wav_smpl_chunk(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.wav"
            _sine(p, 220.0, 0.2)
            data = bytearray(p.read_bytes())
            smpl = struct.pack("<9I", 0, 0, 22675, 60, 0, 0, 0, 1, 0)
            smpl += struct.pack("<6I", 0, 0, 1000, 5000, 0, 0)
            data += b"smpl" + struct.pack("<I", len(smpl)) + smpl
            struct.pack_into("<I", data, 4, len(data) - 8)
            p.write_bytes(bytes(data))
            self.assertEqual(_file_loop(p), (1000, 5000))


if __name__ == "__main__":
    unittest.main()
