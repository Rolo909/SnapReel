"""Unit tests for VisualVideoNode."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from snapreel.core.context import PipelineContext, SceneData
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.infra.comfyui_client import ComfyUIResult
from snapreel.nodes.visual_video import VisualVideoNode


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = PipelineContext(
        work_dir=tmp_path,
        output_dir=tmp_path / "out",
        visual_mode="video",
    )
    ctx.scenes = [
        SceneData(
            scene_id=1,
            narration="Test 1",
            visual_prompt="Prompt 1",
            duration_hint=2.0,
        ),
        SceneData(
            scene_id=2,
            narration="Test 2",
            visual_prompt="Prompt 2",
            duration_hint=3.0,
        ),
    ]
    return ctx


def test_validate_no_scenes():
    ctx = PipelineContext(visual_mode="video")
    node = VisualVideoNode()
    with pytest.raises(NodeValidationError, match="Context has no scenes"):
        node.validate(ctx)


def test_validate_wrong_mode(mock_ctx):
    mock_ctx.visual_mode = "static"
    node = VisualVideoNode()
    with pytest.raises(NodeValidationError, match="Expected video visual_mode"):
        node.validate(mock_ctx)


@patch("snapreel.nodes.visual_video.ComfyUIClient")
def test_visual_video_execute_success(mock_client_cls, mock_ctx, tmp_path):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    # Mock submit to return fake prompt IDs
    mock_client.submit.side_effect = ["pid_1", "pid_2"]

    # Mock wait_for to return fake result paths
    def mock_wait_for(prompt_id, work_dir):
        fake_video = work_dir / f"scene_{prompt_id}.mp4"
        fake_video.touch()
        return ComfyUIResult(
            prompt_id=prompt_id,
            output_files=[fake_video],
            execution_time_s=10.0,
        )

    mock_client.wait_for.side_effect = mock_wait_for

    node = VisualVideoNode()
    result = node.run(mock_ctx)

    assert result.status.value == "completed"
    assert mock_client.start.call_count == 1
    assert mock_client.submit.call_count == 2
    assert mock_client.wait_for.call_count == 2
    assert mock_client.stop.call_count == 1  # Called in cleanup

    # Verify context is populated
    assert mock_ctx.scenes[0].video_segment_path is not None
    assert mock_ctx.scenes[0].video_segment_path.name == "scene_pid_1.mp4"
    assert mock_ctx.scenes[1].video_segment_path is not None
    assert mock_ctx.scenes[1].video_segment_path.name == "scene_pid_2.mp4"


@patch("snapreel.nodes.visual_video.ComfyUIClient")
def test_visual_video_execute_no_output(mock_client_cls, mock_ctx):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_client.submit.return_value = "pid_1"
    
    # Return empty output files
    mock_client.wait_for.return_value = ComfyUIResult(
        prompt_id="pid_1",
        output_files=[],
    )

    node = VisualVideoNode()
    
    # Since we use node.run(), it intercepts the exception and returns FAILED status
    result = node.run(mock_ctx)
    
    assert result.status.value == "failed"
    assert "no output files" in result.message
    
    # Cleanup should still run
    assert mock_client.stop.call_count == 1
