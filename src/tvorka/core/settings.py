"""User settings persisted as JSON in the per-user data directory."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from tvorka.core import paths

log = logging.getLogger(__name__)

DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/Rolo909/Tvorka/main/src/tvorka/data/catalog.yaml"
)

PERFORMANCE_MODES = ("auto", "speed", "balanced", "low_memory", "cpu")


@dataclass
class Settings:
    """All persisted preferences. Unknown keys in the file are ignored."""

    language: str = "ru"
    theme: str = "dark"
    output_dir: str = ""
    models_dir: str = ""
    performance_mode: str = "auto"
    keep_model_loaded: bool = True
    hf_token: str = ""
    catalog_url: str = DEFAULT_CATALOG_URL
    auto_update_catalog: bool = True
    check_updates: bool = True  # ask GitHub once per start whether a newer release exists
    image_format: str = "png"
    video_format: str = "mp4"
    audio_format: str = "wav"
    welcome_done: bool = False  # the first-run welcome screen was completed or skipped
    # Last used values per page, so the app reopens the way it was left.
    last: dict[str, Any] = field(default_factory=dict)
    window: dict[str, Any] = field(default_factory=dict)

    # --- derived paths -------------------------------------------------
    def models_path(self) -> Path:
        return Path(self.models_dir) if self.models_dir else paths.default_models_dir()

    def output_path(self) -> Path:
        return Path(self.output_dir) if self.output_dir else paths.default_output_dir()

    def hub_path(self) -> Path:
        """Hugging Face cache layout root (resumable, deduplicated)."""
        return self.models_path() / "hub"

    def files_path(self) -> Path:
        """Direct-URL downloads and manifests."""
        return self.models_path() / "files"

    def token(self) -> str | None:
        return self.hf_token.strip() or os.environ.get("HF_TOKEN") or None

    # --- persistence ---------------------------------------------------
    @staticmethod
    def file() -> Path:
        return paths.data_dir() / "settings.json"

    @classmethod
    def load(cls) -> Settings:
        data: dict[str, Any] = {}
        path = cls.file()
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = _read_legacy()
        except (OSError, ValueError) as exc:
            log.warning("settings unreadable, using defaults: %s", exc)
        known = {f.name for f in fields(cls)}
        settings = cls(**{k: v for k, v in data.items() if k in known})
        settings._sanitize()
        return settings

    def save(self) -> None:
        path = self.file()
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            log.error("failed to save settings: %s", exc)

    def _sanitize(self) -> None:
        if self.language not in ("ru", "en"):
            self.language = "ru"
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        if self.performance_mode not in PERFORMANCE_MODES:
            self.performance_mode = "auto"
        if not isinstance(self.last, dict):
            self.last = {}
        if not isinstance(self.window, dict):
            self.window = {}

    # --- per-page memory -----------------------------------------------
    def recall(self, page: str, key: str, default: Any = None) -> Any:
        return self.last.get(page, {}).get(key, default)

    def remember(self, page: str, **values: Any) -> None:
        self.last.setdefault(page, {}).update(values)


def _read_legacy() -> dict[str, Any]:
    """Import the language from the pre-1.0 ``settings.json`` kept next to the app."""
    legacy = paths.app_dir() / "settings.json"
    if not legacy.exists():
        return {}
    old = json.loads(legacy.read_text(encoding="utf-8"))
    return {"language": old.get("language", "ru")} if isinstance(old, dict) else {}
