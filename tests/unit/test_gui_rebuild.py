"""Changing the language or theme rebuilds the window: what was typed but not sent must survive."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from tvorka.app import open_window
from tvorka.core.settings import Settings
from tvorka.gui.services import Services


def test_unsent_input_survives_rebuild_and_restart(tmp_path: Path, qapp) -> None:
    settings = Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o"), welcome_done=True)
    services = Services(settings)
    window = open_window(qapp, services)
    window.page("image").prompt.setPlainText("a cozy reading nook")
    window.page("speech").text.setPlainText("Привет, мир")
    window.page("video").prompt.setPlainText("waves at dawn")
    window.page("chat").text.setPlainText("Придумай сюжет")
    settings.language = "en" if settings.language != "en" else "ru"
    rebuilt = open_window(qapp, services, window)
    assert rebuilt.page("image").prompt.toPlainText() == "a cozy reading nook"
    assert rebuilt.page("speech").text.toPlainText() == "Привет, мир"
    assert rebuilt.page("video").prompt.toPlainText() == "waves at dawn"
    assert rebuilt.page("chat").text.toPlainText() == "Придумай сюжет"

    rebuilt.page("image").prompt.setPlainText("typed just before quitting")
    rebuilt.save_pages()
    settings.save()
    assert Settings.load().recall("image", "prompt") == "typed just before quitting"
    rebuilt.retire()
    rebuilt.deleteLater()


def test_window_with_toasts_closes_cleanly(qapp) -> None:
    from PySide6.QtWidgets import QWidget

    from tvorka.gui.widgets.feedback import ToastHost

    errors: list[BaseException] = []
    import sys

    previous = sys.excepthook
    sys.excepthook = lambda _t, exc, _tb: errors.append(exc)
    try:
        window = QWidget()
        host = ToastHost(window)
        host.show("one", "bad")
        host.show("two", "info")
        window.deleteLater()
        qapp.processEvents()
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        sys.excepthook = previous
    assert errors == []
