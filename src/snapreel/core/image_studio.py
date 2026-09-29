"""Standalone backend logic for Image Studio."""

import structlog
from pathlib import Path
from typing import Any, Optional
from PySide6.QtCore import QObject, QThread, Signal

from snapreel.engines.base import ImageGenerationEngine

logger = structlog.get_logger()


class ImageStudioOrchestrator(QThread):
    """Standalone orchestrator for text-to-image and image-to-image generation.
    
    Bypasses the video pipeline and directly interacts with the ImageGenerationEngine.
    """

    # Emitted when generation starts
    generation_started = Signal()

    # Emitted for progress updates (percent, message)
    generation_progress = Signal(int, str)

    # Emitted when generation finishes successfully (image_path)
    generation_finished = Signal(Path)

    # Emitted when generation fails (error_message)
    generation_failed = Signal(str)

    # Emitted when generation is cancelled
    generation_cancelled = Signal()

    def __init__(
        self,
        engine: ImageGenerationEngine,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        reference_image: Optional[Path | str] = None,
        parent: Optional[QObject] = None,
        **kwargs: Any
    ) -> None:
        """Initialize the Image Studio orchestrator.
        
        Args:
            engine: The image generation engine to use.
            prompt: Positive text prompt.
            negative_prompt: Negative text prompt.
            width: Output width in pixels.
            height: Output height in pixels.
            steps: Number of inference steps.
            reference_image: Optional path to a reference image for image-to-image/IP-Adapter.
            parent: Optional parent QObject.
            kwargs: Additional engine-specific arguments.
        """
        super().__init__(parent)
        self.engine = engine
        self.prompt = prompt
        self.negative_prompt = negative_prompt
        self.width = width
        self.height = height
        self.steps = steps
        self.reference_image = reference_image
        self.kwargs = kwargs
        
        self._is_cancelled = False
        self._log = logger.bind(component="image_studio")

    def cancel(self) -> None:
        """Request cancellation of the image generation."""
        self._is_cancelled = True
        self._log.info("image_generation_cancellation_requested")

    def run(self) -> None:
        """Execute the image generation process in a background thread."""
        self.generation_started.emit()
        self._log.info("image_generation_started", prompt=self.prompt)
        
        try:
            if self._is_cancelled:
                self.generation_cancelled.emit()
                return

            self.generation_progress.emit(10, "Loading model...")
            self.engine.load_model()
            
            if self._is_cancelled:
                self.generation_cancelled.emit()
                return
                
            self.generation_progress.emit(40, "Generating image...")
            
            kwargs = self.kwargs.copy()
            if self.reference_image:
                kwargs["reference_image"] = self.reference_image
                
            out_path = self.engine.generate(
                prompt=self.prompt,
                negative_prompt=self.negative_prompt,
                width=self.width,
                height=self.height,
                steps=self.steps,
                **kwargs
            )
            
            if self._is_cancelled:
                self.generation_cancelled.emit()
                return
                
            self.generation_progress.emit(90, "Unloading model...")
            self.engine.unload_model()
            
            self.generation_progress.emit(100, "Done.")
            self._log.info("image_generation_finished", path=str(out_path))
            self.generation_finished.emit(out_path)
            
        except Exception as exc:
            msg = f"Image generation failed: {exc}"
            self._log.error("image_generation_failed", error=msg)
            self.generation_failed.emit(msg)
