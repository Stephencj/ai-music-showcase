"""Top-level vocal render: melody MIDI + lyrics → a sung mono vocal stem."""

from __future__ import annotations

import logging

import numpy as np

from .engine import RoughEngine, VocalEngine
from .lyrics import align_words_to_notes, extract_lead_notes

logger = logging.getLogger("ai_music_studio.vocals.render")


def render_lead_vocal(midi, lyrics, *, sr: int = 44100, voice: str = "",
                      engine: VocalEngine | None = None, fx: bool = True
                      ) -> tuple[np.ndarray, int]:
    """Render a sung lead-vocal stem.

    ``midi``: a PrettyMIDI or path. ``lyrics``: a string (or list of lines).
    Returns ``(audio_mono_float32, sr)`` aligned to the MIDI timeline.
    """
    import pretty_midi
    if not isinstance(midi, pretty_midi.PrettyMIDI):
        midi = pretty_midi.PrettyMIDI(str(midi))

    notes = extract_lead_notes(midi)
    if not notes:
        return np.zeros(0, dtype=np.float32), sr
    notes = _transpose_to_singable(notes)
    text = lyrics if isinstance(lyrics, str) else " ".join(lyrics)
    if not text.strip():
        return np.zeros(0, dtype=np.float32), sr

    segs = align_words_to_notes(text, notes)
    eng = engine or RoughEngine(voice)
    total = float(midi.get_end_time())
    out = np.zeros(int(total * sr) + sr, dtype=np.float32)

    for seg in segs:
        y = eng.render_segment(seg["text"], seg["notes"], sr)
        if y.size == 0:
            continue
        i0 = int(seg["start"] * sr)
        i1 = min(len(out), i0 + len(y))
        out[i0:i1] += y[: i1 - i0]

    out = out[: int(total * sr) + int(0.3 * sr)]
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0:
        out = out * (0.9 / peak)
    if fx:
        out = _apply_fx(out, sr)
    return out.astype(np.float32), sr


def _transpose_to_singable(notes, lo: int = 53, hi: int = 67):
    """Shift the whole melody by octaves so its median lands in a natural
    sung register (~G3–G4). Re-pitching a speaking voice two octaves up is
    where the 'creepy/screechy' comes from; this keeps the contour but in
    a comfortable range. ``lo``/``hi`` bound the median (MIDI)."""
    if not notes:
        return notes
    median = float(np.median([p for p, _, _ in notes]))
    shift = 0
    while median + shift > hi:
        shift -= 12
    while median + shift < lo:
        shift += 12
    if shift == 0:
        return notes
    return [(p + shift, s, e) for (p, s, e) in notes]


def _apply_fx(audio: np.ndarray, sr: int) -> np.ndarray:
    """Light vocal chain: high-pass, gentle compression, a touch of reverb."""
    try:
        from pedalboard import Compressor, Gain, HighpassFilter, Pedalboard, Reverb
        board = Pedalboard([
            HighpassFilter(cutoff_frequency_hz=90.0),
            Compressor(threshold_db=-18.0, ratio=3.0, attack_ms=5.0, release_ms=120.0),
            Reverb(room_size=0.25, wet_level=0.12, dry_level=0.9, width=0.8),
            Gain(gain_db=1.5),
        ])
        return board(audio.astype(np.float32), sr)
    except Exception as exc:  # noqa: BLE001
        logger.warning("vocal FX skipped: %s", exc)
        return audio
