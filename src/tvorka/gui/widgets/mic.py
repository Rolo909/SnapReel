"""Voice input: press to record, press again — the words appear in the text field (nothing is sent)."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QToolButton, QWidget

from tvorka.gui import icons
from tvorka.i18n import messages, tr

log = logging.getLogger(__name__)
MAX_SECONDS = 300  # a longer dictation is cut here; recognition of the recording follows


def mic_bar(page: Any, target: QPlainTextEdit) -> QWidget:
    """A dictation button aligned to the right, to go under a text field."""
    bar = QWidget()
    row = QHBoxLayout(bar)
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    page.mic = MicButton(page, target)
    row.addWidget(page.mic)
    return bar


class QtRecorder(QObject):
    """Records the default microphone to a WAV file with Qt Multimedia."""

    stopped = Signal(str)  # path of the finished recording
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recorder: Any = None
        self._session: Any = None
        self._file = ""

    @staticmethod
    def available() -> bool:
        from PySide6.QtMultimedia import QMediaDevices

        return bool(QMediaDevices.audioInputs())

    def record(self, file: Path) -> None:
        from PySide6.QtMultimedia import QAudioInput, QMediaCaptureSession, QMediaFormat, QMediaRecorder

        self._file = str(file)
        self._session = QMediaCaptureSession(self)
        self._input = QAudioInput(self)
        self._session.setAudioInput(self._input)
        self._recorder = QMediaRecorder(self)
        self._session.setRecorder(self._recorder)
        media = QMediaFormat()
        media.setFileFormat(QMediaFormat.FileFormat.Wave)
        media.setAudioCodec(QMediaFormat.AudioCodec.Wave)
        self._recorder.setMediaFormat(media)
        self._recorder.setOutputLocation(QUrl.fromLocalFile(self._file))
        self._recorder.recorderStateChanged.connect(self._state)
        self._recorder.errorOccurred.connect(lambda _code, text: self.error.emit(text))
        self._recorder.record()

    def stop(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()

    def _state(self, state: Any) -> None:
        from PySide6.QtMultimedia import QMediaRecorder

        if state == QMediaRecorder.RecorderState.StoppedState and self._recorder is not None:
            location = self._recorder.actualLocation().toLocalFile() or self._file
            self._recorder = None
            self.stopped.emit(location)


class MicButton(QToolButton):
    """Dictation into ``target``. ``page`` gives the services and the toasts."""

    def __init__(self, page: Any, target: QPlainTextEdit) -> None:
        super().__init__()
        self.page, self.target = page, target
        self.setProperty("role", "ghost")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.recorder: Any = None  # created on first use; tests put a stand-in here
        self._wired: Any = None  # the recorder whose signals are connected
        self._started = 0.0
        self._request = 0
        self._file: Path | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self.clicked.connect(self._clicked)
        stt = page.services.stt
        stt.transcribed.connect(self._on_text)
        stt.failed.connect(self._on_failed)
        self._show("idle")

    @property
    def state(self) -> str:
        return str(self.property("state") or "idle")

    def _show(self, state: str) -> None:
        self.setProperty("state", state)
        self.setProperty("recording", state == "recording")
        self.style().unpolish(self)
        self.style().polish(self)
        glyph, color, tip = {
            "idle": ("mic", "text", tr("Dictate: press, speak, press again — the text appears here")),
            "recording": ("stop", "bad", tr("Stop and turn the speech into text")),
            "listening": ("refresh", "muted", tr("Recognizing speech…")),
        }[state]
        self.setIcon(icons.icon(glyph, color))
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        if state == "idle":
            self.setText("")
        self.setEnabled(state != "listening")

    def _toast(self, text: str, level: str = "warn") -> None:
        toasts = getattr(self.page, "toasts", None)
        if toasts is not None:
            toasts.show(text, level)

    def _clicked(self) -> None:
        if self.state == "recording":
            self.stop()
            return
        if self.page.services.stt_model() is None:
            self._toast(tr("Voice input needs a speech recognition model. Download one on the Models page "
                           "(Speech recognition): Whisper small suits most computers."))
            return
        if self.recorder is None:
            if not QtRecorder.available():
                self._toast(tr("No microphone found. Connect one and allow Windows to use it "
                               "(Settings → Privacy → Microphone)."))
                return
            self.recorder = QtRecorder(self)
        if self._wired is not self.recorder:
            self.recorder.stopped.connect(self._recorded)
            self.recorder.error.connect(self._record_error)
            self._wired = self.recorder
        handle, name = tempfile.mkstemp(prefix="tvorka-voice-", suffix=".wav")
        os.close(handle)
        self._file = Path(name)
        self._started = time.monotonic()
        self.recorder.record(self._file)
        self._show("recording")
        self._tick()
        self._timer.start()

    def stop(self) -> None:
        if self.state == "recording" and self.recorder is not None:
            self._timer.stop()
            self._show("listening")
            self.setText(tr("Recognizing…"))
            self.recorder.stop()

    def _tick(self) -> None:
        seconds = int(time.monotonic() - self._started)
        self.setText(f"{seconds // 60}:{seconds % 60:02d}")
        if seconds >= MAX_SECONDS:
            self.stop()

    def _recorded(self, path: str) -> None:
        started = self.page.services.transcribe(Path(path))
        if started is None:
            self._finish()
            return
        self._request, _future = started

    def _record_error(self, text: str) -> None:
        log.warning("recording failed: %s", text)
        self._timer.stop()
        self._finish()
        self._toast(tr("The microphone could not be used: {error}", error=text), "bad")

    def _on_text(self, request_id: int, text: str) -> None:
        if request_id != self._request:
            return
        self._finish()
        if not text:
            self._toast(tr("No speech was heard. Speak a little louder or closer to the microphone."), "info")
            return
        cursor = self.target.textCursor()
        before = self.target.toPlainText()[: cursor.position()]
        cursor.insertText((" " if before and not before[-1].isspace() else "") + text)
        self.target.setTextCursor(cursor)
        self.target.setFocus()

    def _on_failed(self, request_id: int, code: str, _detail: str) -> None:
        if request_id == self._request:
            self._finish()
            self._toast(messages.engine_error(code), "bad")

    def _finish(self) -> None:
        self._request = 0
        if self._file is not None:
            self._file.unlink(missing_ok=True)
            self._file = None
        self._show("idle")
