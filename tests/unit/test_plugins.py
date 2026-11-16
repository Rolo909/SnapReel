from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from snapreel.core.advisor import Plan
from snapreel.core.catalog import Catalog, ModelSpec
from snapreel.engines import base
from snapreel.engines.plugins import load_plugins

PLUGIN = textwrap.dedent('''
    from snapreel.engines.base import Engine, register_engine

    class EchoEngine(Engine):
        def load(self, ctx):
            pass

        def generate(self, job, ctx):
            return []

    register_engine("echo_test", EchoEngine)
''')


def test_builtin_engines_registered() -> None:
    assert {"diffusers", "silero", "transformers_tts", "edge"} <= set(base.registered_engines())


def test_unknown_engine_is_unsupported() -> None:
    spec = ModelSpec(id="a/b", name="B", kind="image")
    spec.engine = "missing_engine"
    with pytest.raises(base.EngineError) as info:
        base.create_engine(spec, Plan())
    assert info.value.code == "unsupported"


def test_plugin_registers_engine(tmp_path: Path) -> None:
    (tmp_path / "echo.py").write_text(PLUGIN, encoding="utf-8")
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    (tmp_path / "empty.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "_private.py").write_text("raise SystemExit", encoding="utf-8")
    infos = {info.name: info for info in load_plugins(tmp_path)}
    assert set(infos) == {"echo", "broken", "empty"}
    assert infos["echo"].engines == ["echo_test"] and not infos["echo"].error
    assert "boom" in infos["broken"].error
    assert infos["empty"].error == "no engine registered"

    spec = ModelSpec.from_dict({"id": "me/echo", "name": "Echo", "kind": "speech", "engine": "echo_test"})
    assert type(base.create_engine(spec, Plan())).__name__ == "EchoEngine"


def test_plugin_engine_can_be_used_by_user_models(tmp_path: Path) -> None:
    (tmp_path / "echo.py").write_text(PLUGIN, encoding="utf-8")
    load_plugins(tmp_path)
    Catalog().add_user(ModelSpec(id="me/echo", name="Echo", kind="speech", engine="echo_test"))
    assert Catalog().get("me/echo") is not None
