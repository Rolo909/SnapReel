"""Chat answers: the llama.cpp server driven from a worker thread, the conversations in the GUI thread.

``ChatWorker`` owns the ``llama-server`` process: it starts it for the model a request
names (or reuses the running one), streams the answer and stops on request.
``ChatSession`` keeps the conversations and the answer being written; pages only show
it, so rebuilding the window (language, theme) does not interrupt an answer.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from tvorka.core.advisor import LlmPlan
from tvorka.core.attachments import Attachment
from tvorka.core.chats import (
    ChatStore,
    Conversation,
    Message,
    clean_title,
    context_messages,
    default_title,
    request_params,
)
from tvorka.core.llm import runtime
from tvorka.core.llm.client import LlamaClient, LlmError
from tvorka.core.memory import VideoMemory

log = logging.getLogger(__name__)

TITLE_PROMPT = ("Write a title of 2–5 words for a conversation that starts with the message below. "
                "Use the language of the message. Reply with the title only.\n\n{text}")
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}  # ignored by models without the switch
STATS = ("predicted_per_second", "prompt_per_second", "prompt_tokens", "completion_tokens", "finish")


@dataclass(frozen=True)
class Launch:
    """Everything that decides how the server runs; a different one restarts it."""

    model_id: str
    exe: Path
    model: Path
    plan: LlmPlan
    projector: Path | None = None
    mtp: Path | None = None
    vram_gb: float = 0.0  # what the advisor expects it to take on the graphics card


def default_command(launch: Launch, port: int) -> list[str]:
    return runtime.server_command(launch.exe, launch.model, launch.plan, port, launch.projector, launch.mtp)


@dataclass
class _Request:
    id: int
    launch: Launch
    messages: list[dict[str, Any]]
    params: dict[str, Any]
    title_for: str = ""


class ChatWorker(QThread):
    loading = Signal(int)  # request id: the model is being loaded first
    delta = Signal(int, str, str)  # request id, more answer text, more reasoning text
    finished = Signal(int, dict)  # request id, token counts and speed
    failed = Signal(int, str, str)  # request id, code, detail
    cancelled = Signal(int)
    titled = Signal(int, str)  # request id, a title for its conversation
    model_changed = Signal(str)  # the model now in memory, "" for none

    def __init__(self, log_file: Path, command: Callable[[Launch, int], list[str]] = default_command,
                 flush_s: float = 0.05, ready_timeout_s: float = 900.0) -> None:
        super().__init__()
        self._command = command
        self._flush_s = flush_s  # the interface redraws an answer at most 20 times a second
        self._ready_timeout_s = ready_timeout_s
        self._queue: queue.Queue[_Request | str | None] = queue.Queue()
        self._server = runtime.LlamaServer(log_file)
        self._launch: Launch | None = None
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._current = 0
        self._cancelled: set[int] = set()
        self._client: LlamaClient | None = None
        self._quitting = False
        self._busy = threading.RLock()  # held while the server is used; the arbiter waits on it
        self._memory: VideoMemory | None = None

    def attach_memory(self, memory: VideoMemory) -> None:
        """Share the graphics card with image, video and voice models through ``memory``."""
        self._memory = memory
        memory.register("chat", self._release)

    def _release(self, cancelled: Callable[[], bool]) -> bool:
        """Called from another thread: stop the server once the current answer is written."""
        while not self._busy.acquire(timeout=0.2):
            if cancelled():
                return False
        try:
            self._stop_server()
        finally:
            self._busy.release()
        return True

    @property
    def loaded_model(self) -> str:
        launch = self._launch
        return launch.model_id if launch is not None and self._server.running else ""

    # --- called from the GUI thread ---------------------------------------------------
    def submit(self, launch: Launch, messages: list[dict[str, Any]], params: dict[str, Any],
               title_for: str = "") -> int:
        request = _Request(next(self._ids), launch, messages, params, title_for)
        self._queue.put(request)
        return request.id

    def cancel(self, request_id: int) -> None:
        with self._lock:
            self._cancelled.add(request_id)
            client = self._client if request_id == self._current else None
        if client is not None:
            client.cancel()

    def unload(self) -> None:
        self._queue.put("unload")

    def shutdown(self) -> None:
        self._quitting = True
        with self._lock:
            current = self._current
        if current:
            self.cancel(current)
        self._queue.put(None)

    # --- worker thread ----------------------------------------------------------------
    def run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            if item == "unload":
                self._stop_server()
            elif isinstance(item, _Request):
                self._handle(item)
        self._stop_server()

    def _is_cancelled(self, request_id: int) -> bool:
        with self._lock:
            return self._quitting or request_id in self._cancelled

    def _handle(self, request: _Request) -> None:
        with self._lock:
            self._current = request.id
        try:
            if self._is_cancelled(request.id):
                raise LlmError("cancelled")
            if not self._ready_for(request):
                self.loading.emit(request.id)  # making room and loading may take a while
            launch = request.launch
            if self._memory is not None and not self._memory.claim(
                    "chat", launch.model_id, launch.vram_gb, lambda: self._is_cancelled(request.id)):
                raise LlmError("cancelled")
            with self._busy:
                self._ensure_server(request)
                self.finished.emit(request.id, self._stream(request))
                if request.title_for and not self._is_cancelled(request.id):
                    self._title(request)
        except LlmError as exc:
            if exc.code == "cancelled":
                self.cancelled.emit(request.id)
            else:
                self.failed.emit(request.id, self._explain(exc), exc.detail)
        except Exception as exc:  # the thread must survive anything a request brings
            log.exception("chat request failed")
            self.failed.emit(request.id, "failed", str(exc))
        finally:
            with self._lock:
                self._current, self._client = 0, None
                self._cancelled.discard(request.id)
            if self._memory is not None and not self._server.running:
                self._memory.released("chat")  # it did not load, or it crashed

    def _ready_for(self, request: _Request) -> bool:
        return request.launch == self._launch and self._server.running

    def _ensure_server(self, request: _Request) -> None:
        if self._ready_for(request):
            return
        self._stop_server(keep_claim=True)  # the memory for the new model is already claimed
        port = runtime.free_port()
        command = self._command(request.launch, port)
        self._server.start(command, port)
        self._server.wait_ready(self._ready_timeout_s, lambda: self._is_cancelled(request.id))
        self._launch = request.launch
        self.model_changed.emit(request.launch.model_id)

    def _stream(self, request: _Request) -> dict[str, Any]:
        client = self._server.client()
        with self._lock:
            self._client = client
        usage: dict[str, Any] = {}
        text, reasoning, last = "", "", time.monotonic()
        try:
            for delta in client.chat(request.messages, **request.params):
                if self._is_cancelled(request.id):
                    client.cancel()
                usage.update(delta.usage)
                if delta.finish:
                    usage["finish"] = delta.finish  # "length": the answer ran out of room
                text += delta.content
                reasoning += delta.reasoning
                if (text or reasoning) and time.monotonic() - last >= self._flush_s:
                    self.delta.emit(request.id, text, reasoning)
                    text, reasoning, last = "", "", time.monotonic()
        finally:  # a stopped answer keeps every word already received
            if text or reasoning:
                self.delta.emit(request.id, text, reasoning)
        return {key: usage[key] for key in STATS if key in usage}

    def _title(self, request: _Request) -> None:
        prompt = TITLE_PROMPT.format(text=request.title_for[:2000])
        try:
            answer = "".join(d.content for d in self._server.client().chat(
                [{"role": "user", "content": prompt}], max_tokens=64, temperature=0.2, **NO_THINKING))
        except LlmError as exc:
            log.info("no title for the chat: %s", exc.code)
            return
        title = clean_title(answer)
        if title:
            self.titled.emit(request.id, title)

    def _explain(self, exc: LlmError) -> str:
        """A server that died mid-answer is restarted by the next request; say why it died."""
        if exc.code in ("not_running", "connection") and not self._server.running:
            code = runtime.failure_code(self._server.log_tail())
            self._stop_server()
            return "crashed" if code == "failed" else code
        return exc.code

    def _stop_server(self, keep_claim: bool = False) -> None:
        with self._busy:
            had = self._launch is not None
            self._server.stop()
            self._launch = None
            if self._memory is not None and not keep_claim:
                self._memory.released("chat")
            if had:
                self.model_changed.emit("")


class ChatSession(QObject):
    """The conversations and the answer being written, kept between window rebuilds."""

    listed = Signal()  # conversations added, removed or reordered
    changed = Signal(str)  # conversation id: its messages or title changed
    streaming = Signal(str)  # conversation id: the answer being written grew
    state_changed = Signal()  # started or finished answering, began loading the model
    failed = Signal(str, str, str)  # conversation id, code, detail

    def __init__(self, store: ChatStore, worker: ChatWorker) -> None:
        super().__init__()
        self.store = store
        self.worker = worker
        self.conversations = store.all()
        self.answering = ""  # conversation id
        self.pending: dict[str, list[Attachment]] = {}  # conversation id -> files for the next message
        self.loading = False
        self.partial: Message | None = None
        self._request = 0
        self._titles: dict[int, str] = {}  # request id -> conversation id
        worker.loading.connect(self._on_loading)
        worker.delta.connect(self._on_delta)
        worker.finished.connect(self._on_finished)
        worker.cancelled.connect(self._on_cancelled)
        worker.failed.connect(self._on_failed)
        worker.titled.connect(self._on_titled)

    def get(self, conv_id: str) -> Conversation | None:
        return next((c for c in self.conversations if c.id == conv_id), None)

    @property
    def busy(self) -> bool:
        return bool(self.answering)

    def delete(self, conv_id: str) -> None:
        if conv_id == self.answering:
            self.stop()
        self.conversations = [c for c in self.conversations if c.id != conv_id]
        self.store.delete(conv_id)
        self.listed.emit()

    def save(self, conv: Conversation) -> None:
        conv.updated = time.time()
        if self.get(conv.id) is None:
            self.conversations.insert(0, conv)
        self.conversations.sort(key=lambda c: c.updated, reverse=True)
        self.store.save(conv)
        self.listed.emit()

    def send(self, conv: Conversation, launch: Launch, ctx: int, reasoning: bool = False) -> int:
        """Ask for an answer to the conversation as it is; returns how many old messages did not fit.

        ``reasoning``: the model can think before answering (``Conversation.thinking`` decides).
        """
        first = next((m for m in conv.messages if m.role == "user"), None)
        text = first.content if first is not None else ""
        named = text or ", ".join(a.name for a in first.files) if first is not None else ""
        title_for = text if not conv.title else ""
        conv.title = conv.title or default_title(named)
        self.save(conv)
        messages, dropped = context_messages(conv, ctx, self.store.files_dir(conv.id),
                                             vision=launch.projector is not None)
        self.partial = Message("assistant", model=launch.model_id)
        self.answering, self.loading = conv.id, False
        self._request = self.worker.submit(launch, messages, request_params(conv, reasoning), title_for)
        if title_for:
            self._titles[self._request] = conv.id
        self.state_changed.emit()
        return dropped

    def stop(self) -> None:
        if self._request:
            self.worker.cancel(self._request)

    # --- worker events ----------------------------------------------------------------
    def _on_loading(self, request_id: int) -> None:
        if request_id == self._request:
            self.loading = True
            self.state_changed.emit()

    def _on_delta(self, request_id: int, text: str, reasoning: str) -> None:
        if request_id != self._request or self.partial is None:
            return
        if self.loading:
            self.loading = False
            self.state_changed.emit()
        self.partial.content += text
        self.partial.reasoning += reasoning
        self.streaming.emit(self.answering)

    def _on_finished(self, request_id: int, stats: dict) -> None:
        if request_id == self._request and self.partial is not None:
            self.partial.stats = dict(stats)
            self._close(stopped=stats.get("finish") == "length")

    def _on_cancelled(self, request_id: int) -> None:
        self._titles.pop(request_id, None)
        if request_id == self._request:
            self._close(stopped=True)

    def _on_failed(self, request_id: int, code: str, detail: str) -> None:
        self._titles.pop(request_id, None)
        if request_id == self._request:
            conv_id = self.answering
            self._close(stopped=True)
            self.failed.emit(conv_id, code, detail)

    def _on_titled(self, request_id: int, title: str) -> None:
        conv = self.get(self._titles.pop(request_id, ""))
        if conv is not None:
            conv.title = title
            self.store.save(conv)
            self.changed.emit(conv.id)
            self.listed.emit()

    def _close(self, stopped: bool) -> None:
        conv, partial = self.get(self.answering), self.partial
        self.answering, self.loading, self.partial, self._request = "", False, None, 0
        if conv is not None and partial is not None and (partial.content or partial.reasoning):
            partial.stopped = stopped
            conv.messages.append(partial)
            self.save(conv)
        self.state_changed.emit()
        if conv is not None:
            self.changed.emit(conv.id)
