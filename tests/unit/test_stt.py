"""Speech recognition: the Whisper engine's input, the worker thread, the microphone button, attachments."""

from __future__ import annotations

import os
import wave
from concurrent.futures import Future
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from tvorka.core import attachments
from tvorka.core.attachments import AttachmentError
from tvorka.engines.base import EngineError
from tvorka.engines.whisper import RATE, WhisperEngine, load_speech
from tvorka.workers.stt import SttWorker


def write_wav(path: Path, seconds: float = 1.0, rate: int = 44_100, tone: bool = True) -> Path:
    t = np.arange(int(seconds * rate)) / rate
    samples = (0.3 * np.sin(2 * np.pi * 220 * t)) if tone else np.zeros_like(t)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((samples * 32767).astype(np.int16).tobytes())
    return path


# ------------------------------------------------------------------ engine
def test_speech_is_read_at_16_khz(tmp_path: Path) -> None:
    samples = load_speech(write_wav(tmp_path / "a.wav", 2.0, 44_100))
    assert samples.dtype == np.float32 and abs(samples.size - 2 * RATE) < RATE // 50
    with pytest.raises(EngineError) as error:
        load_speech(tmp_path / "missing.wav")
    assert error.value.code == "unreadable"


def test_silence_is_not_sent_to_the_model(tmp_path: Path) -> None:
    calls = []
    engine = WhisperEngine(tmp_path, "cpu")
    engine.pipe = lambda audio, **kw: calls.append((audio, kw)) or {"text": "  привет,   мир "}
    assert engine.transcribe(write_wav(tmp_path / "quiet.wav", 2.0, tone=False)) == ""
    assert calls == []
    assert engine.transcribe(write_wav(tmp_path / "tone.wav", 2.0)) == "привет, мир"
    audio, options = calls[0]
    assert audio["sampling_rate"] == RATE and options["chunk_length_s"] == 30  # long recordings in parts


# ------------------------------------------------------------------ worker
class FakeEngine:
    loads: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, path: Path, device: str) -> None:
        self.key = (str(path), device)

    def load(self) -> None:
        FakeEngine.loads.append(self.key)

    def transcribe(self, audio: Path) -> str:
        if audio.name == "bad.wav":
            raise EngineError("unreadable", "bad")
        return f"text of {audio.name}"

    def unload(self) -> None:
        pass


@pytest.fixture
def worker(qtbot):
    FakeEngine.loads = []
    stt = SttWorker(FakeEngine)
    stt.start()
    yield stt
    stt.shutdown()
    stt.wait(5000)


def test_worker_keeps_the_model_loaded(worker: SttWorker, qtbot) -> None:
    with qtbot.waitSignal(worker.transcribed, timeout=5000) as first:
        _id, future = worker.submit("m", Path("model"), "cpu", Path("one.wav"))
    assert first.args[1] == "text of one.wav" and future.result(1) == "text of one.wav"
    _id, future = worker.submit("m", Path("model"), "cpu", Path("two.wav"))
    assert future.result(5) == "text of two.wav"
    assert FakeEngine.loads == [("model", "cpu")]  # loaded once
    _id, future = worker.submit("m", Path("model"), "cuda", Path("three.wav"))
    future.result(5)
    assert FakeEngine.loads == [("model", "cpu"), ("model", "cuda")]
    with qtbot.waitSignal(worker.model_changed, timeout=5000, check_params_cb=lambda m: m == ""):
        worker.unload()


def test_worker_reports_a_bad_file(worker: SttWorker, qtbot) -> None:
    with qtbot.waitSignal(worker.failed, timeout=5000) as blocker:
        _id, future = worker.submit("m", Path("model"), "cpu", Path("bad.wav"))
    assert blocker.args[1] == "unreadable"
    with pytest.raises(EngineError):
        future.result(1)
    assert worker.submit("m", Path("model"), "cpu", Path("ok.wav"))[1].result(5) == "text of ok.wav"


# ------------------------------------------------------------------ attachments
def done(text: str) -> Future:
    future: Future = Future()
    future.set_result(text)
    return future


