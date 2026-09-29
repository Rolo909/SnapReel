"""Diffusers-based image generation engine."""

from __future__ import annotations

import gc
import uuid
from pathlib import Path
from typing import Any

import structlog
import torch
from PIL import Image

from snapreel.core.config import AppConfig
from snapreel.engines.base import ImageGenerationEngine, ModelConfig
from snapreel.infra.hardware import ExecutionProfile

logger = structlog.get_logger()


class DiffusersEngine(ImageGenerationEngine):
    """Engine for generating images using Hugging Face diffusers."""

    def __init__(self, profile: ExecutionProfile, model_config: ModelConfig) -> None:
        """Initialize Diffusers engine."""
        super().__init__(profile, model_config)
        self.pipeline: Any | None = None
        self.app_config = AppConfig()
        self._ip_adapter_loaded = False

    def load_model(self) -> None:
        """Load the model into memory with hardware optimizations."""
        # Using type: ignore because diffusers might not be installed in all environments
        from diffusers import AutoPipelineForText2Image, FluxPipeline  # type: ignore

        logger.info("loading_diffusers_model", model_id=self.model_config.id)
        
        # Determine dtype
        dtype_str = self.profile.diffusion_dtype
        torch_dtype = torch.float16 if dtype_str == "float16" else torch.float32

        # Check quantization settings
        quantization = self.settings.get("quantization", "none")
        kwargs: dict[str, Any] = {"torch_dtype": torch_dtype}
        
        if quantization in ["4-bit", "8-bit"]:
            try:
                from transformers import BitsAndBytesConfig  # type: ignore
                kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=(quantization == "4-bit"),
                    load_in_8bit=(quantization == "8-bit"),
                )
                logger.info("quantization_enabled", bits=quantization)
            except ImportError:
                logger.warning("bitsandbytes_not_installed_ignoring_quantization")

        # Load pipeline (using FluxPipeline for FLUX, otherwise AutoPipeline)
        if "flux" in self.model_config.id.lower():
            self.pipeline = FluxPipeline.from_pretrained(
                self.model_config.id, **kwargs
            )
        else:
            self.pipeline = AutoPipelineForText2Image.from_pretrained(
                self.model_config.id, **kwargs
            )

        # Apply VRAM optimizations
        if self.settings.get("cpu_offload", False):
            logger.info("enabling_model_cpu_offload")
            self.pipeline.enable_model_cpu_offload()
        elif self.profile.diffusion_device == "cuda":
            self.pipeline.to("cuda")

        # Optional xformers optimization
        try:
            import xformers  # noqa: F401
            self.pipeline.enable_xformers_memory_efficient_attention()
            logger.info("xformers_enabled")
        except ImportError:
            pass

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
            kwargs: Additional engine-specific arguments like `seed` and `reference_image`.
            
        Returns:
            Path to the saved image file.
        """
        if not self.pipeline:
            raise RuntimeError("Pipeline is not loaded. Call load_model() first.")

        logger.info("generating_image", prompt=prompt, steps=steps)

        # Handle IP-Adapter reference image if provided
        reference_image = kwargs.pop("reference_image", None)
        if reference_image:
            if not self._ip_adapter_loaded:
                logger.info("loading_ip_adapter_weights")
                try:
                    # Assuming SDXL for IP-Adapter based on typical usage for this project
                    self.pipeline.load_ip_adapter(
                        "h94/IP-Adapter",
                        subfolder="sdxl_models",
                        weight_name="ip-adapter_sdxl.bin"
                    )
                    self.pipeline.set_ip_adapter_scale(0.5)
                    self._ip_adapter_loaded = True
                except Exception as e:
                    logger.warning("failed_to_load_ip_adapter", error=str(e))
            
            if isinstance(reference_image, (str, Path)):
                ref_img = Image.open(reference_image).convert("RGB")
            else:
                ref_img = reference_image
            kwargs["ip_adapter_image"] = ref_img

        # Prepare generator for reproducibility
        generator = None
        seed = kwargs.pop("seed", None)
        if seed is not None:
            device = "cpu" if self.settings.get("cpu_offload", False) else self.profile.diffusion_device
            generator = torch.Generator(device=device).manual_seed(seed)

        # Handle models that don't take negative_prompt (e.g. Flux often doesn't)
        if "flux" in self.model_config.id.lower():
            # FluxPipeline might not accept negative_prompt
            output = self.pipeline(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                generator=generator,
                **kwargs
            )
        else:
            output = self.pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                generator=generator,
                **kwargs
            )
        
        image = output.images[0]

        # Save output
        out_dir = self.app_config.get_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"img_{uuid.uuid4().hex[:8]}.png"
        image.save(out_path)
        logger.info("image_saved", path=str(out_path))

        return out_path

    def unload_model(self) -> None:
        """Unload the model to free VRAM/RAM."""
        if self.pipeline:
            logger.info("unloading_diffusers_model")
            del self.pipeline
            self.pipeline = None
            self._ip_adapter_loaded = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
