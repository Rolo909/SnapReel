from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from snapreel.core.hardware import GpuInfo, Hardware, TorchBuild
from snapreel.core.settings import DEFAULT_CATALOG_URL, Settings
from snapreel.gui import theme
from snapreel.gui.pages import settings as settings_module
from snapreel.gui.pages.settings import SettingsPage
from snapreel.gui.services import Services
from snapreel.i18n import set_language


@pytest.fixture
def page(tmp_path: Path, qapp, qtbot) -> SettingsPage:
    set_language("ru")
    theme.apply(qapp, "dark")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))
    widget = SettingsPage(services, None)
    qtbot.addWidget(widget)
    return widget


def machine(torch: TorchBuild) -> Hardware:
    return Hardware("Windows 11", "Test CPU", 6, 12, 16.0, 9.0, 8.0,
                    (GpuInfo("NVIDIA GeForce RTX 3060", "nvidia", 8.0, 7.0, "590.10"),), torch)


def test_hardware_summary_and_healthy_diagnostics(page: SettingsPage) -> None:
    page._show_hardware(machine(TorchBuild(True, "2.14.1+cu130", "13.0")))
    summary = page.hw_summary.text()
    assert "RTX 3060" in summary and "CUDA 13.0" in summary and "Test CPU" in summary
    assert page.install_button.isHidden()


def test_cpu_torch_offers_the_gpu_build(page: SettingsPage, monkeypatch) -> None:
    monkeypatch.setattr(settings_module, "can_install_gpu_torch", lambda: True)
    page._show_hardware(machine(TorchBuild(True, "2.14.1+cpu", "")))
    assert not page.install_button.isHidden() and page.install_button.isEnabled()
    monkeypatch.setattr(settings_module, "can_install_gpu_torch", lambda: False)
    page._show_hardware(machine(TorchBuild(True, "2.14.1+cpu", "")))
    assert not page.install_button.isEnabled()
    assert "Перезапустите" in page.install_status.text()


def test_change_models_folder_warns(page: SettingsPage, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "new models"
    target.mkdir()
    monkeypatch.setattr(settings_module.QFileDialog, "getExistingDirectory", lambda *a, **k: str(target))
    changed = []
    page.services.models_changed.connect(lambda: changed.append(True))
    page._change_folder("models")
    assert page.services.settings.models_path() == target
    assert not page.folder_note.isHidden() and str(tmp_path / "m") in page.folder_note.text()
    assert changed


def test_formats_are_saved(page: SettingsPage) -> None:
    page.image_format.set_value("webp")
    page._set_format("image_format", "webp")
    assert Settings.load().image_format == "webp"


def test_catalog_url_must_be_https(page: SettingsPage) -> None:
    page.catalog_url.setText("http://example.com/catalog.yaml")
    page._catalog_url_changed()
    assert page.services.settings.catalog_url == DEFAULT_CATALOG_URL
    assert "https://" in page.catalog_status.text()


def test_update_catalog_now(page: SettingsPage, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(page.services.catalog, "update_from_url", lambda url: 21)
    page._update_catalog()
    qtbot.waitUntil(lambda: page.update_now.isEnabled(), timeout=3000)
    assert "21" in page.catalog_status.text()


def test_amd_without_rocm_build_offers_setup(page: SettingsPage, monkeypatch) -> None:
    rx = GpuInfo("AMD Radeon RX 7800 XT", "amd", 16.0, 16.0, flavor="rocm-gfx110x")
    hw = Hardware("Windows 11", "Test CPU", 6, 12, 32.0, 20.0, 8.0, (rx,), TorchBuild(True, "2.15.0+cpu"))
    monkeypatch.setattr(settings_module.hardware, "release_home", lambda: None)
    page._show_hardware(hw)
    assert not page.install_button.isHidden() and "RX 7800 XT" in page.install_button.text()
    assert not page.install_button.isEnabled()  # from source: the command is shown instead
    assert "--python 3.13 --extra rocm-gfx110x" in page.install_status.text()
    monkeypatch.setattr(settings_module.hardware, "release_home", lambda: Path("C:/SnapReel"))
    page._show_hardware(hw)
    assert page.install_button.isEnabled()
    rocm = Hardware("Windows 11", "Test CPU", 6, 12, 32.0, 20.0, 8.0, (rx,),
                    TorchBuild(True, "2.11.0+rocm7.13.0", hip="7.13.0"))
    page._show_hardware(rocm)
    assert page.install_button.isHidden() and "ROCm 7.13.0" in page.hw_summary.text()
