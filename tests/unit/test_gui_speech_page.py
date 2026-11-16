from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from snapreel.core.settings import Settings
from snapreel.gui import theme
from snapreel.gui.pages.speech import SpeechPage
from snapreel.gui.services import Services
from snapreel.i18n import set_language


@pytest.fixture
def page(tmp_path: Path, qapp, qtbot) -> SpeechPage:
    set_language("ru")
    theme.apply(qapp, "dark")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))
    widget = SpeechPage(services, None)
    qtbot.addWidget(widget)
    return widget


def test_voices_follow_the_model(page: SpeechPage) -> None:
    page.select_model("silero/v4_ru")
    names = [page.voice.itemText(i) for i in range(page.voice.count())]
    assert "Ксения" in names and page.voice.isEnabled()
    assert not page.online_note.isVisibleTo(page)
    page.select_model("facebook/mms-tts-rus")
    assert page.voice.count() == 1 and not page.voice.isEnabled()
    page.select_model("edge/online")
    assert not page.online_note.isHidden()


def test_counter_and_action(page: SpeechPage, monkeypatch) -> None:
    page.select_model("silero/v4_ru")
    assert page.action.text().startswith("Скачать")  # not installed in the temp folder
    monkeypatch.setattr(page.services, "installed", lambda spec: True)
    page.text.setPlainText("")
    assert not page.action.isEnabled()
    page.text.setPlainText("Привет, мир! " * 10)
    assert page.action.isEnabled() and page.action.text() == "Озвучить"
    assert "Символов: 129" in page.counter.text()


def test_job_parameters(page: SpeechPage, monkeypatch) -> None:
    monkeypatch.setattr(page.services, "installed", lambda spec: True)
    submitted = []
    monkeypatch.setattr(page.services.worker, "submit", lambda job: submitted.append(job))
    page.select_model("silero/v4_ru")
    page.text.setPlainText("Проверка")
    page.speed.set_value(1.5)
    page.generate()
    job = submitted[-1]
    assert job.kind == "speech" and job.get("speed") == 1.5 and not job.get("preview")
    assert job.get("voice") == page.voice.currentData()
    page._play_sample()
    assert submitted[-1].get("preview") is True
