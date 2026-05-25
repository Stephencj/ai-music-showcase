"""Top-level vocal render: melody MIDI + lyrics → a sung mono vocal stem
(lead, optionally with stacked harmony lines)."""

from __future__ import annotations

import logging

import numpy as np

from .engine import RoughEngine, VocalEngine
from .lyrics import (
    align_words_to_notes,
    apply_clarity,
    extract_lead_notes,
    harmony_vowel_segments,
    monophonic_line,
    parse_phonetic,
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
                  harmonies: bool = False,
                  clarity: bool | dict = False,
                  engine_ranges: "list[tuple[float, float, VocalEngine]] | None" = None,
                  phonetic: str = "") -> tuple[np.ndarray, int]:
    """Render the lead vocal and, optionally, stack the block's harmony/
    backing lines underneath it as wordless "ooh" voices (same octave shift,
    time-locked to the lead).

    ``clarity`` toggles the intelligibility transform on the lead line (see
    :func:`src.models.vocals.lyrics.apply_clarity`): pass ``True`` for the
    defaults or a dict of overrides (``ceiling``, ``register``,
    ``min_word_gap``, ``demelisma``). Harmonies are wordless, so the transform
    only touches the lead.

    ``engine_ranges`` enables a **per-section engine map**: a list of
    ``(start_sec, end_sec, engine)`` — each lead word is sung by the engine
    whose range covers its onset, falling back to ``engine`` elsewhere. This is
    how a song can sing its hooks with the studio SVS (richer timbre) but rap
    its dense verses with the rough/TTS engine (far clearer diction on fast
    words — measured ~97 % vs ~72 % readable). Each engine renders its own
    words and they are summed on the shared timeline.

    ``phonetic`` is an optional edited **phonetic version** of the lyric (one
    bracketed ARPABET group per word, see :func:`lyrics.to_phonetic`). When
    given and its word count matches the lyric, the engine sings those phonemes
    instead of running g2p on the spelling — the user's per-word diction fix.
    Note counts still come from the displayed words, so an edit can't desync
    the melody."""
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

    pron = parse_phonetic(phonetic) if phonetic.strip() else None
    segs = align_words_to_notes(text, lead_notes, pron=pron)
    if clarity:
        segs = apply_clarity(segs, **(clarity if isinstance(clarity, dict) else {}))

    if engine_ranges:
        # Partition words by which range covers their onset, render each group
        # with its own engine, and sum on the shared timeline.
        def _pick(start: float) -> VocalEngine:
            for t0, t1, e in engine_ranges:
                if t0 <= start < t1:
                    return e
            return eng
        groups: dict[int, tuple[VocalEngine, list]] = {}
        for s in segs:
            e = _pick(s["start"])
            groups.setdefault(id(e), (e, []))[1].append(s)
        bus = np.zeros(int(total * sr) + sr, dtype=np.float32)
        for e, gsegs in groups.values():
            part, sr = _render_segments(e, gsegs, sr, total)
            n = min(len(bus), len(part))
            bus[:n] += part[:n].astype(np.float32)
        bus = bus[: int(total * sr) + int(0.3 * sr)]
    else:
        bus, sr = _render_segments(eng, segs, sr, total)
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


def section_time_ranges(sections, tempo: float, beats_per_bar: int
                        ) -> list[tuple[float, float, str]]:
    """Convert per-section ``(start_bar, end_bar, engine_name)`` rows into the
    ``(start_sec, end_sec, engine_name)`` ranges that feed ``engine_ranges``.
    Section bar ranges are **inclusive** (e.g. an "Intro 0–3" is 4 bars), so a
    section spans ``[start_bar, end_bar+1)`` bars of time. ``end_sec`` is open,
    matching ``render_vocals``'s ``t0 <= start < t1`` test."""
    barlen = beats_per_bar * 60.0 / float(tempo or 120.0)
    out: list[tuple[float, float, str]] = []
    for start_bar, end_bar, name in sections:
        out.append((start_bar * barlen, (end_bar + 1) * barlen, name))
    return out


