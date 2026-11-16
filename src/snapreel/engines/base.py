"""Engine contract shared by every generation backend."""

from __future__ import annotations

import gc
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from snapreel.core import catalog
from snapreel.core.advisor import Plan
from snapreel.core.catalog import ModelSpec
from snapreel.core.jobs import Job, Result

if TYPE_CHECKING:
    from snapreel.core.settings import Settings
    from snapreel.core.store import ModelStore

log = logging.getLogger(__name__)


class Cancelled(Exception):
    """Raised inside an engine when the user cancels the running job."""


class EngineError(Exception):
    """A failure with a message that is safe and useful to show to the user."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class Context:
    """What an engine may use while it works: progress reporting and cancellation."""

    def __init__(
        self, settings: Settings, store: ModelStore,
        progress: Callable[[float, str], None], cancelled: Callable[[], bool],
    ) -> None:
        self.settings = settings
        self.store = store
        self._progress = progress
        self._cancelled = cancelled

    def progress(self, fraction: float, stage: str = "") -> None:
        self._progress(max(0.0, min(1.0, fraction)), stage)

    @property
    def cancelled(self) -> bool:
        return self._cancelled()

    def check(self) -> None:
        if self._cancelled():
            raise Cancelled


class Engine(ABC):
    """Loads one model and produces results. One instance per loaded model."""

    def __init__(self, spec: ModelSpec, plan: Plan) -> None:
        self.spec = spec
        self.plan = plan

    @abstractmethod
    def load(self, ctx: Context) -> None:
        """Bring the model into memory according to ``self.plan``."""

    @abstractmethod
    def generate(self, job: Job, ctx: Context) -> list[Result]:
        """Run one job and return the saved artefacts."""

    def unload(self) -> None:
        """Release all memory held by the model."""
        free_memory()

    def model_path(self, ctx: Context) -> Path:
        path = ctx.store.location(self.spec)
        if path is None or not path.exists():
            raise EngineError("not_installed", self.spec.name)
        return path


def quiet_libraries() -> None:
    """Silence console progress bars and chatter of diffusers / transformers (both have own handlers)."""
    for name in ("diffusers", "transformers"):
        try:
            module = __import__(f"{name}.utils.logging", fromlist=["logging"])
            module.set_verbosity_error()
            module.disable_progress_bar()
        except (ImportError, AttributeError):
            continue


def free_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:  # noqa: BLE001 - best effort; torch may be absent or mid-teardown
        pass


def is_oom(exc: BaseException) -> bool:
    name = exc.__class__.__name__
    text = str(exc).lower()
    return "OutOfMemory" in name or "out of memory" in text or "not enough memory" in text


EngineFactory = Callable[[ModelSpec, Plan], Engine]
_REGISTRY: dict[str, EngineFactory] = {}


def register_engine(name: str, factory: EngineFactory) -> None:
    """Make ``name`` usable as ``ModelSpec.engine``. Plugins call this on import."""
    if not name.isidentifier():
        raise ValueError(f"engine name must be an identifier: {name!r}")
    _REGISTRY[name] = factory
    catalog.ENGINES.add(name)


def registered_engines() -> list[str]:
    return sorted(_REGISTRY)


def create_engine(spec: ModelSpec, plan: Plan) -> Engine:
    factory = _REGISTRY.get(spec.engine)
    if factory is None:
        raise EngineError("unsupported", spec.engine)
    return factory(spec, plan)


# Built-in engines. Factories import lazily: torch and friends load only when a model is used.
def _diffusers(spec: ModelSpec, plan: Plan) -> Engine:
    if spec.kind == "video":
        from snapreel.engines.diffusers_video import DiffusersVideoEngine

        return DiffusersVideoEngine(spec, plan)
    from snapreel.engines.diffusers_image import DiffusersImageEngine

    return DiffusersImageEngine(spec, plan)


def _silero(spec: ModelSpec, plan: Plan) -> Engine:
    from snapreel.engines.tts import SileroEngine

    return SileroEngine(spec, plan)


def _transformers_tts(spec: ModelSpec, plan: Plan) -> Engine:
    from snapreel.engines.tts import TransformersTtsEngine

    return TransformersTtsEngine(spec, plan)


def _edge(spec: ModelSpec, plan: Plan) -> Engine:
    from snapreel.engines.tts import EdgeEngine

    return EdgeEngine(spec, plan)


for _name, _factory in (("diffusers", _diffusers), ("silero", _silero),
                        ("transformers_tts", _transformers_tts), ("edge", _edge)):
    register_engine(_name, _factory)
