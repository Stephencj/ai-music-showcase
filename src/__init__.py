"""
AI Music Generation Toolkit

A comprehensive toolkit for AI-powered music generation, processing, and DAW integration.
"""

__version__ = "0.1.0"
__author__ = "Stephen C. Juliano"
__email__ = "stephencjuliano@example.com"

import logging
from pathlib import Path

# Configure package-level logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Package constants
PACKAGE_ROOT = Path(__file__).parent
PROJECT_ROOT = PACKAGE_ROOT.parent

# Import key modules for easier access
__all__ = [
    "models",
    "audio_processing",
    "daw_integration",
    "api",
    "workflow",
    "utils",
]