"""Pipeline control widget for SnapReel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QWidget,
)


class PipelineControl(QWidget):
    """Widget containing global pipeline controls (Start/Stop)."""

    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize pipeline controls."""
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.start_button = QPushButton("Start Pipeline")
        self.start_button.setStyleSheet(
            "background-color: #a6e3a1; color: #11111b; font-weight: bold;"
        )
        self.start_button.clicked.connect(self.start_requested.emit)

        self.stop_button = QPushButton("Stop Pipeline")
        self.stop_button.setStyleSheet(
            "background-color: #f38ba8; color: #11111b; font-weight: bold;"
        )
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)

    def set_running_state(self, is_running: bool) -> None:
        """Update button states based on pipeline execution status."""
        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)
