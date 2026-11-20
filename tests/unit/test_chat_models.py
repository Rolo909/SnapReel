"""Chat models (GGUF): recognizing Hub repos and local files, storing one quantization."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import LLAMA_HEADER, gguf_bytes

from tvorka.core import hub
from tvorka.core.hub import HubError
from tvorka.core.llm import gguf
from tvorka.core.local_import import spec_from_path
from tvorka.core.settings import Settings
from tvorka.core.store import ModelStore

GB = 1024**3
REPO_FILES = [
    ("README.md", 100), (".gitattributes", 10),
    ("Tiny-Q4_K_M.gguf", int(4.9 * GB)), ("Tiny-Q8_0.gguf", int(8.5 * GB)),
    ("Tiny-Q2_K.gguf", int(3.2 * GB)), ("mmproj-F16.gguf", int(0.6 * GB)),
]


@pytest.fixture
def fake_hub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``repo_siblings`` and ``remote_header`` without network; returns the files whose header was read."""
    read: list[str] = []
    info = SimpleNamespace(gated=False, card_data={"license": "apache-2.0"}, tags=["gguf"],
                           pipeline_tag="text-generation", library_name="gguf",
                           gguf={"context_length": 32768, "chat_template": "{% if tools %}"})
    monkeypatch.setattr(hub, "repo_siblings", lambda repo, token=None: (info, list(REPO_FILES)))

    def header(repo: str, filename: str, token: str | None = None) -> gguf.GgufInfo:
        read.append(filename)
        return gguf.read_header(io.BytesIO(gguf_bytes(LLAMA_HEADER)))

    monkeypatch.setattr(hub, "remote_header", header)
    return read


def test_gguf_repo_becomes_a_chat_model(fake_hub: list[str]) -> None:
    spec = hub.spec_from_repo("someone/Tiny-GGUF")
    assert (spec.kind, spec.engine, spec.name, spec.license) == ("chat", "llama", "Tiny", "apache-2.0")
    assert [q["name"] for q in spec.quants] == ["Q2_K", "Q4_K_M", "Q8_0"]
    assert spec.mmproj == "mmproj-F16.gguf" and spec.mmproj_gb == pytest.approx(0.6)
    assert spec.context == 32768  # from the Hub's own summary
    assert spec.layers == 32 and spec.kv_gb_per_1k == pytest.approx(0.125)
    assert spec.capabilities == ["vision", "tools"]
    assert spec.download_gb == pytest.approx(5.5)  # Q4_K_M + projector
    assert fake_hub == ["Tiny-Q2_K.gguf"]  # the smallest file is enough to read the header


def test_repo_with_only_a_projector(monkeypatch: pytest.MonkeyPatch) -> None:
    info = SimpleNamespace(gated=False, card_data={}, tags=[], pipeline_tag="", library_name="", gguf={})
    monkeypatch.setattr(hub, "repo_siblings", lambda repo, token=None: (info, [("mmproj-F16.gguf", GB)]))
    with pytest.raises(HubError) as error:
        hub.spec_from_repo("someone/projector-only")
    assert error.value.code == "projector"


def test_plan_named_takes_exactly_the_chosen_files() -> None:
    plan = hub.plan_named(REPO_FILES, ["Tiny-Q4_K_M.gguf", "mmproj-F16.gguf"])
    assert plan.files == ["Tiny-Q4_K_M.gguf", "mmproj-F16.gguf"]
    assert plan.total_bytes == int(4.9 * GB) + int(0.6 * GB)
    with pytest.raises(HubError):
        hub.plan_named(REPO_FILES, ["Tiny-Q5_K_M.gguf"])


# ------------------------------------------------------------------ local files
def test_local_gguf_file(make_gguf: Callable[..., Path]) -> None:
    file = make_gguf("models/Tiny-Q4_K_M.gguf")
    make_gguf("models/mmproj-tiny-f16.gguf", {"general.architecture": "clip", "general.type": "mmproj"})
    spec = spec_from_path(file)
    assert (spec.kind, spec.engine, spec.source) == ("chat", "llama", "local")
    assert spec.path == str(file) and spec.name == "Tiny Llama"
    assert spec.quants[0]["name"] == "Q4_K_M" and spec.quants[0]["files"] == [file.name]
    assert spec.mmproj == str(file.parent / "mmproj-tiny-f16.gguf")
    assert spec.capabilities == ["vision", "tools", "reasoning"]


def test_projector_file_alone_is_explained(make_gguf: Callable[..., Path]) -> None:
    file = make_gguf("mmproj-model-f16.gguf", {"general.architecture": "clip", "general.type": "mmproj"})
    with pytest.raises(HubError) as error:
        spec_from_path(file)
    assert error.value.code == "projector"


def test_split_model_is_loaded_through_its_first_part(make_gguf: Callable[..., Path]) -> None:
    first = make_gguf("big/Big-Q8_0-00001-of-00002.gguf", padding=1000)
    make_gguf("big/Big-Q8_0-00002-of-00002.gguf", padding=5000)
    spec = spec_from_path(first.parent / "Big-Q8_0-00002-of-00002.gguf")
    assert spec.path == str(first)
    assert spec.quants[0]["files"] == ["Big-Q8_0-00001-of-00002.gguf", "Big-Q8_0-00002-of-00002.gguf"]
    assert not spec.id.endswith("00002")


