"""Scenario generation node using llama-cpp-python."""

import json
from pathlib import Path

import structlog

from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext, SceneData
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode

try:
    import llama_cpp
except ImportError:
    llama_cpp = None

logger = structlog.get_logger()


class ScenarioNode(PipelineNode):
    """Generates a structured video script using a local LLM.

    Uses llama-cpp-python with a GBNF grammar to guarantee JSON output.
    """

    def __init__(self, name: str = "ScenarioNode", config: AppConfig | None = None) -> None:
        super().__init__(name)
        self.config = config or AppConfig()
        self.llm = None

    def validate(self, ctx: PipelineContext) -> bool:
        if not ctx.topic:
            raise NodeValidationError(self.name, "Context has no topic set.")
        if llama_cpp is None:
            raise NodeValidationError(self.name, "llama-cpp-python is not installed.")
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.report_progress(0, "Initializing LLM...")
        
        model_path = self.config.get_models_dir() / self.config.llm_model
        
        # We allow execution without model file if we mock it in tests,
        # but in real usage it will raise an error from llama_cpp.
        try:
            self.llm = llama_cpp.Llama(
                model_path=str(model_path),
                n_ctx=self.config.llm_context_size,
                n_threads=self.config.llm_threads,
                verbose=False
            )
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to load LLM from {model_path}: {e}") from e

        # Load GBNF grammar
        grammar_path = self.config.app_dir / "grammars" / "scenario.gbnf"
        try:
            with open(grammar_path, "r", encoding="utf-8") as f:
                grammar_str = f.read()
            grammar = llama_cpp.LlamaGrammar.from_string(grammar_str)
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to load grammar: {e}") from e

        # Load prompt template
        prompt_path = self.config.app_dir / "prompts" / "scenario_system.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                system_prompt_tmpl = f.read()
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to load prompt template: {e}") from e

        system_prompt = system_prompt_tmpl.format(
            language=ctx.language,
            scene_count=ctx.scene_count,
            style=ctx.style
        )
        user_prompt = f"Topic: {ctx.topic}"

        self.report_progress(20, "Generating scenario...")

        try:
            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                grammar=grammar,
                temperature=0.7,
            )
            result_text = response["choices"][0]["message"]["content"]
            
            self._log.debug("llm_response", response=result_text)
            data = json.loads(result_text)
            ctx.title = data.get("title", "Untitled")
            
            scenes = []
            for item in data.get("scenes", []):
                scene = SceneData(
                    scene_id=item["scene_id"],
                    narration=item["narration"],
                    visual_prompt=item["visual_prompt"],
                    duration_hint=item["duration_hint"],
                    sfx=item.get("sfx", "none")
                )
                scenes.append(scene)
                
            ctx.scenes = scenes
            
        except json.JSONDecodeError as e:
            raise NodeExecutionError(self.name, f"Failed to parse LLM output as JSON: {e}") from e
        except Exception as e:
            raise NodeExecutionError(self.name, f"Generation failed: {e}") from e

        self.report_progress(100, "Scenario generation complete.")
        return NodeResult(status=NodeStatus.COMPLETED)

    def cleanup(self) -> None:
        if self.llm:
            del self.llm
            self.llm = None
