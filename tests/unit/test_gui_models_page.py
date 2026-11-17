"""Models page without network or GPU."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from tvorka.core.settings import Settings
from tvorka.gui import theme
from tvorka.gui.pages.models import ModelsPage
from tvorka.gui.services import Services
from tvorka.i18n import set_language


@pytest.fixture
def page(tmp_path: Path, qapp, qtbot) -> ModelsPage:
    set_language("ru")
    theme.apply(qapp, "dark")
    settings = Settings(models_dir=str(tmp_path / "models"), output_dir=str(tmp_path / "out"))
    widget = ModelsPage(Services(settings), None)
    qtbot.addWidget(widget)
    return widget


def visible_cards(page: ModelsPage) -> list:
    return list(page._cards.values())


def test_catalog_lists_every_model(page: ModelsPage) -> None:
    assert len(visible_cards(page)) == len(page.services.catalog.all())
    turbo = page._cards["stabilityai/sd-turbo"]
    assert turbo.primary.text() == "Скачать"  # nothing installed in the temporary folder


def test_kind_filter_and_installed_tab(page: ModelsPage) -> None:
    page.kind.set_value("video")
    page._kind_changed("video")
    assert {c.spec.kind for c in visible_cards(page)} == {"video"}
    page.tab.set_value("installed")
    page._tab_changed("installed")
    assert visible_cards(page) == []  # only the empty-state label


def test_download_button_starts_a_download(page: ModelsPage, monkeypatch) -> None:
    started = []
    monkeypatch.setattr(page.services.downloads, "start", lambda spec: started.append(spec.id))
    page._cards["stabilityai/sd-turbo"].primary.click()
    assert started == ["stabilityai/sd-turbo"]


def test_gated_model_without_token_explains_instead(page: ModelsPage, monkeypatch) -> None:
    started, hints = [], []
    monkeypatch.setattr(page.services.downloads, "start", lambda spec: started.append(spec.id))
    monkeypatch.setattr(page, "_gated_hint", lambda spec: hints.append(spec.id))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    page._download("black-forest-labs/FLUX.1-schnell")
    assert started == [] and hints == ["black-forest-labs/FLUX.1-schnell"]


def test_local_model_preview_and_add(page: ModelsPage, tmp_path: Path, qtbot) -> None:
    import zipfile

    file = tmp_path / "v4_ru.pt"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("v4_ru/tts_models/model.pkl", b"x")
    page._toggle_add()
    page.source.set_value("file")
    page._source_changed("file")
    page.source_edit.setText(str(file))
    page._recognize()
    qtbot.waitUntil(lambda: page._preview_spec is not None, timeout=5000)
    page._add_previewed()
    assert page.services.catalog.get("local/v4_ru") is not None
