"""Pipeline context — shared state passed between pipeline nodes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SceneData:
    """Data for a single scene in the video.

    Populated incrementally by pipeline nodes:
    - ScenarioNode sets: scene_id, narration, visual_prompt, duration_hint, sfx
    - AudioNode sets: audio_path
    - VisualNode sets: image_path
    - AssemblyNode sets: video_segment_path
    """

    scene_id: int
    narration: str
    visual_prompt: str
    duration_hint: float
    sfx: str = "none"
    # Populated by AudioNode:
    audio_path: Path | None = None
    # Populated by VisualNode:
    image_path: Path | None = None
    # Populated by AssemblyNode:
    video_segment_path: Path | None = None


@dataclass
class PipelineContext:
    """Shared context passed through the entire pipeline.

    Each node reads from and writes to this context. User-input fields are
    set at creation time; node-output fields are updated during execution.
    """

    # --- User inputs (set at creation, treated as immutable) ---
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    topic: str = ""
    style: str = "motivational"
    voice: str = "ru-RU-DmitryNeural"
    visual_mode: str = "static"  # "static" | "video"
    scene_count: int = 5
    music_path: Path | None = None
    language: str = "ru"

    # --- Working directories ---
    work_dir: Path = field(default_factory=lambda: Path("."))
    output_dir: Path = field(default_factory=lambda: Path("."))

    # --- Populated by ScenarioNode ---
    title: str = ""
    scenes: list[SceneData] = field(default_factory=list)

    # --- Populated by AudioNode ---
    narration_audio_path: Path | None = None

    # --- Populated by SubtitleNode ---
    subtitle_path: Path | None = None

    # --- Populated by AssemblyNode ---
    final_video_path: Path | None = None

    # --- Extensible metadata ---
    metadata: dict[str, Any] = field(default_factory=dict)

    def scene_work_dir(self, scene_id: int) -> Path:
        """Get or create the working directory for a specific scene.

        Args:
            scene_id: The numeric scene identifier.

        Returns:
            Path to the scene's working directory.
        """
        d = self.work_dir / f"scene_{scene_id:02d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_dirs(self) -> None:
        """Create all required working directories."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "audio").mkdir(exist_ok=True)
        (self.work_dir / "visuals").mkdir(exist_ok=True)
        (self.work_dir / "segments").mkdir(exist_ok=True)
