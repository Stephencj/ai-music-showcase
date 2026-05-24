"""Top-level vocal render: melody MIDI + lyrics → a sung mono vocal stem
(lead, optionally with stacked harmony lines)."""

from __future__ import annotations

import logging

import numpy as np

from .engine import RoughEngine, VocalEngine
from .lyrics import (
    align_words_to_notes,
    extract_lead_notes,
    harmony_vowel_segments,
    monophonic_line,
    select_vocal_tracks,
)

logger = logging.getLogger("ai_music_studio.vocals.render")


def _transpose_to_singable(notes, lo: int = 53, hi: int = 67):
    """Shift the melody by whole octaves so its median lands in a natural
    sung register (~G3–G4). Returns ``(shifted_notes, shift_semitones)`` —
    the shift is reused for harmonies so they keep their intervals."""
    if not notes:
        return notes, 0
    median = float(np.median([p for p, _, _ in notes]))
    shift = 0
    while median + shift > hi:
        shift -= 12
    while median + shift < lo:
        shift += 12
    if shift == 0:
        return notes, 0
    return [(p + shift, s, e) for (p, s, e) in notes], shift


def _render_segments(eng: VocalEngine, segs: list[dict], sr: int, total: float
                     ) -> tuple[np.ndarray, int]:
    """Render aligned segments to a mono waveform on the MIDI timeline."""
    if hasattr(eng, "render_line"):
        return eng.render_line(segs, sr)  # type: ignore[attr-defined]
    out = np.zeros(int(total * sr) + sr, dtype=np.float32)
    for seg in segs:
        y = eng.render_segment(seg["text"], seg["notes"], sr)
        if y.size == 0:
            continue
        i0 = int(seg["start"] * sr)
        i1 = min(len(out), i0 + len(y))
        out[i0:i1] += y[: i1 - i0]
    return out[: int(total * sr) + int(0.3 * sr)], sr


def _finish(audio: np.ndarray, sr: int, fx: bool) -> tuple[np.ndarray, int]:
    if audio.size == 0:
        return audio.astype(np.float32), sr
    peak = float(np.max(np.abs(audio)))
    if peak > 0:
        audio = audio * (0.9 / peak)
    if fx:
        audio = _apply_fx(audio, sr)
    return audio.astype(np.float32), sr


def render_lead_vocal(midi, lyrics, *, sr: int = 44100, voice: str = "",
                      engine: VocalEngine | None = None, fx: bool = True
                      ) -> tuple[np.ndarray, int]:
    """Render just the lead vocal (kept for the simple path / callers)."""
    import pretty_midi
    if not isinstance(midi, pretty_midi.PrettyMIDI):
        midi = pretty_midi.PrettyMIDI(str(midi))
    notes = extract_lead_notes(midi)
    text = lyrics if isinstance(lyrics, str) else " ".join(lyrics)
    if not notes or not text.strip():
        return np.zeros(0, dtype=np.float32), sr
    notes, _ = _transpose_to_singable(notes)
    eng = engine or RoughEngine(voice)
    out, sr = _render_segments(eng, align_words_to_notes(text, notes), sr, float(midi.get_end_time()))
    return _finish(out, sr, fx)


def render_vocals(midi, lyrics, *, sr: int = 44100, voice: str = "",
                  engine: VocalEngine | None = None, fx: bool = True,
                  harmonies: bool = False) -> tuple[np.ndarray, int]:
    """Render the lead vocal and, optionally, stack the block's harmony/
    backing lines underneath it as wordless "ooh" voices (same octave shift,
    time-locked to the lead)."""
    import pretty_midi
    if not isinstance(midi, pretty_midi.PrettyMIDI):
        midi = pretty_midi.PrettyMIDI(str(midi))
    text = lyrics if isinstance(lyrics, str) else " ".join(lyrics)
    lead_notes, harms = select_vocal_tracks(midi)
    if not lead_notes or not text.strip():
        return np.zeros(0, dtype=np.float32), sr

    lead_notes = monophonic_line(lead_notes)
    lead_notes, shift = _transpose_to_singable(lead_notes)
    eng = engine or RoughEngine(voice)
    total = float(midi.get_end_time())

    bus, sr = _render_segments(eng, align_words_to_notes(text, lead_notes), sr, total)
    bus = bus.astype(np.float32)

    if harmonies and harms:
        for _name, hnotes in harms:
            ht = monophonic_line([(p + shift, s, e) for (p, s, e) in hnotes])
            h, _ = _render_segments(eng, harmony_vowel_segments(ht), sr, total)
            if h.size == 0:
                continue
            n = max(len(bus), len(h))
            if len(bus) < n:
                bus = np.pad(bus, (0, n - len(bus)))
            if len(h) < n:
                h = np.pad(h, (0, n - len(h)))
            bus = bus + 0.55 * h.astype(np.float32)   # harmonies sit under the lead

    return _finish(bus, sr, fx)


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
