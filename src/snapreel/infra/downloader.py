"""Model downloader with progress reporting, resume, and hash verification."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import structlog

logger = structlog.get_logger()

# Progress callback: (model_name, bytes_downloaded, total_bytes) -> None
DownloadProgressCallback = Callable[[str, int, int], None]


def _noop_download_progress(_name: str, _downloaded: int, _total: int) -> None:
    """Default no-op download progress callback."""


@dataclass(frozen=True)
class ModelSpec:
    """Specification for a downloadable model."""

    name: str
    repo_id: str
    filename: str | None = None  # For single-file downloads (GGUF)
    size_gb: float = 0.0
    target_dir: str = "models"
    sha256: str | None = None


# Registry of all models needed by SnapReel
MODEL_REGISTRY: dict[str, ModelSpec] = {
    "llm_7b": ModelSpec(
        name="Qwen2.5-7B-Instruct-Q4_K_M",
        repo_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
        filename="qwen2.5-7b-instruct-q4_k_m.gguf",
        size_gb=4.4,
        target_dir="models/llm",
    ),
    "llm_3b": ModelSpec(
        name="Qwen2.5-3B-Instruct-Q4_K_M",
        repo_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
        filename="qwen2.5-3b-instruct-q4_k_m.gguf",
        size_gb=2.0,
        target_dir="models/llm",
    ),
    "whisper": ModelSpec(
        name="faster-whisper-large-v3",
        repo_id="Systran/faster-whisper-large-v3",
        size_gb=1.5,
        target_dir="models/whisper",
    ),
    "sdxl_turbo": ModelSpec(
        name="SDXL-Turbo",
        repo_id="stabilityai/sdxl-turbo",
        size_gb=6.5,
        target_dir="models/diffusion",
    ),
}


class ModelDownloader:
    """Downloads and manages ML model weights.

    Uses huggingface_hub for downloading with resume support and
    progress reporting via callbacks.
    """

    def __init__(
        self,
        base_dir: Path,
        progress_callback: DownloadProgressCallback = _noop_download_progress,
    ) -> None:
        self._base_dir = base_dir
        self._progress = progress_callback
        self._log = logger.bind(component="downloader")

    def is_model_available(self, model_key: str) -> bool:
        """Check if a model is already downloaded.

        Args:
            model_key: Key from MODEL_REGISTRY.

        Returns:
            True if the model files exist locally.
        """
        spec = MODEL_REGISTRY.get(model_key)
        if spec is None:
            return False

        target = self._base_dir / spec.target_dir
        if spec.filename:
            return (target / spec.filename).exists()
        # For full repo downloads, check if directory is non-empty
        return target.exists() and any(target.iterdir())

    def get_missing_models(self, required: list[str] | None = None) -> list[str]:
        """Get list of model keys that are not yet downloaded.

        Args:
            required: Specific model keys to check. If None, checks all.

        Returns:
            List of missing model keys.
        """
        keys = required or list(MODEL_REGISTRY.keys())
        return [k for k in keys if not self.is_model_available(k)]

    def download_model(self, model_key: str) -> Path:
        """Download a model from HuggingFace Hub.

        Args:
            model_key: Key from MODEL_REGISTRY.

        Returns:
            Path to the downloaded model file/directory.

        Raises:
            KeyError: If model_key is not in MODEL_REGISTRY.
            snapreel.core.exceptions.DownloadError: If download fails.
        """
        from snapreel.core.exceptions import DownloadError

        spec = MODEL_REGISTRY[model_key]
        target = self._base_dir / spec.target_dir
        target.mkdir(parents=True, exist_ok=True)

        self._log.info("download_start", model=spec.name, repo=spec.repo_id)

        try:
            from huggingface_hub import hf_hub_download, snapshot_download  # type: ignore[import-untyped]

            if spec.filename:
                # Single file download (GGUF models)
                result_path = hf_hub_download(
                    repo_id=spec.repo_id,
                    filename=spec.filename,
                    local_dir=str(target),
                    resume_download=True,
                )
                downloaded = Path(result_path)
            else:
                # Full repository snapshot
                result_path = snapshot_download(
                    repo_id=spec.repo_id,
                    local_dir=str(target),
                    resume_download=True,
                )
                downloaded = Path(result_path)

            # Verify SHA256 if provided
            if spec.sha256 and spec.filename:
                self._verify_hash(downloaded, spec.sha256, spec.name)

            self._log.info("download_complete", model=spec.name, path=str(downloaded))
            return downloaded

        except Exception as exc:
            msg = f"Download failed: {exc}"
            self._log.error("download_failed", model=spec.name, error=msg)
            raise DownloadError(spec.name, msg) from exc

    def _verify_hash(self, file_path: Path, expected_sha256: str, model_name: str) -> None:
        """Verify the SHA256 hash of a downloaded file.

        Args:
            file_path: Path to the downloaded file.
            expected_sha256: Expected SHA256 hash.
            model_name: Name of the model (for error messages).

        Raises:
            snapreel.core.exceptions.DownloadError: If hash doesn't match.
        """
        from snapreel.core.exceptions import DownloadError

        sha = hashlib.sha256()
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)

        actual = sha.hexdigest()
        if actual != expected_sha256:
            raise DownloadError(
                model_name,
                f"SHA256 mismatch: expected {expected_sha256[:16]}..., got {actual[:16]}...",
            )
        self._log.debug("hash_verified", model=model_name)
