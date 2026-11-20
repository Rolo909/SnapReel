"""Result display: a light table with crop marks, and a contact-sheet strip of session results."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QDrag,
    QFont,
    QImageReader,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListWidget, QListWidgetItem, QWidget

from tvorka.gui import theme
from tvorka.i18n import tr


def file_mime(paths: list[str]) -> QMimeData:
    """Files as drag data: other sections, Explorer and other programs take them."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths if p])
    return mime


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
        self._path = ""
        self._press: QPoint | None = None

    def set_empty_text(self, text: str) -> None:
        self._empty = text
        self.update()

    def set_image(self, path: str | None) -> None:
        self._pixmap = load_scaled(path, 2400) if path else None
        self._path = path or ""
        self.setCursor(Qt.CursorShape.OpenHandCursor if path else Qt.CursorShape.ArrowCursor)
        self.setToolTip(tr("Drag the picture to another section or out of Tvorka") if path else "")
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._press = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Drag the result: into the chat, onto a section button, to the desktop."""
        if self._press is None or not self._path or self._progress is not None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        drag.setMimeData(file_mime([self._path]))
        if self._pixmap is not None and not self._pixmap.isNull():
            drag.setPixmap(self._pixmap.scaled(QSize(120, 120), Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        drag.exec(Qt.DropAction.CopyAction)

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
        self.setDragEnabled(True)  # a result can be dragged to another section
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._count = 0

    def mimeData(self, items: list[QListWidgetItem]) -> QMimeData:
        return file_mime([item.data(Qt.ItemDataRole.UserRole) for item in items])

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
