import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext
from snapreel.core.orchestrator import PipelineOrchestrator
from snapreel.nodes.assembly import AssemblyNode
from snapreel.nodes.audio_tts import AudioNode
from snapreel.nodes.scenario import ScenarioNode
from snapreel.nodes.subtitle import SubtitleNode
from snapreel.nodes.visual_static import VisualStaticNode
from PySide6.QtCore import QCoreApplication

@pytest.fixture(scope="session")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app

@patch("snapreel.nodes.scenario.llama_cpp")
@patch("snapreel.nodes.audio_tts.edge_tts.Communicate")
@patch("snapreel.nodes.visual_static.AutoPipelineForText2Image")
@patch("snapreel.nodes.subtitle.WhisperModel")
@patch("snapreel.infra.ffmpeg.subprocess.run")
@patch("snapreel.infra.ffmpeg.shutil.which")
def test_pipeline_e2e_mocked(
    mock_shutil_which,
    mock_subprocess_run,
    mock_whisper_class,
    mock_sdxl_class,
    mock_edge_tts_class,
    mock_llama_cpp,
    qapp,
    tmp_path,
):
    """
    End-to-End test of the pipeline orchestrator using mocked model calls.
    It verifies that data flows correctly from Scenario -> Audio -> Visual -> Subtitle -> Assembly.
    """
    # 1. Setup minimal configuration and directories
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    
    grammar_dir = app_dir / "grammars"
    grammar_dir.mkdir()
    (grammar_dir / "scenario.gbnf").write_text("mock grammar")

    prompt_dir = app_dir / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "scenario_system.txt").write_text("mock system prompt")

    work_dir = tmp_path / "work"
    out_dir = tmp_path / "out"
    models_dir = tmp_path / "models"
    work_dir.mkdir()
    out_dir.mkdir()
    models_dir.mkdir()

    config = AppConfig(
        app_dir=app_dir,
        models_dir=models_dir,
        output_dir=out_dir,
    )

    ctx = PipelineContext(
        topic="Integration Test Topic",
        style="Cinematic",
        voice="en-US-ChristopherNeural",
        visual_mode="static",
        scene_count=2,
        work_dir=work_dir,
        output_dir=out_dir,
    )

    # 2. Setup Mocks
    
    # Scenario Mocks
    mock_llm_instance = MagicMock()
    mock_llama_cpp.Llama.return_value = mock_llm_instance
    mock_llm_instance.create_chat_completion.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "title": "E2E Test Video",
                    "scenes": [
                        {
                            "scene_id": 1,
                            "narration": "Narration 1",
                            "visual_prompt": "Visual 1",
                            "duration_hint": 2.0,
                            "sfx": "none"
                        },
                        {
                            "scene_id": 2,
                            "narration": "Narration 2",
                            "visual_prompt": "Visual 2",
                            "duration_hint": 2.0,
                            "sfx": "none"
                        }
                    ]
                })
            }
        }]
    }

    # Audio Mocks
    async def mock_tts_save(filename):
        Path(filename).write_bytes(b"mock audio data")
    mock_comm_instance = MagicMock()
    mock_comm_instance.save = mock_tts_save
    mock_edge_tts_class.return_value = mock_comm_instance

    # Visual Mocks
    mock_sdxl_instance = MagicMock()
    mock_sdxl_instance.to.return_value = mock_sdxl_instance
    mock_sdxl_class.from_single_file.return_value = mock_sdxl_instance
    mock_sdxl_class.from_pretrained.return_value = mock_sdxl_instance
    
    def mock_sdxl_call(*args, **kwargs):
        mock_image = MagicMock()
        def save_image(path):
            Path(path).write_bytes(b"mock image data")
        mock_image.save = save_image
        mock_image.size = (1024, 1024)
        mock_image.crop.return_value = mock_image
        mock_image.resize.return_value = mock_image
        
        result = MagicMock()
        result.images = [mock_image]
        return result
    mock_sdxl_instance.return_value = mock_sdxl_call
    mock_sdxl_instance.__call__ = mock_sdxl_call # for python < 3.11? no wait, just assign side_effect
    mock_sdxl_instance.side_effect = mock_sdxl_call

    # Subtitle Mocks
    mock_whisper_instance = MagicMock()
    mock_whisper_class.return_value = mock_whisper_instance
    
    def mock_transcribe(audio_path, **kwargs):
        class DummyWord:
            def __init__(self, word, start, end):
                self.word = word
                self.start = start
                self.end = end
                
        class DummySegment:
            def __init__(self, start, end, text, words):
                self.start = start
                self.end = end
                self.text = text
                self.words = words
                
        segment = DummySegment(start=0.0, end=1.0, text="Narration", words=[DummyWord("Narration", 0.0, 1.0)])
        return [segment], None
    mock_whisper_instance.transcribe = mock_transcribe

    # Assembly Mocks
    mock_shutil_which.return_value = "ffmpeg"
    
    def mock_subprocess(*args, **kwargs):
        # Scan for output files (last argument in many commands, or any .mp4/.wav argument)
        for arg in args[0]:
            arg_str = str(arg)
            if arg_str.endswith(".mp4") or arg_str.endswith(".wav") or arg_str.endswith(".mp3"):
                Path(arg_str).write_bytes(b"mock video/audio data")
        return MagicMock(returncode=0)
    mock_subprocess_run.side_effect = mock_subprocess

    # 3. Create Orchestrator
    nodes = [
        ScenarioNode(config=config),
        AudioNode(),
        VisualStaticNode(config=config),
        SubtitleNode(config=config),
        AssemblyNode(ffmpeg_path=Path("ffmpeg"))
    ]
    orchestrator = PipelineOrchestrator(context=ctx, nodes=nodes)

    # 4. Run Orchestrator
    # We call run() synchronously for testing, bypassing QThread signals,
    # or we can use QTest / pytest-qt to run the thread.
    # But since run() is a normal method, we can just call it to test the logic.
    orchestrator.run()

    # 5. Verify Results
    assert ctx.title == "E2E Test Video"
    assert len(ctx.scenes) == 2
    
    # Check that AudioNode generated audio paths
    assert ctx.scenes[0].audio_path is not None
    assert ctx.scenes[0].audio_path.exists()
    
    # Check that VisualNode generated image paths
    assert ctx.scenes[0].image_path is not None
    assert ctx.scenes[0].image_path.exists()

    # Check Subtitles
    assert ctx.subtitle_path is not None
    assert ctx.subtitle_path.exists()
    ass_content = ctx.subtitle_path.read_text(encoding="utf-8")
    assert "Narration" in ass_content

    # Check final assembly
    assert ctx.final_video_path is not None
    assert ctx.final_video_path.exists()
    assert ctx.final_video_path.suffix == ".mp4"
    assert ctx.final_video_path.stat().st_size > 0
