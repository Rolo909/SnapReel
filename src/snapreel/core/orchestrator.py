"""Pipeline orchestrator for executing nodes sequentially."""

import structlog
from PySide6.QtCore import QObject, QThread, Signal

from snapreel.core.context import PipelineContext
from snapreel.core.node_base import NodeStatus, PipelineNode

logger = structlog.get_logger()


class PipelineOrchestrator(QThread):
    """Orchestrates the sequential execution of pipeline nodes in a background thread."""

    # Emitted when the overall pipeline starts
    pipeline_started = Signal()

    # Emitted when the pipeline finishes successfully, providing the final context
    pipeline_finished = Signal(PipelineContext)

    # Emitted when the pipeline fails, providing an error message
    pipeline_failed = Signal(str)

    # Emitted when the pipeline is cancelled
    pipeline_cancelled = Signal()

    # Emitted when a node starts: (node_index, node_name)
    node_started = Signal(int, str)

    # Emitted when a node updates its progress: (node_index, percent, message)
    node_progress = Signal(int, int, str)

    # Emitted when a node finishes: (node_index, node_name, result)
    node_finished = Signal(int, str, object)  # using object for NodeResult to avoid type issue

    def __init__(
        self,
        context: PipelineContext,
        nodes: list[PipelineNode],
        parent: QObject | None = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            context: The shared pipeline context.
            nodes: The list of nodes to execute in order.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self.context = context
        self.nodes = nodes
        self._is_cancelled = False
        self._log = logger.bind(component="orchestrator")

    def cancel(self) -> None:
        """Request cancellation of the pipeline execution.

        The orchestrator will stop before executing the next node.
        """
        self._is_cancelled = True
        self._log.info("orchestrator_cancellation_requested")

    def run(self) -> None:
        """Execute the pipeline nodes sequentially."""
        self.pipeline_started.emit()
        self._log.info("pipeline_started", total_nodes=len(self.nodes))

        try:
            self.context.ensure_dirs()
        except Exception as exc:
            msg = f"Failed to ensure working directories: {exc}"
            self._log.error("pipeline_failed", error=msg)
            self.pipeline_failed.emit(msg)
            return

        for index, node in enumerate(self.nodes):
            if self._is_cancelled:
                self._log.info("pipeline_cancelled")
                self.pipeline_cancelled.emit()
                return

            self.node_started.emit(index, node.name)

            # Factory function to capture index in the callback closure
            def make_progress_callback(node_idx: int) -> callable:
                def progress_callback(percent: int, message: str) -> None:
                    self.node_progress.emit(node_idx, percent, message)
                return progress_callback

            node.set_progress_callback(make_progress_callback(index))

            # Run the node (validate -> execute -> cleanup)
            result = node.run(self.context)

            self.node_finished.emit(index, node.name, result)

            if result.status == NodeStatus.FAILED:
                msg = f"Node '{node.name}' failed: {result.message}"
                self._log.error("pipeline_failed", node=node.name, error=result.message)
                self.pipeline_failed.emit(msg)
                return

        if self._is_cancelled:
            self._log.info("pipeline_cancelled")
            self.pipeline_cancelled.emit()
        else:
            self._log.info("pipeline_finished")
            self.pipeline_finished.emit(self.context)
