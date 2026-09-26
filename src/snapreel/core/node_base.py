"""Abstract base class for pipeline nodes."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

import structlog

if TYPE_CHECKING:
    from snapreel.core.context import PipelineContext

logger = structlog.get_logger()


class NodeStatus(Enum):
    """Status of a pipeline node."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeResult:
    """Result returned by a pipeline node after execution."""

    status: NodeStatus
    message: str = ""
    elapsed_seconds: float = 0.0


# Type alias for progress callback: (percent: int, message: str) -> None
ProgressCallback = Callable[[int, str], None]


def _noop_progress(_percent: int, _message: str) -> None:
    """Default no-op progress callback."""


class PipelineNode(ABC):
    """Abstract base class for all pipeline nodes.

    Each node in the content generation pipeline must inherit from this class
    and implement validate(), execute(), and cleanup().

    The run() method orchestrates the full lifecycle:
    validate → execute → cleanup (always called, even on failure).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = NodeStatus.PENDING
        self._progress_callback: ProgressCallback = _noop_progress
        self._log = logger.bind(node=name)

    def set_progress_callback(self, callback: ProgressCallback) -> None:
        """Set the progress callback for this node.

        Args:
            callback: Callable receiving (percent, message) updates.
        """
        self._progress_callback = callback

    def report_progress(self, percent: int, message: str) -> None:
        """Report progress to the registered callback.

        Args:
            percent: Completion percentage (0-100).
            message: Human-readable status message.
        """
        self._progress_callback(percent, message)

    @abstractmethod
    def validate(self, ctx: PipelineContext) -> bool:
        """Validate that all prerequisites are met before execution.

        Args:
            ctx: The pipeline context.

        Returns:
            True if validation passes.

        Raises:
            NodeValidationError: If validation fails.
        """
        ...

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> NodeResult:
        """Execute the node's main logic.

        Args:
            ctx: The pipeline context to read from and write to.

        Returns:
            NodeResult with status and timing information.

        Raises:
            NodeExecutionError: If execution fails.
        """
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """Release all resources (models, file handles, GPU memory).

        This method is ALWAYS called after execute(), even on failure.
        Implementations must not raise exceptions.
        """
        ...

    def run(self, ctx: PipelineContext) -> NodeResult:
        """Run the full node lifecycle: validate → execute → cleanup.

        Args:
            ctx: The pipeline context.

        Returns:
            NodeResult with final status and elapsed time.
        """
        self._log.info("node_start")
        self.status = NodeStatus.RUNNING
        start = time.perf_counter()

        try:
            self.validate(ctx)
            result = self.execute(ctx)
            result.elapsed_seconds = time.perf_counter() - start
            self.status = result.status
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - start
            self.status = NodeStatus.FAILED
            self._log.error("node_failed", error=str(exc), elapsed=f"{elapsed:.2f}s")
            return NodeResult(
                status=NodeStatus.FAILED,
                message=str(exc),
                elapsed_seconds=elapsed,
            )
        finally:
            elapsed_final = time.perf_counter() - start
            self._log.info(
                "node_end", elapsed=f"{elapsed_final:.2f}s", status=self.status.value
            )
            self.cleanup()
