"""Audio generation node using edge-tts."""

import asyncio
from pathlib import Path

import edge_tts
import structlog

from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode
from snapreel.infra.ffmpeg import FFmpegManager

logger = structlog.get_logger()


class AudioNode(PipelineNode):
    """Generates per-scene narration audio using edge-tts.
    
    Converts the generated MP3 to WAV using FFmpeg for precise timing and
    compatibility with downstream tools.
    """

    def __init__(self, name: str = "AudioNode") -> None:
        super().__init__(name)
        self.ffmpeg = FFmpegManager()

    def validate(self, ctx: PipelineContext) -> bool:
        if not ctx.scenes:
            raise NodeValidationError(self.name, "Context has no scenes.")
        if not ctx.voice:
            raise NodeValidationError(self.name, "Context has no voice selected.")
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.report_progress(0, "Starting audio generation")
        
        try:
            asyncio.run(self._generate_audio(ctx))
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to generate audio: {e}") from e
            
        self.report_progress(100, "Audio generation complete")
        return NodeResult(status=NodeStatus.COMPLETED)

    async def _generate_audio(self, ctx: PipelineContext) -> None:
        total_scenes = len(ctx.scenes)
        
        # We process scenes one by one to give accurate progress
        for i, scene in enumerate(ctx.scenes):
            if not scene.narration.strip():
                self._log.warning("empty_narration", scene_id=scene.scene_id)
                continue
                
            self.report_progress(
                int((i / total_scenes) * 100), 
                f"Generating audio for scene {scene.scene_id}"
            )
            
            work_dir = ctx.scene_work_dir(scene.scene_id)
            mp3_path = work_dir / "narration.mp3"
            wav_path = work_dir / "narration.wav"
            
            communicate = edge_tts.Communicate(scene.narration, ctx.voice)
            await communicate.save(str(mp3_path))
            
            # Convert to WAV using FFmpeg
            self.ffmpeg.run_command([
                "-y",
                "-i", str(mp3_path),
                "-ac", "1",  # Mono
                "-ar", "44100",  # 44.1kHz
                str(wav_path)
            ], capture=True, check=True)
            
            scene.audio_path = wav_path
            
            # Remove intermediate MP3
            try:
                mp3_path.unlink()
            except OSError:
                pass

        # Concatenate all scene audios into a single narration track
        self.report_progress(95, "Concatenating scene audios...")
        concat_list_path = ctx.work_dir / "audio_concat.txt"
        narration_path = ctx.work_dir / "audio" / "narration.wav"
        
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for scene in ctx.scenes:
                if scene.audio_path and scene.audio_path.exists():
                    # FFmpeg concat requires escaped paths or relative paths.
                    # We'll use absolute paths with forward slashes for safety.
                    safe_path = str(scene.audio_path.absolute()).replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

        self.ffmpeg.run_command([
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(narration_path)
        ], capture=True, check=True)
        
        ctx.narration_audio_path = narration_path

    def cleanup(self) -> None:
        # No persistent resources to release
        pass
