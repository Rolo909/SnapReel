"""Client for the llama.cpp server's OpenAI-compatible API, with streamed answers.

``http.client`` instead of a higher-level library: cancelling must interrupt a read
that may block for minutes while a long prompt is processed, and shutting down the
socket from another thread does exactly that.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


class LlmError(Exception):
    """A problem the UI explains by ``code``: not_running, loading, context_overflow, cancelled…"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class Delta:
    """A piece of a streamed answer. The last one carries ``finish`` and the token counts."""

    content: str = ""
    reasoning: str = ""
    finish: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LlamaClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 3600.0) -> None:
        url = urlparse(base_url)
        self._host, self._port = url.hostname or "127.0.0.1", url.port or 80
        self._api_key = api_key
        self._timeout = timeout
        self._lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None
        self._cancelled = False

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def health(self, timeout: float = 2.0) -> str:
        """``"ok"`` when the model is loaded, ``"loading"`` while it loads."""
        conn = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        try:
            conn.request("GET", "/health")
            response = conn.getresponse()
            response.read()
        except OSError as exc:
            raise LlmError("not_running", str(exc)) from exc
        finally:
            conn.close()
        if response.status == 200:
            return "ok"
        if response.status == 503:
            return "loading"
        raise LlmError("server", f"health: HTTP {response.status}")

    def chat(self, messages: list[dict[str, Any]], **params: Any) -> Iterator[Delta]:
        """Stream an answer. ``cancel()`` from another thread ends it with ``LlmError("cancelled")``."""
        body = {"messages": messages, "stream": True, "stream_options": {"include_usage": True}, **params}
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)
        with self._lock:
            self._cancelled = False
            self._conn = conn
        try:
            conn.request("POST", "/v1/chat/completions", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                         self._headers())
            response = conn.getresponse()
            if response.status != 200:
                raise _http_error(response.status, response.read())
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = _delta(json.loads(data))
                if delta is not None:
                    yield delta
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if self._cancelled:
                raise LlmError("cancelled") from exc
            if isinstance(exc, ConnectionRefusedError):
                raise LlmError("not_running", str(exc)) from exc
            raise LlmError("connection", f"{exc.__class__.__name__}: {exc}") from exc
        finally:
            with self._lock:
                self._conn = None
            conn.close()
        if self._cancelled:
            raise LlmError("cancelled")

    def cancel(self) -> None:
        """Stop the answer being streamed; the server stops generating when the client goes away."""
        with self._lock:
            self._cancelled = True
            sock = self._conn.sock if self._conn is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed


def _delta(chunk: dict[str, Any]) -> Delta | None:
    if "error" in chunk:
        error = chunk["error"] if isinstance(chunk["error"], dict) else {"message": str(chunk["error"])}
        raise _error_code(error)
    choices = chunk.get("choices") or []
    usage = {**(chunk.get("usage") or {}), **(chunk.get("timings") or {})}
    if not choices:
        return Delta(usage=usage) if usage else None
    choice = choices[0]
    delta = choice.get("delta") or {}
    return Delta(str(delta.get("content") or ""), str(delta.get("reasoning_content") or ""),
                 str(choice.get("finish_reason") or ""), usage)


def _http_error(status: int, body: bytes) -> LlmError:
    try:
        error = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {"message": str(error)}
    if status == 401:
        return LlmError("auth", str(error.get("message", "")))
    if status == 503:
        return LlmError("loading", str(error.get("message", "")))
    error.setdefault("message", f"HTTP {status}")
    return _error_code(error)


def _error_code(error: dict[str, Any]) -> LlmError:
    message = str(error.get("message", ""))
    if error.get("type") == "exceed_context_size_error" or "context" in message.lower():
        return LlmError("context_overflow", message)
    return LlmError("server", message)
