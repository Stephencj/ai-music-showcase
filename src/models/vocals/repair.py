"""Same-voice clarity repair: re-sing only the words a listener can't make out.

Global clarity mode (:func:`src.models.vocals.lyrics.apply_clarity`) trades the
whole melody for diction. This is the *surgical* alternative: render the line
normally, ask the intelligibility benchmark which words were misheard, and
re-render **only those words** with the same studio voice at clearer local
pacing — then splice them back. The melody you can already understand is left
untouched; only the blurry words get pulled into a clearer register.

Locating the blurry words needs no audio timestamps: the render already knows
where every word sits (each aligned segment carries its onset + note
durations), so we only need Whisper to tell us *which* reference words didn't
read (a word-level diff), not *where* they are.

VERDICT (measured 2026-05-24, ``tools.clarity_bench --repair``): the word
*locator* is accurate (flags exactly the substituted/dropped words), and the
crossfade removes the audio seam — but **word-level splice-repair is dominated
by global clarity** and sometimes underperforms the baseline. Full song:
baseline 70% → repair 77% → clarity 85%; chorus excerpt: baseline 50% → repair
42% → clarity 85%. Re-rendering a word *in isolation* and splicing it fragments
the continuous voice stream the SVS conditions on (a lone 1–2-note chunk has
worse timing/coarticulation than the word in context), and on a full song
Whisper's messy transcript flags ~140 words, so "surgical" isn't surgical. The
lesson: if you re-render, do it *continuously* (global/whole-phrase), never
word-by-word. Kept as a measured experiment + reusable locator; NOT wired into
the app. See [[project_vocal_intelligibility]].
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from .intelligibility import _normalize, transcribe
from .lyrics import (
    align_words_to_notes, apply_clarity, monophonic_line, select_vocal_tracks,
)
from .render import _finish, _render_segments, _transpose_to_singable

logger = logging.getLogger("ai_music_studio.vocals.repair")


def _word_align(ref: list[str], hyp: list[str]) -> list[tuple[str, int, int]]:
    """Levenshtein backtrace aligning reference→hypothesis word lists. Returns
    ops ``(kind, ref_idx, hyp_idx)`` where kind ∈ {match, sub, del, ins};
    ``-1`` marks the side an op doesn't touch."""
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=int)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    ops: list[tuple[str, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("match" if ref[i - 1] == hyp[j - 1] else "sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            ops.append(("del", i - 1, -1))
            i -= 1
        else:
            ops.append(("ins", -1, j - 1))
            j -= 1
    ops.reverse()
    return ops


def unclear_word_indices(ref_words: list[str], transcript: str) -> list[int]:
    """Indices into ``ref_words`` of words the ASR substituted or dropped —
    i.e. the words a listener likely couldn't make out. Both sides are
    normalized the same way the benchmark normalizes (lowercase, no punct)."""
    hyp_n = _normalize(transcript)
    # Normalize per word (not the joined string) so each index maps back to
    # exactly one segment, even if a word normalizes to an empty token.
    ref_tokens = [_normalize(w)[0] if _normalize(w) else "" for w in ref_words]
    ops = _word_align(ref_tokens, hyp_n)
    return [ri for kind, ri, _ in ops if kind in ("sub", "del") and ri >= 0]


def repair_vocal(midi, lyrics, *, engine, sr: int = 44100,
                 clarity_kw: Optional[dict] = None, fx: bool = True,
                 max_passes: int = 1) -> tuple[np.ndarray, int, dict]:
    """Render the lead, find the unclear words, re-sing only those with local
    clarity (same voice), and splice them back. Returns
    ``(audio, sr, report)`` where ``report`` lists the repaired words.

    ``clarity_kw`` overrides the per-word transform (defaults: register fold +
    de-melisma; the inter-word gap is irrelevant to a one-word re-render)."""
    import pretty_midi
    if not isinstance(midi, pretty_midi.PrettyMIDI):
        midi = pretty_midi.PrettyMIDI(str(midi))
    text = lyrics if isinstance(lyrics, str) else " ".join(lyrics)
    lead, _ = select_vocal_tracks(midi)
    if not lead or not text.strip():
        return np.zeros(0, dtype=np.float32), sr, {"repaired": []}
    lead = monophonic_line(lead)
    lead, _ = _transpose_to_singable(lead)
    segs = align_words_to_notes(text, lead)
    total = float(midi.get_end_time())
    ckw = clarity_kw or {"register": "fold", "min_word_gap": 0.0, "demelisma": True}

    bus, sr = _render_segments(engine, segs, sr, total)
    bus = bus.astype(np.float32)
    ref_words = [s["text"] for s in segs]
    repaired: list[dict] = []

    for _ in range(max_passes):
        transcript = transcribe((bus, sr))
        idxs = unclear_word_indices(ref_words, transcript)
        idxs = [i for i in idxs if not any(r["idx"] == i for r in repaired)]
        if not idxs:
            break
        for i in idxs:
            seg = segs[i]
            clear_seg = apply_clarity([seg], **ckw)[0]
            y, _ = _render_segments(engine, [{**clear_seg, "start": 0.0}], sr,
                                    sum(d for _, d in clear_seg["notes"]) + 0.3)
            _splice(bus, y, seg["start"], sr)
            repaired.append({"idx": i, "word": seg["text"]})
    out, sr = _finish(bus, sr, fx)
    return out, sr, {"repaired": repaired}


def _splice(bus: np.ndarray, patch: np.ndarray, start: float, sr: int,
            xfade: float = 0.012) -> None:
    """Overwrite ``bus`` with ``patch`` at ``start`` seconds, equal-power
    crossfading the edges so the same-voice seam is inaudible (in place)."""
    if patch.size == 0:
        return
    i0 = int(start * sr)
    nf = max(1, int(xfade * sr))
    i1 = min(len(bus), i0 + len(patch))
    if i1 <= i0:
        return
    seg = patch[: i1 - i0].copy()
    # crossfade in at the head and out at the tail against whatever's already there
    if seg.size > 2 * nf:
        ramp = np.linspace(0.0, 1.0, nf, dtype=np.float32)   # 0→1
        rrev = ramp[::-1]                                     # 1→0
        # head: bus fades out, patch fades in
        bus[i0:i0 + nf] = bus[i0:i0 + nf] * (1 - ramp) + seg[:nf] * ramp
        # tail: patch fades out, bus fades back in
        bus[i1 - nf:i1] = bus[i1 - nf:i1] * (1 - rrev) + seg[-nf:] * rrev
        bus[i0 + nf:i1 - nf] = seg[nf:-nf]
    else:
        bus[i0:i1] = seg
