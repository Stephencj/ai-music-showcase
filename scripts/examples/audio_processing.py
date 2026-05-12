#!/usr/bin/env python3
"""
Audio processing utilities example.

Demonstrates various audio processing techniques including:
- Loading and saving audio files
- Normalization and gain adjustment
- Filtering and effects
- Time stretching and pitch shifting
- Audio analysis
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)

class AudioProcessor:
    """Audio processing utilities."""

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate

    def load_audio(self, filepath: Path) -> Tuple[np.ndarray, int]:
        """Load audio file."""
        import soundfile as sf

        audio, sr = sf.read(filepath)
        if len(audio.shape) > 1:
            # Convert to mono by averaging channels
            audio = audio.mean(axis=1)

        if sr != self.sample_rate:
            logger.warning(f"Resampling from {sr}Hz to {self.sample_rate}Hz")
            audio = self.resample(audio, sr, self.sample_rate)

        return audio, self.sample_rate

    def save_audio(self, audio: np.ndarray, filepath: Path):
        """Save audio to file."""
        import soundfile as sf

        filepath.parent.mkdir(parents=True, exist_ok=True)
        sf.write(filepath, audio, self.sample_rate)
        logger.info(f"Audio saved to: {filepath}")

    def normalize(self, audio: np.ndarray, target_db: float = -3.0) -> np.ndarray:
        """Normalize audio to target dB level."""
        import numpy as np

        # Calculate current peak level in dB
        peak = np.max(np.abs(audio))
        if peak == 0:
            return audio

        current_db = 20 * np.log10(peak)
        gain_db = target_db - current_db
        gain_linear = 10 ** (gain_db / 20)

        normalized = audio * gain_linear
        logger.debug(f"Normalized: {current_db:.1f}dB -> {target_db:.1f}dB (gain: {gain_db:.1f}dB)")

        return normalized

    def apply_compression(self, audio: np.ndarray, threshold: float = -20.0,
                          ratio: float = 4.0, attack: float = 0.01,
                          release: float = 0.1) -> np.ndarray:
        """Apply simple compression to audio."""
        import numpy as np

        logger.info(f"Applying compression: threshold={threshold}dB, ratio={ratio}:1")

        # Simple compression algorithm
        # Note: This is a basic implementation. For production, use a proper compressor.
        envelope = np.abs(audio)
        compressed = np.zeros_like(audio)

        # Apply compression curve
        for i in range(len(audio)):
            if envelope[i] > 10 ** (threshold / 20):
                # Above threshold: apply compression
                gain_reduction = (envelope[i] - 10 ** (threshold / 20)) / ratio
                compressed[i] = audio[i] * (1 - gain_reduction / envelope[i])
            else:
                # Below threshold: no compression
                compressed[i] = audio[i]

        return compressed

    def apply_reverb(self, audio: np.ndarray, room_size: float = 0.5,
                     damping: float = 0.5, wet_level: float = 0.3) -> np.ndarray:
        """Apply reverb effect to audio."""
        try:
            import pyrubberband as pyrb
            # Simple reverb using time stretching with small variations
            # Note: For proper reverb, use a convolution reverb or dedicated library
            logger.info(f"Applying reverb: room_size={room_size}")

            # Create impulse response for simple reverb
            impulse_length = int(self.sample_rate * room_size)
            impulse = np.random.randn(impulse_length) * np.exp(-np.arange(impulse_length) / (self.sample_rate * damping))

            # Convolve audio with impulse response
            import scipy.signal
            reverbed = scipy.signal.convolve(audio, impulse, mode='same')

            # Mix dry and wet signals
            result = (1 - wet_level) * audio + wet_level * reverbed

            return result

        except ImportError:
            logger.warning("pyrubberband not installed. Using simple echo instead.")
            # Simple echo as fallback
            delay_samples = int(self.sample_rate * 0.1)  # 100ms delay
            echo = np.zeros_like(audio)
            echo[delay_samples:] = audio[:-delay_samples] * 0.5
            return audio + echo

    def time_stretch(self, audio: np.ndarray, factor: float) -> np.ndarray:
        """Time stretch audio without changing pitch."""
        try:
            import pyrubberband as pyrb
            stretched = pyrb.time_stretch(audio, self.sample_rate, factor)
            logger.info(f"Time stretched by factor: {factor}")
            return stretched
        except ImportError:
            logger.warning("pyrubberband not installed. Using simple resampling.")
            # Simple resampling as fallback
            from scipy import signal
            new_length = int(len(audio) * factor)
            stretched = signal.resample(audio, new_length)
            return stretched

    def pitch_shift(self, audio: np.ndarray, semitones: float) -> np.ndarray:
        """Pitch shift audio without changing duration."""
        try:
            import pyrubberband as pyrb
            shifted = pyrb.pitch_shift(audio, self.sample_rate, semitones)
            logger.info(f"Pitch shifted by {semitones} semitones")
            return shifted
        except ImportError:
            logger.warning("pyrubberband not installed. Cannot perform pitch shift.")
            return audio

    def resample(self, audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Resample audio to target sample rate."""
        from scipy import signal
        ratio = target_sr / orig_sr
        resampled = signal.resample(audio, int(len(audio) * ratio))
        return resampled

    def analyze_audio(self, audio: np.ndarray) -> dict:
        """Analyze audio properties."""
        import numpy as np
        import librosa

        analysis = {}

        # Basic statistics
        analysis['duration'] = len(audio) / self.sample_rate
        analysis['rms'] = np.sqrt(np.mean(audio ** 2))
        analysis['peak'] = np.max(np.abs(audio))
        analysis['crest_factor'] = analysis['peak'] / analysis['rms'] if analysis['rms'] > 0 else 0

        # Spectral features
        if len(audio) > 0:
            spectral_centroid = librosa.feature.spectral_centroid(y=audio, sr=self.sample_rate)[0]
            analysis['spectral_centroid_mean'] = np.mean(spectral_centroid)
            analysis['spectral_centroid_std'] = np.std(spectral_centroid)

        logger.info(f"Audio analysis: {analysis}")
        return analysis

