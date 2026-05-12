#!/usr/bin/env python3
"""
Quickstart MIDI generator driven by genre style presets.

Usage:
    python scripts/examples/style_midi.py --style funk --bars 16
    python scripts/examples/style_midi.py --style metal --key D --bars 8 --seed 42
    python scripts/examples/style_midi.py --style jazz_fusion --bars 12 --session

The generated .mid drops straight into Ardour (drag onto timeline). With
--session, an Ardour session directory is also built for drag-and-drop import.

Available styles: funk, pop, dance, jazz_fusion, rock, metal, disco.
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.daw_integration.generic.styles import STYLES, apply, list_styles
from src.daw_integration.ardour.client import ArdourSessionBuilder


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a MIDI file in a chosen genre style.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Styles: {', '.join(list_styles())}",
    )
    parser.add_argument("--style", required=True, choices=list_styles(),
                        help="Genre preset to use.")
    parser.add_argument("--bars", type=int, default=16,
                        help="Song length in bars (default: 16).")
    parser.add_argument("--key", default=None,
                        help="Override preset key (e.g. C, D, F#).")
    parser.add_argument("--tempo", type=float, default=None,
                        help="Override preset tempo (BPM).")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible melody.")
    parser.add_argument("--no-melody", action="store_true",
                        help="Skip the melody track.")
    parser.add_argument("--session", action="store_true",
                        help="Also build an Ardour session directory.")
    parser.add_argument("--output-dir", default="data/outputs/styles",
                        help="Where to write the .mid file.")
    args = parser.parse_args()

    style = STYLES[args.style]
    midi = apply(
        style,
        bars=args.bars,
        seed=args.seed,
        tempo=args.tempo,
        key=args.key,
        include_melody=not args.no_melody,
    )

    key_label = (args.key or style.key).replace("#", "sharp")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    midi_path = out_dir / f"{args.style}_{key_label}_{args.bars}bars.mid"
    midi.save(midi_path)

    effective_tempo = args.tempo or style.tempo
    effective_key = args.key or style.key
    print(f"  Style:   {style.name}")
    print(f"  Key:     {effective_key} {style.scale}")
    print(f"  Tempo:   {effective_tempo:.0f} BPM")
    print(f"  Bars:    {args.bars}")
    print(f"  Tracks:  {len(midi.tracks)}")
    print(f"  Length:  {midi.total_duration():.1f}s")

    if args.session:
        print("\n=== Building Ardour session ===")
        audio, sr = midi.synthesize(sample_rate=44100)
        builder = ArdourSessionBuilder(
            f"{style.name.replace(' ', '_')}_Session",
            tempo=effective_tempo,
            sample_rate=44100,
        )
        builder.add_audio_track("Preview_Mix", audio, sr, color="#70ad47")
        builder.add_midi_file("Full_Arrangement", midi_path, color="#ffc000")
        session_dir = builder.export(Path("data/outputs/sessions"))
        print(f"  Session: {session_dir}")
        print("  Drag the .mid onto Ardour's timeline, or use Session > Import.")

    print(f"\nDone. Drop {midi_path} into your DAW.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
