"""Hardware profiler — detects CPU, RAM, GPU/VRAM and selects execution profile."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Literal

import psutil
import structlog

logger = structlog.get_logger()

# VRAM thresholds in MB
_VRAM_HIGH = 12_000
_VRAM_MEDIUM = 7_500
_VRAM_LOW = 3_500


@dataclass(frozen=True)
class GpuInfo:
    """Detected GPU information."""

    name: str
    vram_total_mb: int
    vram_free_mb: int
    driver_version: str = ""


@dataclass(frozen=True)
class HardwareInfo:
    """Full hardware profile of the current system."""

    cpu_name: str
    cpu_cores_physical: int
    cpu_cores_logical: int
    ram_total_mb: int
    ram_available_mb: int
    gpu: GpuInfo | None


@dataclass(frozen=True)
class ExecutionProfile:
    """Computed execution profile based on detected hardware.

    Determines which devices to use for each pipeline component.
    """

    name: Literal["high", "medium", "low", "cpu_only"]
    llm_device: str  # Always "cpu"
    llm_threads: int
    diffusion_device: str  # "cuda" | "cpu"
    diffusion_dtype: str  # "float16" | "float32"
    whisper_device: str  # "cuda" | "cpu"
    whisper_compute_type: str  # "int8" | "float16"
    max_concurrent_downloads: int


def detect_hardware() -> HardwareInfo:
    """Detect the current system's hardware capabilities.

    Returns:
        HardwareInfo with CPU, RAM, and GPU details.
    """
    cpu_name = platform.processor() or "Unknown CPU"
    cpu_physical = psutil.cpu_count(logical=False) or 1
    cpu_logical = psutil.cpu_count(logical=True) or 1
    mem = psutil.virtual_memory()
    ram_total = int(mem.total / (1024 * 1024))
    ram_available = int(mem.available / (1024 * 1024))

    gpu = _detect_nvidia_gpu()

    info = HardwareInfo(
        cpu_name=cpu_name,
        cpu_cores_physical=cpu_physical,
        cpu_cores_logical=cpu_logical,
        ram_total_mb=ram_total,
        ram_available_mb=ram_available,
        gpu=gpu,
    )
    logger.info(
        "hardware_detected",
        cpu=cpu_name,
        cores=f"{cpu_physical}P/{cpu_logical}L",
        ram_gb=f"{ram_total / 1024:.1f}",
        gpu=gpu.name if gpu else "None",
        vram_mb=gpu.vram_total_mb if gpu else 0,
    )
    return info


def _detect_nvidia_gpu() -> GpuInfo | None:
    """Detect NVIDIA GPU using pynvml.

    Returns:
        GpuInfo if an NVIDIA GPU is found, None otherwise.
    """
    try:
        import pynvml  # type: ignore[import-untyped]

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name_raw = pynvml.nvmlDeviceGetName(handle)
        name = name_raw.decode("utf-8") if isinstance(name_raw, bytes) else str(name_raw)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        driver_raw = pynvml.nvmlSystemGetDriverVersion()
        driver = (
            driver_raw.decode("utf-8") if isinstance(driver_raw, bytes) else str(driver_raw)
        )
        pynvml.nvmlShutdown()

        return GpuInfo(
            name=name,
            vram_total_mb=int(mem_info.total / (1024 * 1024)),
            vram_free_mb=int(mem_info.free / (1024 * 1024)),
            driver_version=driver,
        )
    except Exception:  # noqa: BLE001
        logger.debug("nvidia_gpu_not_detected", reason="pynvml unavailable or no NVIDIA GPU")
        return None


def compute_profile(hw: HardwareInfo) -> ExecutionProfile:
    """Compute the optimal execution profile based on hardware.

    Args:
        hw: Detected hardware information.

    Returns:
        ExecutionProfile with device assignments and settings.
    """
    llm_threads = max(1, hw.cpu_cores_physical // 2)

    if hw.gpu is None:
        logger.info("profile_selected", profile="cpu_only")
        return ExecutionProfile(
            name="cpu_only",
            llm_device="cpu",
            llm_threads=llm_threads,
            diffusion_device="cpu",
            diffusion_dtype="float32",
            whisper_device="cpu",
            whisper_compute_type="int8",
            max_concurrent_downloads=2,
        )

    vram = hw.gpu.vram_total_mb

    if vram >= _VRAM_HIGH:
        profile_name: Literal["high", "medium", "low", "cpu_only"] = "high"
        diffusion_device = "cuda"
        diffusion_dtype = "float16"
        whisper_device = "cuda"
        whisper_compute = "float16"
    elif vram >= _VRAM_MEDIUM:
        profile_name = "medium"
        diffusion_device = "cuda"
        diffusion_dtype = "float16"
        whisper_device = "cpu"
        whisper_compute = "int8"
    elif vram >= _VRAM_LOW:
        profile_name = "low"
        diffusion_device = "cuda"
        diffusion_dtype = "float16"
        whisper_device = "cpu"
        whisper_compute = "int8"
    else:
        profile_name = "cpu_only"
        diffusion_device = "cpu"
        diffusion_dtype = "float32"
        whisper_device = "cpu"
        whisper_compute = "int8"

    logger.info("profile_selected", profile=profile_name, vram_mb=vram)
    return ExecutionProfile(
        name=profile_name,
        llm_device="cpu",
        llm_threads=llm_threads,
        diffusion_device=diffusion_device,
        diffusion_dtype=diffusion_dtype,
        whisper_device=whisper_device,
        whisper_compute_type=whisper_compute,
        max_concurrent_downloads=4 if profile_name == "high" else 2,
    )
