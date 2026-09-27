"""Unit tests for the AudioNode."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from snapreel.core.context import PipelineContext, SceneData
from snapreel.core.exceptions import NodeValidationError
from snapreel.nodes.audio_tts import AudioNode

@pytest.fixture
def mock_ctx(tmp_path):
    ctx = PipelineContext(
        work_dir=tmp_path,
        output_dir=tmp_path / "out",
        voice="ru-RU-DmitryNeural",
    )
    ctx.scenes = [
        SceneData(
            scene_id=1,
            narration="Hello world.",
            visual_prompt="A greeting.",
            duration_hint=2.0,
        ),
        SceneData(
            scene_id=2,
            narration="Goodbye world.",
            visual_prompt="A farewell.",
            duration_hint=2.0,
        ),
    ]
    return ctx

def test_validate_no_scenes():
    ctx = PipelineContext(voice="ru-RU-DmitryNeural")
    node = AudioNode()
    with pytest.raises(NodeValidationError, match="Context has no scenes"):
        node.validate(ctx)

def test_validate_no_voice(mock_ctx):
    mock_ctx.voice = ""
    node = AudioNode()
    with pytest.raises(NodeValidationError, match="Context has no voice"):
        node.validate(mock_ctx)

def test_validate_success(mock_ctx):
    node = AudioNode()
    assert node.validate(mock_ctx) is True

@patch("snapreel.nodes.audio_tts.FFmpegManager")
@patch("snapreel.nodes.audio_tts.edge_tts.Communicate")
def test_audio_node_execute(mock_communicate_cls, mock_ffmpeg_cls, mock_ctx):
    mock_communicate = MagicMock()
    mock_communicate.save = AsyncMock()
    mock_communicate_cls.return_value = mock_communicate

    mock_ffmpeg = MagicMock()
    mock_ffmpeg.run_command = MagicMock()
    mock_ffmpeg_cls.return_value = mock_ffmpeg

    node = AudioNode()
    # Inject mocked ffmpeg manager
    node.ffmpeg = mock_ffmpeg

    result = node.run(mock_ctx)
    assert result.status.value == "completed"

    assert mock_communicate_cls.call_count == 2
    assert mock_communicate.save.call_count == 2

    assert mock_ffmpeg.run_command.call_count == 3

    # Verify that paths were updated in the context
    assert mock_ctx.narration_audio_path is not None
    assert mock_ctx.narration_audio_path.name == "narration.wav"
    assert mock_ctx.scenes[0].audio_path is not None
    assert mock_ctx.scenes[0].audio_path.name == "narration.wav"
    assert mock_ctx.scenes[1].audio_path is not None
    assert mock_ctx.scenes[1].audio_path.name == "narration.wav"
