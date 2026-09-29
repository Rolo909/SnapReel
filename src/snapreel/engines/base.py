"""Base classes and model registry for generation engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from snapreel.infra.hardware import ExecutionProfile


@dataclass
class ModelConfig:
    """Configuration for a specific model."""

    id: str
    name: str
    engine: str
    type: str
    profiles: dict[str, dict[str, Any]]

    def get_profile_settings(self, profile_name: str) -> dict[str, Any]:
        """Get the specific settings for a given execution profile.
        
        Args:
            profile_name: The name of the profile (e.g., 'high', 'medium').
            
        Returns:
            A dictionary containing the profile-specific settings.
        """
        return self.profiles.get(profile_name, {})


class ModelRegistry:
    """Registry for loading and querying model configurations."""

    def __init__(self, registry_path: Path | str = "models_registry.yaml") -> None:
        """Initialize the model registry.
        
        Args:
            registry_path: Path to the YAML registry file.
        """
        self.registry_path = Path(registry_path)
        self.models: dict[str, ModelConfig] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if not self.registry_path.exists():
            return
            
        with open(self.registry_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        if not data or "models" not in data:
            return
            
        for model_data in data["models"]:
            config = ModelConfig(
                id=model_data["id"],
                name=model_data.get("name", model_data["id"]),
                engine=model_data["engine"],
                type=model_data.get("type", "image"),
                profiles=model_data.get("profiles", {}),
            )
            self.models[config.id] = config

    def get_model(self, model_id: str) -> ModelConfig | None:
        """Get a model's configuration by ID."""
        return self.models.get(model_id)
        
    def list_models(self, engine: str | None = None, model_type: str | None = None) -> list[ModelConfig]:
        """List all models, optionally filtered by engine and type."""
        result = list(self.models.values())
        if engine:
            result = [m for m in result if m.engine == engine]
        if model_type:
            result = [m for m in result if m.type == model_type]
        return result


class ImageGenerationEngine(ABC):
    """Abstract base class for all image generation engines."""

    def __init__(self, profile: ExecutionProfile, model_config: ModelConfig) -> None:
        """Initialize the engine.
        
        Args:
            profile: Hardware execution profile (high, medium, etc.)
            model_config: Specific model configuration from registry
        """
        self.profile = profile
        self.model_config = model_config
        self.settings = model_config.get_profile_settings(profile.name)
        
    @abstractmethod
    def load_model(self) -> None:
        """Load the model into memory. Implementations should apply hardware optimizations here."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        **kwargs: Any
    ) -> Path:
        """Generate an image based on the prompt.
        
        Args:
            prompt: Positive text prompt.
            negative_prompt: Negative text prompt.
            width: Output width in pixels.
            height: Output height in pixels.
            steps: Number of inference steps.
            kwargs: Engine-specific additional arguments.
            
        Returns:
            Path to the saved image file.
        """
        pass
        
    @abstractmethod
    def unload_model(self) -> None:
        """Unload the model to free VRAM/RAM."""
        pass
