"""Reference image input: drag and drop, click to browse, paste from the clipboard."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QFileDialog, QWidget

from tvorka.core import paths
from tvorka.gui import icons, theme
from tvorka.gui.widgets.basic import tool_button
from tvorka.gui.widgets.canvas import load_scaled
from tvorka.i18n import tr

IMAGE_FILTER = "*.png *.jpg *.jpeg *.webp *.bmp"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class DropZone(QWidget):
    changed = Signal(str)  # path, "" when cleared

    def __init__(self, hint: str = "") -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(92)
        self.setAccessibleName(tr("Reference image"))
        self._hint = hint or tr("Drop an image, click to choose or press Ctrl+V")
        self._path = ""
        self._thumb: QPixmap | None = None
        self._hover = False
        self.clear_button = tool_button("close", tr("Remove the reference"))
        self.clear_button.setParent(self)
        self.clear_button.hide()
        self.clear_button.clicked.connect(lambda: self.set_path(""))

    def sizeHint(self) -> QSize:
        return QSize(360, 96)

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        self._path = path
        self._thumb = load_scaled(path, 256) if path else None
        self.clear_button.setVisible(bool(path))
        self.update()
        self.changed.emit(path)

    # --- input -------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            chosen, _ = QFileDialog.getOpenFileName(self, tr("Choose a reference image"), "",
                                                    f"{tr('Images')} ({IMAGE_FILTER})")
            if chosen:
                self.set_path(chosen)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._path:
            self.set_path("")
        else:
            super().keyPressEvent(event)

    def paste(self) -> None:
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData()
        files = [u.toLocalFile() for u in mime.urls()] if mime.hasUrls() else []
        image_file = next((f for f in files if Path(f).suffix.lower() in IMAGE_SUFFIXES), "")
        if image_file:
            self.set_path(image_file)
            return
        image = clipboard.image()
        if not image.isNull():
            folder = paths.data_dir() / "clipboard"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}.png"
            image.save(str(target))
            self.set_path(str(target))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_file(event):
            self._hover = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, _event: object) -> None:
        self._hover = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hover = False
        file = self._dropped_file(event)
        if file:
            self.set_path(file)
            event.acceptProposedAction()

    @staticmethod
    def _dropped_file(event: QDragEnterEvent | QDropEvent) -> str:
        mime = event.mimeData()
        for url in mime.urls() if mime.hasUrls() else []:
            local = url.toLocalFile()
            if Path(local).suffix.lower() in IMAGE_SUFFIXES:
                return local
        return ""

    # --- drawing -----------------------------------------------------------------
    def resizeEvent(self, event: object) -> None:
        self.clear_button.move(self.width() - self.clear_button.sizeHint().width() - 4, 4)
        super().resizeEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(theme.color("raised"))
        pen = QPen(theme.color("accent" if self._hover else ("muted" if self.hasFocus() else "line")), 1)
        if not self._path:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 3, 3)
        if self._thumb is not None and not self._thumb.isNull():
            box = QRectF(8, 8, self.height() - 16, self.height() - 16)
            size = self._thumb.size().scaled(box.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(0, 0, size.width(), size.height())
            target.moveCenter(box.center())
            painter.drawPixmap(target, self._thumb, QRectF(self._thumb.rect()))
            painter.setPen(theme.color("text"))
            painter.setFont(theme.font("body", 9))
            text = QRectF(box.right() + 10, 8, self.width() - box.right() - 50, self.height() - 16)
            name = painter.fontMetrics().elidedText(Path(self._path).name, Qt.TextElideMode.ElideMiddle,
                                                    int(text.width()))
            painter.drawText(text, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        else:
            painter.drawPixmap(int(rect.center().x() - 10), int(rect.top() + 16),
                               icons.pixmap("image", 20, "muted"))
            painter.setPen(theme.color("faint"))
            painter.setFont(theme.font("body", 8.5))
            flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
            painter.drawText(rect.adjusted(12, 40, -12, -6), flags, self._hint)
        painter.end()
