"""The sampled renders keep their low end: a few bars of each style, rendered
through the real instruments, mix and master, measured as octave-band levels
against a gentle-tilt reference (63-125 Hz within about 6 dB of 250-500 Hz,
no sub rumble). Guards the per-instrument fixes: the cello and contrabass
through the strings chain, the piano's left hand through the chords chain,
the organ pedal's weak fundamental, the brush kit's and shaker's rumble.

Needs the sampled libraries (data/instruments/, see its README); skipped
without them. About 30 s for all eight styles."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pretty_midi
import soundfile as sf
from scipy.signal import welch

from src.api import service
from src.api.schemas import GenerateRequest
from src.audio_processing.render import pipeline, sampled
from src.composition import christmas

BANDS = (31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000)

# style: (seed, lowest 63 Hz band, lowest 63-125 Hz power), both in dB against
# 250-500 Hz. Full bands with a bass player keep 63-125 Hz within 6 dB; the
# choir (a quiet organ pedal under voices) is lighter, but not thin.
STYLE_CASES = {
    "christmas_swing_full": (282299, -6.0, -6.0),
    "christmas_jazz_trio_full": (926507, -6.0, -6.0),
    "christmas_pop_full": (446200, -6.0, -6.0),
    "christmas_orchestral_full": (581490, -8.5, -6.0),
    "christmas_fireside_full": (105702, -8.5, -6.0),
    "christmas_choir_full": (834182, -17.0, -9.5),
    "funk_fusion_full": (1, -6.0, -6.0),
    "neo_soul_full": (1, -6.0, -6.0),
}
EXCERPT_S = 16.0


def octave_bands(audio: np.ndarray, sample_rate: int) -> dict[float, float]:
    """Octave-band power (dB) of ``(channels, N)`` audio."""
    f, p = welch(np.atleast_2d(audio).mean(axis=0), sample_rate, nperseg=16384)
    df = f[1] - f[0]
    return {c: float(10 * np.log10(p[(f >= c / 2 ** 0.5) & (f < c * 2 ** 0.5)].sum() * df + 1e-20))
            for c in BANDS}


def _power_db(*db: float) -> float:
    return float(10 * np.log10(sum(10 ** (d / 10) for d in db)))


def _installed() -> bool:
    root = sampled.instrument_dir()
    need = ("grand_piano", "upright_bass", "cello", "organ_pedal", "brush_kit", "electric_bass", "drum_kit")
    return all((root / i.sfz).exists() for i in sampled.SAMPLED_INSTRUMENTS if i.id in need)


@unittest.skipUnless(_installed(), "sampled instrument libraries not installed")
class StyleLowEndTest(unittest.TestCase):
    """Each style's excerpt: 63-125 Hz within about 6 dB of 250-500 Hz, the
    63 Hz band above its style's floor, no rumble below 45 Hz."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="lowend_"))
        cls.bands = {style: cls._render_excerpt(style, case[0]) for style, case in STYLE_CASES.items()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _render_excerpt(cls, style: str, seed: int) -> dict[float, float]:
        """Compose the song the way a generation does (its plan, band, lead
        voice and mix), then render a full-band excerpt from its middle."""
        calls = []

        def capture(midi, output_dir, **kw):
            calls.append((Path(midi), kw))
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            t = np.arange(44100) / 44100
            tone = (0.1 * np.sin(2 * np.pi * 220 * t)).astype("float32")
            sf.write(out / "mix.wav", np.stack([tone, tone], axis=1), 44100)
            return mock.Mock(mix_path=out / "mix.wav")

        with mock.patch.object(service, "API_OUT", cls.tmp / "api"), \
                mock.patch.object(pipeline, "render_to_audio", capture):
            service.run_generation(
                GenerateRequest(genre=style, seed=seed, with_pdf=False,
                                tune="original" if style in christmas.STYLE_IDS else None),
                lambda *_: None, f"lowend-{style}")
        midi_path, kw = calls[0]

        pm = pretty_midi.PrettyMIDI(str(midi_path))
        start = 0.45 * pm.get_end_time()
        for inst in pm.instruments:
            inst.notes = [pretty_midi.Note(n.velocity, n.pitch, n.start - start, n.end - start)
                          for n in inst.notes if start <= n.start < start + EXCERPT_S]
            inst.control_changes, inst.pitch_bends = [], []
        pm.instruments = [i for i in pm.instruments if i.notes]
        excerpt = cls.tmp / f"{style}.mid"
        pm.write(str(excerpt))
        res = pipeline.render_to_audio(midi=excerpt, output_dir=cls.tmp / style, **{**kw, "with_stems": False})
        audio, sr = sf.read(str(res.mix_path), always_2d=True)
        shutil.rmtree(cls.tmp / style, ignore_errors=True)
        return octave_bands(audio.T, sr)

    def test_low_end_within_the_reference_tilt(self):
        for style, (_, floor_63, floor_low) in STYLE_CASES.items():
            b = self.bands[style]
            with self.subTest(style=style):
                mids = (b[250] + b[500]) / 2
                low_vs_mid = _power_db(b[63], b[125]) - _power_db(b[250], b[500])
                self.assertGreaterEqual(low_vs_mid, floor_low, f"63-125 Hz thin against 250-500 Hz: {b}")
                self.assertLessEqual(low_vs_mid, 5.0, f"63-125 Hz boomy: {b}")
                self.assertGreaterEqual(b[63] - mids, floor_63, f"63 Hz band thin: {b}")
                self.assertLessEqual(b[31.5] - max(b.values()), -10.0, f"sub-45 Hz rumble: {b}")


if __name__ == "__main__":
    unittest.main()
