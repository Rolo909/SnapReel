"""ComfyUI-based generation engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

from snapreel.core.config import AppConfig
from snapreel.engines.base import ImageGenerationEngine, ModelConfig
from snapreel.infra.comfyui_client import ComfyUIClient
from snapreel.infra.hardware import ExecutionProfile

logger = structlog.get_logger()


class ComfyUIEngine(ImageGenerationEngine):
    """Engine for generating images and videos using headless ComfyUI."""

    def __init__(self, profile: ExecutionProfile, model_config: ModelConfig) -> None:
        """Initialize ComfyUI engine."""
        super().__init__(profile, model_config)
        self.app_config = AppConfig()
        
        # Determine extra args based on settings and profile
        self.extra_args: list[str] = []
        # If lowvram is specified in model registry or the hardware profile is constrained
        if self.settings.get("lowvram", False) or self.profile.name in ["low", "medium", "cpu_only"]:
            self.extra_args.append("--lowvram")
            
        # ComfyUI is expected to be installed in the app directory or accessible path
        # Using a relative "ComfyUI" folder in the app_dir as default
        comfyui_dir = self.app_config.app_dir / "ComfyUI"
        self.client = ComfyUIClient(comfyui_dir, extra_args=self.extra_args)

    def load_model(self) -> None:
        """Start the headless ComfyUI server."""
        logger.info("starting_comfyui_server", extra_args=self.extra_args)
        self.client.start()

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        **kwargs: Any
    ) -> Path:
        """Generate an image or video by submitting a ComfyUI workflow.
        
        Args:
            prompt: Positive text prompt.
            negative_prompt: Negative text prompt.
            width: Output width in pixels.
            height: Output height in pixels.
            steps: Number of inference steps.
            kwargs: Additional engine-specific arguments. Must include 'workflow_json'.
            
        Returns:
            Path to the first generated file.
        """
        if not self.client.is_running:
            raise RuntimeError("ComfyUI server is not running. Call load_model() first.")

        workflow_json = kwargs.get("workflow_json")
        if not workflow_json:
            raise ValueError("ComfyUIEngine requires 'workflow_json' in kwargs.")

        if isinstance(workflow_json, (str, Path)):
            with open(workflow_json, "r", encoding="utf-8") as f:
                workflow = json.load(f)
        else:
            workflow = workflow_json

        self._inject_parameters(workflow, prompt, negative_prompt, width, height, steps, kwargs.get("seed"))

        prompt_id = self.client.submit(workflow)
        out_dir = self.app_config.get_output_dir()
        result = self.client.wait_for(prompt_id, out_dir)

        if not result.output_files:
            raise RuntimeError(f"ComfyUI prompt {prompt_id} completed but returned no output files.")

        logger.info("comfyui_generation_complete", files=[str(f) for f in result.output_files])
        return result.output_files[0]

    def _inject_parameters(
        self,
        workflow: dict[str, Any],
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        steps: int,
        seed: int | None
    ) -> None:
        """Inject parameters into the workflow dict based on node class_type."""
        for node_id, node in workflow.items():
            class_type = node.get("class_type")
            inputs = node.get("inputs", {})
            
            # Simple heuristic injection for standard ComfyUI nodes
            if class_type == "CLIPTextEncode":
                title = node.get("_meta", {}).get("title", "").lower()
                if "negative" in title:
                    inputs["text"] = negative_prompt
                elif "positive" in title or "prompt" in title:
                    inputs["text"] = prompt
            
            elif class_type == "EmptyLatentImage":
                if "width" in inputs:
                    inputs["width"] = width
                if "height" in inputs:
                    inputs["height"] = height
                    
            elif class_type == "KSampler":
                if "steps" in inputs:
                    inputs["steps"] = steps
                if seed is not None and "seed" in inputs:
                    inputs["seed"] = seed

    def unload_model(self) -> None:
        """Stop the ComfyUI server."""
        if self.client.is_running:
            logger.info("stopping_comfyui_server")
            self.client.stop()
