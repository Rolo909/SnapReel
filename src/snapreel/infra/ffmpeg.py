"""FFmpeg binary manager and command builder."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import structlog

from snapreel.core.exceptions import FFmpegError

logger = structlog.get_logger()


class FFmpegManager:
    """Manages the FFmpeg binary and builds command arguments.

    Locates ffmpeg in PATH or at a configured path. Provides helper methods
    for building common FFmpeg command-line invocations used in the pipeline.
    """

    def __init__(self, ffmpeg_path: Path | None = None) -> None:
        self._ffmpeg_path = self._resolve_ffmpeg(ffmpeg_path)
        self._log = logger.bind(component="ffmpeg")

    @property
    def path(self) -> Path:
        """Get the resolved path to the ffmpeg binary."""
        return self._ffmpeg_path

    def _resolve_ffmpeg(self, configured_path: Path | None) -> Path:
        """Resolve the ffmpeg binary path.

        Args:
            configured_path: User-configured path, or None to auto-detect.

        Returns:
            Resolved Path to ffmpeg binary.

        Raises:
            FFmpegError: If ffmpeg cannot be found.
        """
        if configured_path and configured_path.exists():
            return configured_path

        # Try to find in PATH
        found = shutil.which("ffmpeg")
        if found:
            return Path(found)

        # Try common Windows locations
        common_paths = [
            Path("ffmpeg.exe"),
            Path("bin/ffmpeg.exe"),
            Path("tools/ffmpeg.exe"),
        ]
        for p in common_paths:
            if p.exists():
                return p

        raise FFmpegError("ffmpeg", "FFmpeg not found in PATH or common locations", -1)

    def get_version(self) -> str:
        """Get the FFmpeg version string.

        Returns:
            Version string (e.g., '7.0.1').
        """
        result = self.run_command(["-version"], capture=True)
        first_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
        return first_line

    def run_command(
        self,
        args: list[str],
        *,
        capture: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run an FFmpeg command.

        Args:
            args: Command-line arguments (without 'ffmpeg' prefix).
            capture: Whether to capture stdout/stderr.
            check: Whether to raise FFmpegError on non-zero exit.

        Returns:
            CompletedProcess result.

        Raises:
            FFmpegError: If check=True and ffmpeg exits with non-zero code.
        """
        cmd = [str(self._ffmpeg_path), *args]
        self._log.debug("ffmpeg_command", cmd=" ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            check=False,
        )

        if check and result.returncode != 0:
            stderr = result.stderr or ""
            raise FFmpegError(
                command=" ".join(cmd),
                stderr=stderr,
                returncode=result.returncode,
            )

        return result

    def build_ken_burns_command(
        self,
        image_path: Path,
        output_path: Path,
        duration: float,
        *,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        zoom_speed: float = 0.0015,
    ) -> list[str]:
        """Build FFmpeg args for a Ken Burns (zoom/pan) effect on a static image.

        Args:
            image_path: Path to the source image.
            output_path: Path for the output video segment.
            duration: Duration in seconds.
            width: Output width.
            height: Output height.
            fps: Output frame rate.
            zoom_speed: Zoom increment per frame.

        Returns:
            List of FFmpeg command-line arguments.
        """
        total_frames = int(duration * fps)
        return [
            "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-vf", (
                f"zoompan=z='min(zoom+{zoom_speed},{1 + zoom_speed * total_frames * 0.7})':"
                f"d={total_frames}:s={width}x{height}:fps={fps}"
            ),
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

    def build_assembly_command(
        self,
        video_segments: list[Path],
        narration_path: Path,
        output_path: Path,
        *,
        subtitle_path: Path | None = None,
        music_path: Path | None = None,
        music_volume: float = 0.15,
        fps: int = 30,
        crf: int = 18,
    ) -> list[str]:
        """Build FFmpeg args for the final video assembly.

        Concatenates video segments, mixes narration with optional background
        music (with sidechain ducking), and burns subtitles.

        Args:
            video_segments: List of video segment file paths.
            narration_path: Path to the narration audio file.
            output_path: Path for the final output video.
            subtitle_path: Optional path to .ass subtitle file.
            music_path: Optional path to background music file.
            music_volume: Background music volume (0.0 - 1.0).
            fps: Output frame rate.
            crf: Constant Rate Factor for x264.

        Returns:
            List of FFmpeg command-line arguments.
        """
        args: list[str] = ["-y"]
        n_videos = len(video_segments)

        # Input files
        for seg in video_segments:
            args.extend(["-i", str(seg)])
        args.extend(["-i", str(narration_path)])
        narration_idx = n_videos

        music_idx: int | None = None
        if music_path:
            args.extend(["-i", str(music_path)])
            music_idx = narration_idx + 1

        # Build filter_complex
        filters: list[str] = []

        # Concat video segments
        concat_inputs = "".join(f"[{i}:v]" for i in range(n_videos))
        filters.append(f"{concat_inputs}concat=n={n_videos}:v=1:a=0[vcat]")

        # Audio mixing
        if music_idx is not None:
            # Sidechain compression for audio ducking
            filters.append(f"[{narration_idx}:a]asplit=2[voice_out][voice_sc]")
            filters.append(
                f"[{music_idx}:a]volume={music_volume}[music_adj];"
                f"[music_adj][voice_sc]sidechaincompress="
                f"threshold=0.02:ratio=6:attack=200:release=1000[music_ducked]"
            )
            filters.append(
                "[voice_out][music_ducked]amix=inputs=2:duration=first[amix]"
            )
            audio_out = "[amix]"
        else:
            filters.append(f"[{narration_idx}:a]acopy[amix]")
            audio_out = "[amix]"

        # Subtitle burn-in
        if subtitle_path:
            escaped_sub = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
            filters.append(f"[vcat]ass='{escaped_sub}'[vout]")
            video_out = "[vout]"
        else:
            video_out = "[vcat]"

        args.extend(["-filter_complex", ";".join(filters)])
        args.extend(["-map", video_out, "-map", audio_out])
        args.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", str(crf),
            "-c:a", "aac",
            "-b:a", "192k",
            "-r", str(fps),
            "-shortest",
            str(output_path),
        ])

        return args