def test_folder_with_one_gguf_model(make_gguf: Callable[..., Path]) -> None:
    file = make_gguf("one/Tiny-Q4_K_M.gguf")
    assert spec_from_path(file.parent).path == str(file)
    make_gguf("one/Tiny-Q8_0.gguf")
    with pytest.raises(HubError):  # two quantizations: the user has to pick one
        spec_from_path(file.parent)


def test_damaged_gguf_is_unsupported(tmp_path: Path) -> None:
    file = tmp_path / "broken.gguf"
    file.write_bytes(b"GGUF\x03")
    with pytest.raises(HubError) as error:
        spec_from_path(file)
    assert error.value.code == "unsupported"


# ------------------------------------------------------------------ storage
def test_store_finds_the_downloaded_quant(tmp_path: Path, fake_hub: list[str]) -> None:
    store = ModelStore(Settings(models_dir=str(tmp_path / "models")))
    spec = hub.spec_from_repo("someone/Tiny-GGUF")
    assert store.chat_files(spec) == (None, None) and store.chat_quant(spec) == ""
    task = store.download_task(spec, ["Tiny-Q4_K_M.gguf", "mmproj-F16.gguf"])
    assert task["only"] == ["Tiny-Q4_K_M.gguf", "mmproj-F16.gguf"]

    snapshot = tmp_path / "models" / "hub" / "snap"
    snapshot.mkdir(parents=True)
    manifest = store.manifest_path(spec)
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"path": str(snapshot), "files": task["only"]}), encoding="utf-8")
    assert store.is_installed(spec)
    assert store.chat_files(spec) == (snapshot / "Tiny-Q4_K_M.gguf", snapshot / "mmproj-F16.gguf")
    assert store.chat_quant(spec) == "Q4_K_M"


def test_store_for_a_local_chat_model(make_gguf: Callable[..., Path], tmp_path: Path) -> None:
    file = make_gguf("Tiny-Q4_K_M.gguf")
    spec = spec_from_path(file)
    store = ModelStore(Settings(models_dir=str(tmp_path / "models")))
    assert store.chat_files(spec) == (file, None)
    assert store.chat_quant(spec) == "Q4_K_M"


# ------------------------------------------------------------------ faster answers
def test_repo_with_a_multi_token_head(fake_hub: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    files = [*REPO_FILES, ("mtp-Tiny.gguf", int(0.4 * GB)), ("MTP/mtp-Tiny-BF16.gguf", int(0.8 * GB))]
    info, _files = hub.repo_siblings("someone/Tiny-GGUF")
    monkeypatch.setattr(hub, "repo_siblings", lambda repo, token=None: (info, files))
    spec = hub.spec_from_repo("someone/Tiny-GGUF")
    assert [q["name"] for q in spec.quants] == ["Q2_K", "Q4_K_M", "Q8_0"]  # the head is not a model
    assert (spec.mtp, spec.mtp_gb) == ("mtp-Tiny.gguf", pytest.approx(0.4))
    assert spec.download_gb == pytest.approx(5.9)  # Q4_K_M + projector + head
    assert (spec.experts, spec.expert_share) == (0, 0.0)  # a dense model


def test_local_model_with_a_multi_token_head(make_gguf: Callable[..., Path], tmp_path: Path) -> None:
    file = make_gguf("models/Tiny-Q4_K_M.gguf")
    head = make_gguf("models/mtp-tiny.gguf", {"general.architecture": "gemma4-assistant"})
    spec = spec_from_path(file)
    assert spec.mtp == str(head) and spec.quants[0]["files"] == [file.name]
    assert spec_from_path(file.parent).path == str(file)  # the head does not count as a second model
    store = ModelStore(Settings(models_dir=str(tmp_path / "store")))
    assert store.chat_mtp(spec) == head


def test_store_finds_the_downloaded_head(tmp_path: Path, fake_hub: list[str]) -> None:
    store = ModelStore(Settings(models_dir=str(tmp_path / "models")))
    spec = hub.spec_from_repo("someone/Tiny-GGUF")
    assert store.chat_mtp(spec) is None
    snapshot = tmp_path / "models" / "hub" / "snap"
    snapshot.mkdir(parents=True)
    manifest = store.manifest_path(spec)
    manifest.parent.mkdir(parents=True)
    files = ["Tiny-Q4_K_M.gguf", "mmproj-F16.gguf", "MTP/mtp-Tiny-Q8_0.gguf"]
    manifest.write_text(json.dumps({"path": str(snapshot), "files": files}), encoding="utf-8")
    assert store.chat_mtp(spec) == snapshot / "MTP/mtp-Tiny-Q8_0.gguf"
    assert store.chat_files(spec) == (snapshot / "Tiny-Q4_K_M.gguf", snapshot / "mmproj-F16.gguf")
