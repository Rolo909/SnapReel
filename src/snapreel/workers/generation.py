"""Generation thread: one job at a time, the model stays loaded between jobs."""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import asdict
from typing import Any

from PySide6.QtCore import QThread, Signal

from snapreel.core import advisor
from snapreel.core.advisor import Plan
from snapreel.core.catalog import Catalog
from snapreel.core.hardware import Hardware
from snapreel.core.jobs import History, Job
from snapreel.core.settings import Settings
from snapreel.core.store import ModelStore
from snapreel.engines.base import (
    Cancelled,
    Context,
    Engine,
    EngineError,
    create_engine,
    free_memory,
    is_oom,
)

log = logging.getLogger(__name__)

_UNLOAD = object()


class GenerationWorker(QThread):
    """Owns the loaded engine. All heavy imports (torch, diffusers) happen here."""

    job_started = Signal(int)
    job_progress = Signal(int, float, str)  # id, fraction, stage code
    job_finished = Signal(int, list)  # id, [Result as dict]
    job_failed = Signal(int, str, str)  # id, error code, detail
    job_cancelled = Signal(int)
    model_changed = Signal(str)  # id of the model held in memory, "" when none
    queue_changed = Signal(int)  # jobs waiting or running

    def __init__(self, settings: Settings, catalog: Catalog, store: ModelStore,
                 history: History) -> None:
        super().__init__()
        self._settings = settings
        self._catalog = catalog
        self._store = store
        self._history = history
        self._queue: queue.Queue[Any] = queue.Queue()
        self._cancel: set[int] = set()
        self._lock = threading.Lock()
        self._jobs: set[int] = set()  # submitted and not finished yet
        self._engine: Engine | None = None
        self._hardware: Hardware | None = None
        self._stopping = False
        self.current_job: int | None = None

    # --- called from the GUI thread ------------------------------------
    def set_hardware(self, hardware: Hardware) -> None:
        self._hardware = hardware

    def submit(self, job: Job) -> int:
        with self._lock:
            self._jobs.add(job.id)
            pending = len(self._jobs)
        self._queue.put(job)
        self.queue_changed.emit(pending)
        return job.id

    def cancel(self, job_id: int | None = None) -> None:
        """Cancel one job, or everything queued and running when ``job_id`` is None.

        Cancelling everything marks the jobs known right now, so a job submitted
        immediately afterwards still runs.
        """
        with self._lock:
            if job_id is None:
                self._cancel |= self._jobs
            elif job_id in self._jobs:
                self._cancel.add(job_id)

    def unload_model(self) -> None:
        self._queue.put(_UNLOAD)

    def shutdown(self) -> None:
        self._stopping = True
        self.cancel(None)
        self._queue.put(None)
        self.wait(15000)

    @property
    def loaded_model(self) -> str:
        return self._engine.spec.id if self._engine else ""

    # --- worker thread -------------------------------------------------
    def _is_cancelled(self, job_id: int) -> bool:
        with self._lock:
            return self._stopping or job_id in self._cancel

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if item is _UNLOAD:
                self._drop_engine()
                continue
            job: Job = item
            self.current_job = job.id
            try:
                self._run_job(job)
            finally:
                self.current_job = None
                with self._lock:
                    self._jobs.discard(job.id)
                    self._cancel.discard(job.id)
                    pending = len(self._jobs)
                self.queue_changed.emit(pending)
        self._drop_engine()

    def _run_job(self, job: Job) -> None:
        if self._is_cancelled(job.id):
            self.job_cancelled.emit(job.id)
            return
        self.job_started.emit(job.id)
        ctx = Context(
            self._settings, self._store,
            lambda fraction, stage: self.job_progress.emit(job.id, fraction, stage),
            lambda: self._is_cancelled(job.id),
        )
        try:
            spec = self._catalog.get(job.model_id)
            if spec is None:
                raise EngineError("model_missing", job.model_id)
            plan = self._plan(spec, job)
            results = self._attempt(spec, plan, job, ctx)
            if not job.get("preview"):  # voice samples and other previews stay out of the gallery
                for result in results:
                    self._history.add(result)
            self.job_finished.emit(job.id, [asdict(r) for r in results])
        except Cancelled:
            self.job_cancelled.emit(job.id)
        except EngineError as exc:
            log.warning("job %s failed: %s %s", job.id, exc.code, exc.detail)
            self.job_failed.emit(job.id, exc.code, exc.detail)
        except Exception as exc:
            log.exception("job %s crashed", job.id)
            if is_oom(exc):
                self._drop_engine()
                self.job_failed.emit(job.id, "out_of_memory", "")
            else:
                self.job_failed.emit(job.id, "failed", f"{exc.__class__.__name__}: {exc}"[:800])
        finally:
            if not self._settings.keep_model_loaded:
                self._drop_engine()

    def _plan(self, spec: Any, job: Job) -> Plan:
        if self._hardware is None:
            return Plan()
        width, height = int(job.get("width", spec.native[0])), int(job.get("height", spec.native[1]))
        frames = 1
        if spec.kind in ("image", "video"):  # memory depends on what the model draws, not the final size
            width, height, _route = advisor.resolution_route(spec, width, height)
        if spec.kind == "video":
            seconds = job.get("seconds")
            frames, _capped = advisor.video_frames(spec, job.get("frames"),
                                                   float(seconds) if seconds else None)
        scale = advisor.work_scale(spec, width, height, frames)
        reference = str(job.get("reference_mode") or "") if job.get("reference") else ""
        fit = advisor.assess(spec, self._hardware, mode=self._settings.performance_mode, scale=scale,
                             reference=reference)
        if not fit.ok:
            raise EngineError("does_not_fit", spec.name)
        return fit.plan

    def _attempt(self, spec: Any, plan: Plan, job: Job, ctx: Context) -> list[Any]:
        """Run a job, stepping down to a leaner memory plan if the GPU runs out."""
        while True:
            try:
                engine = self._ensure_engine(spec, plan, ctx)
                return engine.generate(job, ctx)
            except Exception as exc:
                lower = plan.downgraded()
                if not is_oom(exc) or lower is None:
                    raise
                log.warning("out of memory in mode %s, retrying as %s", plan.mode, lower.mode)
                self._drop_engine()
                ctx.progress(0.0, "retry_low_memory")
                plan = lower

    def _ensure_engine(self, spec: Any, plan: Plan, ctx: Context) -> Engine:
        engine = self._engine
        if engine is not None and engine.spec.id == spec.id and engine.plan == plan:
            return engine
        self._drop_engine()
        engine = create_engine(spec, plan)
        try:
            engine.load(ctx)
        except BaseException:
            engine.unload()
            raise
        ctx.check()
        self._engine = engine
        self.model_changed.emit(spec.id)
        return engine

    def _drop_engine(self) -> None:
        if self._engine is not None:
            try:
                self._engine.unload()
            except Exception:
                log.exception("unload failed")
            self._engine = None
            self.model_changed.emit("")
        free_memory()
