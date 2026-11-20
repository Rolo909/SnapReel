"""Gallery: everything created, as a grid; details and actions for the selected work."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl
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

from tvorka.core.jobs import Result
from tvorka.gui import handoff, icons, theme
from tvorka.gui.pages.base import Page
from tvorka.gui.services import Services
from tvorka.gui.widgets.basic import Segmented, caption, label
from tvorka.gui.widgets.canvas import file_mime, load_scaled
from tvorka.gui.widgets.feedback import ToastHost
from tvorka.gui.widgets.model_card import kind_name
from tvorka.i18n import tr

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


class WorksGrid(QListWidget):
    """The grid of works; a work can be dragged into another section or out of Tvorka."""

    def __init__(self) -> None:
        super().__init__()
        self.path_of: dict[str, str] = {}  # work id -> file
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)

    def mimeData(self, items: list[QListWidgetItem]) -> QMimeData:
        return file_mime([self.path_of.get(i.data(Qt.ItemDataRole.UserRole), "") for i in items])


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
        self.grid = WorksGrid()
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
        self.lineage = QPushButton()
        self.lineage.setProperty("role", "link")
        self.lineage.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lineage.clicked.connect(self._show_parent)
        layout.addWidget(self.lineage)
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
        self.send_button = QPushButton(tr("Send to…"))
        self.send_button.setIcon(icons.icon("link"))
        self.send_button.clicked.connect(
            lambda: self._current() and self.send_menu(handoff.from_result(self._current(), "gallery"),
                                                       self.send_button))
        layout.addWidget(self.send_button)
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
            self.grid.path_of[work.id] = work.path
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
                       self.detail_params, self.lineage):
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
        parent = self._parent_of(work)
        if parent is not None:
            text = tr("Made from: {kind} “{prompt}”", kind=kind_name(parent.kind).lower(),
                      prompt=parent.prompt or "—")
            metrics = self.lineage.fontMetrics()
            self.lineage.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, 296))
            self.lineage.setToolTip(text)
        elif str(work.params.get("parent", "")).startswith("chat:"):
            self.lineage.setText(tr("Made from a chat answer"))
        self.lineage.setVisible(parent is not None or str(work.params.get("parent", "")).startswith("chat:"))
        self.lineage.setEnabled(parent is not None)

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
        if work is not None:
            self.send(handoff.from_result(work, "gallery"), work.kind, "settings")

    def _parent_of(self, work: Result) -> Result | None:
        parent = str(work.params.get("parent") or "")
        return next((r for r in self.services.history.items() if r.id == parent), None) if parent else None

    def _show_parent(self) -> None:
        """Lineage: jump to the work this one was made from."""
        work = self._current()
        parent = self._parent_of(work) if work else None
        if parent is None:
            return
        if parent.id not in self._items:  # hidden by the kind filter
            self.kind.set_value("")
            self._rebuild()
        for row in range(self.grid.count()):
            item = self.grid.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == parent.id:
                self.grid.setCurrentItem(item)
                self.grid.scrollToItem(item)
                return

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
