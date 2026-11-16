"""Gallery: everything created, as a grid; details and actions for the selected work."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snapreel.core.jobs import Result
from snapreel.gui import icons, theme
from snapreel.gui.pages.base import Page
from snapreel.gui.services import Services
from snapreel.gui.widgets.basic import Segmented, caption, label
from snapreel.gui.widgets.canvas import load_scaled
from snapreel.gui.widgets.feedback import ToastHost
from snapreel.gui.widgets.model_card import kind_name
from snapreel.i18n import tr

THUMB = 168
BATCH = 16  # thumbnails decoded per event-loop turn


def show_in_folder(path: str) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


def placeholder(kind: str) -> QPixmap:
    """Tile for works without a picture (speech)."""
    pix = QPixmap(QSize(THUMB * 2, THUMB * 2))
    pix.setDevicePixelRatio(2)
    pix.fill(theme.color("raised"))
    painter = QPainter(pix)
    glyph = icons.pixmap({"speech": "voice", "video": "video"}.get(kind, "image"), 40, "muted")
    painter.drawPixmap((THUMB - 40) // 2, (THUMB - 40) // 2, glyph)
    painter.end()
    return pix


def tile_icon(pix: QPixmap) -> QIcon:
    """The same picture in every state: Qt would tint the selected one with the highlight colour."""
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(pix, mode)
    return icon


class GalleryPage(Page):
    key = "gallery"
    icon = "gallery"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._items: dict[str, Result] = {}
        self._pending: list[QListWidgetItem] = []
        self._dirty = True

        outer = QHBoxLayout(self)
        outer.setContentsMargins(28, 22, 0, 0)
        outer.setSpacing(0)

        main = QVBoxLayout()
        main.setSpacing(14)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(tr("Gallery"), "title"))
        self.subtitle = label("", "subtitle")
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.kind = Segmented([("", tr("All")), ("image", tr("Images")), ("video", tr("Video")),
                               ("speech", tr("Voice"))])
        self.kind.changed.connect(self._kind_changed)
        head.addWidget(self.kind, 0, Qt.AlignmentFlag.AlignBottom)
        main.addLayout(head)

        self.stack = QStackedWidget()
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 14, THUMB + 14))
        self.grid.setSpacing(6)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(False)
        self.grid.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.currentItemChanged.connect(self._selected)
        self.grid.itemActivated.connect(self._activated)  # double click or Enter
        delete = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.grid)
        delete.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete.activated.connect(self._delete)
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self._build_empty())
        main.addWidget(self.stack, 1)
        outer.addLayout(main, 1)
        outer.addWidget(self._build_details())

        self._loader = QTimer(self)
        self._loader.setInterval(0)
        self._loader.timeout.connect(self._load_batch)
        services.worker.job_finished.connect(self._on_job_finished)

    def title(self) -> str:
        return tr("Gallery")

    def shown(self) -> None:
        if self._dirty:
            self._rebuild()

    # ============================================================ layout
    def _build_empty(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        mark = QLabel()
        mark.setPixmap(icons.pixmap("gallery", 40, "faint"))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)
        self.empty_text = label(tr("Everything you create will be collected here."), "subtitle")
        self.empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_text)
        start = QPushButton(tr("Create the first image"))
        start.setProperty("role", "accent")
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.clicked.connect(lambda: self._go_to("image"))
        layout.addWidget(start, 0, Qt.AlignmentFlag.AlignCenter)
        return box

    def _build_details(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Sidebar")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(10)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(220)
        layout.addWidget(self.preview)
        self.detail_title = label("", "heading")
        self.detail_title.setWordWrap(True)
        layout.addWidget(self.detail_title)
        self.detail_meta = label("", "faint", wrap=True)
        layout.addWidget(self.detail_meta)
        layout.addWidget(caption(tr("Prompt")))
        self.detail_prompt = label("", "", wrap=True)
        self.detail_prompt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_prompt)
        self.detail_params = label("", "mono", wrap=True)
        layout.addWidget(self.detail_params)
        layout.addStretch(1)
        self.repeat = QPushButton(tr("Repeat these settings"))
        self.repeat.setProperty("role", "accent")
        self.repeat.setIcon(icons.icon("refresh"))
        self.repeat.clicked.connect(self._repeat)
        layout.addWidget(self.repeat)
        row = QHBoxLayout()
        row.setSpacing(6)
        for text, icon, handler in ((tr("Open"), "play", self._open), (tr("Show in folder"), "folder",
                                    self._reveal)):
            button = QPushButton(text)
            button.setIcon(icons.icon(icon))
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self.delete = QPushButton(tr("Delete"))
        self.delete.setIcon(icons.icon("trash"))
        self.delete.setProperty("role", "ghost")
        self.delete.clicked.connect(self._delete)
        layout.addWidget(self.delete)
        self.details = panel
        self._show_details(None)
        return panel

    # ============================================================ data
    def _on_job_finished(self, _job_id: int, _results: list) -> None:
        self._dirty = True
        if self.isVisible():
            self._rebuild()

    def _kind_changed(self, _kind: str) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        self._dirty = False
        self._loader.stop()
        self.grid.clear()
        self._items.clear()
        self._pending.clear()
        kind = self.kind.value() or None
        works = self.services.history.items(kind)
        total = len(self.services.history.items())
        self.subtitle.setText(tr("{count} works", count=total) if total else tr("Nothing here yet"))
        if not works:
            self.empty_text.setText(tr("Everything you create will be collected here.") if not total
                                    else tr("No works of this kind yet."))
            self.stack.setCurrentIndex(1)
            self._show_details(None)
            return
        self.stack.setCurrentIndex(0)
        blank = tile_icon(placeholder("image"))
        for work in works:
            item = QListWidgetItem(blank, "")
            item.setData(Qt.ItemDataRole.UserRole, work.id)
            item.setToolTip(work.prompt[:200])
            self._items[work.id] = work
            self.grid.addItem(item)
            self._pending.append(item)
        self._loader.start()
        self.grid.setCurrentRow(0)

    def _load_batch(self) -> None:
        for _ in range(BATCH):
            if not self._pending:
                self._loader.stop()
                return
            item = self._pending.pop(0)
            work = self._items.get(item.data(Qt.ItemDataRole.UserRole))
            if work is None:
                continue
            item.setIcon(tile_icon(self._thumb(work)))

    @staticmethod
    def _thumb(work: Result) -> QPixmap:
        source = work.thumb or (work.path if work.kind == "image" else "")
        pix = load_scaled(source, THUMB * 2) if source else QPixmap()
        return pix if not pix.isNull() else placeholder(work.kind)

    # ============================================================ details
    def _current(self) -> Result | None:
        item = self.grid.currentItem()
        return self._items.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._show_details(self._items.get(item.data(Qt.ItemDataRole.UserRole)) if item else None)

    def _show_details(self, work: Result | None) -> None:
        for widget in (self.repeat, self.delete, self.detail_title, self.detail_meta, self.detail_prompt,
                       self.detail_params):
            widget.setVisible(work is not None)
        self.details.setVisible(work is not None)
        if work is None:
            self.preview.setPixmap(icons.pixmap("gallery", 32, "faint"))
            return
        pix = self._thumb(work)
        self.preview.setPixmap(pix.scaled(QSize(300, 300), Qt.AspectRatioMode.KeepAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
                               if work.kind != "speech" else pix)
        spec = self.services.catalog.get(work.model_id)
        self.detail_title.setText(work.model_name or (spec.name if spec else work.model_id))
        size = ""
        if work.params.get("width"):
            size = f"{work.params['width']} × {work.params['height']}  ·  "
        if work.params.get("duration"):
            size += tr("{seconds} s", seconds=work.params["duration"]) + "  ·  "
        created = time.strftime("%d.%m.%Y %H:%M", time.localtime(work.created))
        self.detail_meta.setText(f"{kind_name(work.kind)}  ·  {size}{created}")
        self.detail_prompt.setText(work.prompt or "—")
        facts = []
        for key, name in (("seed", tr("seed")), ("steps", tr("Steps")), ("voice", tr("Speaker"))):
            if work.params.get(key) not in (None, ""):
                facts.append(f"{name}: {work.params[key]}")
        self.detail_params.setText("   ".join(facts))
        self.repeat.setVisible(work.kind == "image" and self.services.catalog.get(work.model_id) is not None)

    # ============================================================ actions
    def _activated(self, _item: QListWidgetItem) -> None:
        self._open()

    def _open(self) -> None:
        work = self._current()
        if work is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(work.path))

    def _reveal(self) -> None:
        work = self._current()
        if work is not None:
            show_in_folder(work.path)

    def _repeat(self) -> None:
        work = self._current()
        page = self._go_to(work.kind) if work else None
        if work is not None and page is not None and hasattr(page, "apply_result"):
            page.apply_result(asdict(work))

    def _go_to(self, key: str) -> Any:
        window = self.window()
        page = getattr(window, "page", lambda _k: None)(key)
        if page is not None:
            window.open_page(window.pages.index(page))
        return page

    def _delete(self) -> None:
        work = self._current()
        if work is None:
            return
        answer = QMessageBox.question(
            self, tr("Delete"), tr("Delete this work and its file from disk? This cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        row = self.grid.currentRow()
        self.services.history.remove(work.id, delete_file=True)
        self._rebuild()
        if self.grid.count():
            self.grid.setCurrentRow(min(row, self.grid.count() - 1))