def process_audio_file(input_path: Path, output_dir: Path, processor: AudioProcessor):
    """Process an audio file with various effects."""
    import numpy as np

    logger.info(f"Processing audio file: {input_path}")

    # Load audio
    audio, sr = processor.load_audio(input_path)
    logger.info(f"Loaded audio: {len(audio)/sr:.1f}s, {sr}Hz")

    # Analyze original audio
    original_analysis = processor.analyze_audio(audio)

    # Apply processing chain
    processed = audio.copy()

    # 1. Normalize
    processed = processor.normalize(processed, target_db=-3.0)

    # 2. Apply compression
    processed = processor.apply_compression(processed, threshold=-20.0, ratio=4.0)

    # 3. Apply reverb
    processed = processor.apply_reverb(processed, room_size=0.5, wet_level=0.2)

    # 4. Analyze processed audio
    processed_analysis = processor.analyze_audio(processed)

    # Save processed audio
    output_filename = f"processed_{input_path.stem}.wav"
    output_path = output_dir / output_filename
    processor.save_audio(processed, output_path)

    return output_path, original_analysis, processed_analysis

def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Audio processing utilities"
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input audio file"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs/processed"),
        help="Output directory for processed audio"
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=44100,
        help="Target sample rate"
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

    logger.info("Audio Processing Utilities")
    logger.info("=" * 50)

    try:
        import numpy as np
        import soundfile as sf

        # Initialize processor
        processor = AudioProcessor(sample_rate=args.sample_rate)

        # Process audio file
        output_path, original_analysis, processed_analysis = process_audio_file(
            args.input, args.output_dir, processor
        )

        logger.info("\n" + "=" * 50)
        logger.info("Audio processing completed successfully!")
        logger.info(f"Input: {args.input}")
        logger.info(f"Output: {output_path}")
        logger.info(f"Original duration: {original_analysis['duration']:.1f}s")
        logger.info(f"Processed duration: {processed_analysis['duration']:.1f}s")
        logger.info(f"RMS change: {original_analysis['rms']:.3f} -> {processed_analysis['rms']:.3f}")

    except ImportError as e:
        logger.error(f"Required packages not installed: {e}")
        logger.info("Install with: pip install numpy soundfile scipy librosa pyrubberband")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during audio processing: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()