from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tvorka.core import catalog as catalog_module
from tvorka.core.catalog import Catalog, ModelSpec


def test_builtin_catalog_is_valid() -> None:
    raw = yaml.safe_load(Catalog.builtin_file().read_text(encoding="utf-8"))
    entries = raw["models"]
    loaded = Catalog()
    assert len(loaded.all()) == len(entries), "an entry was rejected or an id is duplicated"
    for model in loaded.all():
        assert model.origin == "builtin"
        assert model.text("ru") and model.text("en"), model.id
        assert model.license, model.id
        assert model.download_gb > 0 or model.source == "online", model.id
        if model.kind == "chat":
            assert model.quants and model.layers and (model.kv_gb_per_1k or model.kv_fixed_gb), model.id
            assert all(q["files"] and q["gb"] > 0 for q in model.quants), model.id
        elif model.source != "online":
            assert model.memory, model.id
        if model.kind == "speech" and model.engine == "silero":
            assert model.voices and model.files, model.id
        if model.kind == "video":
            assert model.default("frames") and model.default("fps"), model.id
    kinds = {m.kind for m in loaded.all()}
    assert kinds == {"image", "video", "speech", "chat", "transcribe"}


def test_user_models_persist(data_dir: Path) -> None:
    first = Catalog()
    first.add_user(ModelSpec(id="me/my-model", name="Mine", kind="image",
                             memory={"unet": 1.0}))
    assert (data_dir / "user_models.json").exists()
    second = Catalog()
    loaded = second.get("me/my-model")
    assert loaded is not None and loaded.origin == "user"
    second.remove_user("me/my-model")
    assert Catalog().get("me/my-model") is None


def test_builtin_models_cannot_be_removed() -> None:
    cat = Catalog()
    cat.remove_user("stabilityai/sd-turbo")
    assert cat.get("stabilityai/sd-turbo") is not None


def test_user_model_overrides_builtin() -> None:
    cat = Catalog()
    cat.add_user(ModelSpec(id="stabilityai/sd-turbo", name="Custom Turbo", kind="image"))
    assert Catalog().get("stabilityai/sd-turbo").name == "Custom Turbo"


def test_broken_user_file_is_ignored(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_models.json").write_text("{not json", encoding="utf-8")
    assert Catalog().get("stabilityai/sd-turbo") is not None


REMOTE = """
version: 1
models:
  - {id: good/hf, name: Good, kind: image, memory: {unet: 1}}
  - {id: bad/local, name: Local, kind: image, source: local, path: "C:/Windows"}
  - id: bad/url
    name: Evil
    kind: speech
    engine: silero
    source: url
    files: [{url: "https://evil.example/model.pt", name: m.pt}]
  - id: bad/http
    name: Plain
    kind: speech
    engine: silero
    source: url
    files: [{url: "http://models.silero.ai/model.pt", name: m.pt}]
  - id: good/silero
    name: Silero
    kind: speech
    engine: silero
    source: url
    files: [{url: "https://models.silero.ai/models/tts/ru/v4_ru.pt", name: v4_ru.pt}]
  - {id: bad/engine, name: X, kind: image, engine: something_else}
  - {id: bad/kind, name: X, kind: music}
  - {name: missing id}
"""


def test_remote_catalog_filters_unsafe_entries() -> None:
    ids = {spec.id for spec in catalog_module._parse(REMOTE, "remote")}
    assert ids == {"good/hf", "good/silero"}


def test_remote_cache_is_merged(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "catalog_remote.yaml").write_text(REMOTE, encoding="utf-8")
    cat = Catalog()
    assert cat.get("good/hf").origin == "remote"
    assert cat.get("bad/local") is None


def test_min_app_version() -> None:
    text = """
models:
  - {id: ok/now, name: A, kind: image}
  - {id: later/one, name: B, kind: image, min_app: "99.0"}
  - {id: old/one, name: C, kind: image, min_app: "0.9.1", future_field: {x: 1}}
"""
    assert {s.id for s in catalog_module._parse(text, "remote")} == {"ok/now", "old/one"}
    assert catalog_module._parse("min_app: '99.1'\n" + text, "remote") == []


def test_invalid_yaml_does_not_crash() -> None:
    assert catalog_module._parse("models: [unclosed", "remote") == []
    assert catalog_module._parse("just a string", "remote") == []


def test_catalog_url_must_be_https() -> None:
    with pytest.raises(ValueError):
        Catalog().update_from_url("http://example.com/catalog.yaml")


def test_summary_string_is_accepted() -> None:
    spec = ModelSpec.from_dict({"id": "a/b", "name": "B", "kind": "image", "summary": "Hello"})
    assert spec.text("ru") == "Hello"
