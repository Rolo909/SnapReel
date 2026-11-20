"""Attachments in the chat: a chip per file, and a message box that takes pasted pictures and files."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit

from tvorka.core.attachments import Attachment
from tvorka.gui import icons
from tvorka.gui.widgets.basic import label, tool_button
from tvorka.i18n import tr

KIND_GLYPH = {"image": "image", "video": "video", "text": "copy", "document": "copy", "audio": "voice"}
THUMB = 28


def local_files(mime: QMimeData) -> list[Path]:
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()] if mime.hasUrls() else []


class AttachmentChip(QFrame):
    """A file going with a message; ``removed`` when its cross is pressed (not shown once sent)."""

    removed = Signal(object)  # the chip itself

    def __init__(self, name: str, item: Attachment | None = None, folder: Path | None = None,
                 removable: bool = True) -> None:
        super().__init__()
        self.setObjectName("Chip")
        self.item = item
        self.setToolTip(name)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 4 if removable else 10, 4)
        row.setSpacing(6)
        self.picture = QLabel()
        self.picture.setFixedSize(THUMB, THUMB)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.picture)
        short = name if len(name) <= 28 else name[:18] + "…" + name[-8:]
        self.title = label(short, "")
        row.addWidget(self.title)
        self.detail = label("", "faint")
        row.addWidget(self.detail)
        if removable:
            close = tool_button("close", tr("Remove"))
            close.setIconSize(QSize(14, 14))
            close.clicked.connect(lambda: self.removed.emit(self))
            row.addWidget(close)
        self.set_item(item, folder)

    def set_item(self, item: Attachment | None, folder: Path | None) -> None:
        """``None`` while the file is still being read."""
        self.item = item
        if item is None:
            self.picture.setPixmap(icons.pixmap("refresh", 16, "muted"))
            self.detail.setText(tr("reading…"))
            return
        thumb = QPixmap()
        if item.images and folder is not None:
            reader = QImageReader(str(folder / item.images[0]))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(THUMB * 2, THUMB * 2, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                thumb = QPixmap.fromImage(image).scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation)
        if thumb.isNull():
            thumb = icons.pixmap(KIND_GLYPH.get(item.kind, "copy"), 18, "muted")
        self.picture.setPixmap(thumb)
        parts = []
        if item.kind == "video":
            parts.append(tr("{count} frames", count=len(item.images)))
        parts.append(tr("~{count} tokens", count=item.tokens))
        if item.truncated:
            parts.append(tr("cut"))
        self.detail.setText(" · ".join(parts))


class ComposerEdit(QPlainTextEdit):
    """The message box: a pasted picture or file becomes an attachment, text stays text."""

    image_pasted = Signal(QImage)
    files_pasted = Signal(list)  # [Path]

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasImage() or bool(local_files(source)) or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:
        files = local_files(source)
        if files:
            self.files_pasted.emit(files)
        elif source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                self.image_pasted.emit(image)
        else:
            super().insertFromMimeData(source)
