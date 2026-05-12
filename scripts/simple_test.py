#!/usr/bin/env python3
"""
Simple test script for AI music generation setup.
"""

import os
import sys
import numpy as np

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_imports():
    """Test that all required packages can be imported."""
    print("=== Testing Imports ===\n")

    imports = [
        ("torch", "PyTorch"),
        ("librosa", "Librosa"),
        ("soundfile", "SoundFile"),
        ("pydub", "Pydub"),
        ("numpy", "NumPy"),
        ("scipy", "SciPy"),
    ]

    all_imports_ok = True
    for module_name, display_name in imports:
        try:
            __import__(module_name)
            print(f"✓ {display_name}")
        except ImportError as e:
            print(f"✗ {display_name}: {e}")
            all_imports_ok = False

    return all_imports_ok


def test_custom_modules():
    """Test that custom modules can be imported."""
    print("\n=== Testing Custom Modules ===\n")

    modules = [
        ("src.generation.basic_generator", "BasicMusicGenerator"),
        ("src.processing.audio_utils", "AudioProcessor"),
    ]

    all_modules_ok = True
    for module_path, display_name in modules:
        try:
            __import__(module_path)
            print(f"✓ {display_name}")
        except ImportError as e:
            print(f"✗ {display_name}: {e}")
            all_modules_ok = False

    return all_modules_ok


def test_basic_generation():
    """Test basic music generation."""
    print("\n=== Testing Basic Generation ===\n")

    try:
        from src.generation.basic_generator import BasicMusicGenerator

        generator = BasicMusicGenerator()
        print(f"✓ BasicMusicGenerator initialized")
        print(f"  Device: {generator.device}")

        # Test sine wave generation
        sine_wave = generator.generate_sine_wave(frequency=440.0, duration=1.0)
        print(f"✓ Sine wave generated")
        print(f"  Shape: {sine_wave.shape}")
        print(f"  Max amplitude: {np.max(np.abs(sine_wave)):.4f}")

        # Test chord generation
        chord = generator.generate_chord(frequencies=[261.63, 329.63, 392.00], duration=1.0)
        print(f"✓ Chord generated")
        print(f"  Shape: {chord.shape}")

        return True
    except Exception as e:
        print(f"✗ Basic generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_audio_processing():
    """Test audio processing."""
    print("\n=== Testing Audio Processing ===\n")

    try:
        from src.processing.audio_utils import AudioProcessor

        processor = AudioProcessor()
        print(f"✓ AudioProcessor initialized")
        print(f"  Sample rate: {processor.sample_rate}")
        print(f"  Channels: {processor.channels}")

        # Create test audio
        sample_rate = 44100
        duration = 1.0
        t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        test_audio = 0.5 * np.sin(2 * np.pi * 440 * t)
        test_audio_stereo = np.stack([test_audio, test_audio * 0.8], axis=0)

        # Test normalization
        normalized = processor.normalize_audio(test_audio_stereo, target_dB=-3.0)
        print(f"✓ Audio normalization")
        print(f"  Original max: {np.max(np.abs(test_audio_stereo)):.4f}")
        print(f"  Normalized max: {np.max(np.abs(normalized)):.4f}")

        # Test feature extraction
        features = processor.extract_features(test_audio_stereo, sample_rate)
        print(f"✓ Feature extraction")
        print(f"  Extracted {len(features)} features")

        return True
    except Exception as e:
        print(f"✗ Audio processing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_environment():
    """Test environment setup."""
    print("\n=== Testing Environment ===\n")

    # Check virtual environment
    venv_path = os.path.join(os.path.dirname(__file__), '..', '.venv')
    if os.path.exists(venv_path):
        print(f"✓ Virtual environment found: {venv_path}")
    else:
        print(f"✗ Virtual environment not found at {venv_path}")

    # Check directory structure
    required_dirs = [
        "data",
        "data/raw",
        "data/processed",
        "data/outputs",
        "models",
        "src",
        "src/generation",
        "src/processing",
        "src/utils",
        "src/integration",
        "notebooks",
        "tests",
        "config",
        "docs",
        "scripts"
    ]

    all_dirs_ok = True
    for dir_path in required_dirs:
        full_path = os.path.join(os.path.dirname(__file__), '..', dir_path)
        if os.path.exists(full_path):
            print(f"✓ Directory exists: {dir_path}/")
        else:
            print(f"✗ Directory missing: {dir_path}/")
            all_dirs_ok = False

    return all_dirs_ok


def main():
    """Run all tests."""
    print("=" * 60)
    print("AI Music Generation Setup Test")
    print("=" * 60)

    tests = [
        ("Environment", test_environment),
        ("Imports", test_imports),
        ("Custom Modules", test_custom_modules),
        ("Basic Generation", test_basic_generation),
        ("Audio Processing", test_audio_processing),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"Error in {test_name}: {e}")
            results.append((test_name, False))

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"{test_name:20} {status}")
        if not success:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed! AI music setup is ready.")
        print("\nNext steps:")
        print("1. Run the Jupyter notebook: notebooks/01_basic_music_generation.ipynb")
        print("2. Install additional tools: pip install magenta")
        print("3. Explore the src/ directory for more examples")
    else:
        print("✗ Some tests failed. Please check the errors above.")

    return all_passed


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)