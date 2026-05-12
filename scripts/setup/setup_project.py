#!/usr/bin/env python3
"""
Setup script for AI Music Generation project.
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def setup_environment(use_conda: bool = True, python_version: str = "3.10"):
    """Set up Python environment."""
    project_root = Path(__file__).parent.parent.parent

    if use_conda:
        logger.info("Setting up Conda environment...")
        env_name = "ai-music"

        # Check if conda is available
        try:
            subprocess.run(["conda", "--version"], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("Conda not found. Please install Conda or use --no-conda flag.")
            return False

        # Create conda environment
        cmd = [
            "conda", "create", "-n", env_name,
            f"python={python_version}", "-y"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Failed to create Conda environment: {result.stderr}")
            return False

        logger.info(f"Conda environment '{env_name}' created successfully.")
        logger.info(f"Activate with: conda activate {env_name}")

    else:
        logger.info("Setting up virtual environment with venv...")
        venv_path = project_root / ".venv"

        cmd = [sys.executable, "-m", "venv", str(venv_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Failed to create virtual environment: {result.stderr}")
            return False

        logger.info(f"Virtual environment created at {venv_path}")
        logger.info(f"Activate with: source {venv_path}/bin/activate")

    return True

def install_dependencies(extras: list = None):
    """Install project dependencies."""
    project_root = Path(__file__).parent.parent.parent

    logger.info("Installing dependencies...")

    # Build pip install command
    cmd = [sys.executable, "-m", "pip", "install", "-e", "."]

    if extras:
        extras_str = ",".join(extras)
        cmd[-1] = f".[{extras_str}]"

    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"Failed to install dependencies: {result.stderr}")
        return False

    logger.info("Dependencies installed successfully.")
    return True

def setup_environment_file():
    """Set up environment configuration file."""
    project_root = Path(__file__).parent.parent.parent
    env_example = project_root / ".env.example"
    env_file = project_root / ".env"

    if not env_example.exists():
        logger.error(f"Environment template not found: {env_example}")
        return False

    if env_file.exists():
        logger.info(f"Environment file already exists: {env_file}")
        return True

    # Copy .env.example to .env
    try:
        env_example_content = env_example.read_text()
        env_file.write_text(env_example_content)
        logger.info(f"Created environment file: {env_file}")
        logger.info("Please edit this file to add your API keys and configuration.")
        return True
    except Exception as e:
        logger.error(f"Failed to create environment file: {e}")
        return False

def create_data_directories():
    """Create necessary data directories."""
    project_root = Path(__file__).parent.parent.parent
    data_dirs = [
        "data/raw",
        "data/processed",
        "data/models",
        "data/samples",
        "data/outputs",
        "logs",
    ]

    for dir_path in data_dirs:
        full_path = project_root / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory: {full_path}")

    logger.info("Data directories created successfully.")
    return True

def setup_git():
    """Initialize git repository if not already initialized."""
    project_root = Path(__file__).parent.parent.parent
    git_dir = project_root / ".git"

    if git_dir.exists():
        logger.info("Git repository already initialized.")
        return True

    logger.info("Initializing git repository...")
    result = subprocess.run(
        ["git", "init"],
        cwd=project_root,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        logger.warning(f"Git initialization failed: {result.stderr}")
        return False

    logger.info("Git repository initialized successfully.")
    return True

def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(description="Setup AI Music Generation project")
    parser.add_argument(
        "--no-conda",
        action="store_true",
        help="Use venv instead of Conda"
    )
    parser.add_argument(
        "--python",
        default="3.10",
        help="Python version (default: 3.10)"
    )
    parser.add_argument(
        "--extras",
        nargs="+",
        default=["dev"],
        help="Extra dependencies to install (e.g., dev, musicgen, ardour)"
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="Skip environment file setup"
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
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    logger.info("Starting AI Music Generation project setup...")

    # Execute setup steps
    steps = [
        ("Creating data directories", create_data_directories),
        ("Setting up git repository", setup_git),
        ("Setting up Python environment",
         lambda: setup_environment(not args.no_conda, args.python)),
        ("Installing dependencies",
         lambda: install_dependencies(args.extras)),
    ]

    if not args.skip_env:
        steps.insert(3, ("Setting up environment file", setup_environment_file))

    success = True
    for step_name, step_func in steps:
        logger.info(f"Step: {step_name}")
        if not step_func():
            logger.error(f"Failed: {step_name}")
            success = False
            break
        logger.info(f"Completed: {step_name}")

    if success:
        logger.info("\n" + "="*60)
        logger.info("Setup completed successfully!")
        logger.info("\nNext steps:")
        logger.info("1. Edit .env file with your API keys and configuration")
        logger.info("2. Activate the environment:")

        if args.no_conda:
            logger.info("   source .venv/bin/activate")
        else:
            logger.info("   conda activate ai-music")

        logger.info("3. Run an example:")
        logger.info("   python scripts/examples/basic_generation.py")
        logger.info("="*60)
    else:
        logger.error("\nSetup failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()