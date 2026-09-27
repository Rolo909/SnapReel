"""Unit tests for VisualStaticNode."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext, SceneData
from snapreel.core.exceptions import NodeValidationError
from snapreel.nodes.visual_static import VisualStaticNode


@pytest.fixture
def mock_ctx(tmp_path):
    ctx = PipelineContext(
        work_dir=tmp_path,
        output_dir=tmp_path / "out",
        visual_mode="static",
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
    ctx = PipelineContext(visual_mode="static")
    node = VisualStaticNode()
    with patch("snapreel.nodes.visual_static.AutoPipelineForText2Image", MagicMock()):
        with pytest.raises(NodeValidationError, match="Context has no scenes"):
            node.validate(ctx)


def test_validate_wrong_mode(mock_ctx):
    mock_ctx.visual_mode = "video"
    node = VisualStaticNode()
    with patch("snapreel.nodes.visual_static.AutoPipelineForText2Image", MagicMock()):
        with pytest.raises(NodeValidationError, match="Expected static visual_mode"):
            node.validate(mock_ctx)


@patch("snapreel.nodes.visual_static.FFmpegManager")
@patch("snapreel.nodes.visual_static.AutoPipelineForText2Image")
@patch("snapreel.nodes.visual_static.torch")
def test_visual_static_execute(mock_torch, mock_pipeline_cls, mock_ffmpeg_cls, mock_ctx):
    # Setup mocks
    mock_torch.cuda.is_available.return_value = False
    mock_torch.float32 = "float32"

    mock_pipeline_instance = MagicMock()
    mock_pipeline_instance.to.return_value = mock_pipeline_instance
    mock_pipeline_cls.from_pretrained.return_value = mock_pipeline_instance

    # Mock image generation result
    mock_image = Image.new("RGB", (512, 512), color="red")
    mock_result = MagicMock()
    mock_result.images = [mock_image]
    mock_pipeline_instance.return_value = mock_result

    mock_ffmpeg_instance = MagicMock()
    mock_ffmpeg_instance.build_ken_burns_command.return_value = ["ffmpeg", "args"]
    mock_ffmpeg_instance.run_command.return_value = None
    mock_ffmpeg_cls.return_value = mock_ffmpeg_instance

    config = AppConfig(diffusion_model="stabilityai/sdxl-turbo", diffusion_steps=1)
    node = VisualStaticNode(config=config)
    node.ffmpeg = mock_ffmpeg_instance

    result = node.run(mock_ctx)

    assert result.status.value == "completed"
    
    assert mock_pipeline_cls.from_pretrained.call_count == 1
    assert mock_pipeline_instance.call_count == 2  # 2 scenes

    # Verify context updates
    assert mock_ctx.scenes[0].image_path is not None
    assert mock_ctx.scenes[0].image_path.name == "image.png"
    assert mock_ctx.scenes[0].video_segment_path is not None
    assert mock_ctx.scenes[0].video_segment_path.name == "segment.mp4"
    
    assert mock_ctx.scenes[1].image_path is not None
    assert mock_ctx.scenes[1].video_segment_path is not None

    # Verify ffmpeg called
    assert mock_ffmpeg_instance.build_ken_burns_command.call_count == 2
    assert mock_ffmpeg_instance.run_command.call_count == 2

    # Verify cleanup
    assert node.pipeline is None


def test_crop_aspect_ratio():
    node = VisualStaticNode()
    
    # Test cropping a wide image to 9:16 (vertical)
    wide_img = Image.new("RGB", (1920, 1080)) # 16:9
    cropped_vertical = node._crop_to_aspect_ratio(wide_img, 9, 16)
    
    # Target ratio 9/16 = 0.5625
    # Since img is wide (16/9 = 1.77), we crop width. New width = 1080 * 9 / 16 = 607
    assert cropped_vertical.size == (607, 1080)

    # Test cropping a tall image to 16:9 (horizontal)
    tall_img = Image.new("RGB", (1080, 1920)) # 9:16
    cropped_horizontal = node._crop_to_aspect_ratio(tall_img, 16, 9)
    
    # Target ratio 16/9 = 1.77
    # Since img is tall (9/16 = 0.5625), we crop height. New height = 1080 / 1.77 = 607
    assert cropped_horizontal.size == (1080, 607)
