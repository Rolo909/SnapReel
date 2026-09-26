"""Application configuration using pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Global application configuration.

    Settings are loaded from environment variables prefixed with SNAPREEL_
    and from a .env file if present. All paths are resolved relative to
    app_dir unless absolute.
    """

    model_config = SettingsConfigDict(
        env_prefix="SNAPREEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths ---
    app_dir: Path = Field(default_factory=lambda: Path(".").resolve())
    models_dir: Path = Field(default=Path("models"))
    output_dir: Path = Field(default=Path("output"))
    ffmpeg_path: Path = Field(default=Path("ffmpeg"))

    # --- Hardware Profile ---
    execution_profile: Literal["auto", "high", "medium", "low", "cpu_only"] = "auto"
    llm_threads: int = Field(default=4, ge=1, le=32)

    # --- LLM ---
    llm_model: str = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
    llm_context_size: int = Field(default=4096, ge=512, le=32768)

    # --- TTS ---
    tts_voice: str = "ru-RU-DmitryNeural"
    tts_rate: str = "+0%"

    # --- Visual ---
    visual_mode: Literal["static", "video"] = "static"
    diffusion_model: str = "stabilityai/sdxl-turbo"
    diffusion_steps: int = Field(default=4, ge=1, le=50)

    # --- Whisper ---
    whisper_model_size: str = "large-v3"
    whisper_compute_type: str = "int8"

    # --- Output ---
    output_resolution: str = "1080x1920"
    output_fps: int = Field(default=30, ge=24, le=60)
    output_crf: int = Field(default=18, ge=0, le=51)

    # --- UI ---
    language: Literal["ru", "en"] = "ru"
    theme: Literal["dark", "light"] = "dark"

    def get_models_dir(self) -> Path:
        """Get the absolute path to the models directory.

        Returns:
            Resolved models directory path.
        """
        if self.models_dir.is_absolute():
            return self.models_dir
        return self.app_dir / self.models_dir

    def get_output_dir(self) -> Path:
        """Get the absolute path to the output directory.

        Returns:
            Resolved output directory path.
        """
        if self.output_dir.is_absolute():
            return self.output_dir
        return self.app_dir / self.output_dir
