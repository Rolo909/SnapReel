"""Log viewer widget for real-time log streaming."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class LogSignal(QObject):
    """QObject to hold the signal for thread-safe log emission."""

    new_log = Signal(str)


class QtLogHandler(logging.Handler):
    """Logging handler that emits a Qt signal for each log record."""

    def __init__(self) -> None:
        super().__init__()
        self.emitter = LogSignal()
        # Fallback basic formatter, though structlog will pre-format messages
        self.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        """Emit the formatted log record as a string."""
        try:
            msg = self.format(record)
            self.emitter.new_log.emit(msg)
        except Exception:
            self.handleError(record)


class LogViewer(QWidget):
    """Widget that displays application logs in real-time."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the log viewer."""
        super().__init__(parent)
        self._setup_ui()
        self._setup_logging()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        # Monospace font
        self.text_edit.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px; background-color: #11111b; color: #a6adc8;"
        )

        layout.addWidget(self.text_edit)

    def _setup_logging(self) -> None:
        self.handler = QtLogHandler()
        self.handler.emitter.new_log.connect(self._append_log)

        # Attach to root logger so it captures everything, including structlog output
        logging.getLogger().addHandler(self.handler)

    def _append_log(self, message: str) -> None:
        """Append a new log message to the text edit."""
        self.text_edit.appendPlainText(message)

        # Scroll to bottom
        scrollbar = self.text_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
