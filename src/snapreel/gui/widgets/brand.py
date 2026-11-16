"""App identity: the logo mark and the author credit."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from snapreel.gui import theme

AUTHOR = "Rolo909"
AUTHOR_URL = "https://github.com/Rolo909"
PROJECT_URL = "https://github.com/Rolo909/SnapReel"


class LogoMark(QWidget):
    """A rounded mint tile with a frame and a spark, drawn in code."""

    def __init__(self, size: int = 30) -> None:
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = float(self.width())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("accent"))
        painter.drawRoundedRect(QRectF(0, 0, side, side), side * 0.28, side * 0.28)
        pen = QPen(theme.color("on_accent"), side * 0.075)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(side * 0.24, side * 0.3, side * 0.42, side * 0.42), 2, 2)
        cx, cy, r = side * 0.7, side * 0.3, side * 0.12
        painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        painter.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
        painter.end()
