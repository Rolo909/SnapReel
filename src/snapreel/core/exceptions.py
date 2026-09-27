"""Domain-specific exceptions for SnapReel."""

from __future__ import annotations


class SnapReelError(Exception):
    """Base exception for all SnapReel errors."""


class NodeExecutionError(SnapReelError):
    """Raised when a pipeline node fails during execution."""

    def __init__(
        self, node_name: str, message: str, cause: Exception | None = None
    ) -> None:
        self.node_name = node_name
        self.cause = cause
        super().__init__(f"[{node_name}] {message}")


class NodeValidationError(SnapReelError):
    """Raised when a pipeline node fails validation before execution."""

    def __init__(self, node_name: str, message: str) -> None:
        self.node_name = node_name
        super().__init__(f"[{node_name}] Validation failed: {message}")


class ModelNotFoundError(SnapReelError):
    """Raised when a required ML model is not found locally."""

    def __init__(self, model_name: str, expected_path: str) -> None:
        self.model_name = model_name
        self.expected_path = expected_path
        super().__init__(f"Model '{model_name}' not found at: {expected_path}")


class FFmpegError(SnapReelError):
    """Raised when an FFmpeg command fails."""

    def __init__(self, command: str, stderr: str, returncode: int) -> None:
        self.command = command
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"FFmpeg exited with code {returncode}: {stderr[:500]}")


class HardwareDetectionError(SnapReelError):
    """Raised when hardware profiling fails."""


class DownloadError(SnapReelError):
    """Raised when a model download fails."""

    def __init__(self, model_name: str, message: str) -> None:
        self.model_name = model_name
        super().__init__(f"Failed to download '{model_name}': {message}")


class PipelineCancelledError(SnapReelError):
    """Raised when the user cancels pipeline execution."""


class ComfyUIError(SnapReelError):
    """Raised when ComfyUI headless server interaction fails."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(f"ComfyUI error: {message}")
