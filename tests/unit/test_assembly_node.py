"""Unit tests for the AssemblyNode."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from snapreel.core.context import PipelineContext, SceneData
from snapreel.core.exceptions import NodeValidationError
from snapreel.nodes.assembly import AssemblyNode


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = PipelineContext(
        work_dir=tmp_path,
        output_dir=tmp_path / "out",
    )
    
    # We don't really create files, just set paths
    scene1_vid = tmp_path / "scene_01.mp4"
    scene2_vid = tmp_path / "scene_02.mp4"
    
    ctx.scenes = [
        SceneData(
            scene_id=1,
            narration="Hello world.",
            visual_prompt="A greeting.",
            duration_hint=2.0,
            video_segment_path=scene1_vid
        ),
        SceneData(
            scene_id=2,
            narration="Goodbye world.",
            visual_prompt="A farewell.",
            duration_hint=2.0,
            video_segment_path=scene2_vid
        ),
    ]
    ctx.narration_audio_path = tmp_path / "narration.wav"
    return ctx


@patch("snapreel.nodes.assembly.FFmpegManager")
def test_validate_no_scenes(mock_ffmpeg_cls):
    ctx = PipelineContext()
    node = AssemblyNode()
    with pytest.raises(NodeValidationError, match="Context has no scenes"):
        node.validate(ctx)


@patch("snapreel.nodes.assembly.FFmpegManager")
def test_validate_missing_video_segment(mock_ffmpeg_cls, mock_ctx):
    mock_ctx.scenes[0].video_segment_path = None
    node = AssemblyNode()
    with pytest.raises(NodeValidationError, match="missing a video segment"):
        node.validate(mock_ctx)


@patch("snapreel.nodes.assembly.FFmpegManager")
def test_validate_missing_narration(mock_ffmpeg_cls, mock_ctx):
    mock_ctx.narration_audio_path = None
    node = AssemblyNode()
    with pytest.raises(NodeValidationError, match="missing narration audio"):
        node.validate(mock_ctx)


@patch("snapreel.nodes.assembly.FFmpegManager")
def test_validate_success(mock_ffmpeg_cls, mock_ctx):
    node = AssemblyNode()
    assert node.validate(mock_ctx) is True


@patch("snapreel.nodes.assembly.FFmpegManager")
def test_assembly_node_execute(mock_ffmpeg_cls, mock_ctx):
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.build_assembly_command.return_value = ["-c", "copy"]
    mock_ffmpeg_cls.return_value = mock_ffmpeg

    node = AssemblyNode()
    # Inject mocked ffmpeg manager
    node.ffmpeg = mock_ffmpeg

    result = node.run(mock_ctx)
    assert result.status.value == "completed"

    assert mock_ffmpeg.build_assembly_command.call_count == 1
    assert mock_ffmpeg.run_command.call_count == 1
    mock_ffmpeg.run_command.assert_called_once_with(["-c", "copy"])

    assert mock_ctx.final_video_path is not None
    assert mock_ctx.final_video_path == mock_ctx.output_dir / "final_video.mp4"
