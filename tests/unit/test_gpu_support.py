"""AMD / Intel graphics: detection, device choice, and agreement with the Windows installer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from snapreel.core import advisor, hardware
from snapreel.core.catalog import Catalog
from snapreel.core.hardware import Adapter, GpuInfo, Hardware, TorchBuild

ROOT = Path(__file__).resolve().parents[2]

# (Windows adapter name, PCI vendor, PCI device) -> expected PyTorch build ("" = processor)
CASES = [
    ("AMD Radeon RX 9070 XT", "1002", "7550", "rocm-gfx120x"),
    ("AMD Radeon RX 9060 XT", "1002", "7590", "rocm-gfx120x"),
    ("AMD Radeon RX 7900 XTX", "1002", "744C", "rocm-gfx110x"),
    ("AMD Radeon RX 7600", "1002", "7480", "rocm-gfx110x"),
    ("AMD Radeon PRO W7800", "1002", "7448", "rocm-gfx110x"),
    ("AMD Radeon RX 6800 XT", "1002", "73BF", "rocm-gfx103x"),
    ("AMD Radeon RX 6600", "1002", "73FF", "rocm-gfx103x"),
    ("AMD Radeon 780M Graphics", "1002", "15BF", "rocm-gfx110x"),
    ("AMD Radeon(TM) Graphics", "1002", "15BF", "rocm-gfx110x"),  # generic name, Phoenix by id
    ("AMD Radeon 890M Graphics", "1002", "150E", "rocm-gfx1150"),
    ("AMD Radeon 8060S Graphics", "1002", "1586", "rocm-gfx1151"),
    ("AMD Radeon 860M Graphics", "1002", "1114", "rocm-gfx1152"),
    ("AMD Radeon(TM) Graphics", "1002", "164E", ""),  # Ryzen 7000 desktop: 2 CUs, slower than the CPU
    ("AMD Radeon RX 580 Series", "1002", "67DF", ""),
    ("AMD Radeon RX 5700 XT", "1002", "731F", ""),
    ("Intel(R) Arc(TM) A770 Graphics", "8086", "56A0", "xpu"),
    ("Intel(R) Arc(TM) B580 Graphics", "8086", "E20B", "xpu"),
    ("Intel(R) Arc(TM) Pro A60 Graphics", "8086", "56B2", "xpu"),
    ("Intel(R) Arc(TM) Graphics", "8086", "7D55", "xpu"),  # Core Ultra
    ("Intel(R) Arc(TM) 140V GPU (16GB)", "8086", "64A0", "xpu"),
    ("Intel(R) Iris(R) Xe Graphics", "8086", "9A49", ""),
    ("Intel(R) UHD Graphics 770", "8086", "4680", ""),
]


@pytest.mark.parametrize(("name", "vendor", "device", "flavor"), CASES)
def test_classify(name: str, vendor: str, device: str, flavor: str) -> None:
    gpu = hardware.classify(Adapter(name, vendor, device, 2 * 1024**3), ram_gb=32)
    assert gpu is not None and gpu.flavor == flavor


def test_integrated_gpu_gets_half_the_ram() -> None:
    gpu = hardware.classify(Adapter("AMD Radeon 780M Graphics", "1002", "15BF", 512 * 1024**2), ram_gb=32)
    assert gpu is not None and gpu.integrated and gpu.vram_total_gb == 16
    b580 = Adapter("Intel(R) Arc(TM) B580 Graphics", "8086", "E20B", 12 * 1024**3)
    arc = hardware.classify(b580, ram_gb=32)
    assert arc is not None and not arc.integrated and arc.vram_total_gb == 12


def test_software_adapters_are_ignored() -> None:
    for name in ("Microsoft Basic Display Adapter", "Parsec Virtual Display Adapter", ""):
        assert hardware.classify(Adapter(name), ram_gb=16) is None


def machine(*gpus: GpuInfo, torch: TorchBuild | None = None) -> Hardware:
    return Hardware("Windows 11", "CPU", 8, 16, 32, 24, 8, gpus, torch or TorchBuild(True, "2.11.0"))


RX7800 = GpuInfo("AMD Radeon RX 7800 XT", "amd", 16, 16, flavor="rocm-gfx110x")
ARC = GpuInfo("Intel(R) Arc(TM) A770 Graphics", "intel", 16, 16, flavor="xpu")
IGPU = GpuInfo("AMD Radeon 780M Graphics", "amd", 16, 16, flavor="rocm-gfx110x", integrated=True)
OLD = GpuInfo("AMD Radeon RX 580 Series", "amd", 8, 8)


def test_amd_runs_on_rocm_as_cuda_device() -> None:
    hw = machine(RX7800, torch=TorchBuild(True, "2.11.0+rocm7.13.0", hip="7.13"))
    assert hw.device == "cuda" and hw.issues == []


def test_intel_runs_on_xpu() -> None:
    hw = machine(ARC, torch=TorchBuild(True, "2.15.0+xpu", xpu="20260102"))
    assert hw.device == "xpu" and hw.issues == []


def test_wrong_build_falls_back_to_processor_and_says_so() -> None:
    for gpu in (RX7800, ARC):
        hw = machine(gpu)  # processor-only PyTorch
        assert hw.device == "cpu" and "torch_cpu_build" in hw.issues
    hw = machine(ARC, torch=TorchBuild(True, "2.11.0+rocm7.13.0", hip="7.13"))
    assert hw.device == "cpu"


def test_unsupported_card_is_named() -> None:
    hw = machine(OLD)
    assert hw.gpu is None and hw.device == "cpu" and "gpu_unsupported" in hw.issues


def test_discrete_card_wins_over_integrated() -> None:
    assert machine(IGPU, ARC).gpu is ARC
    assert machine(ARC, RX7800).gpu is RX7800


def test_advisor_plans_for_amd_and_intel() -> None:
    catalog = Catalog()
    spec = catalog.get("stabilityai/sd-turbo")
    assert spec is not None
    rocm = advisor.assess(spec, machine(RX7800, torch=TorchBuild(True, "2.11.0+rocm7.13.0", hip="7.13")))
    assert rocm.plan.device == "cuda" and rocm.verdict == advisor.GREAT
    xpu = advisor.assess(spec, machine(ARC, torch=TorchBuild(True, "2.15.0+xpu", xpu="1")))
    assert xpu.plan.device == "xpu" and xpu.verdict == advisor.GREAT


@pytest.mark.parametrize(("text", "backend", "label"), [
    ("__version__ = '2.11.0+rocm7.13.0'\ncuda: Optional[str] = None\nhip: Optional[str] = '7.13.0'\n",
     "rocm", "ROCm 7.13.0"),
    ("__version__ = '2.15.0+xpu'\ncuda: Optional[str] = None\nhip: Optional[str] = None\n"
     "xpu: Optional[str] = '20260102'\n", "xpu", "Intel XPU"),
    ("__version__ = '2.15.0+cpu'\ncuda: Optional[str] = None\n", "", ""),
])
def test_torch_build_reads_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                   text: str, backend: str, label: str) -> None:
    (tmp_path / "version.py").write_text(text, encoding="utf-8")

    class Spec:
        origin = str(tmp_path / "__init__.py")

    monkeypatch.setattr(hardware.importlib.util, "find_spec", lambda _name: Spec())
    build = hardware.torch_build()
    assert build.backend == backend and build.label == label


def test_setup_command_pins_python_for_amd() -> None:
    assert hardware.setup_command(RX7800) == "uv sync --python 3.13 --extra rocm-gfx110x --extra online"
    assert hardware.setup_command(ARC) == "uv sync --extra xpu --extra online"


def test_every_flavor_is_a_pyproject_extra() -> None:
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    table = hardware.gpu_table()
    for vendor in ("amd", "intel"):
        for row in table[vendor]:
            assert row["flavor"] in extras


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
def test_installer_picks_the_same_build(tmp_path: Path) -> None:
    """The installer (PowerShell) and the app (Python) read one table: they must agree."""
    app = tmp_path / "SnapReel" / "app"
    (app / "setup").mkdir(parents=True)
    (app / "src" / "snapreel" / "data").mkdir(parents=True)
    shutil.copy(ROOT / "packaging" / "windows" / "launcher.ps1", app / "setup")
    shutil.copy(ROOT / "src" / "snapreel" / "data" / "gpu_support.json", app / "src" / "snapreel" / "data")
    shutil.copy(ROOT / "src" / "snapreel" / "__init__.py", app / "src" / "snapreel")
    def detect(simulate: str) -> dict:
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                   str(app / "setup" / "launcher.ps1"), "-DetectOnly", "-SimulateGpu", simulate]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60, check=True)
        return json.loads(done.stdout)

    for name, vendor, device, flavor in CASES:
        chosen = detect(f"{name}|VEN_{vendor}&DEV_{device}")
        assert chosen["flavor"] == (flavor or "cpu"), name
        assert chosen["python"] == ("3.13" if flavor.startswith("rocm") else "")
    # All at once: the best card wins, as in Hardware.gpu.
    simulate = ";".join(f"{name}|VEN_{vendor}&DEV_{device}" for name, vendor, device, _ in CASES)
    gpus = [hardware.classify(Adapter(n, v, d), ram_gb=32) for n, v, d, _ in CASES]
    best = machine(*[g for g in gpus if g is not None]).gpu
    assert best is not None and detect(simulate)["gpu"] == best.name
