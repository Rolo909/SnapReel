"""Everything the pages share: settings, models, history, downloads, the generation worker."""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, Signal

from tvorka.core import hardware, paths
from tvorka.core.advisor import Fit, assess
from tvorka.core.catalog import Catalog, ModelSpec
from tvorka.core.hardware import Hardware
from tvorka.core.jobs import History
from tvorka.core.settings import Settings
from tvorka.core.store import ModelStore
from tvorka.engines.plugins import PluginInfo
from tvorka.workers.downloads import DownloadManager, run_async
from tvorka.workers.generation import GenerationWorker

log = logging.getLogger(__name__)


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
        self.hardware: Hardware | None = None
        self.downloads.finished.connect(lambda _id: self.models_changed.emit())

    def start(self) -> None:
        self.worker.start()
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
        self.worker.set_hardware(hw)
        self.hardware_ready.emit(hw)

    # --- helpers used by several pages --------------------------------------
    def installed(self, spec: ModelSpec) -> bool:
        return self.store.is_installed(spec)

    def fit(self, spec: ModelSpec, scale: float = 1.0, reference: str = "") -> Fit | None:
        if self.hardware is None:
            return None
        installed = self.installed(spec)
        disk = None if installed else hardware.disk_free_gb(self.settings.models_path())
        return assess(spec, self.hardware, mode=self.settings.performance_mode, scale=scale,
                      disk_free_gb=disk, installed=installed, reference=reference)

    def busy(self) -> bool:
        return self.worker.current_job is not None or bool(self.downloads.active_ids())

    def shutdown(self, patience_s: float = 180.0) -> None:
        """Stop generation and downloads, persist settings. Never QThread.terminate().

        A model that is still loading cannot be interrupted (CogVideoX takes ~2 min), so
        the worker gets time to reach a cancellation point. Destroying a running QThread
        would crash the process; as a last resort the process exits without it.
        """
        self.settings.save()
        self.downloads.cancel_all()
        self.worker.shutdown()
        waited = 15.0
        while self.worker.isRunning() and waited < patience_s:
            self.worker.wait(1000)
            waited += 1.0
        if self.worker.isRunning():
            log.warning("generation thread still busy after %.0f s; exiting anyway", waited)
            logging.shutdown()
            os._exit(0)
