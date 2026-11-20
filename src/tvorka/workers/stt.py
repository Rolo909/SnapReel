"""Speech recognition in its own thread: the microphone and attachments wait here, generation does not."""

from __future__ import annotations

import itertools
import logging
import queue
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from tvorka.engines.base import EngineError

log = logging.getLogger(__name__)


def default_engine(path: Path, device: str) -> Any:
    from tvorka.engines.whisper import WhisperEngine

    return WhisperEngine(path, device)


@dataclass
class _Request:
    id: int
    model_id: str
    model_path: Path
    device: str
    audio: Path
    future: Future[str] = field(default_factory=Future)


class SttWorker(QThread):
    """Keeps one Whisper model loaded and transcribes files one at a time."""

    transcribed = Signal(int, str)  # request id, text ("" when nothing was said)
    failed = Signal(int, str, str)  # request id, code, detail
    model_changed = Signal(str)  # model id in memory, "" for none

    def __init__(self, engine: Callable[[Path, str], Any] = default_engine) -> None:
        super().__init__()
        self._make_engine = engine
        self._queue: queue.Queue[_Request | str | None] = queue.Queue()
        self._ids = itertools.count(1)
        self._engine: Any = None
        self._loaded: tuple[str, str] = ("", "")  # model path, device

    def submit(self, model_id: str, model_path: Path, device: str, audio: Path) -> tuple[int, Future[str]]:
        """Transcribe ``audio``; the answer comes as a signal and in the returned future."""
        request = _Request(next(self._ids), model_id, model_path, device, audio)
        self._queue.put(request)
        return request.id, request.future

    def unload(self) -> None:
        self._queue.put("unload")

    def shutdown(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if item == "unload":
                self._drop()
            elif isinstance(item, _Request):
                self._handle(item)
        self._drop()

    def _handle(self, request: _Request) -> None:
        try:
            key = (str(request.model_path), request.device)
            if self._engine is None or self._loaded != key:
                self._drop()
                engine = self._make_engine(request.model_path, request.device)
                engine.load()
                self._engine, self._loaded = engine, key
                self.model_changed.emit(request.model_id)
            text = self._engine.transcribe(request.audio)
        except EngineError as exc:
            request.future.set_exception(exc)
            self.failed.emit(request.id, exc.code, exc.detail)
            return
        except Exception as exc:  # the thread must outlive any file
            log.exception("speech recognition failed")
            request.future.set_exception(EngineError("failed", str(exc)))
            self.failed.emit(request.id, "failed", str(exc))
            return
        request.future.set_result(text)
        self.transcribed.emit(request.id, text)

    def _drop(self) -> None:
        if self._engine is not None:
            self._engine.unload()
            self._engine, self._loaded = None, ("", "")
            self.model_changed.emit("")
