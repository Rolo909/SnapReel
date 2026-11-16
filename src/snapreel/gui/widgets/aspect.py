"""Output format controls: aspect tiles drawn as viewfinder frames, and an exact size field."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QToolButton,
    QWidget,
)

from snapreel.gui import icons, theme
from snapreel.i18n import tr

# Seven tiles fit the 400 px control column; any other ratio is one click away in "Exact size".
ASPECTS = [(1, 1), (4, 5), (3, 4), (9, 16), (16, 9), (3, 2), (21, 9)]


class AspectTile(QAbstractButton):
    """A frame of the given proportions with viewfinder corner marks."""

    def __init__(self, w: int, h: int) -> None:
        super().__init__()
        self.ratio = (w, h)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{w}:{h}")
        self.setAccessibleName(f"{w}:{h}")
        self.setFixedSize(QSize(44, 52))

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        hover = self.underMouse()
        if active or hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.color("raised"))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self.hasFocus():
            painter.setPen(QPen(theme.color("accent"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        w, h = self.ratio
        box = 28.0
        fw, fh = (box, box * h / w) if w >= h else (box * w / h, box)
        frame = QRectF((self.width() - fw) / 2, 4 + (box - fh) / 2, fw, fh)
        line = theme.color("accent_text" if active else ("text" if hover else "muted"))
        painter.setPen(QPen(theme.color("line"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)
        pen = QPen(line, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(pen)
        mark = min(6.0, fw / 3, fh / 3)
        for x, y, dx, dy in ((frame.left(), frame.top(), 1, 1), (frame.right(), frame.top(), -1, 1),
                             (frame.left(), frame.bottom(), 1, -1), (frame.right(), frame.bottom(), -1, -1)):
            painter.drawLine(QLineF(x, y, x + dx * mark, y))
            painter.drawLine(QLineF(x, y, x, y + dy * mark))
        painter.setFont(theme.font("body", 7.5))
        painter.setPen(theme.color("text" if active else "muted"))
        painter.drawText(QRectF(0, 36, self.width(), 14), Qt.AlignmentFlag.AlignCenter, f"{w}:{h}")
        painter.end()


class AspectPicker(QWidget):
    changed = Signal(int, int)

    def __init__(self, aspects: list[tuple[int, int]] | None = None) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._tiles: list[AspectTile] = []
        for w, h in aspects or ASPECTS:
            tile = AspectTile(w, h)
            self._group.addButton(tile)
            layout.addWidget(tile)
            self._tiles.append(tile)
        layout.addStretch(1)
        self._tiles[0].setChecked(True)
        self._group.buttonClicked.connect(lambda t: self.changed.emit(*t.ratio))

    def value(self) -> tuple[int, int]:
        checked = self._group.checkedButton()
        return checked.ratio if checked else (1, 1)

    def set_value(self, w: int, h: int) -> None:
        for tile in self._tiles:
            if tile.ratio == (w, h):
                tile.setChecked(True)


class SizeField(QWidget):
    """Exact output size: width × height, with an aspect lock."""

    changed = Signal(int, int)

    def __init__(self, maximum: int = 8192) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.width_box, self.height_box = QSpinBox(), QSpinBox()
        for box, name in ((self.width_box, tr("Width")), (self.height_box, tr("Height"))):
            box.setRange(64, maximum)
            box.setSingleStep(8)
            box.setSuffix(" px")
            box.setAccessibleName(name)
            box.setToolTip(name)
        self.lock = QToolButton()
        self.lock.setCheckable(True)
        self.lock.setChecked(True)
        self.lock.setProperty("role", "ghost")
        self.lock.setIcon(icons.icon("lock"))
        self.lock.setToolTip(tr("Keep proportions"))
        times = QLabel("×")
        times.setProperty("role", "muted")
        layout.addWidget(self.width_box, 1)
        layout.addWidget(times)
        layout.addWidget(self.height_box, 1)
        layout.addWidget(self.lock)
        self._ratio = 1.0
        self._guard = False
        self.width_box.valueChanged.connect(lambda v: self._edited(v, True))
        self.height_box.valueChanged.connect(lambda v: self._edited(v, False))

    def _edited(self, value: int, is_width: bool) -> None:
        if self._guard:
            return
        if self.lock.isChecked():
            self._guard = True
            if is_width:
                self.height_box.setValue(max(64, round(value / self._ratio)))
            else:
                self.width_box.setValue(max(64, round(value * self._ratio)))
            self._guard = False
        else:
            self._ratio = self.width_box.value() / self.height_box.value()
        self.changed.emit(*self.value())

    def value(self) -> tuple[int, int]:
        return self.width_box.value(), self.height_box.value()

    def set_value(self, width: int, height: int) -> None:
        self._guard = True
        self.width_box.setValue(width)
        self.height_box.setValue(height)
        self._guard = False
        self._ratio = width / max(1, height)
        self.changed.emit(width, height)