def _apply_fx(audio: np.ndarray, sr: int) -> np.ndarray:
    """Vocal chain tuned for intelligibility: trim low mud, even it out, then
    lift the presence band (consonant clarity) and add air, with only a hint of
    reverb so the words stay forward instead of smearing. The SVS vocoder rolls
    off the highs, which is what makes raw output sound muffled/"deaf"; this
    puts the diction back."""
    try:
        from pedalboard import (Compressor, Gain, HighpassFilter, HighShelfFilter,
                                 PeakFilter, Pedalboard, Reverb)
        board = Pedalboard([
            # Settings chosen by the ASR intelligibility benchmark (see
            # intelligibility.py): this "v2" curve scored best for word
            # readability; pushing presence/air harder ("v3") looked brighter
            # but the recognizer read FEWER words — it smeared diction.
            HighpassFilter(cutoff_frequency_hz=120.0),                  # cut rumble/mud
            PeakFilter(cutoff_frequency_hz=280.0, gain_db=-3.0, q=1.0),  # un-box the low-mids
            PeakFilter(cutoff_frequency_hz=480.0, gain_db=-3.0, q=1.3),  # kill "woolly" mud (the muffle)
            Compressor(threshold_db=-20.0, ratio=3.5, attack_ms=4.0, release_ms=110.0),
            PeakFilter(cutoff_frequency_hz=3400.0, gain_db=6.0, q=0.9),  # PRESENCE: consonants
            PeakFilter(cutoff_frequency_hz=6000.0, gain_db=4.0, q=1.1),  # definition / consonant edge
            HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=5.0),    # air / breath
            Reverb(room_size=0.16, wet_level=0.05, dry_level=0.97, width=0.7),  # minimal smear
            Gain(gain_db=2.0),
        ])
        return board(audio.astype(np.float32), sr)
    except Exception as exc:  # noqa: BLE001
        logger.warning("vocal FX skipped: %s", exc)
        return audio


def carve_for_vocal(inst: np.ndarray, voc: np.ndarray, sr: int,
                    carve_hz: float = 2600.0, carve_db: float = -4.0,
                    duck_db: float = 4.5) -> np.ndarray:
    """Make the instrumental leave room for the lead so the lyric is clear:
    (1) a static dip in the band's presence region (frequency separation), and
    (2) gentle sidechain ducking — pull the band down by up to ``duck_db`` while
    the vocal is sounding (level separation). ``inst`` is (n, ch); ``voc`` is the
    vocal (mono or stereo) used only to derive the ducking envelope."""
    inst = inst.astype(np.float32)
    try:
        from pedalboard import PeakFilter, Pedalboard
        inst = Pedalboard([PeakFilter(cutoff_frequency_hz=carve_hz,
                                      gain_db=carve_db, q=1.2)])(inst, sr)
    except Exception as exc:  # noqa: BLE001
        logger.warning("instrumental carve skipped: %s", exc)
    if voc is None or getattr(voc, "size", 0) == 0:
        return inst
    v = voc if voc.ndim == 1 else voc.mean(axis=1)
    env = np.abs(v).astype(np.float32)
    win = max(1, int(sr * 0.08))                       # ~80 ms attack/release smoothing
    env = np.convolve(env, np.ones(win, np.float32) / win, mode="same")
    if env.max() > 0:
        env = env / env.max()
    floor = 10.0 ** (-abs(duck_db) / 20.0)             # gain at full vocal level
    gain = 1.0 - (1.0 - floor) * env
    n = len(inst)
    if len(gain) < n:
        gain = np.pad(gain, (0, n - len(gain)), constant_values=1.0)
    else:
        gain = gain[:n]
    return inst * gain[:, None] if inst.ndim == 2 else inst * gain[:len(inst)]
