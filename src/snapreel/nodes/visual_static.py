"""Visual static generation node (Path A)."""

from pathlib import Path
from typing import Any

import structlog
from PIL import Image

from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode
from snapreel.infra.ffmpeg import FFmpegManager

try:
    import torch
    from diffusers import AutoPipelineForText2Image
except ImportError:
    torch = None
    AutoPipelineForText2Image = None

logger = structlog.get_logger()


class VisualStaticNode(PipelineNode):
    """Generates images using diffusers and creates Ken Burns video segments.

    - Uses SDXL-Turbo (or configured diffusion model).
    - Crops generated images to 9:16.
    - Uses FFmpeg to apply a Ken Burns pan/zoom effect for scene duration.
    """

    def __init__(self, name: str = "VisualStaticNode", config: AppConfig | None = None) -> None:
        super().__init__(name)
        self.config = config or AppConfig()
        self.ffmpeg = FFmpegManager(self.config.ffmpeg_path)
        self.pipeline: Any = None

    def validate(self, ctx: PipelineContext) -> bool:
        if not ctx.scenes:
            raise NodeValidationError(self.name, "Context has no scenes.")
        if ctx.visual_mode != "static":
            raise NodeValidationError(self.name, f"Expected static visual_mode, got {ctx.visual_mode}.")
        if AutoPipelineForText2Image is None:
            raise NodeValidationError(self.name, "diffusers or torch is not installed.")
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.report_progress(0, "Loading diffusion model...")

        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32

            # Use local cache/models dir if possible, otherwise rely on HF hub
            model_id = self.config.diffusion_model
            self.pipeline = AutoPipelineForText2Image.from_pretrained(
                model_id,
                torch_dtype=dtype,
                variant="fp16" if device == "cuda" else None
            ).to(device)
            
            # SDXL-Turbo specific optimization
            if "turbo" in model_id.lower() and hasattr(self.pipeline, "set_progress_bar_config"):
                self.pipeline.set_progress_bar_config(disable=True)
                
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to load diffusion model: {e}") from e

        total_scenes = len(ctx.scenes)
        target_w, target_h = self._parse_resolution(self.config.output_resolution)

        for i, scene in enumerate(ctx.scenes):
            progress_base = int((i / total_scenes) * 100)
            self.report_progress(progress_base, f"Generating image for scene {scene.scene_id}...")

            work_dir = ctx.scene_work_dir(scene.scene_id)
            image_path = work_dir / "image.png"
            video_path = work_dir / "segment.mp4"

            try:
                # 1. Generate Image
                result = self.pipeline(
                    prompt=scene.visual_prompt,
                    num_inference_steps=self.config.diffusion_steps,
                    guidance_scale=0.0, # SDXL-Turbo uses 0.0 guidance
                    width=512, # Turbo optimal base resolution
                    height=512
                )
                image = result.images[0]

                # 2. Crop to 9:16 aspect ratio
                cropped_img = self._crop_to_aspect_ratio(image, 9, 16)
                cropped_img.save(image_path)
                scene.image_path = image_path

                # 3. Generate Video Segment (Ken Burns)
                self.report_progress(progress_base + 5, f"Creating video segment for scene {scene.scene_id}...")
                
                # Use audio duration if available, else fallback to duration_hint
                duration = scene.duration_hint
                if scene.audio_path and scene.audio_path.exists():
                    # Probe actual audio duration if FFprobe was available, 
                    # but here we rely on the hint as an approximation, or Ken Burns 
                    # will generate for the duration hint and assembly will shortest-match.
                    pass 

                cmd_args = self.ffmpeg.build_ken_burns_command(
                    image_path=image_path,
                    output_path=video_path,
                    duration=duration,
                    width=target_w,
                    height=target_h,
                    fps=self.config.output_fps
                )
                self.ffmpeg.run_command(cmd_args, capture=True, check=True)
                
                scene.video_segment_path = video_path

            except Exception as e:
                raise NodeExecutionError(self.name, f"Failed processing scene {scene.scene_id}: {e}") from e

        self.report_progress(100, "Visual static generation complete.")
        return NodeResult(status=NodeStatus.COMPLETED)

    def _parse_resolution(self, res_str: str) -> tuple[int, int]:
        try:
            w, h = map(int, res_str.split("x"))
            return w, h
        except ValueError:
            return 1080, 1920

    def _crop_to_aspect_ratio(self, image: Image.Image, aspect_w: int, aspect_h: int) -> Image.Image:
        """Center crop an image to the target aspect ratio."""
        target_ratio = aspect_w / aspect_h
        img_w, img_h = image.size
        img_ratio = img_w / img_h

        if img_ratio > target_ratio:
            # Image is wider than target ratio - crop width
            new_w = int(img_h * target_ratio)
            left = (img_w - new_w) // 2
            return image.crop((left, 0, left + new_w, img_h))
        elif img_ratio < target_ratio:
            # Image is taller than target ratio - crop height
            new_h = int(img_w / target_ratio)
            top = (img_h - new_h) // 2
            return image.crop((0, top, img_w, top + new_h))
        
        return image

    def cleanup(self) -> None:
        if self.pipeline:
            del self.pipeline
            self.pipeline = None
            if torch and torch.cuda.is_available():
                torch.cuda.empty_cache()
