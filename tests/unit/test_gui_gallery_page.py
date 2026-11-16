from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from PIL import Image

from snapreel.core.jobs import Job, Result
from snapreel.core.settings import Settings
from snapreel.gui import theme
from snapreel.gui.pages.gallery import GalleryPage
from snapreel.gui.services import Services
from snapreel.i18n import set_language


@pytest.fixture
def services(tmp_path: Path, qapp) -> Services:
    set_language("ru")
    theme.apply(qapp, "dark")
    return Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))


def add_work(services: Services, tmp_path: Path, name: str, kind: str = "image") -> Result:
    path = tmp_path / name
    Image.new("RGB", (64, 32), "teal").save(path)
    job = Job(kind, "stabilityai/sd-turbo", "a teal box", {"seed": 7, "width": 64, "height": 32})
    result = Result.make(job, path, "SD Turbo", 0.5)
    services.history.add(result)
    return result


def test_empty_gallery_invites_to_create(services: Services, qtbot) -> None:
    page = GalleryPage(services, None)
    qtbot.addWidget(page)
    page.shown()
    assert page.stack.currentIndex() == 1


def test_grid_details_and_delete(services: Services, qtbot, tmp_path: Path, monkeypatch) -> None:
    first = add_work(services, tmp_path, "a.png")
    add_work(services, tmp_path, "b.png")
    page = GalleryPage(services, None)
    qtbot.addWidget(page)
    page.shown()
    assert page.grid.count() == 2 and page.stack.currentIndex() == 0
    qtbot.waitUntil(lambda: not page._pending, timeout=3000)
    page.grid.setCurrentRow(1)
    assert page.detail_prompt.text() == "a teal box"
    assert "64 × 32" in page.detail_meta.text()

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page._delete()
    assert not Path(first.path).exists()
    assert page.grid.count() == 1


def test_kind_filter(services: Services, qtbot, tmp_path: Path) -> None:
    add_work(services, tmp_path, "a.png")
    page = GalleryPage(services, None)
    qtbot.addWidget(page)
    page.kind.set_value("video")
    page._kind_changed("video")
    assert page.stack.currentIndex() == 1