def test_sound_file_becomes_text(tmp_path: Path) -> None:
    sound = write_wav(tmp_path / "note.wav")
    with pytest.raises(AttachmentError) as error:  # no recognition model
        attachments.prepare(sound, tmp_path / "files", lambda p: None)
    assert error.value.code == "audio"
    item = attachments.prepare(sound, tmp_path / "files", lambda p: "купить молоко")
    assert (item.kind, item.text, item.files) == ("audio", "купить молоко", ["note.wav"])
    content = attachments.message_content("что в заметке?", [item], tmp_path / "files")
    assert "What is said in “note.wav”" in content and "купить молоко" in content
    with pytest.raises(AttachmentError) as error:
        attachments.prepare(sound, tmp_path / "files", lambda p: "")
    assert error.value.code == "silent"

    def broken(path: Path) -> str:
        raise EngineError("unreadable", "x")

    with pytest.raises(AttachmentError) as error:
        attachments.prepare(sound, tmp_path / "files", broken)
    assert error.value.code == "unreadable"


def test_video_gets_frames_and_its_speech(tmp_path: Path) -> None:
    import av

    source = tmp_path / "clip.mp4"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(20):
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 10, np.uint8), format="rgb24")
            container.mux(stream.encode(frame))
        container.mux(stream.encode())
    heard = attachments.prepare(source, tmp_path / "a", lambda p: "привет из видео")
    assert len(heard.images) == attachments.VIDEO_FRAMES and heard.text == "привет из видео"

    def silent(path: Path) -> str:
        raise EngineError("no_sound", path.name)

    quiet = attachments.prepare(source, tmp_path / "b", silent)  # a video without sound is fine
    assert quiet.text == "" and len(quiet.images) == attachments.VIDEO_FRAMES
    assert attachments.prepare(source, tmp_path / "c", lambda p: None).text == ""  # no model: frames only


# ------------------------------------------------------------------ microphone
class FakeRecorder:
    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            stopped = Signal(str)
            error = Signal(str)

        self._signals = Signals()
        self.stopped, self.error = self._signals.stopped, self._signals.error
        self.file: Path | None = None

    def record(self, file: Path) -> None:
        self.file = file

    def stop(self) -> None:
        write_wav(self.file)
        self.stopped.emit(str(self.file))


class Toasts:
    def __init__(self) -> None:
        self.shown: list[str] = []

    def show(self, text: str, level: str = "info", *args: object, **kwargs: object) -> None:
        self.shown.append(text)


@pytest.fixture
def page(tmp_path: Path, qapp, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QPlainTextEdit

    from tvorka.core.settings import Settings
    from tvorka.gui.services import Services
    from tvorka.i18n import set_language

    set_language("ru")
    services = Services(Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o")))
    return SimpleNamespace(services=services, toasts=Toasts(), text=QPlainTextEdit())


def test_microphone_needs_a_recognition_model(page) -> None:
    from tvorka.gui.widgets.mic import MicButton

    mic = MicButton(page, page.text)
    mic.click()
    assert mic.state == "idle" and "распознавания речи" in page.toasts.shown[0]


def test_dictation_lands_in_the_text_field(page, qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from tvorka.gui.widgets.mic import MicButton

    monkeypatch.setattr(page.services, "stt_model", lambda: object())
    heard: list[Path] = []

    def transcribe(audio: Path) -> tuple[int, Future]:
        heard.append(audio)
        return 7, done("и ещё маяк")

    monkeypatch.setattr(page.services, "transcribe", transcribe)
    page.text.setPlainText("Закат над морем")
    cursor = page.text.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    page.text.setTextCursor(cursor)
    mic = MicButton(page, page.text)
    mic.recorder = FakeRecorder()
    mic.click()
    assert mic.state == "recording" and mic.text() == "0:00"
    mic.click()  # stop: the recording goes to recognition
    assert mic.state == "listening" and heard and heard[0].is_file()
    page.services.stt.transcribed.emit(7, "и ещё маяк")
    assert page.text.toPlainText() == "Закат над морем и ещё маяк"  # inserted, nothing sent
    assert mic.state == "idle" and not heard[0].exists()  # the recording is not kept
    mic.click()
    mic.click()
    page.services.stt.transcribed.emit(7, "")
    assert page.toasts.shown[-1].startswith("Речь не слышна")


def test_best_installed_recognition_model(page, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_advisor import machine

    services = page.services
    assert services.stt_model() is None and services.transcribe(Path("x.wav")) is None
    have = {"openai/whisper-small", "openai/whisper-large-v3-turbo"}
    monkeypatch.setattr(services, "installed", lambda spec: spec.id in have)
    services.hardware = machine(8)
    assert services.stt_model().id == "openai/whisper-large-v3-turbo"  # fits the card: the accurate one
    services.hardware = machine(None)
    assert services.stt_model().id == "openai/whisper-small"  # no card: turbo would be slow
