"""llama.cpp server: build choice, command line, process lifecycle and the streaming client."""

from __future__ import annotations

import hashlib
import sys
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import llama_stub
import pytest

from tvorka.core.advisor import LlmPlan
from tvorka.core.hardware import GpuInfo, Hardware, TorchBuild
from tvorka.core.llm import runtime
from tvorka.core.llm.client import LlamaClient, LlmError
from tvorka.core.settings import Settings
from tvorka.core.store import ModelStore
from tvorka.workers import download_proc

STUB = Path(llama_stub.__file__)


def machine(*gpus: GpuInfo) -> Hardware:
    return Hardware("Test OS", "Test CPU", 6, 12, 16, 10, 8, gpus, TorchBuild(True, "2.14", "13.0"))


def nvidia(driver: str) -> GpuInfo:
    return GpuInfo("RTX 3060", "nvidia", 8, 7.5, driver)


@pytest.mark.parametrize(("hw", "system", "arch", "build"), [
    (machine(nvidia("617.14")), "win32", "AMD64", "win-cuda-13"),
    (machine(nvidia("560.94")), "win32", "AMD64", "win-cuda-12"),
    (machine(nvidia("472.12")), "win32", "AMD64", "win-vulkan"),
    (machine(GpuInfo("Radeon RX 5700", "amd", 8, 8)), "win32", "AMD64", "win-vulkan"),
    (machine(), "win32", "AMD64", "win-cpu"),
    (machine(nvidia("580.1")), "linux", "x86_64", "linux-vulkan"),
    (machine(GpuInfo("Apple Silicon GPU", "apple", 11, 8)), "darwin", "arm64", "macos-arm64"),
    (machine(), "win32", "ARM64", ""),
])
def test_build_for_the_computer(hw: Hardware, system: str, arch: str, build: str) -> None:
    assert runtime.pick_build(hw, system, arch) == build


def test_every_build_is_pinned_and_checked() -> None:
    table = runtime.runtime_table()
    for name, build in table["builds"].items():
        spec = runtime.runtime_spec(name, table)
        assert spec.source == "url" and spec.id.startswith(f"llama.cpp/{table['version']}-")
        for item in spec.files:
            assert item["extract"] and len(item["sha256"]) == 64, name
            url = urlparse(item["url"])
            assert url.scheme == "https" and url.hostname == "github.com", name
            assert url.path.startswith(f"/ggml-org/llama.cpp/releases/download/{table['version']}/"), name
        assert build["files"], name


def test_command_follows_the_plan(tmp_path: Path) -> None:
    exe, model, proj = tmp_path / "llama-server.exe", tmp_path / "m.gguf", tmp_path / "mmproj.gguf"
    full = runtime.server_command(exe, model, LlmPlan("Q4_K_M", 8192, 32, True, True), 5000, proj)
    assert full[:3] == [str(exe), "-m", str(model)]
    assert full[full.index("-ngl") + 1] == "all" and full[full.index("-c") + 1] == "8192"
    assert full[full.index("--host") + 1] == "127.0.0.1" and "--api-key" not in full
    assert full[full.index("--mmproj") + 1] == str(proj) and "--no-mmproj-offload" not in full
    part = runtime.server_command(exe, model, LlmPlan("Q4_K_M", 4096, 20), 5000, proj)
    assert part[part.index("-ngl") + 1] == "20" and "--no-mmproj-offload" in part
    cpu = runtime.server_command(exe, model, LlmPlan("Q4_K_M", 4096), 5000)
    assert cpu[cpu.index("--device") + 1] == "none" and "--mmproj" not in cpu
    for plain in (full, part, cpu):  # nothing speculative unless the plan asks for it
        assert not {"--n-cpu-moe", "-ctk", "-ctv", "--spec-type", "-md"} & set(plain)


def test_command_speeds_up_answers_as_planned(tmp_path: Path) -> None:
    exe, model, mtp = tmp_path / "llama-server.exe", tmp_path / "m.gguf", tmp_path / "mtp-m.gguf"
    plan = LlmPlan("UD-Q3_K_XL", 8192, 30, True, True, cpu_moe_layers=21, kv_type="q8_0", mtp=True)
    command = runtime.server_command(exe, model, plan, 5000, mtp=mtp)
    assert command[command.index("-ngl") + 1] == "all"
    assert command[command.index("--n-cpu-moe") + 1] == "21"
    assert command[command.index("-ctk") + 1] == "q8_0" and command[command.index("-ctv") + 1] == "q8_0"
    assert command[command.index("--spec-type") + 1] == "draft-mtp"
    assert command[command.index("-md") + 1] == str(mtp) and command[command.index("-ngld") + 1] == "all"
    # The head is on disk but the advisor left it out (no room on the card): it is not used.
    off = runtime.server_command(exe, model, LlmPlan("Q4_K_M", 8192, 32, True), 5000, mtp=mtp)
    assert "--spec-type" not in off and "-md" not in off


@pytest.mark.parametrize(("text", "code"), [
    ("ggml_backend_cuda_buffer_type_alloc_buffer: allocating 5000 MiB on device 0: cudaMalloc failed: "
     "out of memory", "out_of_memory"),
    ("llama_model_load: error loading model: unknown model architecture: 'foo'", "unsupported"),
    ("main: error: failed to load model 'x.gguf'", "load_failed"),
    ("segfault", "failed"),
])
def test_failure_code(text: str, code: str) -> None:
    assert runtime.failure_code(text) == code


