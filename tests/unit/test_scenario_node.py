"""Unit tests for ScenarioNode."""

import json
from unittest.mock import MagicMock, patch

import pytest
from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeValidationError
from snapreel.nodes.scenario import ScenarioNode

@pytest.fixture
def mock_ctx():
    return PipelineContext(
        topic="Test Topic",
        language="en",
        scene_count=2,
        style="motivational"
    )

def test_validate_no_topic():
    ctx = PipelineContext(topic="")
    node = ScenarioNode()
    with patch("snapreel.nodes.scenario.llama_cpp", MagicMock()):
        with pytest.raises(NodeValidationError, match="no topic"):
            node.validate(ctx)

@patch("snapreel.nodes.scenario.llama_cpp")
def test_validate_success(mock_llama_cpp, mock_ctx):
    node = ScenarioNode()
    assert node.validate(mock_ctx) is True

@patch("snapreel.nodes.scenario.llama_cpp")
def test_scenario_execute_success(mock_llama_cpp, mock_ctx, tmp_path):
    # Setup dummy grammars and prompts files in tmp_path to mock AppConfig.app_dir
    grammar_dir = tmp_path / "grammars"
    grammar_dir.mkdir()
    (grammar_dir / "scenario.gbnf").write_text("dummy grammar")

    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "scenario_system.txt").write_text("Language: {language}, Scenes: {scene_count}, Style: {style}")

    config = AppConfig(app_dir=tmp_path, models_dir=tmp_path / "models")
    node = ScenarioNode(config=config)

    # Mock LLM instance and its response
    mock_llm_instance = MagicMock()
    mock_llama_cpp.Llama.return_value = mock_llm_instance

    mock_response_json = json.dumps({
        "title": "A Great Test Video",
        "scenes": [
            {
                "scene_id": 1,
                "narration": "First scene narration.",
                "visual_prompt": "Cinematic shot of first scene.",
                "duration_hint": 3.0,
                "sfx": "woosh"
            },
            {
                "scene_id": 2,
                "narration": "Second scene narration.",
                "visual_prompt": "Cinematic shot of second scene.",
                "duration_hint": 2.5,
                "sfx": "none"
            }
        ]
    })

    mock_llm_instance.create_chat_completion.return_value = {
        "choices": [
            {
                "message": {
                    "content": mock_response_json
                }
            }
        ]
    }

    result = node.run(mock_ctx)

    assert result.status.value == "completed"
    assert mock_ctx.title == "A Great Test Video"
    assert len(mock_ctx.scenes) == 2
    
    assert mock_ctx.scenes[0].scene_id == 1
    assert mock_ctx.scenes[0].narration == "First scene narration."
    assert mock_ctx.scenes[0].sfx == "woosh"
    
    assert mock_ctx.scenes[1].scene_id == 2
    assert mock_ctx.scenes[1].visual_prompt == "Cinematic shot of second scene."

    # Validate that Llama was loaded with expected args
    mock_llama_cpp.Llama.assert_called_once()
    mock_llama_cpp.LlamaGrammar.from_string.assert_called_once_with("dummy grammar")
    mock_llm_instance.create_chat_completion.assert_called_once()

    # Ensure cleanup deleted the LLM instance
    assert node.llm is None
