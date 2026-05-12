#!/usr/bin/env python3
"""
Render the full Hit the Sack soundtrack: 1 main theme + 5 game tracks.

Usage:
    python scripts/examples/render_hit_the_sack.py
    python scripts/examples/render_hit_the_sack.py --copy-to /Users/stephencjuliano/Documents/hit-the-sack/assets/sounds

Each spec in data/song_specs/hit_the_sack/ renders to:
    data/outputs/hit_the_sack/<name>.mid
    data/outputs/hit_the_sack/<name>.ogg

The .ogg files are ready to drop into the game's assets/sounds/ folder.
"""

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.daw_integration.generic.song_spec import load_spec, render, total_bars


def render_one(spec_path: Path, out_dir: Path) -> tuple[Path, Path]:
    """Render one spec to .mid + .ogg. Returns (midi_path, ogg_path)."""
    spec = load_spec(spec_path)
    safe_name = spec_path.stem  # e.g. "main_theme"

    print(f"\n=== {spec.title} ({safe_name}) ===")
    print(f"  Style: {spec.style}  |  Key: {spec.key}  |  Tempo: {spec.tempo} BPM  |  Bars: {total_bars(spec)}")

    midi = render(spec)

    midi_path = out_dir / f"{safe_name}.mid"
    midi.save(midi_path)

    audio, sr = midi.synthesize(sample_rate=44100)
    # Plain peak normalization to -1.4 dBFS — no gain boost, no soft-clip.
    # Loud enough to be clearly audible at game-volume 1.0 without clipping.
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = audio * (0.85 / peak)
    # Convert mono to stereo so the file matches typical game asset format.
    audio_stereo = np.column_stack([audio, audio])
    ogg_path = out_dir / f"{safe_name}.ogg"
    sf.write(str(ogg_path), audio_stereo, sr, format="OGG")

    print(f"  Duration: {midi.total_duration():.1f}s  |  Tracks: {len(midi.tracks)}")
    print(f"  → {midi_path}")
    print(f"  → {ogg_path}")
    return midi_path, ogg_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the Hit the Sack soundtrack.")
    parser.add_argument("--copy-to", type=Path, default=None,
                        help="Optional path to also copy .ogg files (e.g. the game's assets/sounds folder).")
    args = parser.parse_args()

    spec_dir = project_root / "data" / "song_specs" / "hit_the_sack"
    out_dir = project_root / "data" / "outputs" / "hit_the_sack"
    out_dir.mkdir(parents=True, exist_ok=True)

    spec_files = sorted(spec_dir.glob("*.yaml"))
    if not spec_files:
        print(f"No specs found in {spec_dir}", file=sys.stderr)
        return 1

    print(f"Rendering {len(spec_files)} tracks → {out_dir}")
    rendered = []
    for spec_path in spec_files:
        midi_path, ogg_path = render_one(spec_path, out_dir)
        rendered.append(ogg_path)

    if args.copy_to:
        args.copy_to.mkdir(parents=True, exist_ok=True)
        print(f"\nCopying .ogg files to {args.copy_to}/")
        for ogg in rendered:
            dst = args.copy_to / ogg.name
            shutil.copy2(ogg, dst)
            print(f"  → {dst}")

    print(f"\nDone. {len(rendered)} tracks rendered to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
