#!/usr/bin/env python3
"""
End-to-end workflow: generate music → export for DAW import.

Demonstrates:
  1. Generate audio with MusicGen (AI text-to-music)
  2. Create MIDI accompaniment (chords, bass, drums)
  3. Package everything into a session directory for Ardour

Usage:
    # Full workflow (requires MusicGen model download on first run)
    python scripts/examples/daw_export.py

    # MIDI-only (no AI model needed — fast)
    python scripts/examples/daw_export.py --midi-only

    # Custom prompt
    python scripts/examples/daw_export.py --prompt "dark ambient drone" --key A --scale minor
"""

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.daw_integration.generic.midi_export import MidiExporter
from src.daw_integration.generic.styles import STYLES, apply as apply_style, list_styles
from src.daw_integration.ardour.client import ArdourSessionBuilder


def build_midi_tracks(
    key: str | None, scale: str, tempo: float | None, bars: int, seed: int | None,
    style: str | None = None,
) -> tuple[MidiExporter, Path]:
    """Create MIDI accompaniment and return (exporter, midi_path)."""
    if style:
        preset = STYLES[style]
        midi = apply_style(preset, bars=bars, seed=seed, tempo=tempo, key=key)
    else:
        effective_key = key or "C"
        effective_tempo = tempo if tempo is not None else 120.0
        midi = MidiExporter(tempo=effective_tempo)
        midi.add_chord_progression(key=effective_key, bars=bars, octave=3,
                                   scale_name=scale, track_name="Chords")
        midi.add_bass_line(key=effective_key, bars=bars, pattern="root_fifth",
                           scale_name=scale, track_name="Bass")
        midi.add_melody(key=effective_key, scale_name=scale, bars=bars, octave=5,
                        seed=seed, track_name="Melody")
        midi.add_drum_pattern("basic_rock", bars=bars, track_name="Drums")

    midi_path = Path("data/outputs/daw_session") / "accompaniment.mid"
    midi.save(midi_path)
    return midi, midi_path


def main():
    parser = argparse.ArgumentParser(description="Generate music and export for DAW")
    parser.add_argument("--prompt", default="upbeat indie rock with electric guitar and drums")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--size", default="small", choices=["small", "medium", "large"])
    parser.add_argument("--key", default=None, help="Root note (defaults: C, or preset key when --style is used).")
    parser.add_argument("--scale", default="major", help="Scale name (ignored when --style is used).")
    parser.add_argument("--tempo", type=float, default=None, help="BPM (defaults: 120, or preset tempo when --style is used).")
    parser.add_argument("--bars", type=int, default=8)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--style", default=None, choices=list_styles(),
                        help="Genre preset (overrides --scale and default patterns).")
    parser.add_argument("--midi-only", action="store_true", help="Skip AI generation, MIDI only")
    parser.add_argument("--session-name", default="AI_Session")
    args = parser.parse_args()

    output_base = Path("data/outputs/sessions")

    # ------------------------------------------------------------------
    # 1. MIDI accompaniment (always runs — fast, no model needed)
    # ------------------------------------------------------------------
    print("\n=== Building MIDI accompaniment ===")
    midi, midi_path = build_midi_tracks(
        args.key, args.scale, args.tempo, args.bars, args.seed, style=args.style,
    )
    midi_duration = midi.total_duration()
    preset = STYLES[args.style] if args.style else None
    effective_key = args.key or (preset.key if preset else "C")
    effective_scale = preset.scale if preset else args.scale
    effective_tempo = args.tempo if args.tempo is not None else (preset.tempo if preset else 120.0)
    style_label = f"style={args.style}  |  " if args.style else ""
    print(f"  {style_label}Key: {effective_key} {effective_scale}  |  Tempo: {effective_tempo} BPM  |  Duration: {midi_duration:.1f}s")

    # Also render MIDI to audio for preview
    print("  Rendering MIDI to audio preview...")
    midi_audio, midi_sr = midi.synthesize(sample_rate=44100)

    # ------------------------------------------------------------------
    # 2. AI-generated audio (optional)
    # ------------------------------------------------------------------
    ai_audio = None
    ai_sr = None

    if not args.midi_only:
        print(f"\n=== Generating AI audio with MusicGen ({args.size}) ===")
        from src.models import get_model, ModelConfig

        config = ModelConfig(
            name="musicgen",
            model_size=args.size,
            duration=args.duration,
            seed=args.seed,
        )
        model = get_model("musicgen", config=config)

        with model:
            result = model.generate(args.prompt, duration=args.duration)
            ai_audio = result.audio
            ai_sr = result.sample_rate
            print(f"  Generated {result.duration:.1f}s at {ai_sr} Hz")

    # ------------------------------------------------------------------
    # 3. Build session directory for Ardour
    # ------------------------------------------------------------------
    print(f"\n=== Exporting session: {args.session_name} ===")
    builder = ArdourSessionBuilder(
        args.session_name,
        tempo=effective_tempo,
        sample_rate=44100,
    )

    # Add MIDI-rendered audio
    builder.add_audio_track("MIDI_Mix", midi_audio, midi_sr, color="#70ad47")

    # Add MIDI file for individual-track import
    builder.add_midi_file("Accompaniment", midi_path, color="#ffc000")

    # Add AI audio if available
    if ai_audio is not None:
        builder.add_audio_track("AI_Lead", ai_audio, ai_sr, color="#5b9bd5")

    session_dir = builder.export(output_base)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 50)
    print("Session ready for Ardour import!")
    print(f"  Directory: {session_dir}")
    print(f"  Open Ardour → Session → Import, or drag files onto timeline")
    if ai_audio is not None:
        print(f"  AI audio sample rate is {ai_sr} Hz — Ardour will resample if session differs")


if __name__ == "__main__":
    main()
