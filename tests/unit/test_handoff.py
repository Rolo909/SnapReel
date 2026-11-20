"""Passing work between sections: which routes each asset gets, and what each section does with it."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from PIL import Image
from test_stt import write_wav

from tvorka.core.jobs import Job, Result
from tvorka.core.settings import Settings
from tvorka.engines import media
from tvorka.gui import handoff
from tvorka.gui.handoff import Asset, Route
from tvorka.gui.services import Services
from tvorka.i18n import set_language


@pytest.fixture
def window(tmp_path: Path, qapp, qtbot):
    from tvorka.app import open_window

    set_language("ru")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o"),
                                 welcome_done=True))
    win = open_window(qapp, services)
    qtbot.addWidget(win)
    return win


def work(services: Services, kind: str, path: Path, prompt: str = "a lighthouse", **params) -> Result:
    model = {"image": "stabilityai/sd-turbo", "video": "THUDM/CogVideoX-2b", "speech": "silero/v4_ru"}[kind]
    result = Result.make(Job(kind, model, prompt, params), path, "Model", 1.0)
    services.history.add(result)
    return result


def picture(path: Path, color: str = "red") -> Path:
    Image.new("RGB", (64, 48), color).save(path)
    return path


def clip(path: Path, frames: int = 8) -> Path:
    media.write_video(np.stack([np.full((48, 64, 3), i * 30, np.uint8) for i in range(frames)]), 8, path)
    return path


def routes(window, asset: Asset) -> set[tuple[str, str]]:
    return {(r.page, r.role) for r in window.routes_for(asset)}


def test_every_kind_has_its_routes(window, tmp_path: Path) -> None:
    services = window.services
    image = handoff.from_result(work(services, "image", picture(tmp_path / "a.png")), "image")
    assert routes(window, image) == {("image", "reference"), ("image", "settings"), ("video", "first_frame"),
                                     ("chat", "attachment")}
    video = handoff.from_result(work(services, "video", clip(tmp_path / "v.mp4")), "video")
    assert routes(window, video) == {("video", "first_frame"), ("chat", "attachment")}
    voice = handoff.from_result(work(services, "speech", write_wav(tmp_path / "s.wav")), "speech")
    assert routes(window, voice) == {("chat", "attachment")}  # no clip on the Video page yet
    window.page("video")._current = str(tmp_path / "v.mp4")
    assert routes(window, voice) == {("chat", "attachment"), ("video", "voiceover")}
    answer = handoff.text("A lighthouse in a storm", "chat", parent="chat:abc")
    assert routes(window, answer) == {("image", "prompt"), ("video", "prompt"), ("speech", "text")}
    assert ("chat", "text") in routes(window, handoff.text("note", "gallery"))
    assert routes(window, handoff.text("   ")) == set() and routes(window, Asset("file", "x.zip")) == set()
    assert handoff.from_path("x.mp3").kind == "audio" and handoff.from_path("x.zip") is None


def test_picture_becomes_the_first_frame_and_remembers_where_from(window, tmp_path: Path,
                                                                   monkeypatch) -> None:
    services = window.services
    source = work(services, "image", picture(tmp_path / "a.png"))
    window.send(handoff.from_result(source, "image"), Route("video", "first_frame", ""))
    video = window.page("video")
    assert window.current_page() is video and video.dropzone.path() == source.path
    assert video.parent_for(video.prompt.toPlainText(), video.dropzone.path()) == source.id
    video.dropzone.set_path(str(picture(tmp_path / "other.png", "blue")))  # replaced: no longer its child
    assert video.parent_for(video.prompt.toPlainText(), video.dropzone.path()) == ""


def test_continue_the_clip_from_its_last_frame(window, tmp_path: Path) -> None:
    services = window.services
    source = work(services, "video", clip(tmp_path / "v.mp4"))
    video = window.page("video")
    video._current = source.path
    video._continue_clip()
    frame = Path(video.dropzone.path())
    assert frame.is_file() and frame.suffix == ".png"
    assert np.asarray(Image.open(frame)).mean() > 180  # the last, brightest frame
    assert video.parent_for("", str(frame)) == source.id


def test_chat_answer_becomes_a_prompt_with_lineage(window, monkeypatch) -> None:
    image = window.page("image")
    monkeypatch.setattr(window.services, "installed", lambda spec: True)
    window.send(handoff.text(" A lighthouse in a storm ", "chat", parent="chat:abc"),
                Route("image", "prompt", ""))
    assert image.prompt.toPlainText() == "A lighthouse in a storm"
    jobs: list[Job] = []
    monkeypatch.setattr(window.services.worker, "submit", lambda job: jobs.append(job) or job.id)
    image._update_action()
    image.generate()
    assert jobs and jobs[-1].params["parent"] == "chat:abc"
    image.prompt.setPlainText("Something else")  # typed over: a new work of its own
    image.generate()
    assert "parent" not in jobs[-1].params


def test_gallery_repeat_goes_through_the_protocol(window, tmp_path: Path) -> None:
    services = window.services
    work(services, "image", picture(tmp_path / "a.png"), prompt="old sailor", steps=3, seed=42)
    gallery = window.page("gallery")
    window.open_page(window.pages.index(gallery))
    gallery._rebuild()
    gallery._repeat()
    image = window.page("image")
    assert window.current_page() is image
    assert image.prompt.toPlainText() == "old sailor" and image.seed.value() == 42


def test_voice_over_on_the_clip(window, tmp_path: Path, qtbot) -> None:
    services = window.services
    source = work(services, "video", clip(tmp_path / "v.mp4", 8))  # 1 s of picture
    voice = work(services, "speech", write_wav(tmp_path / "s.wav", 2.5))
    video = window.page("video")
    video._current = source.path
    before = len(services.history.items("video"))
    window.send(handoff.from_result(voice, "speech"), Route("video", "voiceover", ""))
    qtbot.waitUntil(lambda: len(services.history.items("video")) > before, timeout=20_000)
    made = services.history.items("video")[0]
    assert made.params["parent"] == source.id and made.params["voiceover"] == voice.id
    assert made.params["duration"] == 2.5  # the picture holds its last frame while the voice goes on
    import av

    with av.open(made.path) as container:
        assert {s.type for s in container.streams} == {"video", "audio"}


def test_gallery_shows_where_a_work_comes_from(window, tmp_path: Path) -> None:
    services = window.services
    parent = work(services, "image", picture(tmp_path / "a.png"), prompt="a red square")
    child = work(services, "video", clip(tmp_path / "v.mp4"), parent=parent.id)
    gallery = window.page("gallery")
    window.open_page(window.pages.index(gallery))
    gallery.kind.set_value("video")
    gallery._rebuild()
    assert gallery._current().id == child.id
    assert gallery.lineage.isVisibleTo(gallery) and "a red square" in gallery.lineage.toolTip()
    assert gallery.lineage.text().startswith("Создано из")
    gallery._show_parent()  # jumps to the picture even though only videos were shown
    assert gallery._current().id == parent.id and gallery.kind.value() == ""


def test_dragging_out_and_dropping_on_a_section(window, tmp_path: Path) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QDropEvent

    from tvorka.gui.widgets.canvas import FilmStrip, file_mime

    strip = FilmStrip()
    strip.add(str(picture(tmp_path / "a.png")))
    assert [Path(u.toLocalFile()) for u in strip.mimeData([strip.item(0)]).urls()] == [tmp_path / "a.png"]

    button = window._buttons.button(window.pages.index(window.page("chat")))
    mime = file_mime([str(tmp_path / "a.png")])  # kept alive: the event does not own it
    drop = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QEvent.Type.Drop)
    window.eventFilter(button, drop)  # one way to take it: no question asked
    chat = window.page("chat")
    assert window.current_page() is chat
    assert chat._reading == 1 or chat._chips  # the picture is being attached
