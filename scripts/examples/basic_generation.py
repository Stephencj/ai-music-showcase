#!/usr/bin/env python3
"""
Basic example of AI music generation workflow.

This script demonstrates a simple pipeline for generating music using AI models.
"""
import argparse
import logging
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.models.base import ModelConfig, GenerationResult
from src.audio_processing.postprocessing import AudioPostProcessor

logger = logging.getLogger(__name__)

class MockMusicGenerator:
    """Mock music generator for demonstration purposes."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = "MockMusicGen"

    def generate(self, prompt: str, duration: float = None) -> GenerationResult:
        """Generate mock audio (returns silence for demonstration)."""
        import numpy as np

        duration = duration or self.config.duration
        sample_rate = 44100
        samples = int(duration * sample_rate)

        # Generate silence (in real implementation, this would be actual audio)
        audio = np.zeros(samples, dtype=np.float32)

        return GenerationResult(
            audio=audio,
            sample_rate=sample_rate,
            duration=duration,
            model_name=self.name,
            config=self.config,
            metadata={"prompt": prompt, "actual_audio": False}
        )

class MockAudioPostProcessor:
    """Mock audio post-processor for demonstration."""

    def process(self, audio: GenerationResult) -> GenerationResult:
        """Apply mock post-processing."""
        import numpy as np

        # In real implementation, this would apply effects, normalization, etc.
        logger.info(f"Applying post-processing to {audio.duration:.1f}s audio")

        # Return the same audio (mock)
        return audio

def generate_music(prompt: str, duration: float, output_dir: Path):
    """Generate music using the mock pipeline."""
    logger.info(f"Starting music generation pipeline...")
    logger.info(f"Prompt: {prompt}")
    logger.info(f"Duration: {duration}s")

    # Create model configuration
    config = ModelConfig(
        name="mock_model",
        model_size="medium",
        duration=duration,
        temperature=1.0,
        device="cpu"
    )

    # Initialize components
    generator = MockMusicGenerator(config)
    processor = MockAudioPostProcessor()

    # Generate audio
    logger.info("Generating audio...")
    raw_audio = generator.generate(prompt, duration)

    # Apply post-processing
    logger.info("Applying post-processing...")
    processed_audio = processor.process(raw_audio)

    # Save audio (mock - creates empty file)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prompt[:30].replace(' ', '_')}.wav"
    output_path = output_dir / filename

    # In real implementation, this would save actual audio
    with open(output_path, 'wb') as f:
        f.write(b"MOCK AUDIO FILE - In real implementation, this would be actual WAV data")

    logger.info(f"Audio saved to: {output_path}")

    return output_path

def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Basic AI music generation example"
    )
    parser.add_argument(
        "--prompt",
        default="A relaxing ambient track with piano and strings",
        help="Text prompt for music generation"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Duration in seconds"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/examples"),
        help="Output directory for generated audio"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("AI Music Generation Example")
    logger.info("=" * 50)

    try:
        # Generate music
        output_path = generate_music(
            prompt=args.prompt,
            duration=args.duration,
            output_dir=args.output_dir
        )

        logger.info("\n" + "=" * 50)
        logger.info("Example completed successfully!")
        logger.info(f"Output: {output_path}")
        logger.info("\nNote: This is a mock implementation.")
        logger.info("To use real AI models, install model dependencies:")
        logger.info("  pip install -e '.[musicgen]'  # for MusicGen")
        logger.info("  pip install audiocraft        # for AudioCraft")

    except Exception as e:
        logger.error(f"Error during generation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()