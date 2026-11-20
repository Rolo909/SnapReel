"""Local model storage: what is installed, where it lives, how to remove it."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from tvorka.core.catalog import ModelSpec
from tvorka.core.llm import gguf
from tvorka.core.settings import Settings

log = logging.getLogger(__name__)


def safe_name(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "--", model_id).strip("-")


def dir_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


class ModelStore:
    """Resolves models to paths on disk. Layout under the models directory::

        hub/        Hugging Face cache (resumable, shared blobs)
        files/      direct-URL downloads, one folder per model
        manifests/  one JSON per installed model
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def root(self) -> Path:
        return self._settings.models_path()

    def manifest_path(self, spec: ModelSpec) -> Path:
        return self.root / "manifests" / f"{safe_name(spec.id)}.json"

    def manifest(self, spec: ModelSpec) -> dict[str, Any] | None:
        try:
            data = json.loads(self.manifest_path(spec).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def files_dir(self, spec: ModelSpec) -> Path:
        return self._settings.files_path() / safe_name(spec.id)

    def hub_repo_dir(self, spec: ModelSpec) -> Path:
        return self._settings.hub_path() / f"models--{spec.repo_id.replace('/', '--')}"

    def is_installed(self, spec: ModelSpec) -> bool:
        if spec.source == "online":
            return True
        if spec.source == "local":
            return bool(spec.path) and Path(spec.path).exists()
        location = self.location(spec)
        return location is not None and location.exists()

    def location(self, spec: ModelSpec) -> Path | None:
        """Folder (or file) an engine should load, or None when not installed."""
        if spec.source == "local":
            return Path(spec.path) if spec.path else None
        manifest = self.manifest(spec)
        if not manifest:
            return None
        path = Path(str(manifest.get("path", "")))
        return path if str(path) not in ("", ".") else None

    def variant(self, spec: ModelSpec) -> str | None:
        if spec.source == "local" and spec.path:
            root = Path(spec.path)
            if root.is_dir() and any(root.rglob("*.fp16.safetensors")):
                return "fp16"
            return None
        manifest = self.manifest(spec) or {}
        return manifest.get("variant") or None

    def size_bytes(self, spec: ModelSpec) -> int:
        manifest = self.manifest(spec) or {}
        return int(manifest.get("bytes") or 0)

    def delete(self, spec: ModelSpec) -> None:
        """Remove downloaded weights. Local (user-owned) folders are never touched."""
        if spec.source == "hf":
            shutil.rmtree(self.hub_repo_dir(spec), ignore_errors=True)
        elif spec.source == "url":
            shutil.rmtree(self.files_dir(spec), ignore_errors=True)
        self.manifest_path(spec).unlink(missing_ok=True)

    def chat_files(self, spec: ModelSpec) -> tuple[Path | None, Path | None]:
        """A chat model's GGUF file to load (the first part of a split one) and its projector."""
        if spec.source == "local":
            model = Path(spec.path) if spec.path else None
            return model, Path(spec.mmproj) if spec.mmproj else None
        location, manifest = self.location(spec), self.manifest(spec) or {}
        if location is None:
            return None, None
        names = [str(n) for n in manifest.get("files", [])]
        models = sorted(n for n in names if gguf.is_model_file(n))
        projectors = [n for n in names if gguf.is_projector_file(n)]
        return (location / models[0] if models else None,
                location / projectors[0] if projectors else None)

    def chat_mtp(self, spec: ModelSpec) -> Path | None:
        """A chat model's multi-token prediction head, None when it has none on disk."""
        if spec.source == "local":
            return Path(spec.mtp) if spec.mtp else None
        location, manifest = self.location(spec), self.manifest(spec) or {}
        names = [str(n) for n in manifest.get("files", []) if gguf.is_mtp_file(str(n))]
        return location / names[0] if location is not None and names else None

    def chat_quant(self, spec: ModelSpec) -> str:
        """The quantization on disk, "" when the chat model is not installed."""
        if spec.source == "local":
            return spec.quants[0]["name"] if spec.quants else ""
        model, _projector = self.chat_files(spec)
        return gguf.quant_name(model.name) if model else ""

    def download_task(self, spec: ModelSpec, only: list[str] | None = None) -> dict[str, Any]:
        """Serializable description consumed by the download subprocess.

        ``only`` limits a Hugging Face download to these files (one quantization of a GGUF repo).
        """
        return {
            "id": spec.id,
            "source": spec.source,
            "repo": spec.repo_id,
            "files": spec.files,
            "only": only or [],
            "hub_dir": str(self._settings.hub_path()),
            "files_dir": str(self.files_dir(spec)),
            "manifest": str(self.manifest_path(spec)),
            "prefer_half": spec.dtype != "fp32",
        }
