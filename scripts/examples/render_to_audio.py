#!/usr/bin/env python3
"""
Render a generated MIDI (or song spec) to a finished audio track.

Pipeline: MIDI → per-track FluidSynth stems → per-family effects (HPF +
comp + reverb etc. via pedalboard) → mix bus → master preset
(``default`` / ``loud`` / ``cinematic`` / ``transparent``).

Examples::

    # Render an existing .mid
    python scripts/examples/render_to_audio.py \\
        --midi data/outputs/styles/funk_C_16bars.mid \\
        --master cinematic \\
        --output data/outputs/renders/funk_demo

    # Render a song spec end-to-end (style → MIDI → audio)
    python scripts/examples/render_to_audio.py \\
        --song-spec data/song_specs/refined_strut.yaml \\
        --output data/outputs/renders/refined_strut

    # Render a style preset directly (no .mid input needed)
    python scripts/examples/render_to_audio.py \\
        --style pop --bars 8 --seed 42 \\
        --output data/outputs/renders/pop_demo

    # Skip stems for speed
    python scripts/examples/render_to_audio.py \\
        --midi some.mid --no-stems --output /tmp/quick

    # Pin a specific soundfont
    python scripts/examples/render_to_audio.py \\
        --midi some.mid --soundfont ~/Sounds/MyKit.sf2 \\
        --output /tmp/render
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.audio_processing.render import (  # noqa: E402
    MASTER_PRESETS,
    render_to_audio,
)
from src.audio_processing.render.soundfont_resolver import (  # noqa: E402
    download_default,
)
from src.daw_integration.generic.midi_export import MidiExporter  # noqa: E402
from src.daw_integration.generic.styles import STYLES, apply, list_styles  # noqa: E402


def _build_midi(args: argparse.Namespace) -> MidiExporter | Path:
    if args.midi:
        path = Path(args.midi)
        if not path.exists():
            raise SystemExit(f"--midi path not found: {path}")
        return path

    if args.song_spec:
        from src.daw_integration.generic.song_spec import load_spec, render
        spec = load_spec(Path(args.song_spec))
        if args.seed is not None:
            spec.seed = args.seed
        return render(spec)

    if args.style:
        return apply(
            STYLES[args.style],
            bars=args.bars,
            seed=args.seed,
        )

    raise SystemExit("Pass one of: --midi, --song-spec, --style")


def _resolve_soundfont(value: str | None) -> str | None:
    if value is None or value == "auto":
        return None
    if value == "download":
        return str(download_default())
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render MIDI to a finished audio track.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = parser.add_argument_group("Input (pick one)")
    src.add_argument("--midi", type=Path,
                     help="Render an existing .mid file.")
    src.add_argument("--song-spec", type=Path,
                     help="Render a song spec YAML (style → MIDI → audio).")
    src.add_argument("--style", choices=list_styles(),
                     help="Render a style preset directly.")
    src.add_argument("--bars", type=int, default=16,
                     help="Bars to generate when using --style (default: 16).")

    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for generators (--style/--song-spec).")
    parser.add_argument("--soundfont", default="auto",
                        help="Path to .sf2/.sf3, or 'auto' (default), or "
                             "'download' to fetch MuseScore General SF3.")
    parser.add_argument("--master",
                        choices=list(MASTER_PRESETS.keys()),
                        default="default",
                        help="Master-bus preset (default: default).")
    parser.add_argument("--no-stems", action="store_true",
                        help="Skip per-track stem export.")
    parser.add_argument("--sample-rate", type=int, default=44100,
                        help="Render sample rate (default: 44100).")
    parser.add_argument("--output", "-o", required=True, type=Path,
                        help="Output directory (created if missing).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress info logs.")
    args = parser.parse_args()

    if sum(bool(x) for x in (args.midi, args.song_spec, args.style)) != 1:
        parser.error("Pass exactly one of --midi / --song-spec / --style.")

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    midi = _build_midi(args)
    soundfont = _resolve_soundfont(args.soundfont)

    print("=== Rendering ===")
    if isinstance(midi, MidiExporter):
        print(f"  Tracks:  {len(midi.tracks)}  ({', '.join(t.name for t in midi.tracks)})")
        print(f"  Tempo:   {midi.tempo:.0f} BPM")
    else:
        print(f"  MIDI:    {midi}")
    print(f"  Master:  {args.master}")
    print(f"  Stems:   {'yes' if not args.no_stems else 'no'}")
    print(f"  Output:  {args.output}")

    result = render_to_audio(
        midi,
        output_dir=args.output,
        soundfont=soundfont,
        sample_rate=args.sample_rate,
        with_stems=not args.no_stems,
        master_preset=args.master,
    )

    print()
    print(f"  Soundfont: {result.soundfont}")
    print(f"  Duration:  {result.duration_seconds:.1f}s")
    print(f"  Mix:       {result.mix_path}")
    if result.stem_paths:
        print(f"  Stems:     {len(result.stem_paths)} files in "
              f"{result.mix_path.parent / 'stems'}/")
    if result.manifest_path:
        print(f"  Manifest:  {result.manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
