"""A stand-in for ``llama-server``: ``/health`` and a streamed ``/v1/chat/completions``.

Used in-process (``serve()``) and as a program (``python llama_stub.py --port N``), so the
process management of ``LlamaServer`` is tested without the real server or a model.
Special prompts: ``"slow"`` streams for a long time, ``"too long"`` overflows the context.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    api_key = ""
    ready_at = 0.0
    requests: list[dict[str, Any]]

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # the client hung up (cancel): expected


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: StubServer

    def log_message(self, *_args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path not in ("/health", "/v1/health"):
            self._json(404, {"error": {"message": "not found"}})
        elif time.monotonic() < self.server.ready_at:
            self._json(503, {"error": {"code": 503, "message": "Loading model"}})
        else:
            self._json(200, {"status": "ok"})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.server.requests.append(body)
        key = self.server.api_key
        if key and self.headers.get("Authorization") != f"Bearer {key}":
            self._json(401, {"error": {"message": "Invalid API Key", "type": "authentication_error"}})
            return
        prompt = body["messages"][-1]["content"]
        if prompt == "too long":
            self._json(400, {"error": {"code": 400, "type": "exceed_context_size_error",
                                       "message": "request exceeds the available context size"}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        pieces: list[dict[str, str]] = [{"reasoning_content": "Thinking"}]
        pieces += [{"content": w} for w in ("Hello", ", ", "world")]
        delay = 0.0
        if prompt == "slow":
            pieces, delay = [{"content": "x"}] * 2000, 0.01
        for piece in pieces:
            self._event({"choices": [{"index": 0, "delta": piece, "finish_reason": None}]})
            time.sleep(delay)
        self._event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "timings": {"predicted_per_second": 42.0}})
        self._event({"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
        self._chunk(b"data: [DONE]\n\n")
        self._chunk(b"")

    def _event(self, payload: dict[str, Any]) -> None:
        self._chunk(f"data: {json.dumps(payload)}\n\n".encode())

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(port: int = 0, api_key: str = "", load_seconds: float = 0.0) -> StubServer:
    server = StubServer(("127.0.0.1", port), Handler)
    server.api_key, server.ready_at, server.requests = api_key, time.monotonic() + load_seconds, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--load", type=float, default=0.0)
    parser.add_argument("--fail", default="")
    args, _rest = parser.parse_known_args()
    if args.fail:
        print(args.fail, flush=True)
        sys.exit(1)
    serve(args.port, os.environ.get("LLAMA_API_KEY", ""), args.load)
    threading.Event().wait()
