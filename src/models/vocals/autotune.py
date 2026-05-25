"""Pitch-correct a recorded vocal — Auto-Tune to the composed melody (or to a
key/scale).

The melody we generate is a set of target pitches over time, so a rough human
take can be snapped onto it: analyse the recording with the WORLD vocoder
(F0 + spectral envelope + aperiodicity), replace the **F0** with a target
contour, and resynthesize. Because WORLD separates pitch (F0) from timbre (the
spectral envelope ``sp``), swapping only F0 is **formant-preserving by
construction** — no chipmunking. Only *voiced* frames are retuned, so
consonants/breaths are left alone.

Two target modes:
  * **to a guide melody** — ``targets`` is ``[(midi, start_sec, end_sec), …]``
    (e.g. the block's composed Lead Vocal). Each frame is pulled to the note
    sounding at its time; frames in a rest are left untouched.
  * **to a key/scale** — no melody; each voiced frame snaps to the nearest
    note of ``key``/``scale`` (classic retune-to-key).

``mode``: ``"hard"`` snaps exactly to the target (the T-Pain sound);
``"natural"`` moves the pitch a fraction (``strength``, 0–1) of the way there,
keeping some of the original drift/vibrato.

NOTE (v1): assumes the take shares the song's timeline (sing to the guide / a
click). Loose-timing alignment (DTW between take and melody) is a follow-up.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("ai_music_studio.vocals.autotune")

_FRAME_MS = 5.0  # WORLD frame period

_SCALE_STEPS = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "natural_minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "pentatonic_major": (0, 2, 4, 7, 9),
    "pentatonic_minor": (0, 3, 5, 7, 10),
}
_NAME2PC = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4,
            "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
            "A#": 10, "BB": 10, "B": 11}


def _hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * np.log2(hz / 440.0)


def _midi_to_hz(m: float) -> float:
    return 440.0 * (2.0 ** ((m - 69.0) / 12.0))


def _scale_pcs(key: str, scale: str) -> set[int]:
    steps = _SCALE_STEPS.get((scale or "major").lower(), _SCALE_STEPS["major"])
    root = _NAME2PC.get((key or "C").strip().upper(), 0)
    return {(root + s) % 12 for s in steps}


def _snap_midi_to_scale(midi: float, pcs: set[int]) -> float:
    """Nearest MIDI note whose pitch class is in ``pcs``."""
    base = int(round(midi))
    for d in range(0, 7):
        for cand in ((base - d), (base + d)):
            if cand % 12 in pcs:
                return float(cand)
    return float(base)


def _target_midi_at(t: float, targets: list[tuple[float, float, float]]) -> float | None:
    """The guide melody's MIDI at time ``t`` (None in a rest)."""
    for midi, s, e in targets:
        if s <= t < e:
            return float(midi)
    return None


def retune_f0(f0: np.ndarray, times: np.ndarray, *,
              targets: list[tuple[float, float, float]] | None = None,
              key: str | None = None, scale: str = "major",
              mode: str = "hard", strength: float = 1.0) -> np.ndarray:
    """Return a corrected F0 contour (pure; no audio). Unvoiced frames
    (``f0<=0``) pass through untouched. With ``targets`` each voiced frame is
    pulled to the guide note at its time (rest frames untouched); otherwise it
    snaps to the nearest ``key``/``scale`` note. ``mode='hard'`` snaps exactly;
    ``'natural'`` moves ``strength`` of the way (in cents) toward the target."""
    f0 = np.asarray(f0, dtype=float).copy()
    pcs = _scale_pcs(key, scale) if (targets is None and key) else None
    s = float(np.clip(strength, 0.0, 1.0))
    for i, hz in enumerate(f0):
        if hz <= 0:
            continue
        if targets is not None:
            tm = _target_midi_at(times[i], targets)
            if tm is None:
                continue                       # rest → leave the take alone
            target_hz = _midi_to_hz(tm)
        elif pcs:
            target_hz = _midi_to_hz(_snap_midi_to_scale(_hz_to_midi(hz), pcs))
        else:
            continue
        if mode == "hard":
            f0[i] = target_hz
        else:  # natural: geometric blend toward the target by `strength`
            f0[i] = hz * (target_hz / hz) ** s
    return f0


def autotune(vocal: np.ndarray, sr: int, *,
             targets: list[tuple[float, float, float]] | None = None,
             key: str | None = None, scale: str = "major",
             mode: str = "hard", strength: float = 1.0,
             offset_sec: float = 0.0) -> np.ndarray:
    """Pitch-correct ``vocal`` (mono float) to ``targets`` (guide melody, abs
    seconds) or to ``key``/``scale``. ``offset_sec`` shifts the take's clock if
    it doesn't start at the song's t=0. Returns mono float32 at ``sr``."""
    import pyworld as pw

    x = np.ascontiguousarray(np.asarray(vocal, dtype=np.float64))
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.size < sr // 10:
        return x.astype(np.float32)
    f0, t = pw.harvest(x, sr, frame_period=_FRAME_MS)
    f0 = pw.stonemask(x, f0, t, sr)
    sp = pw.cheaptrick(x, f0, t, sr)          # spectral envelope = timbre (kept)
    ap = pw.d4c(x, f0, t, sr)
    new_f0 = retune_f0(f0, t + float(offset_sec), targets=targets, key=key,
                       scale=scale, mode=mode, strength=strength)
    y = pw.synthesize(np.ascontiguousarray(new_f0), sp, ap, sr, frame_period=_FRAME_MS)
    return y.astype(np.float32)


def targets_from_block(name: str) -> list[tuple[float, float, float]]:
    """The block's composed **Lead Vocal** as ``(midi, start_sec, end_sec)`` —
    the guide melody to tune a recording onto."""
    from src.daw_integration.generic import blocks as block_store
    from src.models.vocals.lyrics import monophonic_line, select_vocal_tracks
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(block_store._midi_path(name)))
    lead, _ = select_vocal_tracks(pm)
    return [(float(p), float(s), float(e)) for (p, s, e) in monophonic_line(lead)]
