"""Measure the clarity transform with the Whisper-WER benchmark.

Slices a window of the real lead melody (default: the first chorus, located by
a marker word in the lyric), then renders the *same* words with the studio
voice under several clarity settings and scores each with
``intelligibility.score`` — so we compare clarity levers on identical material,
fast (one short excerpt, shared model cache), before committing to a full-song
render.

    python -m tools.clarity_bench Boy_Band_Full_Song --marker broke --segs 26
"""
from __future__ import annotations

import argparse
import time

import numpy as np

from src.daw_integration.generic import blocks as block_store
from src.models.vocals import get_engine
from src.models.vocals.intelligibility import score
from src.models.vocals.lyrics import (
    align_words_to_notes, apply_clarity, monophonic_line, select_vocal_tracks,
)
from src.models.vocals.render import _finish, _render_segments, _transpose_to_singable


def chorus_window(name: str, lyrics: str, marker: str, n_segs: int):
    """Return (segments, reference_text) for a window of `n_segs` words starting
    at the first word == `marker`, with start times rebased to 0."""
    pm, _ = block_store.load_block(name)
    lead, _ = select_vocal_tracks(pm)
    lead = monophonic_line(lead)
    lead, _ = _transpose_to_singable(lead)
    segs = align_words_to_notes(lyrics, lead)
    start = next((i for i, s in enumerate(segs)
                  if s["text"].lower() == marker.lower()), 0)
    window = segs[start:start + n_segs]
    t0 = window[0]["start"]
    window = [{**s, "start": s["start"] - t0} for s in window]
    ref = " ".join(s["text"] for s in window)
    return window, ref


def render(eng, segs, sr=44100):
    total = max(s["start"] + sum(d for _, d in s["notes"]) for s in segs) + 0.3
    y, sr = _render_segments(eng, segs, sr, total)
    return _finish(y, sr, fx=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("block")
    ap.add_argument("--marker", default="broke")
    ap.add_argument("--segs", type=int, default=26)
    ap.add_argument("--voice", default="tiger_fresh")
    ap.add_argument("--full", action="store_true",
                    help="render the WHOLE song baseline vs the winning clarity "
                         "config (the real-world headline number, slower)")
    ap.add_argument("--repair", action="store_true",
                    help="full song: baseline vs same-voice splice-repair vs "
                         "global clarity — shows the surgical-vs-global tradeoff")
    args = ap.parse_args(argv)

    _, meta = block_store.load_block(args.block)
    lyrics = meta.get("lyrics") or (meta.get("spec") or {}).get("lyrics") or ""

    if args.repair:
        from src.models.vocals.render import render_vocals
        from src.models.vocals.repair import repair_vocal
        pm, _ = block_store.load_block(args.block)
        eng = get_engine("studio", args.voice)
        t = time.time()
        yb, sr = render_vocals(pm, lyrics, voice=args.voice, engine=eng, fx=True)
        rb = score(lyrics, (yb, sr))
        print(f"[baseline] acc={rb['accuracy']*100:5.1f}%  ({time.time()-t:.0f}s)")
        t = time.time()
        yr, sr, rep = repair_vocal(pm, lyrics, engine=eng, fx=True, max_passes=2)
        rr = score(lyrics, (yr, sr))
        words = ", ".join(r["word"] for r in rep["repaired"]) or "(none)"
        print(f"[repair  ] acc={rr['accuracy']*100:5.1f}%  ({time.time()-t:.0f}s)  "
              f"fixed {len(rep['repaired'])}: {words}")
        t = time.time()
        yc, sr = render_vocals(pm, lyrics, voice=args.voice, engine=eng,
                               fx=True, clarity=True)
        rc = score(lyrics, (yc, sr))
        print(f"[clarity ] acc={rc['accuracy']*100:5.1f}%  ({time.time()-t:.0f}s)")
        return

    if args.full:
        from src.models.vocals.render import render_vocals
        pm, _ = block_store.load_block(args.block)
        eng = get_engine("studio", args.voice)
        for label, clarity in (("baseline", False), ("clarity", True)):
            t = time.time()
            y, sr = render_vocals(pm, lyrics, voice=args.voice, engine=eng,
                                  fx=True, clarity=clarity)
            r = score(lyrics, (y, sr))
            print(f"[full/{label:8s}] acc={r['accuracy']*100:5.1f}%  "
                  f"({len(y)/sr:.0f}s audio, {time.time()-t:.0f}s)")
        return

    window, ref = chorus_window(args.block, lyrics, args.marker, args.segs)
    dur = max(s["start"] + sum(d for _, d in s["notes"]) for s in window)
    print(f"window: {len(window)} words, {dur:.1f}s")
    print(f"REF: {ref}\n")

    eng = get_engine("studio", args.voice)

    variants = {
        "baseline":        None,
        "fold":            dict(register="fold", min_word_gap=0.0, demelisma=False),
        "gap.10":          dict(register="off",  min_word_gap=0.10, demelisma=False),
        "demelisma":       dict(register="off",  min_word_gap=0.0, demelisma=True),
        "fold+gap+demel":  dict(register="fold", min_word_gap=0.10, demelisma=True),
        "shift+gap+demel": dict(register="shift", min_word_gap=0.10, demelisma=True),
    }
    results = {}
    for label, kw in variants.items():
        segs = window if kw is None else apply_clarity(window, **kw)
        t = time.time()
        y, sr = render(eng, segs)
        r = score(ref, (y, sr))
        results[label] = r
        print(f"[{label:16s}] acc={r['accuracy']*100:5.1f}%  "
              f"({time.time()-t:.0f}s)  HEARD: {r['transcript'][:80]}")

    base = results["baseline"]["accuracy"]
    print("\nsummary (Δ vs baseline):")
    for label, r in results.items():
        d = (r["accuracy"] - base) * 100
        print(f"  {label:16s} {r['accuracy']*100:5.1f}%  {d:+5.1f}")


if __name__ == "__main__":
    main()
