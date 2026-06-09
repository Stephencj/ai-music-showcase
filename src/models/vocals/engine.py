"""Vocal engines. The MVP ``RoughEngine`` synthesizes each word with macOS
``say`` then re-pitches it to the melody notes with the WORLD vocoder
(pyworld) — time-stretched to the note durations — so it actually *sings*
the line. Falls back to a librosa pitch/time shift if pyworld is absent."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf

logger = logging.getLogger("ai_music_studio.vocals.engine")

_FRAME_MS = 5.0  # WORLD frame period


def midi_to_hz(m) -> np.ndarray:
    return 440.0 * (2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0))


class VocalEngine:
    """Interface: turn an aligned segment into a mono float32 waveform at
    ``sr``. A segment is ``{text, notes: [(midi, dur_seconds)], start}``."""

    name = "base"

    def render_segment(self, text: str, notes: list[tuple[int, float]], sr: int) -> np.ndarray:
        raise NotImplementedError


class RoughEngine(VocalEngine):
    name = "rough"

    def __init__(self, voice: str = "") -> None:
        self.voice = voice  # "" = system default say voice

    # -- TTS ----------------------------------------------------------------
    def _say(self, text: str, sr: int) -> np.ndarray:
        path = tempfile.mktemp(suffix=".aiff")
        cmd = ["say"]
        if self.voice:
            cmd += ["-v", self.voice]
        cmd += ["-o", path, text]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            audio, file_sr = sf.read(path, dtype="float64")
        except Exception as exc:  # noqa: BLE001
            logger.warning("say failed for %r: %s", text, exc)
            return np.zeros(0)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if file_sr != sr:
            import librosa
            audio = librosa.resample(audio, orig_sr=file_sr, target_sr=sr)
        return audio

    # -- pitch/time to the notes -------------------------------------------
    def render_segment(self, text: str, notes: list[tuple[int, float]], sr: int) -> np.ndarray:
        target_dur = float(sum(d for _, d in notes))
        audio = self._say(text, sr)
        if audio.size == 0 or target_dur <= 0:
            return np.zeros(int(max(0.0, target_dur) * sr), dtype=np.float32)
        try:
            return self._sing_world(audio, sr, notes, target_dur)
        except Exception as exc:  # noqa: BLE001 — fall back, don't crash a render
            logger.warning("WORLD resynth failed (%s) — librosa fallback", exc)
            return self._sing_librosa(audio, sr, notes, target_dur)

    def _sing_world(self, audio, sr, notes, target_dur) -> np.ndarray:
        import pyworld as pw

        x = np.ascontiguousarray(audio.astype(np.float64))
        f0, t = pw.harvest(x, sr, frame_period=_FRAME_MS)
        f0 = pw.stonemask(x, f0, t, sr)
        sp = pw.cheaptrick(x, f0, t, sr)
        ap = pw.d4c(x, f0, t, sr)
        n_src = len(f0)
        if n_src < 2:
            raise ValueError("source too short")
        n_tgt = max(2, int(round(target_dur * 1000.0 / _FRAME_MS)))

        # Resample envelope + aperiodicity + voiced-mask onto the target grid.
        idx = np.linspace(0, n_src - 1, n_tgt)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, n_src - 1)
        fr = (idx - lo)[:, None]
        sp_t = np.ascontiguousarray(sp[lo] * (1 - fr) + sp[hi] * fr)
        ap_t = np.ascontiguousarray(ap[lo] * (1 - fr) + ap[hi] * fr)
        voiced = (f0 > 0).astype(float)
        voiced_t = (voiced[lo] * (1 - fr[:, 0]) + voiced[hi] * fr[:, 0]) > 0.5

        # Target F0 contour: piecewise-constant per note (with light vibrato),
        # zeroed where the source was unvoiced so consonants stay crisp.
        frame_t = np.arange(n_tgt) * _FRAME_MS / 1000.0
        durs = np.array([d for _, d in notes], dtype=float)
        ends = np.cumsum(durs)
        starts = ends - durs
        pitches = np.array([m for m, _ in notes])
        which = np.clip(np.searchsorted(ends, frame_t, side="right"), 0, len(notes) - 1)
        f0_t = midi_to_hz(pitches[which])
        # Per-note vibrato: only on sustained notes, phase reset at each
        # onset and eased in after ~0.2s — so short notes hit cleanly and
        # held notes bloom (instead of a constant global wobble on every
        # syllable). Mirrors the studio engine's tasteful vibrato.
        t_in_note = frame_t - starts[which]
        sustained = (durs[which] >= 0.45).astype(float)
        ramp = np.clip((t_in_note - 0.2) / 0.25, 0.0, 1.0)
        vib = 0.005 * np.sin(2 * np.pi * 5.5 * t_in_note) * ramp * sustained
        f0_t = f0_t * (1.0 + vib)
        f0_t = np.where(voiced_t, f0_t, 0.0)

        y = pw.synthesize(np.ascontiguousarray(f0_t),
                          sp_t, ap_t, sr, frame_period=_FRAME_MS)
        return y.astype(np.float32)

    def _sing_librosa(self, audio, sr, notes, target_dur) -> np.ndarray:
        import librosa
        a = audio.astype(np.float32)
        cur = len(a) / sr
        if cur > 0 and target_dur > 0:
            try:
                a = librosa.effects.time_stretch(a, rate=cur / target_dur)
            except Exception:  # noqa: BLE001
                pass
        mean_midi = float(np.mean([m for m, _ in notes]))
        try:
            a = librosa.effects.pitch_shift(a, sr=sr, n_steps=mean_midi - 57.0)  # ~A3 speaking ref
        except Exception:  # noqa: BLE001
            pass
        return a.astype(np.float32)
