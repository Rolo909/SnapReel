"""Everything the pages share: settings, models, history, downloads, the generation worker."""

from __future__ import annotations

import logging
import os
from concurrent.futures import Future
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tvorka.core import hardware, paths
from tvorka.core.advisor import Fit, assess, llm_gpu
from tvorka.core.catalog import Catalog, ModelSpec
from tvorka.core.chats import ChatStore
from tvorka.core.hardware import Hardware
from tvorka.core.jobs import History
from tvorka.core.llm import runtime
from tvorka.core.memory import VideoMemory
from tvorka.core.settings import Settings
from tvorka.core.store import ModelStore
from tvorka.engines.plugins import PluginInfo
from tvorka.workers.chat import ChatSession, ChatWorker
from tvorka.workers.downloads import DownloadManager, run_async
from tvorka.workers.generation import GenerationWorker
from tvorka.workers.stt import SttWorker

log = logging.getLogger(__name__)


def memory_budget(hw: Hardware) -> float:
    """Video memory our models may share: what was free when Tvorka started (the desktop, a browser
    and other programs keep theirs), never more than the card minus a safety margin."""
    gpu = hw.gpu or llm_gpu(hw)
    if gpu is None:
        return 0.0
    free = gpu.vram_free_gb if gpu.vram_free_gb > 0 else gpu.vram_total_gb
    return max(0.0, min(gpu.vram_total_gb - 0.8, free))


class Services(QObject):
    hardware_ready = Signal(object)  # Hardware
    update_available = Signal(object)  # updates.Release
    models_changed = Signal()  # catalog or installed set changed

    def __init__(self, settings: Settings, plugins: list[PluginInfo] | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.plugins = plugins or []
        self.catalog = Catalog()
        self.store = ModelStore(settings)
        self.history = History(paths.data_dir() / "history.json")
        self.downloads = DownloadManager(settings, self.store, self)
        self.worker = GenerationWorker(settings, self.catalog, self.store, self.history)
        self.chat_worker = ChatWorker(paths.data_dir() / "logs" / "llama-server.log")
        self.chat = ChatSession(ChatStore(paths.data_dir() / "chats"), self.chat_worker)
        self.stt = SttWorker()
        self.memory = VideoMemory()  # the chat server and the generation engine share the card
        self.worker.attach_memory(self.memory)
        self.chat_worker.attach_memory(self.memory)
        self.hardware: Hardware | None = None
        self.downloads.finished.connect(lambda _id: self.models_changed.emit())

    def start(self) -> None:
        self.worker.start()
        self.chat_worker.start()
        self.stt.start()
        run_async(hardware.detect, self._on_hardware,
                  lambda exc: log.error("hardware detection failed: %s", exc))
        if self.settings.check_updates:
            self._check_updates()
        if self.settings.auto_update_catalog:
            url = self.settings.catalog_url
            run_async(lambda: self.catalog.update_from_url(url), self._on_catalog_updated,
                      lambda exc: log.info("catalog not updated: %s", exc))  # offline is fine

    def _check_updates(self) -> None:
        from tvorka.core import updates

        run_async(updates.latest_release, self._on_release,
                  lambda exc: log.info("update check skipped: %s", exc))  # offline is fine

    def _on_release(self, release: object) -> None:
        if release is not None:
            log.info("newer release available: %s", release)
            self.update_available.emit(release)

    def _on_catalog_updated(self, count: int) -> None:
        log.info("catalog updated: %d models", count)
        self.models_changed.emit()

    def _on_hardware(self, hw: Hardware) -> None:
        self.hardware = hw
        self.memory.budget_gb = memory_budget(hw)
        self.worker.set_hardware(hw)
        self.hardware_ready.emit(hw)

    # --- helpers used by several pages --------------------------------------
    def installed(self, spec: ModelSpec) -> bool:
        return self.store.is_installed(spec)

    def fit(self, spec: ModelSpec, scale: float = 1.0, reference: str = "", ctx: int = 0) -> Fit | None:
        if self.hardware is None:
            return None
        installed = self.installed(spec)
        disk = None if installed else hardware.disk_free_gb(self.settings.models_path())
        quant = self.store.chat_quant(spec) if spec.kind == "chat" and installed else ""
        return assess(spec, self.hardware, mode=self.settings.performance_mode, scale=scale,
                      disk_free_gb=disk, installed=installed, reference=reference, quant=quant, ctx=ctx)

    def chat_runtime(self) -> ModelSpec | None:
        """The llama.cpp server build for this computer; None until the hardware is known or if none fits."""
        if self.hardware is None:
            return None
        build = runtime.pick_build(self.hardware)
        return runtime.runtime_spec(build) if build else None

    def stt_model(self) -> ModelSpec | None:
        """The speech recognition model to use: the best installed one for this computer."""
        order = ["great", "good", "slow", "very_slow", "no"]
        best: tuple[int, float] | None = None
        chosen = None
        for spec in self.catalog.all("transcribe"):
            if not self.installed(spec):
                continue
            fit = self.fit(spec)
            rank = (order.index(fit.verdict) if fit is not None else 2, -spec.download_gb)  # bigger is better
            if rank[0] < 4 and (best is None or rank < best):
                best, chosen = rank, spec
        return chosen

    def transcribe(self, audio: Path) -> tuple[int, Future[str]] | None:
        """Start recognizing the speech in ``audio``; None when no recognition model is installed."""
        spec = self.stt_model()
        location = self.store.location(spec) if spec is not None else None
        if spec is None or location is None:
            return None
        fit = self.fit(spec)
        device = fit.plan.device if fit is not None and fit.plan.device != "gpu" else "cpu"
        return self.stt.submit(spec.id, location, device, audio)

    def busy(self) -> bool:
        return (self.worker.current_job is not None or self.chat.busy
                or bool(self.downloads.active_ids()))

    def shutdown(self, patience_s: float = 180.0) -> None:
        """Stop generation and downloads, persist settings. Never QThread.terminate().

        A model that is still loading cannot be interrupted (CogVideoX takes ~2 min), so
        the worker gets time to reach a cancellation point. Destroying a running QThread
        would crash the process; as a last resort the process exits without it.
        """
        self.settings.save()
        self.downloads.cancel_all()
        self.chat_worker.shutdown()  # stops the answer and the llama.cpp server
        self.stt.shutdown()
        self.worker.shutdown()
        self.chat_worker.wait(15_000)
        self.stt.wait(15_000)
        waited = 15.0
        while self.worker.isRunning() and waited < patience_s:
            self.worker.wait(1000)
            waited += 1.0
        if self.worker.isRunning():
            log.warning("generation thread still busy after %.0f s; exiting anyway", waited)
            logging.shutdown()
            os._exit(0)
