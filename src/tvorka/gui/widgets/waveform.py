"""Audio waveform with playback progress; peaks are computed off the GUI thread."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from tvorka.gui import theme
from tvorka.workers.downloads import run_async

BARS = 120


def compute_peaks(path: str, bars: int = BARS) -> np.ndarray:
    from tvorka.engines import media

    samples, _rate = media.read_audio(Path(path))
    return media.peaks(samples, bars)


class WaveformView(QWidget):
    """Bars for loudness; the played part is drawn in the accent colour. Click to seek."""

    seek = Signal(float)  # fraction 0..1

    def __init__(self) -> None:
        super().__init__()
        self._peaks: np.ndarray | None = None
        self._position = 0.0
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(320, 44)

    def load(self, path: str) -> None:
        self._peaks = None
        self.update()
        run_async(lambda: compute_peaks(path), self._loaded)

    def _loaded(self, peaks: np.ndarray) -> None:
        self._peaks = peaks
        self.update()

    def set_position(self, fraction: float) -> None:
        self._position = max(0.0, min(1.0, fraction))
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.width() > 0:
            self.seek.emit(max(0.0, min(1.0, event.position().x() / self.width())))

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        height = float(self.height())
        mid = height / 2
        if self._peaks is None:
            painter.setBrush(theme.color("line"))
            painter.drawRoundedRect(QRectF(0, mid - 1, self.width(), 2), 1, 1)
            painter.end()
            return
        count = len(self._peaks)
        step = self.width() / max(1, count)
        bar = max(1.5, step * 0.6)
        played = theme.color("accent")
        rest = theme.color("faint")
        for index, peak in enumerate(self._peaks):
            h = max(2.0, float(peak) * (height - 4))
            x = index * step + (step - bar) / 2
            painter.setBrush(played if (index + 0.5) / count <= self._position else rest)
            painter.drawRoundedRect(QRectF(x, mid - h / 2, bar, h), bar / 2, bar / 2)
        painter.end()
