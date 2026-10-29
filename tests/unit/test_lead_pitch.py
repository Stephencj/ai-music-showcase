"""Lead pitch: no half-step rubs with the chord, tuned samples, no silent failures."""

import logging
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

import src.composition  # noqa: F401
from src.api.arrangement import build_sections
from src.composition.fusion import chord_tones, fit_to_chord
from src.composition.song_composer import compose_song
from src.daw_integration.generic.styles import STYLES


class FitToChordTest(unittest.TestCase):
    def test_avoid_note_moves_to_a_chord_tone(self):
        pool = list(range(60, 84))
        # Eb over C7 (C E G Bb + 9th D, 13th A) rubs the E: it moves.
        fitted = fit_to_chord(63, 0, "7", pool)
        self.assertIn(fitted % 12, chord_tones(0, "7"))
        self.assertLessEqual(abs(fitted - 63), 2)

    def test_chord_tones_and_safe_notes_stay(self):
        pool = list(range(60, 84))
        self.assertEqual(fit_to_chord(64, 0, "7", pool), 64)     # E, the 3rd
        self.assertEqual(fit_to_chord(69, 0, "maj7", pool), 69)  # A: no half-step neighbour held (C E G B D)

    def test_direction_breaks_ties(self):
        pool = list(range(60, 84))
        # F over Cmaj7-ish voicing (C, E, G, B, D): E and G are equidistant? F→E is 1, F→G is 2.
        self.assertEqual(fit_to_chord(65, 0, "maj7", pool) % 12, 4)


class NoSilentFailuresTest(unittest.TestCase):
    def test_every_strict_style_composes_without_technique_errors(self):
        for genre in ("funk_fusion_full", "neo_soul_full", "fusion_full"):
            with self.subTest(genre=genre), tempfile.TemporaryDirectory() as td:
                errors: list[logging.LogRecord] = []
                handler = logging.Handler(level=logging.ERROR)
                handler.emit = errors.append
                log = logging.getLogger("src.composition.song_composer")
                log.addHandler(handler)
                try:
                    compose_song(genre=genre, sections=build_sections(genre, [], None, None), seed=5,
                                 enabled_instruments=tuple(STYLES[genre].default_instruments),
                                 output_dir=Path(td), skip_audio=True)
                finally:
                    log.removeHandler(handler)
                self.assertFalse(errors, [r.getMessage() for r in errors])


class AutoTuneTest(unittest.TestCase):
    def test_a_sharp_sample_is_corrected(self):
        from src.audio_processing.render.autotune import SampleTuner
        from src.audio_processing.render.sfz import Note, SfzRenderer, load_sfz
        import librosa
        sr = 44100
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            hz = 440.0 * 2 ** (20 / 1200)                     # 20 cents sharp
            t = np.arange(sr) / sr
            sf.write(str(root / "a.wav"), (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32), sr)
            (root / "i.sfz").write_text("<region> sample=a.wav pitch_keycenter=69")
            tuner = SampleTuner(root / ".tuning.json")
            out = SfzRenderer(load_sfz(root / "i.sfz"), sr, sample_tune=tuner.cents).render([Note(69, 0, 0.8, 100)])
            f = librosa.yin(out.mean(axis=0)[4000:20000], fmin=400, fmax=480, sr=sr, frame_length=4096)
            self.assertLess(abs(float(np.median(1200 * np.log2(f / 440.0)))), 4.0)
            tuner.save()
            self.assertTrue((root / ".tuning.json").exists())


if __name__ == "__main__":
    unittest.main()


class VibratoTest(unittest.TestCase):
    def _pitch_track(self, audio, sr, a, b):
        import librosa
        seg = audio.mean(axis=0)[int(a * sr):int(b * sr)]
        f = librosa.yin(seg, fmin=380, fmax=500, sr=sr, frame_length=2048, hop_length=256)
        return 1200 * np.log2(f / 440.0)

    def _render(self, notes, vibrato):
        from src.audio_processing.render.sfz import SfzRenderer, Vibrato, load_sfz
        sr = 44100
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            t = np.arange(sr * 2) / sr
            sf.write(str(root / "a.wav"), (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32), sr)
            (root / "i.sfz").write_text("<region> sample=a.wav pitch_keycenter=69")
            return SfzRenderer(load_sfz(root / "i.sfz"), sr,
                               vibrato=Vibrato() if vibrato else None).render(notes), sr

    def test_held_notes_get_a_delayed_vibrato(self):
        from src.audio_processing.render.sfz import Note
        out, sr = self._render([Note(69, 0.0, 1.0, 100)], vibrato=True)
        early = self._pitch_track(out, sr, 0.02, 0.11)
        late = self._pitch_track(out, sr, 0.4, 0.9)
        self.assertLess(float(np.ptp(early)), 10.0)         # steady at first (detector jitter only)
        self.assertGreater(float(np.ptp(late)), 22.0)       # then wobbles ± ~15 cents
        self.assertLess(abs(float(np.median(late))), 4.0)   # centred on pitch

    def test_short_notes_stay_straight(self):
        from src.audio_processing.render.sfz import Note
        out, sr = self._render([Note(69, 0.0, 0.2, 100)], vibrato=True)
        self.assertLess(float(np.ptp(self._pitch_track(out, sr, 0.05, 0.18))), 10.0)
