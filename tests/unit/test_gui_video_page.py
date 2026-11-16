from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from snapreel.core.settings import Settings
from snapreel.gui import theme
from snapreel.gui.pages.video import VideoPage
from snapreel.gui.services import Services
from snapreel.i18n import set_language


@pytest.fixture
def page(tmp_path: Path, qapp, qtbot, monkeypatch) -> VideoPage:
    set_language("ru")
    theme.apply(qapp, "dark")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))
    monkeypatch.setattr(services, "installed", lambda spec: True)
    widget = VideoPage(services, None)
    qtbot.addWidget(widget)
    return widget


def test_duration_limits_follow_the_model(page: VideoPage) -> None:
    page.select_model("THUDM/CogVideoX-2b")
    assert page.seconds.box.maximum() == pytest.approx(6.0)  # 49 frames at 8 fps
    assert "49" in page.frames_info.text() and "предел" not in page.frames_info.text()
    assert page.aspect_field.isHidden()  # fixed 720×480 model
    page.select_model("Lightricks/LTX-Video")
    assert not page.aspect_field.isHidden()


def test_reference_requirement(page: VideoPage) -> None:
    page.select_model("THUDM/CogVideoX-5b-I2V")
    page.prompt.setPlainText("waves")
    assert not page.frame_hint.isHidden()
    assert not page.action.isEnabled()  # needs a first frame
    page.select_model("THUDM/CogVideoX-2b")
    assert page.frame_card.isHidden()  # text only
    assert page.action.isEnabled()


def test_job_parameters(page: VideoPage, monkeypatch) -> None:
    submitted = []
    monkeypatch.setattr(page.services.worker, "submit", lambda job: submitted.append(job))
    page.select_model("THUDM/CogVideoX-2b")
    page.prompt.setPlainText("a paper boat")
    page.seconds.set_value(2.0)
    page.fps.set_value("24")
    page.generate()
    job = submitted[-1]
    assert job.kind == "video" and job.get("seconds") == 2.0 and job.get("fps") == 24
    assert (job.get("width"), job.get("height")) == (720, 480)
    assert "reference" not in job.params