def test_installed_server_is_found(tmp_path: Path) -> None:
    store = ModelStore(Settings(models_dir=str(tmp_path / "models")))
    spec = runtime.runtime_spec("win-vulkan")
    assert runtime.server_path(store, spec) is None
    folder = tmp_path / "models" / "files" / "llama" / "bin"
    exe = folder / ("llama-server.exe" if sys.platform == "win32" else "llama-server")
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    manifest = store.manifest_path(spec)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f'{{"path": "{folder.as_posix()}"}}', encoding="utf-8")
    assert runtime.server_path(store, spec) == exe


# ------------------------------------------------------------------ client
@pytest.fixture
def stub() -> llama_stub.StubServer:
    server = llama_stub.serve(api_key="secret")
    yield server
    server.shutdown()
    server.server_close()


def client_for(server: llama_stub.StubServer, key: str = "secret") -> LlamaClient:
    return LlamaClient(f"http://127.0.0.1:{server.server_address[1]}", key)


def test_answer_is_streamed(stub: llama_stub.StubServer) -> None:
    deltas = list(client_for(stub).chat([{"role": "user", "content": "hi"}], temperature=0.7))
    assert "".join(d.reasoning for d in deltas) == "Thinking"
    assert "".join(d.content for d in deltas) == "Hello, world"
    assert deltas[-2].finish == "stop" and deltas[-2].usage["predicted_per_second"] == 42.0
    assert deltas[-1].usage == {"prompt_tokens": 5, "completion_tokens": 3}
    request = stub.requests[-1]
    assert request["stream"] is True and request["temperature"] == 0.7


def test_wrong_key_and_full_context(stub: llama_stub.StubServer) -> None:
    with pytest.raises(LlmError) as error:
        list(client_for(stub, "wrong").chat([{"role": "user", "content": "hi"}]))
    assert error.value.code == "auth"
    with pytest.raises(LlmError) as error:
        list(client_for(stub).chat([{"role": "user", "content": "too long"}]))
    assert error.value.code == "context_overflow"


def test_cancel_stops_a_running_answer(stub: llama_stub.StubServer) -> None:
    client = client_for(stub)
    received: list[str] = []
    with pytest.raises(LlmError) as error:
        for delta in client.chat([{"role": "user", "content": "slow"}]):
            received.append(delta.content)
            if len(received) == 5:
                threading.Thread(target=client.cancel).start()
    assert error.value.code == "cancelled"
    assert 5 <= len(received) < 2000


def test_health(stub: llama_stub.StubServer) -> None:
    assert client_for(stub).health() == "ok"
    loading = llama_stub.serve(load_seconds=60)
    try:
        assert client_for(loading).health() == "loading"
    finally:
        loading.shutdown()
        loading.server_close()
    with pytest.raises(LlmError) as error:
        LlamaClient(f"http://127.0.0.1:{runtime.free_port()}").health()
    assert error.value.code == "not_running"


# ------------------------------------------------------------------ process
def stub_command(port: int, *extra: str) -> list[str]:
    return [sys.executable, str(STUB), "--port", str(port), *extra]


def test_server_starts_answers_and_stops(tmp_path: Path) -> None:
    server = runtime.LlamaServer(tmp_path / "logs" / "llama-server.log")
    port = runtime.free_port()
    server.start(stub_command(port, "--load", "0.5"), port)
    try:
        server.wait_ready(timeout=30)
        assert server.running
        text = "".join(d.content for d in server.client().chat([{"role": "user", "content": "hi"}]))
        assert text == "Hello, world"
    finally:
        server.stop()
    assert not server.running


def test_server_that_fails_to_load_explains_why(tmp_path: Path) -> None:
    server = runtime.LlamaServer(tmp_path / "llama-server.log")
    port = runtime.free_port()
    server.start(stub_command(port, "--fail", "llama_model_load: error loading model: bad file"), port)
    with pytest.raises(LlmError) as error:
        server.wait_ready(timeout=30)
    assert error.value.code == "load_failed"
    assert not server.running


def test_waiting_can_be_cancelled(tmp_path: Path) -> None:
    server = runtime.LlamaServer(tmp_path / "llama-server.log")
    port = runtime.free_port()
    server.start(stub_command(port, "--load", "60"), port)
    with pytest.raises(LlmError) as error:
        server.wait_ready(timeout=30, cancelled=lambda: True)
    assert error.value.code == "cancelled" and not server.running


# ------------------------------------------------------------------ download of the server
def test_server_archive_is_checked_and_unpacked(tmp_path: Path) -> None:
    archive = tmp_path / "src" / "llama-bin.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("llama-server.exe", b"MZ")
        bundle.writestr("ggml-cuda.dll", b"dll")
    item = {"name": archive.name, "url": archive.as_uri(), "size": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "extract": True}
    dest = tmp_path / "files"
    result = download_proc._download_urls({"files_dir": str(dest), "files": [item]})
    assert Path(result["path"]) == dest / "bin"
    assert (dest / "bin" / "llama-server.exe").read_bytes() == b"MZ"
    assert not (dest / archive.name).exists()  # the archive is not kept

    bad = {**item, "sha256": "0" * 64}
    with pytest.raises(download_proc.DownloadError) as error:
        download_proc._download_urls({"files_dir": str(tmp_path / "other"), "files": [bad]})
    assert error.value.code == "checksum"
    assert not any((tmp_path / "other").glob("*.zip*"))  # nothing damaged is left to resume


def test_unpack_refuses_paths_outside_the_folder(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.txt", b"x")
    with pytest.raises(download_proc.DownloadError):
        download_proc.unpack(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()
