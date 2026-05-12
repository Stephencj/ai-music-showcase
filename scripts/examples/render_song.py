#!/usr/bin/env python3
"""
Render a multi-section MIDI song from a YAML spec.

Usage:
    python scripts/examples/render_song.py --spec data/song_specs/funk_jam.yaml
    python scripts/examples/render_song.py --spec data/song_specs/rock_anthem.yaml --session
    python scripts/examples/render_song.py --spec my.yaml --seed 99 --out /tmp/my.mid

See ``data/song_specs/*.yaml`` for examples you can copy and edit.
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.daw_integration.generic.song_spec import load_spec, render, total_bars
from src.daw_integration.ardour.client import ArdourSessionBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a multi-section MIDI song from a YAML spec.")
    parser.add_argument("--spec", required=True, type=Path,
                        help="Path to the song spec YAML file.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output .mid path (default: data/outputs/songs/<title>.mid).")
    parser.add_argument("--seed", type=int, default=None,
                        help="Override the seed in the spec.")
    parser.add_argument("--session", action="store_true",
                        help="Also build an Ardour session directory with a preview audio render.")
    parser.add_argument("--audio-format", choices=["wav", "ogg", "none"], default="none",
                        help="Render the song to an audio file alongside the .mid (FluidSynth via pretty_midi).")
    args = parser.parse_args()

    spec = load_spec(args.spec)
    if args.seed is not None:
        spec.seed = args.seed

    print(f"=== Rendering: {spec.title} ===")
    print(f"  Style:    {spec.style}")
    print(f"  Key:      {spec.key}")
    print(f"  Tempo:    {spec.tempo} BPM")
    print(f"  Bars:     {total_bars(spec)}  ({len(spec.sections)} sections)")
    for s in spec.sections:
        mod = f"  key={s.key}" if s.key else ""
        dens = f"  density={s.density}" if s.density != 1.0 else ""
        fill = f"  fill={s.fill_at}" if s.fill_at else ""
        fade = "  fade" if s.fade else ""
        print(f"    - {s.name:10s} {s.bars:>3d} bars{mod}{dens}{fill}{fade}")

    midi = render(spec)

    if args.out is None:
        safe_title = spec.title.lower().replace(" ", "_").replace("/", "_")
        out = Path("data/outputs/songs") / f"{safe_title}.mid"
    else:
        out = args.out

    midi.save(out)
    print(f"\n  Duration: {midi.total_duration():.1f}s")
    print(f"  Tracks:   {len(midi.tracks)}")
    print(f"  File:     {out}")

    if args.audio_format != "none":
        import soundfile as sf
        audio, sr = midi.synthesize(sample_rate=44100)
        # Normalize peak to -3dB to avoid clipping in lossy encoders
        import numpy as np
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = audio * (0.707 / peak)
        audio_out = out.with_suffix(f".{args.audio_format}")
        fmt = "OGG" if args.audio_format == "ogg" else "WAV"
        sf.write(str(audio_out), audio, sr, format=fmt)
        print(f"  Audio:    {audio_out}")

    if args.session:
        print("\n=== Building Ardour session ===")
        audio, sr = midi.synthesize(sample_rate=44100)
        builder = ArdourSessionBuilder(
            spec.title.replace(" ", "_"),
            tempo=spec.tempo,
            sample_rate=44100,
        )
        builder.add_audio_track("Preview_Mix", audio, sr, color="#70ad47")
        builder.add_midi_file("Full_Arrangement", out, color="#ffc000")
        session_dir = builder.export(Path("data/outputs/sessions"))
        print(f"  Session:  {session_dir}")

    print(f"\nDone. Drop {out} into Ardour.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
