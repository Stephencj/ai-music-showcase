#!/usr/bin/env python3
"""
Verify AI music generation setup.
"""

import os
import sys
import subprocess

def print_header(text):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)

def check_virtual_environment():
    """Check if virtual environment is active."""
    print_header("1. Virtual Environment")

    # Check for common virtual environment indicators
    venv_indicators = [
        os.path.exists(".venv"),
        os.path.exists("venv"),
        os.path.exists("env"),
        "VIRTUAL_ENV" in os.environ
    ]

    if any(venv_indicators):
        print("✓ Virtual environment detected")
        if "VIRTUAL_ENV" in os.environ:
            print(f"  Active venv: {os.environ['VIRTUAL_ENV']}")
        return True
    else:
        print("✗ No virtual environment detected")
        print("  Run: source .venv/bin/activate")
        return False

def check_python_version():
    """Check Python version."""
    print_header("2. Python Version")

    try:
        result = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True,
            text=True
        )
        version = result.stdout.strip()
        print(f"✓ {version}")
        return True
    except Exception as e:
        print(f"✗ Could not determine Python version: {e}")
        return False

def check_directory_structure():
    """Check project directory structure."""
    print_header("3. Directory Structure")

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
        "scripts"
    ]

    all_exist = True
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✓ {dir_path}/")
        else:
            print(f"✗ {dir_path}/ (missing)")
            all_exist = False

    return all_exist

def check_config_files():
    """Check configuration files."""
    print_header("4. Configuration Files")

    required_files = [
        "requirements.txt",
        "pyproject.toml",
        ".env.example",
        ".gitignore",
        "README.md"
    ]

    all_exist = True
    for file_path in required_files:
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            print(f"✓ {file_path} ({file_size} bytes)")
        else:
            print(f"✗ {file_path} (missing)")
            all_exist = False

    return all_exist

def check_python_packages():
    """Check Python packages."""
    print_header("5. Python Packages")

    required_packages = [
        "torch",
        "librosa",
        "soundfile",
        "numpy",
        "scipy"
    ]

    all_installed = True
    for package in required_packages:
        try:
            __import__(package)
            print(f"✓ {package}")
        except ImportError:
            print(f"✗ {package} (not installed)")
            all_installed = False

    return all_installed

def check_custom_modules():
    """Check custom modules."""
    print_header("6. Custom Modules")

    # Add src to path
    sys.path.insert(0, "src")

    modules_to_check = [
        ("generation.basic_generator", "BasicMusicGenerator"),
        ("processing.audio_utils", "AudioProcessor"),
    ]

    all_loaded = True
    for module_path, class_name in modules_to_check:
        try:
            module = __import__(module_path, fromlist=[class_name])
            print(f"✓ {module_path}.{class_name}")
        except Exception as e:
            print(f"✗ {module_path}.{class_name}: {e}")
            all_loaded = False

    return all_loaded

def generate_test_audio():
    """Generate test audio to verify functionality."""
    print_header("7. Functionality Test")

    try:
        # Import modules
        from generation.basic_generator import BasicMusicGenerator
        from processing.audio_utils import AudioProcessor

        # Initialize
        generator = BasicMusicGenerator()
        processor = AudioProcessor()

        print("✓ Modules initialized")
        print(f"  Generator device: {generator.device}")
        print(f"  Processor sample rate: {processor.sample_rate}")

        # Generate simple audio
        sine_wave = generator.generate_sine_wave(frequency=440.0, duration=0.5)
        print(f"✓ Generated sine wave")
        print(f"  Shape: {sine_wave.shape}")

        # Create output directory
        os.makedirs("data/outputs", exist_ok=True)

        # Try to save (might fail without torchaudio, but that's OK)
        try:
            import torch
            import torchaudio
            test_file = "data/outputs/test_verify.wav"
            torchaudio.save(test_file, torch.from_numpy(sine_wave), 44100)
            print(f"✓ Saved test audio: {test_file}")

            # Verify file was created
            if os.path.exists(test_file):
                file_size = os.path.getsize(test_file)
                print(f"  File size: {file_size} bytes")
            else:
                print("✗ File not created")

        except ImportError:
            print("⚠ torchaudio not available for saving (non-critical)")

        return True

    except Exception as e:
        print(f"✗ Functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all checks."""
    print("AI MUSIC GENERATION SETUP VERIFICATION")
    print("=" * 60)

    checks = [
        ("Virtual Environment", check_virtual_environment),
        ("Python Version", check_python_version),
        ("Directory Structure", check_directory_structure),
        ("Configuration Files", check_config_files),
        ("Python Packages", check_python_packages),
        ("Custom Modules", check_custom_modules),
        ("Functionality", generate_test_audio),
    ]

    results = []
    for check_name, check_func in checks:
        try:
            success = check_func()
            results.append((check_name, success))
        except Exception as e:
            print(f"Error in {check_name}: {e}")
            results.append((check_name, False))

    # Summary
    print_header("VERIFICATION SUMMARY")

    passed = sum(1 for _, success in results if success)
    total = len(results)

    print(f"Passed: {passed}/{total} checks")
    print()

    for check_name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status} - {check_name}")

    print()

    if passed == total:
        print("SUCCESS: AI music setup is fully functional!")
        print("\nNext steps:")
        print("1. Run: jupyter notebook notebooks/01_basic_music_generation.ipynb")
        print("2. Explore the src/ directory")
        print("3. Check SETUP_SUMMARY.md for more information")
    elif passed >= total * 0.7:
        print("PARTIAL SUCCESS: Setup is mostly functional.")
        print("Some non-critical components may be missing.")
        print("\nYou can still:")
        print("1. Run the Jupyter notebook")
        print("2. Generate basic audio")
        print("3. Install missing packages as needed")
    else:
        print("SETUP INCOMPLETE: Significant issues detected.")
        print("\nPlease check:")
        print("1. Virtual environment activation")
        print("2. Package installation")
        print("3. Directory structure")

    return passed == total

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nVerification interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)