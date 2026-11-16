"""Result display: a light table with crop marks, and a contact-sheet strip of session results."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFont, QImageReader, QPainter, QPainterPath, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from snapreel.gui import theme
from snapreel.i18n import tr


def load_scaled(path: str, longest: int) -> QPixmap:
    """Read an image already scaled down (cheap for multi-megapixel files)."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > longest:
        reader.setScaledSize(size.scaled(QSize(longest, longest), Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


class Canvas(QWidget):
    """Shows the current result; while working it shows the stage and a progress bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(240, 200)
        self._pixmap: QPixmap | None = None
        self._empty = tr("The result will appear here")
        self._progress: float | None = None
        self._stage = ""

    def set_empty_text(self, text: str) -> None:
        self._empty = text
        self.update()

    def set_image(self, path: str | None) -> None:
        self._pixmap = load_scaled(path, 2400) if path else None
        self.update()

    def set_progress(self, fraction: float | None, stage: str = "") -> None:
        self._progress = fraction
        self._stage = stage
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.color("panel"))
        bar = 44 if self._progress is not None else 0
        area = QRectF(self.rect()).adjusted(24, 24, -24, -24 - bar)
        if self._pixmap is not None and not self._pixmap.isNull():
            size = self._pixmap.size().scaled(area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(area.center())
            clip = QPainterPath()
            clip.addRoundedRect(target, 8, 8)
            painter.save()
            painter.setClipPath(clip)
            painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
            painter.restore()
            painter.setPen(QPen(theme.color("line"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(target.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        elif self._empty:
            painter.setFont(theme.font("body", 10))
            painter.setPen(theme.color("faint"))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._empty)
        if self._progress is not None:
            self._progress_bar(painter, QRectF(24, self.height() - 40, self.width() - 48, 28))
        painter.end()

    def _progress_bar(self, painter: QPainter, rect: QRectF) -> None:
        fraction = max(0.0, min(1.0, self._progress or 0.0))
        painter.setFont(theme.font("body", 9, QFont.Weight.DemiBold))
        painter.setPen(theme.color("text"))
        text_rect = QRectF(rect.left(), rect.top(), rect.width(), 16)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft, self._stage)
        painter.setFont(theme.font("mono", 8.5))
        painter.setPen(theme.color("muted"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight, f"{round(fraction * 100)} %")
        track = QRectF(rect.left(), rect.top() + 21, rect.width(), 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("line"))
        painter.drawRoundedRect(track, 3, 3)
        if fraction > 0:
            painter.setBrush(theme.color("accent"))
            painter.drawRoundedRect(QRectF(track.left(), track.top(), max(6.0, track.width() * fraction), 6),
                                    3, 3)


class FilmStrip(QListWidget):
    """Thumbnails of this session's results, newest first."""

    picked = Signal(str)

    THUMB = 84

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(self.THUMB, self.THUMB))
        self.setFixedHeight(self.THUMB + 34)
        self.setSpacing(4)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFont(theme.font("mono", 7.5))
        self.currentItemChanged.connect(
            lambda item, _old: item is not None and self.picked.emit(item.data(Qt.ItemDataRole.UserRole)))
        self._count = 0

    def add(self, path: str, thumb: str | None = None) -> None:
        self._count += 1
        item = QListWidgetItem(load_scaled(thumb or path, self.THUMB * 2), f"{self._count:02d}")
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(Path(path).name)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.insertItem(0, item)
        self.blockSignals(True)
        self.setCurrentRow(0)
        self.blockSignals(False)

    def current_path(self) -> str:
        item = self.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else ""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setFont(theme.font("body", 9))
            painter.setPen(theme.color("faint"))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             tr("Results of this session will line up here"))
            painter.end()
