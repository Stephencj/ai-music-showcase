#!/usr/bin/env python3
"""Render a seamless Christmas playlist mix from the command line.

    python scripts/christmas_mix.py --minutes 60 --name "christmas-ambience-1"
    python scripts/christmas_mix.py --count 4 --styles christmas_jazz_trio_full christmas_fireside_full --wav

Writes data/outputs/playlists/<name>.mp3 (and .wav with --wav) plus
<name>.json (the tracklist), and prints YouTube-style chapter lines. The same
mix is available as the `christmas_mix` song tool (MCP and /api/tools) and as
POST /api/christmas-mix.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from src.audio_processing.render import playlist

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=0.0, help="mix length (or give --count)")
    ap.add_argument("--count", type=int, default=0, help="number of songs")
    ap.add_argument("--styles", nargs="*", default=[], help="christmas_* style ids (default: all six)")
    ap.add_argument("--tunes", nargs="*", default=[], help="carol ids (default: every carol)")
    ap.add_argument("--originals", type=float, default=0.4, help="share of original tunes (0-1)")
    ap.add_argument("--min-seconds", type=float, default=150.0)
    ap.add_argument("--max-seconds", type=float, default=240.0)
    ap.add_argument("--crossfade", type=float, default=4.0)
    ap.add_argument("--lufs", type=float, default=-16.0, help="mix loudness (YouTube plays at about -14)")
    ap.add_argument("--arrangement", default="", help="Christmas variants for every song, e.g. less_busy,warmer")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--name", default="christmas-mix")
    ap.add_argument("--wav", action="store_true", help="also keep the 24-bit WAV")
    a = ap.parse_args()
    if a.count <= 0 and a.minutes <= 0:
        ap.error("give --minutes or --count")

    tracks = playlist.plan_mix(total_minutes=a.minutes, count=a.count, styles=a.styles, tunes=a.tunes,
                               originals=a.originals, track_seconds=(a.min_seconds, a.max_seconds), seed=a.seed,
                               arrangement=a.arrangement)
    res = playlist.render_mix(tracks, name=a.name, crossfade=a.crossfade, target_lufs=a.lufs,
                              formats=("mp3", "wav") if a.wav else ("mp3",),
                              progress=lambda msg, frac: print(f"[{frac:4.0%}] {msg}", flush=True))
    print(f"\n{res.seconds / 60:.1f} min at {res.lufs} LUFS")
    for kind, path in res.files.items():
        print(f"{kind}: {path}")
    print("\n" + playlist.chapters(res.tracks))


if __name__ == "__main__":
    main()
