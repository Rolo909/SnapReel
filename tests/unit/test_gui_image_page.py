"""The image page without a GPU: the worker thread is never started."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from tvorka.core.settings import Settings
from tvorka.gui import theme
from tvorka.gui.main_window import MainWindow
from tvorka.gui.pages.image import ImagePage
from tvorka.gui.services import Services
from tvorka.i18n import set_language


@pytest.fixture
def services(tmp_path: Path, qapp) -> Services:
    set_language("ru")
    theme.apply(qapp, "dark")
    settings = Settings(models_dir=str(tmp_path / "models"), output_dir=str(tmp_path / "out"))
    return Services(settings)


def test_page_builds_and_tracks_prompt(services: Services, qtbot) -> None:
    page = ImagePage(services, None)
    qtbot.addWidget(page)
    assert page.model_box.count() == len(services.catalog.all("image"))
    # Nothing is installed in the temporary models folder: the button offers a download.
    assert page.action.text().startswith("Скачать")


def test_installed_model_needs_a_prompt(services: Services, qtbot, monkeypatch) -> None:
    monkeypatch.setattr(services, "installed", lambda spec: True)
    page = ImagePage(services, None)
    qtbot.addWidget(page)
    page.prompt.setPlainText("")
    assert not page.action.isEnabled()
    page.prompt.setPlainText("a cat")
    assert page.action.isEnabled() and page.action.text() == "Создать"


def test_model_change_updates_fields(services: Services, qtbot) -> None:
    page = ImagePage(services, None)
    qtbot.addWidget(page)
    page.model_box.setCurrentIndex(page.model_box.findData("stabilityai/sd-turbo"))
    assert page.steps.value() == 2 and page.negative_field.isHidden()
    assert page.steps.slider.maximum() == 8
    page.model_box.setCurrentIndex(page.model_box.findData("Lykon/dreamshaper-8"))
    assert page.steps.value() == 25 and not page.negative_field.isHidden()
    assert page.reference_mode.value() == "img2img"


def test_exact_size_shows_the_route(services: Services, qtbot) -> None:
    page = ImagePage(services, None)
    qtbot.addWidget(page)
    page.model_box.setCurrentIndex(page.model_box.findData("stabilityai/sd-turbo"))
    page.size_mode.set_value("exact")
    page._size_mode_changed("exact")
    page.exact.set_value(3840, 2160)
    assert page.upscale_field.isVisibleTo(page)
    assert "680 × 384" in page.size_info.text()
    page.exact.set_value(512, 512)
    assert not page.upscale_field.isVisibleTo(page)


def test_main_window_navigation(services: Services, qtbot) -> None:
    from tvorka.app import build_pages

    window = MainWindow(services, build_pages(services, None))
    qtbot.addWidget(window)
    window.open_page(4)
    assert window.current_page().key == "models"
    window.open_page(99)
    assert window.current_page().key == "models"


def test_settings_page_switches_language_and_theme(services: Services, qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    from tvorka.app import open_window

    window = open_window(QApplication.instance(), services)
    qtbot.addWidget(window)
    window.open_page(window.pages.index(window.page("settings")))
    settings_page = window.current_page()
    assert settings_page.key == "settings"
    settings_page.language.set_value("en")
    settings_page._language_changed("en")
    new = QApplication.instance().property("main_window")
    qtbot.addWidget(new)
    assert new is not window
    assert services.settings.language == "en"
    assert new.current_page().key == "settings"
    assert new.current_page().title() == "Settings"
    new.current_page()._theme_changed("light")
    newest = QApplication.instance().property("main_window")
    qtbot.addWidget(newest)
    from tvorka.gui import theme

    assert theme.name() == "light" and services.settings.theme == "light"
    from tvorka.i18n import set_language

    set_language("ru")
    theme.apply(QApplication.instance(), "dark")


def test_first_run_opens_the_welcome_screen_once(services: Services, qtbot) -> None:
    from PySide6.QtWidgets import QApplication

    from tvorka.app import open_window

    window = open_window(QApplication.instance(), services)
    qtbot.addWidget(window)
    assert window.current_page().key == "welcome"
    assert all(b.text().strip() != window.current_page().title() for b in window._buttons.buttons())
    window.current_page()._skip()
    assert services.settings.welcome_done and window.current_page().key == "image"
    again = open_window(QApplication.instance(), services, None)
    qtbot.addWidget(again)
    assert again.current_page().key != "welcome"


def test_welcome_start_downloads_selection(services: Services, qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from tvorka.app import open_window
    from tvorka.core.hardware import GpuInfo, Hardware, TorchBuild

    services.hardware = Hardware("OS", "CPU", 6, 12, 16.0, 9.0, 8.0,
                                 (GpuInfo("GPU", "nvidia", 8.0, 7.5),), TorchBuild(True, "2.14", "13.0"))
    started = []
    monkeypatch.setattr(services.downloads, "start", lambda spec: started.append(spec.id))
    window = open_window(QApplication.instance(), services)
    qtbot.addWidget(window)
    welcome = window.current_page()
    welcome.shown()
    assert welcome.start.text() == "Скачать выбранное и начать"
    welcome._start()
    assert "stabilityai/sd-turbo" in started and "THUDM/CogVideoX-2b" not in started
    assert window.current_page().key == "image"
    assert window.current_page().model_box.currentData() == "stabilityai/sd-turbo"


def test_buttons_take_focus_from_tab_only_and_pages_focus_their_input(services: Services, qtbot) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from tvorka.app import build_pages

    services.settings.welcome_done = True
    window = MainWindow(services, build_pages(services, None))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    buttons = [b for b in window.findChildren(QPushButton) if b.isVisible()]  # polished ones
    assert buttons and all(b.focusPolicy() != Qt.FocusPolicy.StrongFocus for b in buttons)
    window.open_page(0)
    assert window.pages[0].focus_widget() is window.pages[0].prompt
    assert window.page("speech").focus_widget() is window.page("speech").text
    assert window.page("models").focus_widget() is window.page("models")
