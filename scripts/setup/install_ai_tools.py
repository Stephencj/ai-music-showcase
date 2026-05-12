#!/usr/bin/env python3
"""
Install AI music generation tools and models.

This script installs various AI music generation tools including:
- AudioCraft (MusicGen)
- Magenta
- Riffusion
- Stable Audio
- Other related tools
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class AIToolsInstaller:
    """Installer for AI music generation tools."""

    def __init__(self, use_conda: bool = False, upgrade: bool = False):
        self.use_conda = use_conda
        self.upgrade = upgrade
        self.project_root = Path(__file__).parent.parent.parent

    def run_command(self, cmd: List[str], description: str) -> bool:
        """Run a shell command."""
        logger.info(f"{description}...")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root
            )

            if result.returncode == 0:
                logger.info(f"✓ {description} completed successfully")
                if result.stdout:
                    logger.debug(f"Output: {result.stdout[:500]}")
                return True
            else:
                logger.error(f"✗ {description} failed")
                logger.error(f"Error: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"✗ {description} failed with exception: {e}")
            return False

    def install_core_dependencies(self) -> bool:
        """Install core Python dependencies."""
        cmd = [sys.executable, "-m", "pip", "install", "-e", "."]

        if self.upgrade:
            cmd.append("--upgrade")

        return self.run_command(cmd, "Installing core dependencies")

    def install_audiocraft(self) -> bool:
        """Install AudioCraft (MusicGen)."""
        # AudioCraft installation
        cmds = [
            # Install AudioCraft
            [sys.executable, "-m", "pip", "install", "audiocraft"],
            # Install transformers for MusicGen
            [sys.executable, "-m", "pip", "install", "transformers", "accelerate"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            if not self.run_command(cmd, f"Installing {cmd[3] if len(cmd) > 3 else 'AudioCraft tools'}"):
                success = False

        return success

    def install_magenta(self) -> bool:
        """Install Magenta for MIDI generation."""
        # Magenta has specific installation requirements
        cmds = [
            # Install Magenta
            [sys.executable, "-m", "pip", "install", "magenta"],
            # Install tensorflow (Magenta dependency)
            [sys.executable, "-m", "pip", "install", "tensorflow"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            if not self.run_command(cmd, f"Installing {cmd[3] if len(cmd) > 3 else 'Magenta tools'}"):
                success = False

        return success

    def install_riffusion(self) -> bool:
        """Install Riffusion for audio generation."""
        cmds = [
            # Install diffusers and transformers
            [sys.executable, "-m", "pip", "install", "diffusers", "transformers", "torch", "torchaudio"],
            # Install audio processing libraries
            [sys.executable, "-m", "pip", "install", "librosa", "soundfile"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            if not self.run_command(cmd, f"Installing Riffusion dependencies"):
                success = False

        return success

    def install_stable_audio(self) -> bool:
        """Install Stable Audio tools."""
        cmds = [
            # Install diffusers for Stable Audio
            [sys.executable, "-m", "pip", "install", "diffusers", "transformers"],
            # Install audio utilities
            [sys.executable, "-m", "pip", "install", "scipy", "soundfile"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            if not self.run_command(cmd, f"Installing Stable Audio dependencies"):
                success = False

        return success

    def install_audio_tools(self) -> bool:
        """Install general audio processing tools."""
        cmds = [
            # Audio processing
            [sys.executable, "-m", "pip", "install", "librosa", "soundfile", "pydub"],
            # MIDI processing
            [sys.executable, "-m", "pip", "install", "mido", "pretty-midi"],
            # Audio effects
            [sys.executable, "-m", "pip", "install", "pyrubberband"],
            # DAW integration
            [sys.executable, "-m", "pip", "install", "python-osc"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            tool_name = cmd[3] if len(cmd) > 3 else "audio tools"
            if not self.run_command(cmd, f"Installing {tool_name}"):
                success = False

        return success

    def install_development_tools(self) -> bool:
        """Install development tools."""
        cmds = [
            # Testing
            [sys.executable, "-m", "pip", "install", "pytest", "pytest-cov"],
            # Code quality
            [sys.executable, "-m", "pip", "install", "black", "flake8", "mypy"],
            # Documentation
            [sys.executable, "-m", "pip", "install", "sphinx", "sphinx-rtd-theme"],
        ]

        if self.upgrade:
            for cmd in cmds:
                cmd.append("--upgrade")

        success = True
        for cmd in cmds:
            if not self.run_command(cmd, f"Installing development tools"):
                success = False

        return success

    def download_models(self, model_dir: Path) -> bool:
        """Download pretrained models."""
        logger.info("Downloading pretrained models...")

        # Create model directory
        model_dir.mkdir(parents=True, exist_ok=True)

        # Note: Actual model downloads would happen on first use
        # This is just placeholder documentation
        models_to_download = {
            "MusicGen": [
                "facebook/musicgen-small",
                "facebook/musicgen-medium",
                "facebook/musicgen-large",
                "facebook/musicgen-melody",
            ],
            "Riffusion": [
                "riffusion/riffusion-model-v1",
            ],
            "Stable Audio": [
                "stabilityai/stable-audio-tools",
            ],
        }

        logger.info("Model download information:")
        for model_type, model_list in models_to_download.items():
            logger.info(f"  {model_type}:")
            for model in model_list:
                logger.info(f"    - {model}")

        logger.info("\nNote: Models will be downloaded automatically on first use")
        logger.info("      via Hugging Face transformers/diffusers libraries.")

        return True

    def setup_environment(self) -> bool:
        """Set up environment variables and paths."""
        logger.info("Setting up environment...")

        # Check for .env file
        env_example = self.project_root / ".env.example"
        env_file = self.project_root / ".env"

        if not env_file.exists() and env_example.exists():
            logger.info("Creating .env file from template...")
            try:
                import shutil
                shutil.copy(env_example, env_file)
                logger.info(f"Created {env_file}")
                logger.info("Please edit this file to add your API keys")
            except Exception as e:
                logger.error(f"Failed to create .env file: {e}")
                return False

        # Create necessary directories
        directories = [
            "data/models",
            "data/raw",
            "data/processed",
            "data/outputs",
            "data/samples",
            "logs",
        ]

        for dir_path in directories:
            full_path = self.project_root / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Created directory: {full_path}")

        logger.info("Environment setup completed")
        return True

    def verify_installation(self) -> Dict[str, bool]:
        """Verify that installations were successful."""
        logger.info("Verifying installations...")

        verification_results = {}

        # Test imports
        test_imports = {
            "Core": ["torch", "numpy", "librosa"],
            "AudioCraft": ["audiocraft"],
            "Transformers": ["transformers"],
            "Diffusers": ["diffusers"],
            "Magenta": ["magenta"],
            "Audio Tools": ["soundfile", "pydub"],
            "MIDI Tools": ["mido", "pretty_midi"],
        }

        for category, imports in test_imports.items():
            success = True
            for import_name in imports:
                try:
                    __import__(import_name)
                    logger.debug(f"  ✓ {import_name}")
                except ImportError:
                    logger.warning(f"  ✗ {import_name} not found")
                    success = False

            verification_results[category] = success
            if success:
                logger.info(f"✓ {category} imports successful")
            else:
                logger.warning(f"✗ {category} imports incomplete")

        return verification_results

def main():
    """Main installation function."""
    parser = argparse.ArgumentParser(
        description="Install AI music generation tools"
    )
    parser.add_argument(
        "--tools",
        nargs="+",
        choices=["all", "core", "audiocraft", "magenta", "riffusion", "stable_audio", "audio", "dev"],
        default=["all"],
        help="Tools to install"
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade existing packages"
    )
    parser.add_argument(
        "--use-conda",
        action="store_true",
        help="Use conda for installation (not implemented)"
    )
    parser.add_argument(
        "--download-models",
        action="store_true",
        help="Download pretrained models"
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("data/models"),
        help="Directory for model downloads"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify installation after completing"
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

    logger.info("AI Music Generation Tools Installer")
    logger.info("=" * 60)

    # Check Python version
    if sys.version_info < (3, 10):
        logger.error("Python 3.10 or higher is required")
        sys.exit(1)

    # Initialize installer
    installer = AIToolsInstaller(
        use_conda=args.use_conda,
        upgrade=args.upgrade
    )

    try:
        # Determine what to install
        if "all" in args.tools:
            tools_to_install = ["core", "audiocraft", "magenta", "riffusion", "stable_audio", "audio", "dev"]
        else:
            tools_to_install = args.tools

        # Installation mapping
        install_functions = {
            "core": installer.install_core_dependencies,
            "audiocraft": installer.install_audiocraft,
            "magenta": installer.install_magenta,
            "riffusion": installer.install_riffusion,
            "stable_audio": installer.install_stable_audio,
            "audio": installer.install_audio_tools,
            "dev": installer.install_development_tools,
        }

        # Run installations
        success = True
        for tool in tools_to_install:
            if tool in install_functions:
                if not install_functions[tool]():
                    logger.warning(f"Installation of {tool} had issues")
                    success = False
            else:
                logger.warning(f"Unknown tool: {tool}")

        # Setup environment
        if not installer.setup_environment():
            logger.warning("Environment setup had issues")
            success = False

        # Download models if requested
        if args.download_models:
            if not installer.download_models(args.model_dir):
                logger.warning("Model download had issues")
                success = False

        # Verify installation if requested
        if args.verify:
            results = installer.verify_installation()
            all_verified = all(results.values())
            if not all_verified:
                logger.warning("Some installations failed verification")
                success = False

        # Summary
        logger.info("\n" + "=" * 60)
        if success:
            logger.info("Installation completed successfully!")
            logger.info("\nNext steps:")
            logger.info("1. Edit .env file with your API keys")
            logger.info("2. Run an example script:")
            logger.info("   python scripts/examples/basic_generation.py")
            logger.info("3. Explore the notebooks/ directory for tutorials")
        else:
            logger.warning("Installation completed with warnings")
            logger.info("Check the logs above for issues")

        logger.info("=" * 60)

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("\nInstallation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Installation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()