"""Chat page on the llama-server stand-in: send → stream → stop, history, edit, answer again."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from test_advisor import machine
from test_chat_worker import stub_command

from tvorka.core.chats import ChatStore
from tvorka.core.settings import Settings
from tvorka.gui import theme
from tvorka.gui.pages import chat as chat_page
from tvorka.gui.pages.chat import ChatPage
from tvorka.gui.services import Services
from tvorka.i18n import set_language

MODEL = "unsloth/Qwen3.5-2B-GGUF"


@pytest.fixture
def services(tmp_path: Path, qapp, monkeypatch: pytest.MonkeyPatch):
    set_language("ru")
    theme.apply(qapp, "dark")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))
    services.hardware = machine(8)
    monkeypatch.setattr(services, "installed", lambda spec: True)
    monkeypatch.setattr(services.store, "chat_files", lambda spec: (tmp_path / "m.gguf", None))
    monkeypatch.setattr(services.store, "chat_mtp", lambda spec: None)
    monkeypatch.setattr(chat_page.runtime, "server_path", lambda store, spec: tmp_path / "llama-server")
    services.chat_worker._command = stub_command
    services.chat_worker.start()
    yield services
    services.chat_worker.shutdown()
    services.chat_worker.wait(10_000)


@pytest.fixture
def page(services: Services, qtbot) -> ChatPage:
    widget = ChatPage(services, None)
    qtbot.addWidget(widget)
    widget.select_model(MODEL)
    return widget


def send(page: ChatPage, qtbot, text: str) -> None:
    page.text.setPlainText(text)
    assert page.action.isEnabled() and page.action.text() == "Отправить"
    page.generate()


def wait_answer(page: ChatPage, qtbot) -> None:
    qtbot.waitUntil(lambda: not page.session.busy, timeout=20_000)


def shown(view) -> str:
    """The text a message view displays (answers are rendered Markdown, i.e. HTML)."""
    from PySide6.QtGui import QTextDocument

    document = QTextDocument()
    document.setHtml(view.body.text())
    return document.toPlainText().strip()


def texts(page: ChatPage) -> list[tuple[str, str]]:
    return [(view.role, shown(view)) for view in page._views]


def test_send_streams_the_answer_and_keeps_the_history(services: Services, page: ChatPage, qtbot,
                                                        tmp_path: Path) -> None:
    assert page.empty.isVisibleTo(page)
    send(page, qtbot, "hi")
    assert page.text.toPlainText() == "" and page.action.text() == "Остановить"
    assert not page.empty.isVisibleTo(page)
    wait_answer(page, qtbot)
    assert texts(page) == [("user", "hi"), ("assistant", "Hello, world")]
    answer = page._views[-1]
    assert answer.reasoning.isVisibleTo(page) and not answer.reasoning.content.isVisibleTo(page)  # folded
    assert answer.reasoning_text.text() == "Thinking" and "42 ток/с" in answer.meta.text()
    assert page.action.text() == "Отправить" and not page.action.isEnabled()  # nothing typed
    titled = [page.list.item(i).text() for i in range(page.list.count())]
    assert titled == ["Сегодня", "hi"] or titled == ["Сегодня", "Hello, world"]

    # A new page (the window was rebuilt, or Tvorka restarted) opens the same chat.
    page.save_state()
    again = ChatPage(services, None)
    qtbot.addWidget(again)
    assert again._conv.id == page._conv.id and texts(again) == texts(page)
    [stored] = ChatStore(Path(os.environ["TVORKA_DATA_DIR"]) / "chats").all()
    assert [m.content for m in stored.messages] == ["hi", "Hello, world"]


def test_stop_keeps_the_partial_answer(page: ChatPage, qtbot) -> None:
    send(page, qtbot, "slow")
    qtbot.waitUntil(lambda: page._live is not None and len(shown(page._live)) > 5, timeout=20_000)
    page.cancel()  # Esc
    wait_answer(page, qtbot)
    answer = page.session.get(page._conv.id).messages[-1]
    assert answer.stopped and set(answer.content) == {"x"}
    assert page._views[-1].note.isVisibleTo(page) and page._views[-1].note.text() == "Ответ прерван."


def test_rebuilt_page_follows_a_running_answer(services: Services, page: ChatPage, qtbot) -> None:
    send(page, qtbot, "slow")
    qtbot.waitUntil(lambda: page._live is not None and bool(shown(page._live)), timeout=20_000)
    page.save_state()
    rebuilt = ChatPage(services, None)
    qtbot.addWidget(rebuilt)
    assert rebuilt._live is not None and rebuilt.action.text() == "Остановить"
    before = len(shown(rebuilt._live))
    qtbot.waitUntil(lambda: len(shown(rebuilt._live)) > before, timeout=10_000)
    rebuilt.cancel()
    wait_answer(rebuilt, qtbot)
    assert rebuilt._views[-1].role == "assistant"


def test_edit_replaces_the_rest_of_the_conversation(page: ChatPage, qtbot) -> None:
    send(page, qtbot, "first")
    wait_answer(page, qtbot)
    send(page, qtbot, "second")
    wait_answer(page, qtbot)
    assert len(page._conv.messages) == 4
    page._message_action("edit", 2)
    assert page.text.toPlainText() == "second" and page.editing_bar.isVisibleTo(page)
    page.text.setPlainText("second, better")
    page.generate()
    wait_answer(page, qtbot)
    assert [m.content for m in page._conv.messages] == ["first", "Hello, world", "second, better",
                                                        "Hello, world"]
    assert not page.editing_bar.isVisibleTo(page)


def test_answer_again_replaces_the_last_answer(page: ChatPage, qtbot) -> None:
    send(page, qtbot, "hi")
    wait_answer(page, qtbot)
    page._conv.messages[-1].content = "old answer"
    page._message_action("regenerate", 1)
    wait_answer(page, qtbot)
    assert [m.content for m in page._conv.messages] == ["hi", "Hello, world"]


def test_new_chat_and_delete(page: ChatPage, qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    send(page, qtbot, "hi")
    wait_answer(page, qtbot)
    first = page._conv
    page.new_chat()
    assert page._conv is not first and page._views == [] and page.empty.isVisibleTo(page)
    assert page._conv.model == MODEL
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    page._delete(first.id)
    assert page.session.get(first.id) is None and page.list_empty.isVisibleTo(page)


def test_settings_of_the_chat(page: ChatPage) -> None:
    page.role_box.setCurrentIndex(page.role_box.findData("translator"))
    assert page.auto_temperature.isChecked() and not page.temperature.isEnabled()
    assert page._conv.temperature is None  # as the model's authors recommend
    page.auto_temperature.setChecked(False)
    page.temperature.set_value(0.2)
    page.memory._buttons["16384"].click()
    assert (page._conv.role, page._conv.temperature, page._conv.ctx) == ("translator", 0.2, 16384)
    page.text.setPlainText("привет")
    assert page.counter.text().endswith("/ 16 384 токенов")
    page.instruction.setPlainText("Отвечай стихами")
    assert page._conv.instruction == "Отвечай стихами"
    assert not page.thinking.isHidden() and not page._conv.thinking  # Qwen3.5 can think; off by default
    page.thinking.setChecked(True)
    assert page._conv.thinking


def test_download_comes_first(services: Services, page: ChatPage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "installed", lambda spec: False)
    page._update_action()
    assert page.action.text().startswith("Скачать") and page.action.isEnabled()
    started = []
    monkeypatch.setattr(services.downloads, "start",
                        lambda spec, files=None: started.append((spec.id, files)))
    page._action_clicked()
    assert started[0][0].startswith("llama.cpp/")  # the server first, then the model
    assert started[1][0] == MODEL and any(f.endswith(".gguf") for f in started[1][1])


# ------------------------------------------------------------------ attachments
def attach(page: ChatPage, qtbot, *files: Path) -> None:
    page.add_files(list(files))
    qtbot.waitUntil(lambda: page._reading == 0, timeout=10_000)


def test_text_file_goes_with_the_message(page: ChatPage, qtbot, tmp_path: Path) -> None:
    note = tmp_path / "plan.md"
    note.write_text("# План\nсцена 1", encoding="utf-8")
    attach(page, qtbot, note)
    [chip] = page._chips
    assert chip.item is not None and chip.item.kind == "text" and "ток." in chip.detail.text()
    assert page.action.isEnabled()  # a file alone can be sent
    page.generate()
    wait_answer(page, qtbot)
    sent = page._conv.messages[0]
    assert sent.content == "" and [a.name for a in sent.files] == ["plan.md"]
    assert (page._folder() / "plan.md").is_file() and page._chips == []
    assert page._conv.title == "plan.md"
    assert page._views[0].findChildren(type(chip))  # the message shows its file


def test_pictures_need_a_model_that_sees(services: Services, page: ChatPage, qtbot, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    Image.new("RGB", (300, 200), "red").save(tmp_path / "red.png")
    attach(page, qtbot, tmp_path / "red.png")
    page.text.setPlainText("какого цвета?")
    assert not page.action.isEnabled() and "не видит картинки" in page.status.text()  # no projector on disk
    with_projector = (tmp_path / "m.gguf", tmp_path / "mmproj.gguf")
    monkeypatch.setattr(services.store, "chat_files", lambda spec: with_projector)
    page._update_action()
    assert page.action.isEnabled() and page.status.text() == ""


def test_pasted_picture_removed_and_kept_across_rebuild(services: Services, page: ChatPage, qtbot) -> None:
    from PySide6.QtGui import QColor, QImage

    image = QImage(64, 32, QImage.Format.Format_RGB32)
    image.fill(QColor("green"))
    page.text.image_pasted.emit(image)
    qtbot.waitUntil(lambda: page._reading == 0, timeout=10_000)
    [chip] = page._chips
    stored = page._folder() / chip.item.files[0]
    assert stored.is_file() and chip.item.kind == "image"

    page.save_state()
    rebuilt = ChatPage(services, None)  # the window was rebuilt: the file is still waiting to be sent
    qtbot.addWidget(rebuilt)
    assert [c.item.name for c in rebuilt._chips] == [chip.item.name]
    rebuilt._remove_chip(rebuilt._chips[0])
    assert not stored.exists() and rebuilt._pending() == [] and not rebuilt.chips.isVisibleTo(rebuilt)


def test_file_that_cannot_be_attached(page: ChatPage, qtbot, tmp_path: Path) -> None:
    (tmp_path / "tool.exe").write_bytes(b"MZ")
    attach(page, qtbot, tmp_path / "tool.exe")
    assert page._chips == [] and page._pending() == []


def test_editing_keeps_the_files_of_the_message(page: ChatPage, qtbot, tmp_path: Path) -> None:
    note = tmp_path / "a.txt"
    note.write_text("данные", encoding="utf-8")
    attach(page, qtbot, note)
    page.text.setPlainText("что в файле?")
    page.generate()
    wait_answer(page, qtbot)
    page._message_action("edit", 0)
    assert [c.item.name for c in page._chips] == ["a.txt"]
    page._cancel_edit()
    assert page._chips == [] and (page._folder() / "a.txt").is_file()  # still used by the message
    page._message_action("edit", 0)
    page.text.setPlainText("а коротко?")
    page.generate()
    wait_answer(page, qtbot)
    assert [m.content for m in page._conv.messages] == ["а коротко?", "Hello, world"]
    assert [a.name for a in page._conv.messages[0].files] == ["a.txt"]
