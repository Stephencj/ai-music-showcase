#!/usr/bin/env python3
"""
Test script for basic music generation.
"""

import os
import sys

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.generation.basic_generator import BasicMusicGenerator
from src.processing.audio_utils import AudioProcessor
import torchaudio


def main():
    """Main test function."""
    print("=== AI Music Generation Basic Test ===\n")

    # Create output directory
    output_dir = "data/outputs"
    os.makedirs(output_dir, exist_ok=True)

    # Initialize generator and processor
    print("Initializing components...")
    generator = BasicMusicGenerator()
    processor = AudioProcessor()

    # Test 1: Generate simple sounds
    print("\n1. Generating basic sounds...")
    sample_rate = 44100

    # Generate and save sine wave
    sine_wave = generator.generate_sine_wave(frequency=440.0, duration=2.0)
    sine_file = os.path.join(output_dir, "a4_sine.wav")
    torchaudio.save(sine_file, torch.from_numpy(sine_wave), sample_rate)
    print(f"  - Generated A4 sine wave: {sine_file}")

    # Generate and save chord
    c_major = [261.63, 329.63, 392.00]  # C4, E4, G4
    chord = generator.generate_chord(frequencies=c_major, duration=3.0)
    chord_file = os.path.join(output_dir, "c_major.wav")
    torchaudio.save(chord_file, torch.from_numpy(chord), sample_rate)
    print(f"  - Generated C major chord: {chord_file}")

    # Test 2: Generate test melody
    print("\n2. Generating test melody...")
    melody, sr = generator.generate_test_melody()
    melody_file = os.path.join(output_dir, "test_melody.wav")
    torchaudio.save(melody_file, torch.from_numpy(melody), sr)
    print(f"  - Generated test melody: {melody_file}")

    # Test 3: Test audio processing
    print("\n3. Testing audio processing...")
    try:
        # Load the generated melody
        loaded_audio, loaded_sr = processor.load_audio(melody_file)
        print(f"  - Loaded audio shape: {loaded_audio.shape}")
        print(f"  - Sample rate: {loaded_sr}")

        # Extract features
        features = processor.extract_features(loaded_audio, loaded_sr)
        print(f"  - Extracted {len(features)} features")
        print(f"  - Tempo: {features.get('tempo', 'N/A')} BPM")

        # Test normalization
        normalized = processor.normalize_audio(loaded_audio, target_dB=-3.0)
        normalized_file = os.path.join(output_dir, "normalized_melody.wav")
        processor.save_audio(normalized, normalized_file, loaded_sr)
        print(f"  - Normalized audio saved: {normalized_file}")

    except Exception as e:
        print(f"  - Audio processing test failed: {e}")

    # Test 4: Test format conversion
    print("\n4. Testing format conversion...")
    try:
        mp3_file = os.path.join(output_dir, "test_melody.mp3")
        processor.convert_format(melody_file, mp3_file, "mp3")
        print(f"  - Converted to MP3: {mp3_file}")
    except Exception as e:
        print(f"  - Format conversion failed (may need ffmpeg): {e}")

    print("\n=== Test Complete ===")
    print(f"\nGenerated files are in: {output_dir}")
    print("\nNext steps:")
    print("1. Install additional AI music tools: pip install magenta")
    print("2. Try the Jupyter notebooks in the 'notebooks/' directory")
    print("3. Check the 'src/generation/' directory for more advanced examples")

    return True


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)