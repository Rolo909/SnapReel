"""Unit tests for the PipelineOrchestrator."""

import pytest
from PySide6.QtCore import QCoreApplication

from snapreel.core.context import PipelineContext
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode
from snapreel.core.orchestrator import PipelineOrchestrator


class DummyNode(PipelineNode):
    def __init__(self, name: str, should_fail: bool = False, fail_message: str = ""):
        super().__init__(name)
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.executed = False
        self.cleaned_up = False

    def validate(self, ctx: PipelineContext) -> bool:
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.executed = True
        self.report_progress(50, "Halfway there")
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        return NodeResult(status=NodeStatus.COMPLETED, message="Success")

    def cleanup(self) -> None:
        self.cleaned_up = True


@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


def test_orchestrator_successful_run(qapp, tmp_path):
    ctx = PipelineContext(work_dir=tmp_path / "work", output_dir=tmp_path / "out")
    node1 = DummyNode("node1")
    node2 = DummyNode("node2")
    
    orchestrator = PipelineOrchestrator(context=ctx, nodes=[node1, node2])
    
    signals_emitted = []
    
    orchestrator.pipeline_started.connect(lambda: signals_emitted.append("started"))
    orchestrator.pipeline_finished.connect(lambda c: signals_emitted.append("finished"))
    orchestrator.node_started.connect(lambda i, n: signals_emitted.append(f"node_started_{n}"))
    orchestrator.node_progress.connect(lambda i, p, m: signals_emitted.append(f"progress_{p}"))
    orchestrator.node_finished.connect(lambda i, n, r: signals_emitted.append(f"node_finished_{n}"))
    
    orchestrator.run()
    
    assert "started" in signals_emitted
    assert "node_started_node1" in signals_emitted
    assert "progress_50" in signals_emitted
    assert "node_finished_node1" in signals_emitted
    assert "node_started_node2" in signals_emitted
    assert "node_finished_node2" in signals_emitted
    assert "finished" in signals_emitted
    
    assert node1.executed
    assert node1.cleaned_up
    assert node2.executed
    assert node2.cleaned_up
    assert ctx.work_dir.exists()


def test_orchestrator_failure(qapp, tmp_path):
    ctx = PipelineContext(work_dir=tmp_path / "work", output_dir=tmp_path / "out")
    node1 = DummyNode("node1", should_fail=True, fail_message="Test failure")
    node2 = DummyNode("node2")
    
    orchestrator = PipelineOrchestrator(context=ctx, nodes=[node1, node2])
    
    signals_emitted = []
    
    orchestrator.pipeline_failed.connect(lambda m: signals_emitted.append(f"failed: {m}"))
    orchestrator.pipeline_finished.connect(lambda c: signals_emitted.append("finished"))
    
    orchestrator.run()
    
    assert any("failed: Node 'node1' failed: Test failure" in s for s in signals_emitted)
    assert "finished" not in signals_emitted
    
    assert node1.executed
    assert node1.cleaned_up
    assert not node2.executed


def test_orchestrator_cancellation(qapp, tmp_path):
    ctx = PipelineContext(work_dir=tmp_path / "work", output_dir=tmp_path / "out")
    node1 = DummyNode("node1")
    node2 = DummyNode("node2")
    
    orchestrator = PipelineOrchestrator(context=ctx, nodes=[node1, node2])
    
    signals_emitted = []
    orchestrator.pipeline_cancelled.connect(lambda: signals_emitted.append("cancelled"))
    orchestrator.node_finished.connect(lambda i, n, r: orchestrator.cancel())  # Cancel after first node
    
    orchestrator.run()
    
    assert "cancelled" in signals_emitted
    assert node1.executed
    assert not node2.executed
