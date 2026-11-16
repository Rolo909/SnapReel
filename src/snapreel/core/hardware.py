"""Hardware detection: CPU, RAM, GPUs, and the installed PyTorch build.

Nothing here imports torch — importing it costs several seconds, so the
build is read from ``torch/version.py`` on disk instead.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psutil

log = logging.getLogger(__name__)

GB = 1024**3


@dataclass(frozen=True)
class GpuInfo:
    name: str
    vendor: str  # "nvidia" | "amd" | "intel" | "apple" | "other"
    vram_total_gb: float
    vram_free_gb: float
    driver: str = ""


@dataclass(frozen=True)
class TorchBuild:
    installed: bool = False
    version: str = ""
    cuda: str = ""  # CUDA runtime version the wheel was built with, "" for CPU builds

    @property
    def has_cuda(self) -> bool:
        return bool(self.cuda)


@dataclass(frozen=True)
class Hardware:
    os_name: str
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_free_gb: float
    swap_gb: float
    gpus: tuple[GpuInfo, ...] = ()
    torch: TorchBuild = field(default_factory=TorchBuild)

    @property
    def gpu(self) -> GpuInfo | None:
        """The GPU generation will run on: the largest one PyTorch can use."""
        usable = [g for g in self.gpus if g.vendor in ("nvidia", "apple")]
        return max(usable, key=lambda g: g.vram_total_gb) if usable else None

    @property
    def device(self) -> str:
        """Torch device string generation will actually use."""
        gpu = self.gpu
        if gpu is None:
            return "cpu"
        if gpu.vendor == "apple":
            return "mps"
        return "cuda" if self.torch.has_cuda else "cpu"

    @property
    def issues(self) -> list[str]:
        """Machine-readable problems the UI explains and offers to fix."""
        out: list[str] = []
        if not self.torch.installed:
            out.append("torch_missing")
        elif any(g.vendor == "nvidia" for g in self.gpus) and not self.torch.has_cuda:
            out.append("torch_cpu_build")
        if self.gpus and self.gpu is None:
            out.append("gpu_unsupported")
        if not self.gpus:
            out.append("no_gpu")
        if self.ram_total_gb < 15:
            out.append("low_ram")
        return out


def detect() -> Hardware:
    """Collect a full hardware snapshot. Safe to call from a worker thread."""
    mem = psutil.virtual_memory()
    try:
        swap = psutil.swap_memory().total / GB
    except (OSError, RuntimeError):
        swap = 0.0
    gpus = _nvidia_gpus()
    if not gpus:
        gpus = _apple_gpu(mem.total / GB) or _other_gpus()
    hw = Hardware(
        os_name=f"{platform.system()} {platform.release()}",
        cpu_name=_cpu_name(),
        cpu_cores=psutil.cpu_count(logical=False) or 1,
        cpu_threads=psutil.cpu_count(logical=True) or 1,
        ram_total_gb=mem.total / GB,
        ram_free_gb=mem.available / GB,
        swap_gb=swap,
        gpus=tuple(gpus),
        torch=torch_build(),
    )
    log.info("hardware: %s", hw)
    return hw


def free_memory() -> tuple[float, float | None]:
    """Cheap live reading: (free RAM GB, free VRAM GB or None)."""
    ram = psutil.virtual_memory().available / GB
    gpus = _nvidia_gpus()
    return ram, (gpus[0].vram_free_gb if gpus else None)


def disk_free_gb(path: Path) -> float:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free / GB
    except OSError:
        return 0.0


def torch_build() -> TorchBuild:
    try:
        spec = importlib.util.find_spec("torch")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.origin:
        return TorchBuild()
    try:
        text = (Path(spec.origin).parent / "version.py").read_text(encoding="utf-8")
    except OSError:
        return TorchBuild(installed=True)
    version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", text)
    cuda = re.search(r"^cuda[^=\n]*=\s*['\"]([^'\"]+)", text, re.MULTILINE)
    return TorchBuild(True, version.group(1) if version else "", cuda.group(1) if cuda else "")


CUDA_INDEX = "https://download.pytorch.org/whl/cu130"


def release_home() -> Path | None:
    """The release folder when SnapReel was installed by its first-run installer."""
    home = os.environ.get("SNAPREEL_HOME")
    if home and (Path(home) / "app" / "setup" / "uv.exe").exists():
        return Path(home)
    return None


def cuda_install_command() -> tuple[list[str], dict[str, str]]:
    """Command (and extra environment) that replaces a CPU-only PyTorch with the CUDA build.

    Installed releases have no pip in their environment: they use the bundled uv and its
    download cache, so a later repair or move never downloads the same files again.
    """
    python = str(Path(sys.executable).with_name("python.exe")) if sys.platform == "win32" else sys.executable
    home = release_home()
    if home is not None:
        uv = str(home / "app" / "setup" / "uv.exe")
        return ([uv, "pip", "install", "--python", python, "--reinstall-package", "torch", "torch",
                 "--index-url", CUDA_INDEX],
                {"UV_CACHE_DIR": str(home / "runtime" / "cache")})
    return ([python, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", "torch",
             "--index-url", CUDA_INDEX], {})


# ----------------------------------------------------------------------
def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        if sys.platform == "darwin":
            return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, ValueError):
        pass
    return platform.processor() or "CPU"


def _nvidia_gpus() -> list[GpuInfo]:
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import pynvml

        pynvml.nvmlInit()
        try:
            driver = _s(pynvml.nvmlSystemGetDriverVersion())
            out = []
            for i in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                out.append(
                    GpuInfo(_s(pynvml.nvmlDeviceGetName(handle)), "nvidia",
                            mem.total / GB, mem.free / GB, driver)
                )
            return out
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001 - any NVML failure simply means "no NVIDIA GPU"
        return []


def _apple_gpu(ram_gb: float) -> list[GpuInfo]:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        # Unified memory: the GPU can address most of system RAM.
        return [GpuInfo("Apple Silicon GPU", "apple", ram_gb * 0.7, ram_gb * 0.5)]
    return []


def _other_gpus() -> list[GpuInfo]:
    """Name non-NVIDIA adapters so the UI can explain why they are not used."""
    if sys.platform != "win32":
        return []
    raw = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json",
    ])
    try:
        items = json.loads(raw) if raw.strip() else []
    except ValueError:
        return []
    if isinstance(items, dict):
        items = [items]
    out = []
    for item in items:
        name = str(item.get("Name") or "").strip()
        if not name or "basic" in name.lower() or "virtual" in name.lower():
            continue
        low = name.lower()
        vendor = "amd" if ("amd" in low or "radeon" in low) else "intel" if "intel" in low else "other"
        vram = max(0, int(item.get("AdapterRAM") or 0)) / GB
        out.append(GpuInfo(name, vendor, vram, vram))
    return out


def _run(cmd: list[str]) -> str:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=8, check=False, creationflags=flags
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _s(value: object) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
