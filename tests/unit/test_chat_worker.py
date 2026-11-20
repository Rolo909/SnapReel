"""ChatWorker and ChatSession against the llama-server stand-in (``llama_stub.py`` as a process)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from tvorka.core.advisor import LlmPlan
from tvorka.core.chats import ChatStore, Conversation, Message
from tvorka.workers.chat import ChatSession, ChatWorker, Launch

STUB = Path(__file__).with_name("llama_stub.py")
started: list[list[str]] = []


def stub_command(launch: Launch, port: int) -> list[str]:
    command = [sys.executable, str(STUB), "--port", str(port), "--load", "0.3"]
    if launch.model.name == "broken.gguf":
        command += ["--fail", "llama_model_load: error loading model: unknown model architecture: 'x'"]
    started.append(command)
    return command


def launch(name: str = "m.gguf", model_id: str = "test/chat") -> Launch:
    return Launch(model_id, Path("llama-server"), Path(name), LlmPlan("Q4_K_M", 8192, 32, True))


@pytest.fixture
def session(tmp_path: Path, qtbot):
    started.clear()
    worker = ChatWorker(tmp_path / "logs" / "llama-server.log", stub_command, ready_timeout_s=30)
    worker.start()
    chat = ChatSession(ChatStore(tmp_path / "chats"), worker)
    yield chat
    worker.shutdown()
    worker.wait(10_000)


def ask(conv: Conversation, text: str) -> Conversation:
    conv.messages.append(Message("user", text))
    return conv


def test_answer_is_streamed_saved_and_titled(session: ChatSession, qtbot, tmp_path: Path) -> None:
    conv = ask(Conversation(), "hi")
    with qtbot.waitSignal(session.worker.titled, timeout=20_000):
        session.send(conv, launch(), 8192)
        assert session.busy and session.answering == conv.id
    assert not session.busy
    answer = conv.messages[-1]
    assert (answer.role, answer.content, answer.reasoning) == ("assistant", "Hello, world", "Thinking")
    assert answer.model == "test/chat" and not answer.stopped
    assert answer.stats["predicted_per_second"] == 42.0
    assert conv.title == "Hello, world"  # the stub answers every request the same way
    [saved] = ChatStore(tmp_path / "chats").all()
    assert saved.messages == conv.messages and saved.title == "Hello, world"
    assert session.worker.loaded_model == "test/chat"


def test_server_is_reused_and_restarted_for_another_model(session: ChatSession, qtbot) -> None:
    conv = ask(Conversation(title="t"), "one")
    with qtbot.waitSignal(session.state_changed, timeout=20_000, check_params_cb=lambda: not session.busy):
        session.send(conv, launch(), 8192)
    ask(conv, "two")
    with qtbot.waitSignal(session.state_changed, timeout=20_000, check_params_cb=lambda: not session.busy):
        session.send(conv, launch(), 8192)
    assert len(started) == 1  # same model, same plan: no reload
    ask(conv, "three")
    with qtbot.waitSignal(session.worker.model_changed, timeout=20_000,
                          check_params_cb=lambda model: model == "other/chat"):
        session.send(conv, launch(model_id="other/chat"), 8192)
    qtbot.waitUntil(lambda: not session.busy, timeout=20_000)
    assert len(started) == 2
    assert [m.content for m in conv.messages if m.role == "assistant"] == ["Hello, world"] * 3


def test_stop_keeps_the_words_already_written(session: ChatSession, qtbot) -> None:
    conv = ask(Conversation(title="t"), "slow")
    session.send(conv, launch(), 8192)
    qtbot.waitUntil(lambda: session.partial is not None and len(session.partial.content) > 5, timeout=20_000)
    with qtbot.waitSignal(session.worker.cancelled, timeout=10_000):
        session.stop()
    answer = conv.messages[-1]
    assert answer.role == "assistant" and answer.stopped and 5 < len(answer.content) < 2000
    assert set(answer.content) == {"x"}


def test_model_that_cannot_load_is_explained(session: ChatSession, qtbot) -> None:
    conv = ask(Conversation(title="t"), "hi")
    with qtbot.waitSignal(session.failed, timeout=20_000) as blocker:
        session.send(conv, launch("broken.gguf"), 8192)
    assert blocker.args[:2] == [conv.id, "unsupported"]
    assert conv.messages[-1].role == "user" and not session.busy  # nothing half-written was added
    assert session.worker.loaded_model == ""


def test_context_overflow_is_reported(session: ChatSession, qtbot) -> None:
    conv = ask(Conversation(title="t"), "too long")
    with qtbot.waitSignal(session.failed, timeout=20_000) as blocker:
        session.send(conv, launch(), 8192)
    assert blocker.args[1] == "context_overflow"


def test_deleting_the_chat_being_answered(session: ChatSession, qtbot, tmp_path: Path) -> None:
    conv = ask(Conversation(title="t"), "slow")
    session.send(conv, launch(), 8192)
    qtbot.waitUntil(lambda: session.partial is not None and bool(session.partial.content), timeout=20_000)
    with qtbot.waitSignal(session.worker.cancelled, timeout=10_000):
        session.delete(conv.id)
    assert session.get(conv.id) is None and not session.busy
    assert ChatStore(tmp_path / "chats").all() == []
