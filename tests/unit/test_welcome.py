"""Recommendations of the first-run screen (pure logic, no GUI)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tvorka.core import advisor
from tvorka.core.catalog import Catalog
from tvorka.core.hardware import GpuInfo, Hardware, TorchBuild
from tvorka.gui.pages.welcome import recommend

CUDA = TorchBuild(True, "2.14.1+cu130", "13.0")


def machine(vram: float | None, ram: float = 16.0) -> Hardware:
    gpus = () if vram is None else (GpuInfo("GPU", "nvidia", vram, vram),)
    return Hardware("OS", "CPU", 6, 12, ram, ram * 0.6, 8.0, gpus, CUDA)


def run(hw: Hardware, installed: set[str] | None = None, lang: str = "ru") -> dict:
    catalog = Catalog()
    return recommend(catalog.all(), lambda spec: advisor.assess(spec, hw),
                     lambda spec: spec.id in (installed or set()), lang)


def test_rtx_3060_gets_light_models() -> None:
    recs = run(machine(8.0))
    assert recs["image"].spec.id == "stabilityai/sd-turbo" and recs["image"].suggested
    assert recs["speech"].spec.engine in ("silero", "transformers_tts") and recs["speech"].suggested
    assert recs["video"].spec.id == "THUDM/CogVideoX-2b"
    assert not recs["video"].suggested  # slow on 8 GB: offered, not ticked


def test_never_online_or_gated() -> None:
    for vram in (None, 4.0, 24.0):
        for rec in run(machine(vram, ram=64)).values():
            assert rec.spec.source != "online" and not rec.spec.gated


def test_installed_model_wins_a_tie() -> None:
    recs = run(machine(24.0, ram=64), installed={"Lykon/dreamshaper-8"})
    assert recs["image"].spec.id == "Lykon/dreamshaper-8" and recs["image"].installed


def test_models_that_do_not_fit_are_skipped() -> None:
    recs = run(machine(None, ram=8.0))
    for rec in recs.values():
        assert rec.fit is None or rec.fit.ok


def test_voice_follows_the_interface_language() -> None:
    assert "ru" in run(machine(8.0), lang="ru")["speech"].spec.languages
    assert "en" in run(machine(8.0), lang="en")["speech"].spec.languages
