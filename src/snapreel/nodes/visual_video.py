"""Visual video generation node (Path B) using ComfyUI."""

import json
from pathlib import Path
from typing import Any

import structlog

from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode
from snapreel.infra.comfyui_client import ComfyUIClient

logger = structlog.get_logger()


class VisualVideoNode(PipelineNode):
    """Generates AI video segments using a headless ComfyUI server.

    Submits workflows (e.g., LTX-Video or Wan 2.1 with Real-ESRGAN upscaling)
    via REST API, polls for completion, and downloads the resulting videos.
    """

    def __init__(self, name: str = "VisualVideoNode", config: AppConfig | None = None) -> None:
        super().__init__(name)
        self.config = config or AppConfig()
        
        # We assume ComfyUI is installed in the app_dir/ComfyUI or via env
        comfy_dir = getattr(self.config, "comfyui_dir", self.config.app_dir / "ComfyUI")
        self.client = ComfyUIClient(comfy_dir)

    def validate(self, ctx: PipelineContext) -> bool:
        if not ctx.scenes:
            raise NodeValidationError(self.name, "Context has no scenes.")
        if ctx.visual_mode != "video":
            raise NodeValidationError(self.name, f"Expected video visual_mode, got {ctx.visual_mode}.")
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.report_progress(0, "Starting ComfyUI server...")
        
        try:
            self.client.start()
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to start ComfyUI: {e}") from e

        total_scenes = len(ctx.scenes)
        
        for i, scene in enumerate(ctx.scenes):
            progress_base = int((i / total_scenes) * 100)
            self.report_progress(progress_base, f"Submitting workflow for scene {scene.scene_id}...")

            work_dir = ctx.scene_work_dir(scene.scene_id)
            workflow = self._build_workflow(scene.visual_prompt)

            try:
                # Submit workflow and wait for completion
                prompt_id = self.client.submit(workflow)
                
                self.report_progress(progress_base + 5, f"Rendering video for scene {scene.scene_id}...")
                
                result = self.client.wait_for(prompt_id, work_dir)
                
                if not result.output_files:
                    raise NodeExecutionError(
                        self.name, 
                        f"ComfyUI generated no output files for scene {scene.scene_id}."
                    )
                
                # We expect the last node in workflow to be a video saver (SaveVideo / SaveAnimatedWEBP)
                # We assign the first generated file as the video segment
                video_file = result.output_files[0]
                scene.video_segment_path = video_file
                
                self._log.info("video_generated", scene_id=scene.scene_id, path=str(video_file))

            except Exception as e:
                raise NodeExecutionError(self.name, f"Failed generating video for scene {scene.scene_id}: {e}") from e

        self.report_progress(100, "Visual video generation complete.")
        return NodeResult(status=NodeStatus.COMPLETED)

    def _build_workflow(self, prompt: str) -> dict[str, Any]:
        """Build a ComfyUI workflow JSON dict for the given prompt.
        
        In a production scenario, this loads a complex JSON exported from ComfyUI
        (with LTX-Video/Wan 2.1 and RealESRGAN nodes) and injects the prompt text.
        """
        # Minimal mock workflow structure for demonstration & testing
        return {
            "3": {
                "inputs": {
                    "text": prompt, 
                    "clip": ["4", 0]
                },
                "class_type": "CLIPTextEncode"
            },
            "10": {
                "inputs": {
                    "model_name": "RealESRGAN_x4plus.pth"
                },
                "class_type": "UpscaleModelLoader"
            },
            "99": {
                "inputs": {
                    "filename_prefix": "scene_video",
                    "fps": self.config.output_fps,
                    "images": ["10", 0] # Upscaled images
                },
                "class_type": "SaveVideo"
            }
        }

    def cleanup(self) -> None:
        """Ensure the ComfyUI server is gracefully terminated."""
        self.client.stop()
