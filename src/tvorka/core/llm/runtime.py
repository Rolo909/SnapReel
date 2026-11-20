"""The llama.cpp server: which build suits this computer, where it is, how it runs.

The server is a separate program (``llama-server``) downloaded on demand from the
llama.cpp releases, pinned in ``data/llama_runtime.json`` with SHA-256 checksums.
It listens on 127.0.0.1 only, on a random port, behind a random API key.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from tvorka.core import paths
from tvorka.core.advisor import LlmPlan, llm_gpu
from tvorka.core.catalog import ModelSpec
from tvorka.core.hardware import Hardware
from tvorka.core.llm.client import LlamaClient, LlmError
from tvorka.core.store import ModelStore

log = logging.getLogger(__name__)
GB = 1024**3


def runtime_table() -> dict[str, Any]:
    return json.loads((paths.package_dir() / "data" / "llama_runtime.json").read_text(encoding="utf-8"))


def pick_build(hw: Hardware, system: str = sys.platform, machine: str = "",
               table: dict[str, Any] | None = None) -> str:
    """Name of the server build for this computer; "" when there is none."""
    builds = (table or runtime_table())["builds"]
    machine = (machine or platform.machine()).lower()
    if system == "darwin":
        return "macos-arm64" if machine in ("arm64", "aarch64") else ""
    if machine not in ("amd64", "x86_64", "x64"):
        return ""
    prefix = "win" if system == "win32" else "linux"
    gpu = llm_gpu(hw)
    if gpu is not None and gpu.vendor == "nvidia" and prefix == "win":
        driver = _major(gpu.driver)
        for name, build in builds.items():  # newest CUDA first, as listed
            if build.get("vendor") == "nvidia" and name.startswith(prefix) and driver >= build["min_driver"]:
                return name
    # Vulkan reaches AMD, Intel and older NVIDIA drivers alike.
    name = f"{prefix}-vulkan" if gpu is not None else f"{prefix}-cpu"
    return name if name in builds else ""


def _major(version: str) -> int:
    found = re.match(r"\d+", version.strip())
    return int(found.group()) if found else 0


def runtime_spec(build: str, table: dict[str, Any] | None = None) -> ModelSpec:
    """The server build as a downloadable item (see ``DownloadManager``); never shown in the catalog."""
    table = table or runtime_table()
    version, files = table["version"], table["builds"][build]["files"]
    return ModelSpec(
        id=f"llama.cpp/{version}-{build}", name=f"llama.cpp {version}", kind="chat", engine="llama",
        source="url", author="ggml-org", license="MIT",
        files=[{**f, "extract": True} for f in files],
        download_gb=round(sum(int(f["size"]) for f in files) / GB, 2),
    )


def server_path(store: ModelStore, spec: ModelSpec) -> Path | None:
    """The installed ``llama-server`` executable of ``spec``, or None."""
    folder = store.location(spec)
    if folder is None or not folder.is_dir():
        return None
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    return next(iter(sorted(folder.rglob(name))), None)


def server_command(exe: Path, model: Path, plan: LlmPlan, port: int,
                   projector: Path | None = None, mtp: Path | None = None) -> list[str]:
    """Arguments that make the server do exactly what the advisor promised.

    ``mtp`` is the model's multi-token prediction head; it is used only when the plan says so.
    """
    layers = "all" if plan.all_on_gpu else str(plan.gpu_layers)
    command = [str(exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
               "-c", str(plan.ctx), "-ngl", layers, "-np", "1", "--no-webui"]
    if plan.device == "cpu":
        command += ["--device", "none"]  # keep even scratch buffers off the GPU
    if plan.cpu_moe_layers:
        command += ["--n-cpu-moe", str(plan.cpu_moe_layers)]
    if plan.kv_type != "f16":
        command += ["-ctk", plan.kv_type, "-ctv", plan.kv_type]
    if plan.mtp and mtp is not None:
        command += ["--spec-type", "draft-mtp", "-md", str(mtp), "-ngld", "all"]
    if projector is not None:
        command += ["--mmproj", str(projector)]
        if not plan.projector_on_gpu:
            command.append("--no-mmproj-offload")
    return command


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class LlamaServer:
    """One running ``llama-server`` process with one model loaded."""

    def __init__(self, log_file: Path) -> None:
        self._log_file = log_file
        self._log: IO[bytes] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._job: Any = None
        self.port = 0
        self.api_key = ""

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def client(self) -> LlamaClient:
        return LlamaClient(self.base_url, self.api_key)

    def start(self, command: list[str], port: int) -> None:
        """Launch ``command`` (from :func:`server_command`, listening on ``port``)."""
        self.stop()
        self.port, self.api_key = port, secrets.token_urlsafe(24)
        env = {**os.environ, "LLAMA_API_KEY": self.api_key}  # not on the command line: others can read that
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log = open(self._log_file, "wb")  # noqa: SIM115 - closed in stop()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("starting llama-server: %s", " ".join(command))
        self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self._log,
                                         stderr=subprocess.STDOUT, env=env, creationflags=flags,
                                         cwd=str(Path(command[0]).parent))
        self._job = _kill_with_parent(self._process)

    def wait_ready(self, timeout: float = 900.0, cancelled: Callable[[], bool] = lambda: False,
                   poll: float = 0.25) -> None:
        """Block until the model is loaded. Raises :class:`LlmError` and stops the server on failure."""
        client = self.client()
        deadline = time.monotonic() + timeout
        while True:
            if self._process is None or self._process.poll() is not None:
                code = failure_code(self.log_tail())
                self.stop()
                raise LlmError(code, self.log_tail(1500))
            if cancelled():
                self.stop()
                raise LlmError("cancelled")
            with contextlib.suppress(LlmError):  # not listening yet
                if client.health() == "ok":
                    return
            if time.monotonic() > deadline:
                self.stop()
                raise LlmError("timeout")
            time.sleep(poll)

    def stop(self, grace: float = 5.0) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(grace)
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._job is not None:
            _close_handle(self._job)
            self._job = None

    def log_tail(self, size: int = 6000) -> str:
        try:
            data = self._log_file.read_bytes()[-size:]
        except OSError:
            return ""
        return data.decode("utf-8", "replace")


def failure_code(log_text: str) -> str:
    """Why the server exited, judged by its log."""
    low = log_text.lower()
    if any(k in low for k in ("out of memory", "failed to allocate", "cudamalloc failed",
                              "erroroutofdevicememory", "unable to allocate")):
        return "out_of_memory"
    if "unknown model architecture" in low or "unsupported model" in low:
        return "unsupported"
    if "failed to load model" in low or "error loading model" in low or "failed to open" in low:
        return "load_failed"
    return "failed"


# ------------------------------------------------------------------ Windows: die with the app
def _kill_with_parent(process: subprocess.Popen[bytes]) -> Any:
    """Put the server in a job object that ends it when Tvorka ends, even after a crash.

    Otherwise an orphaned server would keep gigabytes of video memory until reboot.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                                 wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) and \
        kernel32.AssignProcessToJobObject(job, int(process._handle))  # type: ignore[attr-defined]
    if not ok:
        log.warning("llama-server is not tied to the app (error %s)", ctypes.get_last_error())
        _close_handle(job)
        return None
    return job


def _close_handle(handle: Any) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.WinDLL("kernel32").CloseHandle(handle)
