"""
MusicGen model wrapper for text-to-music generation.

Uses Meta's MusicGen via HuggingFace transformers.
Supports small (~300M), medium (~1.5B), and large (~3.3B) model sizes.
"""

import gc
import logging
from pathlib import Path
from typing import Optional, Union

import numpy as np
import soundfile as sf
import torch

from ..base import BaseModel, GenerationResult, ModelConfig

logger = logging.getLogger(__name__)

# MusicGen generates at 32kHz
MUSICGEN_SAMPLE_RATE = 32000

MODEL_SIZES = {
    "small": "facebook/musicgen-small",
    "medium": "facebook/musicgen-medium",
    "large": "facebook/musicgen-large",
}


class MusicGenModel(BaseModel):
    """MusicGen text-to-music generation model."""

    def __init__(self, config: Optional[ModelConfig] = None):
        super().__init__(config)
        self._model = None
        self._processor = None

    def get_default_config(self) -> ModelConfig:
        return ModelConfig(
            name="musicgen",
            model_size="small",
            duration=10.0,
            temperature=1.0,
            top_p=0.9,
            device="mps" if torch.backends.mps.is_available() else "cpu",
        )

    @property
    def model_id(self) -> str:
        size = self.config.model_size
        if size not in MODEL_SIZES:
            raise ValueError(f"Unknown model size '{size}'. Choose from: {list(MODEL_SIZES.keys())}")
        return MODEL_SIZES[size]

    def initialize(self):
        """Load model and processor from HuggingFace."""
        if self._initialized:
            return

        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        logger.info(f"Loading MusicGen ({self.config.model_size}) from {self.model_id}...")
        print(f"Loading MusicGen ({self.config.model_size})... this may take a moment on first run.")

        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = MusicgenForConditionalGeneration.from_pretrained(self.model_id)

        # Auto-detect best available device
        device = self.config.device
        if device == "cuda" and not torch.cuda.is_available():
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"

        # MPS support for MusicGen can be flaky — fall back gracefully
        if device == "mps":
            try:
                self._model = self._model.to("mps")
            except Exception:
                logger.warning("MPS transfer failed, falling back to CPU")
                device = "cpu"
                self._model = self._model.to("cpu")
        else:
            self._model = self._model.to(device)

        self.config.device = device
        self._initialized = True
        print(f"MusicGen ready on {device}")

    def generate(
        self,
        prompt: str,
        duration: Optional[float] = None,
        **kwargs,
    ) -> GenerationResult:
        """
        Generate music from a text prompt.

        Args:
            prompt: Text description of desired music
                    (e.g. "upbeat electronic dance music with a catchy melody")
            duration: Duration in seconds (default from config, max ~30s for small model)
            **kwargs: Extra args forwarded to model.generate()

        Returns:
            GenerationResult with audio at 32 kHz
        """
        if not self._initialized:
            self.initialize()

        duration = duration or self.config.duration

        # MusicGen generates ~50 tokens/sec of audio (1500 tokens ≈ 30s)
        max_new_tokens = int(duration * 50)

        inputs = self._processor(
            text=[prompt],
            padding=True,
            return_tensors="pt",
        )
        # Move inputs to same device as model
        inputs = {k: v.to(self.config.device) if isinstance(v, torch.Tensor) else v
                  for k, v in inputs.items()}

        gen_kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": True,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "top_p": kwargs.get("top_p", self.config.top_p),
        }
        if self.config.seed is not None:
            torch.manual_seed(self.config.seed)

        logger.info(f"Generating {duration:.1f}s of audio for: {prompt[:80]}")
        print(f"Generating ~{duration:.0f}s of audio...")

        with torch.inference_mode():
            audio_values = self._model.generate(**inputs, **gen_kwargs)

        # audio_values shape: (batch, channels, samples) or (batch, samples)
        audio_np = audio_values[0].detach().cpu().numpy()
        if audio_np.ndim == 1:
            audio_np = audio_np[np.newaxis, :]  # (1, samples)

        del audio_values, inputs
        if self.config.device == "mps" and hasattr(torch, "mps"):
            torch.mps.empty_cache()
        elif self.config.device == "cuda":
            torch.cuda.empty_cache()
        gc.collect()

        actual_duration = audio_np.shape[-1] / MUSICGEN_SAMPLE_RATE

        return GenerationResult(
            audio=audio_np,
            sample_rate=MUSICGEN_SAMPLE_RATE,
            duration=actual_duration,
            model_name=f"musicgen-{self.config.model_size}",
            config=self.config,
            metadata={"prompt": prompt, "max_new_tokens": max_new_tokens},
        )

    def save_audio(
        self,
        result: GenerationResult,
        output_path: Union[str, Path],
        format: str = "wav",
    ) -> Path:
        """Save generated audio to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # soundfile expects (samples, channels)
        audio = result.audio
        if audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
            audio = audio.T

        sf.write(str(output_path), audio, result.sample_rate, format=format)
        logger.info(f"Saved audio to {output_path}")
        print(f"Saved: {output_path} ({result.duration:.1f}s)")
        return output_path

    def cleanup(self):
        """Unload model from memory."""
        if self._model is not None:
            device = self.config.device
            del self._model
            del self._processor
            self._model = None
            self._processor = None
            self._initialized = False
            gc.collect()
            if device == "mps" and hasattr(torch, "mps"):
                torch.mps.empty_cache()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("MusicGen model unloaded")
