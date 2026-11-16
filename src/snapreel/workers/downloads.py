"""Download manager: one killable subprocess per model, plus small background tasks."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QThread, Signal

from snapreel.core import paths
from snapreel.core.catalog import ModelSpec
from snapreel.core.settings import Settings
from snapreel.core.store import ModelStore

log = logging.getLogger(__name__)


def worker_command(flag: str, argument: str) -> tuple[str, list[str]]:
    """How to re-launch this app in a worker mode (works frozen and from source)."""
    if paths.is_frozen():
        return sys.executable, [flag, argument]
    return sys.executable, ["-m", "snapreel", flag, argument]


class _Download:
    def __init__(self, process: QProcess, task_file: Path) -> None:
        self.process = process
        self.task_file = task_file
        self.done = 0
        self.total = 0
        self.speed = 0.0
        self.error: tuple[str, str] | None = None
        self.finished = False
        self._mark = (time.monotonic(), 0)

    def update(self, done: int, total: int) -> None:
        self.done, self.total = done, total
        now = time.monotonic()
        if now - self._mark[0] >= 1.5:
            fresh = max(0.0, (done - self._mark[1]) / (now - self._mark[0]))
            self.speed = fresh if self.speed == 0 else self.speed * 0.6 + fresh * 0.4
            self._mark = (now, done)


class DownloadManager(QObject):
    progress = Signal(str, object, object, float)  # model id, done bytes, total bytes, bytes/s
    finished = Signal(str)
    failed = Signal(str, str, str)  # model id, code, message
    cancelled = Signal(str)

    def __init__(self, settings: Settings, store: ModelStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._store = store
        self._active: dict[str, _Download] = {}

    def is_active(self, model_id: str) -> bool:
        return model_id in self._active

    def state(self, model_id: str) -> tuple[int, int, float] | None:
        item = self._active.get(model_id)
        return (item.done, item.total, item.speed) if item else None

    def active_ids(self) -> list[str]:
        return list(self._active)

    def start(self, spec: ModelSpec) -> None:
        if spec.id in self._active or spec.source not in ("hf", "url"):
            return
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed right below, kept on disk
            "w", suffix=".json", prefix="snapreel-dl-", delete=False, encoding="utf-8")
        with handle:
            json.dump(self._store.download_task(spec), handle)
        program, args = worker_command("--download", handle.name)

        process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        token = self._settings.token()
        if token:
            env.insert("HF_TOKEN", token)
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        item = _Download(process, Path(handle.name))
        self._active[spec.id] = item
        # Bound to this download, not the model id: a cancelled process may report
        # its exit after a new download of the same model has started.
        process.readyReadStandardOutput.connect(lambda: self._read(spec.id, item))
        process.finished.connect(lambda *_: self._on_exit(spec.id, item))
        process.errorOccurred.connect(lambda *_: self._on_exit(spec.id, item))
        process.start(program, args)
        self.progress.emit(spec.id, 0, int(spec.download_gb * 1024**3), 0.0)

    def cancel(self, model_id: str) -> None:
        item = self._active.pop(model_id, None)
        if item is None:
            return
        item.finished = True
        item.process.closeWriteChannel()  # the worker exits on stdin EOF (see download_proc)
        item.process.kill()
        item.task_file.unlink(missing_ok=True)
        self.cancelled.emit(model_id)

    def cancel_all(self) -> None:
        for model_id in list(self._active):
            self.cancel(model_id)

    def _read(self, model_id: str, item: _Download) -> None:
        if self._active.get(model_id) is not item:
            return
        while item.process.canReadLine():
            line = bytes(item.process.readLine().data()).decode("utf-8", "replace").strip()
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("event")
            if kind == "plan":
                item.update(item.done, int(event.get("total") or 0))
            elif kind == "progress":
                item.update(int(event.get("done") or 0), int(event.get("total") or 0))
            elif kind == "error":
                item.error = (str(event.get("code") or "failed"), str(event.get("message") or ""))
            elif kind == "done":
                item.update(item.total, item.total)
            self.progress.emit(model_id, item.done, item.total, item.speed)

    def _on_exit(self, model_id: str, item: _Download) -> None:
        if self._active.get(model_id) is not item or item.finished:
            return
        self._read(model_id, item)
        item.finished = True
        self._active.pop(model_id, None)
        item.task_file.unlink(missing_ok=True)
        ok = item.process.exitStatus() == QProcess.ExitStatus.NormalExit and item.process.exitCode() == 0
        if ok and not item.error:
            self.finished.emit(model_id)
            return
        code, message = item.error or ("failed", "")
        if not message:
            message = bytes(item.process.readAllStandardError().data()).decode("utf-8", "replace")[-600:]
        log.warning("download %s failed: %s %s", model_id, code, message)
        self.failed.emit(model_id, code, message)


class Task(QThread):
    """Run a function off the GUI thread and deliver its result (or exception)."""

    done = Signal(object)
    error = Signal(object)

    _alive: ClassVar[set[Task]] = set()

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        Task._alive.add(self)
        self.finished.connect(lambda: Task._alive.discard(self))

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - delivered to the caller via the signal
            log.info("background task failed: %s", exc)
            self.error.emit(exc)


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None],
              on_error: Callable[[Exception], None] | None = None) -> Task:
    task = Task(fn)
    task.done.connect(on_done)
    if on_error is not None:
        task.error.connect(on_error)
    task.start()
    return task
