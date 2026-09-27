"""Subtitle generation node using faster-whisper."""

from pathlib import Path
from typing import Any

import structlog

from snapreel.core.config import AppConfig
from snapreel.core.context import PipelineContext
from snapreel.core.exceptions import NodeExecutionError, NodeValidationError
from snapreel.core.node_base import NodeResult, NodeStatus, PipelineNode

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = structlog.get_logger()

# Basic ASS template with karaoke styles
# PrimaryColour: White, SecondaryColour: Yellow (for the karaoke fill effect)
# Alignment 2 = Bottom Center
ASS_TEMPLATE = """[Script Info]
Title: SnapReel Subtitles
ScriptType: v4.00+
WrapStyle: 1
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,80,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,2,50,50,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def format_ass_time(seconds: float) -> str:
    """Format seconds into H:MM:SS.cs for ASS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    # ASS uses centiseconds (2 decimals)
    return f"{h}:{m:02d}:{s:05.2f}"


class SubtitleNode(PipelineNode):
    """Generates word-level timestamps and ASS karaoke subtitles.

    Transcribes the combined narration audio using faster-whisper,
    then generates a stylized .ass file suitable for FFmpeg burn-in.
    """

    def __init__(self, name: str = "SubtitleNode", config: AppConfig | None = None) -> None:
        super().__init__(name)
        self.config = config or AppConfig()
        self.model: Any = None

    def validate(self, ctx: PipelineContext) -> bool:
        if not ctx.narration_audio_path or not ctx.narration_audio_path.exists():
            raise NodeValidationError(
                self.name, 
                "Context missing narration_audio_path. Did AudioNode run successfully?"
            )
        if WhisperModel is None:
            raise NodeValidationError(self.name, "faster-whisper is not installed.")
        return True

    def execute(self, ctx: PipelineContext) -> NodeResult:
        self.report_progress(0, "Loading Whisper model...")

        try:
            # Note: in a real environment we might want to check CUDA availability
            # but faster-whisper defaults nicely if we pass device="auto".
            # For strict control, we can use config.whisper_compute_type.
            self.model = WhisperModel(
                self.config.whisper_model_size,
                device="auto",
                compute_type=self.config.whisper_compute_type,
                cpu_threads=self.config.llm_threads
            )
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to load Whisper model: {e}") from e

        self.report_progress(30, "Transcribing audio (word-level)...")
        
        try:
            assert ctx.narration_audio_path is not None
            
            segments_gen, _info = self.model.transcribe(
                str(ctx.narration_audio_path),
                language=ctx.language,
                word_timestamps=True,
            )
            
            # Exhaust the generator to get all segments
            segments = list(segments_gen)
            
        except Exception as e:
            raise NodeExecutionError(self.name, f"Transcription failed: {e}") from e

        self.report_progress(80, "Generating ASS subtitles...")
        
        ass_path = ctx.work_dir / "subtitles.ass"
        
        try:
            self._write_ass_file(segments, ass_path)
            ctx.subtitle_path = ass_path
        except Exception as e:
            raise NodeExecutionError(self.name, f"Failed to write ASS file: {e}") from e

        self.report_progress(100, "Subtitle generation complete.")
        return NodeResult(status=NodeStatus.COMPLETED)

    def _write_ass_file(self, segments: list[Any], out_path: Path) -> None:
        lines = [ASS_TEMPLATE]
        
        for seg in segments:
            start_str = format_ass_time(seg.start)
            end_str = format_ass_time(seg.end)
            
            text_parts = []
            current_time = seg.start
            
            for word in seg.words:
                # Calculate gap before the word
                gap = word.start - current_time
                if gap > 0:
                    gap_cs = int(round(gap * 100))
                    if gap_cs > 0:
                        text_parts.append(f"{{\\k{gap_cs}}}")
                
                # Calculate word duration
                dur = word.end - word.start
                dur_cs = int(round(dur * 100))
                
                # \K gives a smooth color sweep
                clean_word = word.word.strip()
                # Include leading/trailing spaces correctly in the text outside the tag
                prefix_space = " " if word.word.startswith(" ") else ""
                suffix_space = " " if word.word.endswith(" ") else ""
                
                text_parts.append(f"{prefix_space}{{\\K{dur_cs}}}{clean_word}{suffix_space}")
                
                current_time = word.end
            
            ass_text = "".join(text_parts)
            # ASS line format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{ass_text}\n"
            lines.append(line)
            
        with open(out_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def cleanup(self) -> None:
        if self.model:
            del self.model
            self.model = None
