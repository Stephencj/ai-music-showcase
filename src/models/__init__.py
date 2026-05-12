"""
AI Model implementations for music generation.

This module provides interfaces and implementations for various AI music generation models.
"""

from .base import BaseModel, ModelConfig, GenerationResult
from .musicgen import MusicGenModel

# Model registry
_MODEL_REGISTRY = {
    "musicgen": MusicGenModel,
}

def register_model(name: str, model_class):
    """Register a model class in the registry."""
    _MODEL_REGISTRY[name] = model_class

def get_model(name: str, **kwargs):
    """Get a model instance by name."""
    if name not in _MODEL_REGISTRY:
        raise ValueError(f"Model '{name}' not found. Available models: {list(_MODEL_REGISTRY.keys())}")
    return _MODEL_REGISTRY[name](**kwargs)

def list_models():
    """List all registered models."""
    return list(_MODEL_REGISTRY.keys())

__all__ = [
    "BaseModel",
    "ModelConfig",
    "GenerationResult",
    "MusicGenModel",
    "register_model",
    "get_model",
    "list_models",
]