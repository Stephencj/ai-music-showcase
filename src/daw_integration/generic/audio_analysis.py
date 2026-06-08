"""Audio → chord progression / key / tempo analysis.

The "listen to a song and break down its progression" half of Phase D. It
deliberately reuses the chord template-matcher and key-relative labelling from
:mod:`chord_analysis`, so an analysed audio file produces the *same* score-data
shape a rendered block does — which means the practice-mode chord chart and the
piano/guitar diagrams render an imported song with no extra UI work.

Only ``librosa`` (already a project dependency) is used; no new packages.
"""

from __future__ import annotations

from typing import Optional

from .chord_analysis import (
    _CHORD_TEMPLATES, _detect_chord, _label_chord, _tonic_pc,
)
from .midi_export import NOTE_NAMES

# Krumhansl–Kessler key profiles (major / minor), used to estimate the key by
# correlating the average chroma against all 12 rotations of each profile.
_KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = sum((a[i] - ma) ** 2 for i in range(n)) ** 0.5
    db = sum((b[i] - mb) ** 2 for i in range(n)) ** 0.5
    return num / (da * db) if da > 0 and db > 0 else 0.0


def _estimate_key(mean_chroma: list[float]) -> tuple[str, str]:
    """Return (tonic_name, 'major'|'minor') best matching the chroma."""
    best = (0, "major")
    best_score = -2.0
    for root in range(12):
        rot = [mean_chroma[(root + i) % 12] for i in range(12)]
        for mode, profile in (("major", _KK_MAJOR), ("minor", _KK_MINOR)):
            s = _corr(rot, profile)
            if s > best_score:
                best_score = s
                best = (root, mode)
    return NOTE_NAMES[best[0]], best[1]


def analyze_audio(
    path: str,
    *,
    beats_per_bar: int = 4,
    sr: int = 22050,
) -> dict:
    """Analyse an audio file into the score-data dict consumed by the UI.

    Detects tempo + beats, estimates the key, then assigns one chord per bar by
    template-matching the bar's beat-synchronous chroma. Time signature is
    assumed 4/4 (the common case); ``beats_per_bar`` overrides the grouping.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(path, sr=sr, mono=True)
    duration = float(len(y) / sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Harmonic chroma (CQT on the harmonic component → cleaner than raw STFT).
    y_harm = librosa.effects.harmonic(y, margin=4)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)
    chroma_times = librosa.frames_to_time(
        range(chroma.shape[1]), sr=sr, hop_length=512
    )
    # A low-band chroma to prime the chord root — the bass note disambiguates
    # relative major/minor (Am vs C), the main weakness of chroma matching.
    try:
        bass_chroma = librosa.feature.chroma_cqt(
            y=y_harm, sr=sr,
            fmin=librosa.note_to_hz("C1"), n_octaves=2,
        )
    except Exception:
        bass_chroma = None

    mean_chroma = [float(chroma[pc].mean()) for pc in range(12)]
    key_root, scale = _estimate_key(mean_chroma)
    tonic = _tonic_pc(key_root)

    # Bar boundaries: every `beats_per_bar` beats from the first beat. If beat
    # tracking found too few beats, fall back to a uniform tempo grid.
    if len(beat_times) >= beats_per_bar + 1:
        bar_starts = beat_times[::beats_per_bar]
        if bar_starts[-1] < duration - 1e-3:
            bar_starts = bar_starts + [duration]
    else:
        bar_sec = beats_per_bar * 60.0 / max(tempo, 1e-6)
        n = max(1, int(round(duration / bar_sec)))
        bar_starts = [i * bar_sec for i in range(n + 1)]

    def chroma_window(mat, t0: float, t1: float) -> Optional[list[float]]:
        i0 = int(np.searchsorted(chroma_times, t0))
        i1 = int(np.searchsorted(chroma_times, t1))
        if i1 <= i0:
            i1 = min(i0 + 1, mat.shape[1])
        seg = mat[:, i0:i1]
        if seg.shape[1] == 0:
            return None
        return [float(seg[pc].mean()) for pc in range(12)]

    per_bar: list[dict] = []
    for bar in range(len(bar_starts) - 1):
        t0, t1 = bar_starts[bar], bar_starts[bar + 1]
        win = chroma_window(chroma, t0, t1) or [0.0] * 12
        bass_pc = None
        if bass_chroma is not None:
            bwin = chroma_window(bass_chroma, t0, t1)
            if bwin and max(bwin) > 1e-6:
                bass_pc = max(range(12), key=lambda pc: bwin[pc])
        detected = _detect_chord(win, bass_pc)
        entry = {"bar": bar, "start_time": round(t0, 4), "end_time": round(t1, 4)}
        if detected is None:
            entry.update({"root": None, "quality": None, "symbol": "N.C.",
                          "roman": "", "nashville": ""})
        else:
            entry.update(_label_chord(detected[0], detected[1], tonic))
        per_bar.append(entry)

    spans: list[dict] = []
    for e in per_bar:
        if spans and spans[-1]["symbol"] == e["symbol"]:
            spans[-1]["end_bar"] = e["bar"]
            spans[-1]["end_time"] = e["end_time"]
        else:
            spans.append({
                "start_bar": e["bar"], "end_bar": e["bar"],
                "start_time": e["start_time"], "end_time": e["end_time"],
                "root": e["root"], "quality": e["quality"],
                "symbol": e["symbol"], "roman": e["roman"],
                "nashville": e["nashville"],
            })

    bars = len(per_bar)
    avg_bar = (duration / bars) if bars else 0.0
    return {
        "key": key_root,
        "scale": scale,
        "tempo": round(tempo, 2),
        "time_signature": [beats_per_bar, 4],
        "bars": bars,
        "bar_seconds": round(avg_bar, 4),
        "beats_per_bar": beats_per_bar,
        "duration": round(duration, 3),
        "sections": [],
        "chords": per_bar,
        "chord_spans": spans,
    }


def progression_romans(score: dict) -> list[str]:
    """The detected progression as Roman numerals (for 'generate similar')."""
    return [s["roman"] for s in score.get("chord_spans", []) if s.get("roman")]
