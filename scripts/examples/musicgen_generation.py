#!/usr/bin/env python3
"""
MusicGen text-to-music generation example.

Demonstrates using the MusicGen model wrapper for text-to-music generation.
The model weights are downloaded automatically on first run (~500 MB for small).

Usage:
    python scripts/examples/musicgen_generation.py
    python scripts/examples/musicgen_generation.py --prompt "jazz piano trio" --duration 15
    python scripts/examples/musicgen_generation.py --size medium --prompt "epic orchestral"
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.models import get_model, ModelConfig


def main():
    parser = argparse.ArgumentParser(description="Generate music from text with MusicGen")
    parser.add_argument("--prompt", default="a chill lo-fi hip hop beat with soft piano and vinyl crackle")
    parser.add_argument("--duration", type=float, default=10.0, help="Duration in seconds")
    parser.add_argument("--size", default="small", choices=["small", "medium", "large"])
    parser.add_argument("--output", type=Path, default=None, help="Output WAV path")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    # Build config
    config = ModelConfig(
        name="musicgen",
        model_size=args.size,
        duration=args.duration,
        temperature=args.temperature,
        seed=args.seed,
    )

    # Use the model registry
    model = get_model("musicgen", config=config)

    with model:
        result = model.generate(args.prompt, duration=args.duration)

        # Determine output path
        if args.output:
            out = args.output
        else:
            slug = args.prompt[:40].replace(" ", "_").replace("/", "-")
            out = Path("data/outputs/musicgen") / f"{slug}.wav"

        model.save_audio(result, out)
        print(f"\nDone! {result.duration:.1f}s of audio at {result.sample_rate} Hz")
        print(f"Prompt: {args.prompt}")


if __name__ == "__main__":
    main()
