"""
Base classes for AI music generation models.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Union
import numpy as np

logger = logging.getLogger(__name__)

@dataclass
class ModelConfig:
    """Configuration for a model."""
    name: str
    model_size: str = "medium"
    duration: float = 30.0
    temperature: float = 1.0
    top_p: float = 0.9
    device: str = "cuda"
    batch_size: int = 1
    seed: Optional[int] = None
    extra_params: Dict[str, Any] = None

    def __post_init__(self):
        if self.extra_params is None:
            self.extra_params = {}

@dataclass
class GenerationResult:
    """Result of audio generation."""
    audio: np.ndarray
    sample_rate: int
    duration: float
    model_name: str
    config: ModelConfig
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class BaseModel(ABC):
    """Abstract base class for all AI music generation models."""

    def __init__(self, config: Optional[ModelConfig] = None):
        """
        Initialize the model.

        Args:
            config: Model configuration. If None, uses default config.
        """
        self.config = config or self.get_default_config()
        self._initialized = False

    @abstractmethod
    def get_default_config(self) -> ModelConfig:
        """Get default configuration for this model."""
        pass

    @abstractmethod
    def initialize(self):
        """Initialize the model (load weights, setup pipeline)."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        duration: Optional[float] = None,
        **kwargs
    ) -> GenerationResult:
        """
        Generate audio from text prompt.

        Args:
            prompt: Text description of desired audio
            duration: Duration in seconds (overrides config)
            **kwargs: Additional generation parameters

        Returns:
            GenerationResult containing audio and metadata
        """
        pass

    def generate_batch(
        self,
        prompts: list[str],
        durations: Optional[list[float]] = None,
        **kwargs
    ) -> list[GenerationResult]:
        """
        Generate audio for multiple prompts.

        Args:
            prompts: List of text prompts
            durations: List of durations (or single duration for all)
            **kwargs: Additional generation parameters

        Returns:
            List of GenerationResult objects
        """
        if not self._initialized:
            self.initialize()

        if durations is None:
            durations = [self.config.duration] * len(prompts)
        elif isinstance(durations, (int, float)):
            durations = [durations] * len(prompts)

        results = []
        for prompt, duration in zip(prompts, durations):
            logger.info(f"Generating audio for prompt: {prompt[:50]}...")
            result = self.generate(prompt, duration, **kwargs)
            results.append(result)

        return results

    @abstractmethod
    def save_audio(
        self,
        result: GenerationResult,
        output_path: Union[str, Path],
        format: str = "wav"
    ) -> Path:
        """
        Save generated audio to file.

        Args:
            result: GenerationResult to save
            output_path: Path to save audio file
            format: Audio format (wav, mp3, flac, etc.)

        Returns:
            Path to saved file
        """
        pass

    @abstractmethod
    def cleanup(self):
        """Clean up model resources (unload from memory)."""
        pass

    def __enter__(self):
        """Context manager entry."""
        if not self._initialized:
            self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()

    def __repr__(self):
        return f"{self.__class__.__name__}(config={self.config})"