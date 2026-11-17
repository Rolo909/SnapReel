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
    flavor: str = ""  # PyTorch build (pyproject extra) for an AMD / Intel GPU; "" = not supported
    integrated: bool = False  # shares system RAM

    @property
    def supported(self) -> bool:
        return self.vendor in ("nvidia", "apple") or bool(self.flavor)


@dataclass(frozen=True)
class TorchBuild:
    installed: bool = False
    version: str = ""
    cuda: str = ""  # CUDA runtime version the wheel was built with, "" for CPU builds
    hip: str = ""  # ROCm (AMD) build
    xpu: str = ""  # Intel GPU build

    @property
    def has_cuda(self) -> bool:
        return bool(self.cuda)

    @property
    def backend(self) -> str:
        """One of "cuda", "rocm", "xpu", or "" for a processor-only build."""
        return "cuda" if self.cuda else "rocm" if self.hip else "xpu" if self.xpu else ""

    @property
    def label(self) -> str:
        names = {"cuda": f"CUDA {self.cuda}", "rocm": f"ROCm {self.hip}", "xpu": "Intel XPU"}
        return names.get(self.backend, "")


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
        """The GPU generation will run on: the best one PyTorch can use (discrete before integrated)."""
        usable = [g for g in self.gpus if g.supported]
        rank = {"nvidia": 3, "apple": 3, "amd": 2, "intel": 1}
        return max(usable, key=lambda g: (not g.integrated, rank.get(g.vendor, 0), g.vram_total_gb),
                   default=None)

    @property
    def device(self) -> str:
        """Torch device string generation will actually use."""
        gpu = self.gpu
        if gpu is None:
            return "cpu"
        if gpu.vendor == "apple":
            return "mps"
        needed = {"nvidia": "cuda", "amd": "rocm", "intel": "xpu"}.get(gpu.vendor)
        if needed is None or needed != self.torch.backend:
            return "cpu"
        return "xpu" if needed == "xpu" else "cuda"  # ROCm builds expose AMD GPUs as "cuda"

    @property
    def issues(self) -> list[str]:
        """Machine-readable problems the UI explains and offers to fix."""
        out: list[str] = []
        if not self.torch.installed:
            out.append("torch_missing")
        elif self.gpu is not None and self.gpu.vendor != "apple" and self.device == "cpu":
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
    gpus += _apple_gpu(mem.total / GB) or _other_gpus(mem.total / GB, skip_nvidia=bool(gpus))
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
    if gpus:
        return ram, gpus[0].vram_free_gb
    return ram, _torch_free_vram()


def _torch_free_vram() -> float | None:
    """AMD / Intel have no NVML: ask PyTorch, but only once it is loaded anyway (it is slow to import)."""
    torch = sys.modules.get("torch")
    if torch is None:
        return None
    try:
        if torch.cuda.is_available():
            return torch.cuda.mem_get_info()[0] / GB
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            return xpu.mem_get_info()[0] / GB
    except Exception:  # noqa: BLE001 - the reading is optional; any backend error means "unknown"
        pass
    return None


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

    def value(name: str) -> str:
        found = re.search(rf"^{name}\b[^=\n]*=\s*['\"]([^'\"]+)", text, re.MULTILINE)
        return found.group(1) if found else ""

    return TorchBuild(True, value("__version__"), value("cuda"), value("hip"), value("xpu"))


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


def setup_command(gpu: GpuInfo) -> str:
    """The command that installs the PyTorch build for an AMD / Intel GPU when running from source."""
    python = gpu_table().get("python", {}).get("rocm", "3.13") if gpu.flavor.startswith("rocm") else ""
    pin = f"--python {python} " if python else ""
    return f"uv sync {pin}--extra {gpu.flavor} --extra online"


def reinstall_command(home: Path) -> list[str]:
    """Re-run the release installer once this process has exited: it picks the build for the GPU."""
    script = home / "app" / "setup" / "launcher.ps1"
    return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", str(script), "-Reinstall", "-WaitPid", str(os.getpid())]


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


@dataclass(frozen=True)
class Adapter:
    """A display adapter as Windows lists it."""

    name: str
    vendor_id: str = ""  # PCI vendor, e.g. "1002"
    device_id: str = ""  # PCI device, e.g. "744C"
    memory_bytes: int = 0  # dedicated video memory
    driver: str = ""


VENDORS = {"10DE": "nvidia", "1002": "amd", "1022": "amd", "8086": "intel"}


def gpu_table() -> dict:
    """The AMD / Intel support table, shared with the Windows installer."""
    path = Path(__file__).resolve().parent.parent / "data" / "gpu_support.json"
    return json.loads(path.read_text(encoding="utf-8"))


def classify(adapter: Adapter, ram_gb: float, table: dict | None = None) -> GpuInfo | None:
    """Turn a Windows adapter into a GpuInfo; None for software and virtual adapters."""
    name = adapter.name.strip()
    low = name.lower()
    if not name or any(word in low for word in ("basic", "virtual", "remote", "parsec", "indirect")):
        return None
    vendor = VENDORS.get(adapter.vendor_id.upper()) or (
        "nvidia" if "nvidia" in low else "amd" if ("amd" in low or "radeon" in low)
        else "intel" if "intel" in low else "other")
    flavor, integrated = "", False
    for row in (table or gpu_table()).get(vendor, []):
        if adapter.device_id.upper() in row.get("ids", ()) or re.search(row["name"], name, re.IGNORECASE):
            flavor, integrated = row["flavor"], bool(row["integrated"])
            break
    vram = adapter.memory_bytes / GB
    if integrated:
        # Windows lets an integrated GPU use up to half of the RAM on top of its own reserve.
        vram = max(vram, ram_gb / 2)
    return GpuInfo(name, vendor, vram, vram, adapter.driver, flavor, integrated)


def _other_gpus(ram_gb: float, skip_nvidia: bool = False) -> list[GpuInfo]:
    """AMD / Intel (and unknown) adapters, read from the registry: they have no NVML."""
    out = []
    for adapter in _windows_adapters():
        gpu = classify(adapter, ram_gb)
        if gpu is not None and not (skip_nvidia and gpu.vendor == "nvidia"):
            out.append(gpu)
    return out


DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
ADAPTER_VALUES = ("DriverDesc", "MatchingDeviceId", "DriverVersion",
                  "HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize")


def _windows_adapters() -> list[Adapter]:
    if sys.platform != "win32":
        return []
    import winreg

    out: list[Adapter] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS)
    except OSError:
        return out
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            if not name.isdigit():
                continue
            values: dict[str, object] = {}
            try:
                with winreg.OpenKey(root, name) as key:
                    for value in ADAPTER_VALUES:
                        try:
                            values[value] = winreg.QueryValueEx(key, value)[0]
                        except OSError:
                            continue
            except OSError:
                continue
            ids = re.search(r"ven_([0-9a-f]{4}).*?dev_([0-9a-f]{4})", str(values.get("MatchingDeviceId", "")),
                            re.IGNORECASE)
            memory = (values.get("HardwareInformation.qwMemorySize")
                      or values.get("HardwareInformation.MemorySize"))
            if isinstance(memory, bytes):
                memory = int.from_bytes(memory[:8], "little")
            out.append(Adapter(str(values.get("DriverDesc", "")), ids.group(1) if ids else "",
                               ids.group(2) if ids else "", int(memory or 0),
                               str(values.get("DriverVersion", ""))))
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
