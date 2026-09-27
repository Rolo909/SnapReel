"""Unit tests for SubtitleNode."""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeValidationError
from snapreel.nodes.subtitle import SubtitleNode, format_ass_time


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = PipelineContext(
        work_dir=tmp_path,
        language="en",
    )
    
    # Create a dummy audio file
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    dummy_audio = audio_dir / "narration.wav"
    dummy_audio.touch()
    
    ctx.narration_audio_path = dummy_audio
    return ctx


def test_format_ass_time():
    assert format_ass_time(0.0) == "0:00:00.00"
    assert format_ass_time(1.234) == "0:00:01.23"
    assert format_ass_time(61.5) == "0:01:01.50"
    assert format_ass_time(3605.99) == "1:00:05.99"


def test_validate_no_audio():
    ctx = PipelineContext()
    node = SubtitleNode()
    with patch("snapreel.nodes.subtitle.WhisperModel", MagicMock()):
        with pytest.raises(NodeValidationError, match="Context missing narration_audio_path"):
            node.validate(ctx)


@patch("snapreel.nodes.subtitle.WhisperModel")
def test_subtitle_execute_success(mock_whisper_cls, mock_ctx):
    # Setup Whisper mock
    mock_model = MagicMock()
    mock_whisper_cls.return_value = mock_model
    
    # Create fake segments
    class FakeWord:
        def __init__(self, start, end, word):
            self.start = start
            self.end = end
            self.word = word
            
    class FakeSegment:
        def __init__(self, start, end, words):
            self.start = start
            self.end = end
            self.words = words
            
    fake_segments = [
        FakeSegment(
            start=0.0,
            end=2.0,
            words=[
                FakeWord(0.5, 1.0, "Hello"),
                FakeWord(1.2, 1.8, " world")
            ]
        )
    ]
    
    # transcribe returns (generator, info)
    mock_model.transcribe.return_value = (iter(fake_segments), {"language": "en"})
    
    node = SubtitleNode()
    result = node.run(mock_ctx)
    
    assert result.status.value == "completed"
    assert mock_whisper_cls.call_count == 1
    assert mock_model.transcribe.call_count == 1
    
    # Verify .ass file generation
    assert mock_ctx.subtitle_path is not None
    assert mock_ctx.subtitle_path.exists()
    
    content = mock_ctx.subtitle_path.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "[Events]" in content
    
    # Check the dialogue line
    # Word 1: start 0.5, gap 0.5 (50cs), dur 0.5 (50cs)
    # Word 2: start 1.2, prev end 1.0 -> gap 0.2 (20cs), dur 0.6 (60cs)
    # Expected text: {\k50}{\K50}Hello {\k20}{\K60}world
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,{\\k50}{\\K50}Hello {\\k20}{\\K60}world" in content
