"""Model catalog: bundled list, remote updates, and user-added models."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from tvorka.core import paths

log = logging.getLogger(__name__)

KINDS = ("image", "video", "speech", "chat", "transcribe")
# Built-in engine names; plugins add theirs through ``engines.base.register_engine``.
# Entries naming an engine that is not available are skipped when a catalog is read.
ENGINES: set[str] = {"diffusers", "silero", "transformers_tts", "edge", "llama", "whisper"}
# Direct-URL weights are executable (torch.package), so only these hosts are accepted.
TRUSTED_URL_HOSTS = {"models.silero.ai"}


@dataclass
class ModelSpec:
    """Everything the app needs to know about one model."""

    id: str
    name: str
    kind: str
    engine: str = "diffusers"
    source: str = "hf"  # hf | url | local | online
    repo: str = ""
    path: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    author: str = ""
    license: str = ""
    summary: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    download_gb: float = 0.0
    # Component name -> GB it occupies in memory at the run precision.
    memory: dict[str, float] = field(default_factory=dict)
    act_gb: float = 1.5  # working memory at the native resolution
    dtype: str = "auto"  # fp16 | bf16 | fp32 | auto
    native: list[int] = field(default_factory=lambda: [1024, 1024])
    max_side: int = 2048
    multiple: int = 8
    fixed_size: bool = False
    defaults: dict[str, Any] = field(default_factory=dict)
    reference: list[str] = field(default_factory=list)
    requires_reference: bool = False
    i2v_pipeline: str = ""
    i2i_pipeline: str = ""
    frame_rule: int = 1  # frame counts must be k * frame_rule + 1
    voices: list[dict[str, str]] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    # Chat models (GGUF): one entry per quantization, {"name": "Q4_K_M", "files": [...], "gb": 5.3}.
    quants: list[dict[str, Any]] = field(default_factory=list)
    mmproj: str = ""  # projector that lets the model see images (repo file, or a path for local models)
    mmproj_gb: float = 0.0
    context: int = 0  # longest context the model was trained for, tokens
    layers: int = 0
    kv_gb_per_1k: float = 0.0  # KV cache per 1024 tokens of context
    kv_fixed_gb: float = 0.0  # KV cache that does not grow with the context (sliding-window layers)
    capabilities: list[str] = field(default_factory=list)  # vision | tools | reasoning
    mtp: str = ""  # draft head for multi-token prediction (repo file, or a path for local models)
    mtp_gb: float = 0.0
    experts: int = 0  # mixture of experts: experts per layer (0 for a dense model)
    experts_used: int = 0  # experts each token goes through
    expert_share: float = 0.0  # fraction of the weights in routed experts (what may stay in RAM)
    gated: bool = False
    origin: str = "builtin"  # builtin | remote | user | hub

    @property
    def repo_id(self) -> str:
        return self.repo or self.id

    @property
    def weights_gb(self) -> float:
        return sum(self.memory.values())

    def text(self, lang: str) -> str:
        return self.summary.get(lang) or self.summary.get("en") or ""

    def default(self, key: str, fallback: Any = None) -> Any:
        return self.defaults.get(key, fallback)

    def quant(self, name: str) -> dict[str, Any] | None:
        return next((q for q in self.quants if q.get("name") == name), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], origin: str = "builtin") -> ModelSpec:
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        if isinstance(clean.get("summary"), str):
            clean["summary"] = {"en": clean["summary"]}
        spec = cls(**clean)
        spec.origin = origin
        if spec.kind not in KINDS or spec.engine not in ENGINES:
            raise ValueError(f"unsupported model entry: {spec.id}")
        return spec


class Catalog:
    """Merged view over builtin, remote and user models (later sources win)."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or paths.data_dir()
        self._models: dict[str, ModelSpec] = {}
        self.reload()

    # --- files ---------------------------------------------------------
    @property
    def user_file(self) -> Path:
        return self._data_dir / "user_models.json"

    @property
    def remote_file(self) -> Path:
        return self._data_dir / "catalog_remote.yaml"

    @staticmethod
    def builtin_file() -> Path:
        return paths.package_dir() / "data" / "catalog.yaml"

    # --- loading -------------------------------------------------------
    def reload(self) -> None:
        models: dict[str, ModelSpec] = {}
        for spec in _parse(_read(self.builtin_file()), "builtin"):
            models[spec.id] = spec
        for spec in _parse(_read(self.remote_file), "remote"):
            models[spec.id] = spec
        for spec in self._load_user():
            models[spec.id] = spec
        self._models = models

    def _load_user(self) -> list[ModelSpec]:
        try:
            raw = json.loads(self.user_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        out = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(ModelSpec.from_dict(item, "user"))
            except (TypeError, ValueError) as exc:
                log.warning("skipping broken user model: %s", exc)
        return out

    def _save_user(self) -> None:
        user = [m.to_dict() for m in self._models.values() if m.origin == "user"]
        self.user_file.write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- queries -------------------------------------------------------
    def all(self, kind: str | None = None) -> list[ModelSpec]:
        return [m for m in self._models.values() if kind is None or m.kind == kind]

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

    # --- mutation ------------------------------------------------------
    def add_user(self, spec: ModelSpec) -> None:
        spec.origin = "user"
        self._models[spec.id] = spec
        self._save_user()

    def remove_user(self, model_id: str) -> None:
        spec = self._models.get(model_id)
        if spec and spec.origin == "user":
            del self._models[model_id]
            self._save_user()
            self.reload()

    def update_from_url(self, url: str, timeout: float = 12.0) -> int:
        """Fetch the remote catalog, validate it, cache it. Returns the model count."""
        if urlparse(url).scheme != "https":
            raise ValueError("catalog URL must use https")
        request = urllib.request.Request(url, headers={"User-Agent": "Tvorka"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read(2_000_000).decode("utf-8")
        specs = _parse(text, "remote")
        if not specs:
            raise ValueError("remote catalog is empty or invalid")
        self.remote_file.write_text(text, encoding="utf-8")
        self.reload()
        return len(specs)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _parse(text: str, origin: str) -> list[ModelSpec]:
    if not text.strip():
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        log.warning("catalog (%s) is not valid YAML: %s", origin, exc)
        return []
    if isinstance(data, dict) and _too_new(data.get("min_app")):
        log.warning("catalog (%s) needs Tvorka %s or newer", origin, data.get("min_app"))
        return []
    out: list[ModelSpec] = []
    for item in (data or {}).get("models", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and _too_new(item.get("min_app")):
            log.info("skipping %s: needs Tvorka %s", item.get("id"), item.get("min_app"))
            continue
        try:
            spec = ModelSpec.from_dict(item, origin)
        except (TypeError, ValueError, KeyError) as exc:
            log.warning("skipping catalog entry: %s", exc)
            continue
        if origin != "builtin" and not _is_safe(spec):
            log.warning("skipping untrusted catalog entry: %s", spec.id)
            continue
        out.append(spec)
    return out


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def _too_new(min_app: Any) -> bool:
    """True when an entry (or the whole catalog) requires a newer app than this one."""
    if not min_app:
        return False
    from tvorka import __version__

    return _version(str(min_app)) > _version(__version__)


def _is_safe(spec: ModelSpec) -> bool:
    """Remote catalogs may only reference Hugging Face repos or trusted hosts."""
    if spec.source == "local":
        return False
    if spec.source == "url":
        return all(
            urlparse(str(f.get("url", ""))).scheme == "https"
            and urlparse(str(f.get("url", ""))).hostname in TRUSTED_URL_HOSTS
            for f in spec.files
        ) and bool(spec.files)
    return True
