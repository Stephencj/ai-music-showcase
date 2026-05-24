"""Objective vocal intelligibility benchmark.

Transcribe a rendered vocal with Whisper (deliberately *without* priming it
with the lyrics, so it can't cheat) and score the Word Error Rate against the
intended lyrics. Lower WER / higher word-accuracy = more coherent, readable
lyrics — i.e. "can a listener actually make out the words without reading
along?". This is the metric to optimise for word-forward styles (rap/hip-hop),
and the gate we used to choose the vocal FX chain (see ``render._apply_fx``):
a brighter mix can *look* clearer on a spectrum yet read WORSE here.

Pure-speech ASR is pessimistic on *singing* (sustained vowels, melisma,
vibrato), so treat the absolute number as a floor and lean on relative
comparisons between renders/settings.

Usage:
    from src.models.vocals.intelligibility import score
    r = score(reference_lyrics, "take.wav")        # path or (np.ndarray, sr)
    print(r["accuracy"], r["transcript"])

    python -m src.models.vocals.intelligibility take.wav lyrics.txt
"""
from __future__ import annotations

import logging
import re
from typing import Optional, Union

import numpy as np

logger = logging.getLogger("ai_music_studio.vocals.intelligibility")

DEFAULT_MODEL = "openai/whisper-small"
_ASR_CACHE: dict[str, object] = {}


def _normalize(text: str) -> list[str]:
    """Lowercase, drop apostrophes (so contractions stay one token) and other
    punctuation, split to a word list. Applied to both sides equally."""
    text = text.lower().replace("’", "").replace("'", "")
    return re.sub(r"[^a-z0-9\s]", " ", text).split()


def _wer(ref: list[str], hyp: list[str]) -> float:
    """Word-level Levenshtein error rate (substitutions+insertions+deletions
    over reference length)."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return 1.0 if m else 0.0
    d = np.zeros((n + 1, m + 1), dtype=int)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    return float(d[n, m]) / n


def _get_asr(model: str = DEFAULT_MODEL):
    """Lazily build (and cache) the Whisper ASR pipeline on CPU."""
    if model not in _ASR_CACHE:
        from transformers import pipeline
        logger.info("loading ASR model %s (cpu)…", model)
        _ASR_CACHE[model] = pipeline(
            "automatic-speech-recognition", model=model, device="cpu")
    return _ASR_CACHE[model]


def _load_audio(audio: Union[str, "tuple", np.ndarray], sr: Optional[int]):
    """Return (mono float32 @ 16 kHz). Accepts a file path, an ndarray (needs
    ``sr``), or an ``(ndarray, sr)`` tuple."""
    import librosa
    import soundfile as sf
    if isinstance(audio, str):
        x, src_sr = sf.read(audio)
    elif isinstance(audio, tuple):
        x, src_sr = audio
    else:
        if sr is None:
            raise ValueError("sr is required when passing a raw array")
        x, src_sr = audio, sr
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if src_sr != 16000:
        x = librosa.resample(x, orig_sr=src_sr, target_sr=16000)
    return x


def transcribe(audio: Union[str, tuple, np.ndarray], sr: Optional[int] = None,
               model: str = DEFAULT_MODEL) -> str:
    """Transcribe a vocal to text with Whisper (no lyric priming)."""
    x = _load_audio(audio, sr)
    asr = _get_asr(model)
    out = asr({"array": x, "sampling_rate": 16000},
              chunk_length_s=30, stride_length_s=5, return_timestamps=False,
              generate_kwargs={"language": "en", "task": "transcribe"})
    return str(out["text"]).strip()


def score(reference: str, audio: Union[str, tuple, np.ndarray],
          sr: Optional[int] = None, model: str = DEFAULT_MODEL) -> dict:
    """Score how intelligible a rendered vocal is against its intended lyrics.

    Returns ``{wer, accuracy, transcript, ref_words, hyp_words}`` where
    ``accuracy = max(0, 1 - wer)`` (fraction of intended words read back)."""
    transcript = transcribe(audio, sr, model)
    ref, hyp = _normalize(reference), _normalize(transcript)
    wer = _wer(ref, hyp)
    return {
        "wer": wer,
        "accuracy": max(0.0, 1.0 - wer),
        "transcript": transcript,
        "ref_words": len(ref),
        "hyp_words": len(hyp),
    }


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m src.models.vocals.intelligibility "
              "<audio> <reference.txt|reference-string>")
        return 2
    audio_path, ref_arg = argv[0], argv[1]
    import os
    reference = open(ref_arg).read() if os.path.exists(ref_arg) else ref_arg
    r = score(reference, audio_path)
    print(f"WER={r['wer']*100:.1f}%  word-accuracy={r['accuracy']*100:.1f}%  "
          f"({r['ref_words']} ref words)")
    print("HEARD:", r["transcript"])
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
