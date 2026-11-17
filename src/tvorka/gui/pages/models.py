"""Models: the catalog, Hugging Face search, installed models, and adding your own."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tvorka.core import hardware, hub, local_import
from tvorka.core.catalog import ModelSpec
from tvorka.core.store import dir_size
from tvorka.gui import icons
from tvorka.gui.pages.base import Page
from tvorka.gui.services import Services
from tvorka.gui.widgets.basic import Card, Segmented, label, tool_button
from tvorka.gui.widgets.feedback import ToastHost
from tvorka.gui.widgets.model_card import ModelCard, size_text
from tvorka.i18n import messages, tr
from tvorka.workers.downloads import run_async

log = logging.getLogger(__name__)
GB = 1024**3


def _clear(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()  # deletion is deferred to the event loop; never let it linger on screen
            widget.deleteLater()


class ModelsPage(Page):
    key = "models"
    icon = "models"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._cards: dict[str, ModelCard] = {}
        self._preview_spec: ModelSpec | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 0)
        outer.setSpacing(14)

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(tr("Models"), "title"))
        titles.addWidget(label(tr("Download ready-made models, find more on Hugging Face or add your own."),
                               "subtitle"))
        self.disk = label("", "mono")
        titles.addWidget(self.disk)
        head.addLayout(titles, 1)
        outer.addLayout(head)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.tab = Segmented([("catalog", tr("Catalog")), ("hub", "Hugging Face"),
                              ("installed", tr("Installed"))])
        self.tab.changed.connect(self._tab_changed)
        self.kind = Segmented([("", tr("All")), ("image", tr("Images")), ("video", tr("Video")),
                               ("speech", tr("Voice"))])
        self.kind.changed.connect(self._kind_changed)
        self.add_button = QPushButton(tr("Add your own"))
        self.add_button.setIcon(icons.icon("plus"))
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self._toggle_add)
        bar.addWidget(self.tab)
        bar.addStretch(1)
        bar.addWidget(self.add_button)
        outer.addLayout(bar)
        kinds = QHBoxLayout()
        kinds.addWidget(self.kind)
        kinds.addStretch(1)
        outer.addLayout(kinds)

        outer.addWidget(self._build_add_panel())

        self.search_row = QWidget()
        search_layout = QHBoxLayout(self.search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search Hugging Face: flux, anime, portrait, tts…"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.returnPressed.connect(self._search_now)
        search_layout.addWidget(self.search)
        outer.addWidget(self.search_row)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(450)
        self._search_timer.timeout.connect(self._run_search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 8, 24)
        self.list.setSpacing(10)
        self.list.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        services.models_changed.connect(self._refresh)
        services.hardware_ready.connect(self._on_hardware)
        services.downloads.progress.connect(self._on_progress)
        services.downloads.finished.connect(self._on_finished)
        services.downloads.failed.connect(self._on_failed)
        services.downloads.cancelled.connect(self._on_cancelled)
        self._tab_changed("catalog")

    def title(self) -> str:
        return tr("Models")

    def shown(self) -> None:
        self._update_disk()

    # ============================================================ layout pieces
    def _build_add_panel(self) -> QWidget:
        self.add_panel = Card(tr("Add your own model"))
        self.source = Segmented([("hf", "Hugging Face"), ("folder", tr("Folder")), ("file", tr("File"))])
        self.source.changed.connect(self._source_changed)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.source_edit = QLineEdit()
        self.source_edit.returnPressed.connect(self._recognize)
        self.browse = QPushButton(tr("Browse…"))
        self.browse.setIcon(icons.icon("folder"))
        self.browse.clicked.connect(self._browse)
        self.recognize = QPushButton(tr("Check"))
        self.recognize.setProperty("role", "accent")
        self.recognize.clicked.connect(self._recognize)
        row.addWidget(self.source_edit, 1)
        row.addWidget(self.browse)
        row.addWidget(self.recognize)
        self.add_status = label("", "muted", wrap=True)
        self.preview = QVBoxLayout()
        self.preview.setSpacing(8)
        self.add_panel.body.addWidget(self.source)
        self.add_panel.body.addLayout(row)
        self.add_panel.body.addWidget(self.add_status)
        self.add_panel.body.addLayout(self.preview)
        self.add_panel.setVisible(False)
        self._source_changed("hf")
        return self.add_panel

    # ============================================================ list
    def _tab_changed(self, tab: str) -> None:
        self.search_row.setVisible(tab == "hub")
        self._refresh()
        if tab == "hub":
            self.search.setFocus()
            self._run_search()

    def _kind_changed(self, _kind: str) -> None:
        if self.tab.value() == "hub":
            self._run_search()
        else:
            self._refresh()

    def _refresh(self) -> None:
        tab = self.tab.value()
        if tab == "hub":
            return
        _clear(self.list)
        self._cards.clear()
        kind = self.kind.value() or None
        specs = self.services.catalog.all(kind)
        if tab == "installed":
            specs = [s for s in specs if self.services.installed(s) and s.source != "online"]
        specs.sort(key=lambda s: (not self.services.installed(s), s.kind, s.download_gb))
        if not specs:
            text = (tr("Nothing installed yet. Pick a model in the Catalog and press Download.")
                    if tab == "installed" else tr("No models of this kind."))
            empty = label(text, "faint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addWidget(empty)
            return
        for spec in specs:
            card = ModelCard(spec)
            card.download.connect(self._download)
            card.cancel.connect(self.services.downloads.cancel)
            card.delete.connect(self._delete)
            card.use.connect(self._use)
            card.open_page.connect(self._open_hub_page)
            self._cards[spec.id] = card
            self._update_card(spec.id)
            self.list.addWidget(card)
        self._update_disk()

    def _update_card(self, model_id: str) -> None:
        card = self._cards.get(model_id)
        if card is None:
            return
        spec = card.spec
        installed = self.services.installed(spec)
        on_disk = self.services.store.size_bytes(spec) / GB if installed else 0.0
        card.set_state(installed, self.services.downloads.state(model_id), self.services.fit(spec), on_disk)

    def _on_hardware(self, _hw: object) -> None:
        for model_id in list(self._cards):
            self._update_card(model_id)

    def _update_disk(self) -> None:
        root = self.services.settings.models_path()

        def measure() -> tuple[float, float]:
            return dir_size(root) / GB if root.exists() else 0.0, hardware.disk_free_gb(root)

        run_async(measure, self._show_disk)

    def _show_disk(self, sizes: tuple[float, float]) -> None:
        used, free = sizes
        self.disk.setText(tr("Models take {used} · {free} free", used=size_text(used), free=size_text(free)))

    # ============================================================ actions
    def _download(self, model_id: str) -> None:
        spec = self.services.catalog.get(model_id)
        if spec is None:
            return
        if spec.gated and not self.services.settings.token():
            self._gated_hint(spec)
            return
        self.services.downloads.start(spec)
        self._update_card(model_id)

    def _gated_hint(self, spec: ModelSpec) -> None:
        if self.toasts is not None:
            self.toasts.show(messages.hub_error("gated"), "warn",
                             (tr("Open the model page"), lambda: self._open_hub_page(spec.id)))

    def _delete(self, model_id: str) -> None:
        spec = self.services.catalog.get(model_id)
        if spec is None:
            return
        if spec.source == "local":
            question = tr("Remove “{name}” from the list? Its files on disk stay where they are.",
                          name=spec.name)
        else:
            size = size_text(self.services.store.size_bytes(spec) / GB or spec.download_gb)
            question = tr("Delete “{name}” ({size}) from disk? This cannot be undone; "
                          "you can download it again.", name=spec.name, size=size)
        answer = QMessageBox.question(self, tr("Delete model"), question,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.services.worker.loaded_model == spec.id:
            self.services.worker.unload_model()
        if spec.source != "local":
            self.services.store.delete(spec)
        if spec.origin == "user" and spec.source == "local":
            self.services.catalog.remove_user(spec.id)
        self.services.models_changed.emit()

    def _use(self, model_id: str) -> None:
        spec = self.services.catalog.get(model_id)
        window = self.window()
        page = getattr(window, "page", lambda _k: None)(spec.kind if spec else "")
        if page is not None and hasattr(page, "select_model"):
            page.select_model(model_id)
            window.open_page(window.pages.index(page))
        elif self.toasts is not None:
            self.toasts.show(tr("This section is not available yet."), "info")

    def _open_hub_page(self, model_id: str) -> None:
        spec = self.services.catalog.get(model_id)
        repo = spec.repo_id if spec else model_id
        QDesktopServices.openUrl(QUrl(f"https://huggingface.co/{repo}"))

    # ============================================================ download events
    def _on_progress(self, model_id: str, *_args: object) -> None:
        self._update_card(model_id)

    def _on_finished(self, model_id: str) -> None:
        self._update_card(model_id)
        self._update_disk()
        spec = self.services.catalog.get(model_id)
        if spec is not None and self.toasts is not None:
            self.toasts.show(tr("{name} is ready to use", name=spec.name), "ok",
                             (tr("Use"), lambda: self._use(model_id)))

    def _on_failed(self, model_id: str, code: str, _message: str) -> None:
        self._update_card(model_id)
        if self.toasts is not None:
            spec = self.services.catalog.get(model_id)
            action = None
            if code == "gated":
                action = (tr("Open the model page"), lambda: self._open_hub_page(model_id))
            prefix = f"{spec.name}: " if spec else ""
            self.toasts.show(prefix + messages.hub_error(code), "bad", action)

    def _on_cancelled(self, model_id: str) -> None:
        self._update_card(model_id)

    # ============================================================ Hugging Face search
    def _search_now(self) -> None:
        self._search_timer.stop()
        self._run_search()

    def _run_search(self) -> None:
        if self.tab.value() != "hub":
            return
        query = self.search.text().strip()
        kind = self.kind.value() or "image"
        _clear(self.list)
        self.list.addWidget(label(tr("Searching…"), "faint"))
        token = self.services.settings.token()
        run_async(lambda: (query, hub.search(kind, query, 30, token)),
                  self._show_hits, self._search_failed)

    def _show_hits(self, payload: tuple[str, list[hub.HubHit]]) -> None:
        query, hits = payload
        if self.tab.value() != "hub" or query != self.search.text().strip():
            return  # a newer search is on its way
        _clear(self.list)
        if not hits:
            self.list.addWidget(label(tr("Nothing found. Try another word."), "faint"))
            return
        for hit in hits:
            self.list.addWidget(self._hit_row(hit))

    def _search_failed(self, exc: Exception) -> None:
        if self.tab.value() != "hub":
            return
        _clear(self.list)
        code = getattr(exc, "code", "network")
        self.list.addWidget(label(messages.hub_error(code), "bad"))

    def _hit_row(self, hit: hub.HubHit) -> QWidget:
        row = QFrame()
        row.setObjectName("Card")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        name = label(hit.id)
        name.setProperty("role", "heading")
        texts.addWidget(name)
        downloads = f"{hit.downloads:,}".replace(",", " ")
        texts.addWidget(label(tr("{count} downloads · {likes} likes", count=downloads, likes=hit.likes),
                              "faint"))
        layout.addLayout(texts, 1)
        known = self.services.catalog.get(hit.id)
        if hit.gated:
            lock = label("", "warn")
            lock.setPixmap(icons.pixmap("lock", 14, "warn"))
            lock.setToolTip(tr("Restricted access: needs a Hugging Face token"))
            layout.addWidget(lock)
        page = tool_button("link", tr("Open the model page"))
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://huggingface.co/{hit.id}")))
        layout.addWidget(page)
        button = QPushButton(tr("In your list") if known else tr("Check and add"))
        button.setProperty("role", "accent")
        button.setEnabled(known is None)
        button.clicked.connect(lambda: self._check_repo(hit.id))
        layout.addWidget(button)
        return row

    def _check_repo(self, repo_id: str) -> None:
        self.add_panel.setVisible(True)
        self.source.set_value("hf")
        self._source_changed("hf")
        self.source_edit.setText(repo_id)
        self._recognize()

    # ============================================================ add your own
    def _toggle_add(self) -> None:
        self.add_panel.setVisible(not self.add_panel.isVisible())
        if self.add_panel.isVisible():
            self.source_edit.setFocus()

    def _source_changed(self, source: str) -> None:
        self.browse.setVisible(source != "hf")
        self.source_edit.clear()
        self.source_edit.setPlaceholderText({
            "hf": tr("author/model or a link to its Hugging Face page"),
            "folder": tr("Folder with a diffusers or transformers model"),
            "file": tr("A .safetensors / .ckpt checkpoint or a Silero .pt file"),
        }[source])
        self.add_status.setText("")
        _clear(self.preview)

    def _browse(self) -> None:
        if self.source.value() == "folder":
            chosen = QFileDialog.getExistingDirectory(self, tr("Choose a model folder"))
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, tr("Choose a model file"), "",
                                                    f"{tr('Models')} (*.safetensors *.ckpt *.pt)")
        if chosen:
            self.source_edit.setText(chosen)
            self._recognize()

    def _recognize(self) -> None:
        text = self.source_edit.text().strip()
        if not text:
            return
        source = self.source.value()
        _clear(self.preview)
        self.add_status.setProperty("role", "muted")
        self.add_status.setText(tr("Checking…"))
        self.recognize.setEnabled(False)
        token = self.services.settings.token()
        cache = str(self.services.settings.hub_path())
        if source == "hf":
            job = lambda: hub.spec_from_repo(text, token, self.kind.value() or None, cache)  # noqa: E731
        else:
            job = lambda: local_import.spec_from_path(text, self.kind.value() or None)  # noqa: E731
        run_async(job, self._show_preview, self._recognize_failed)

    def _recognize_failed(self, exc: Exception) -> None:
        self.recognize.setEnabled(True)
        code = getattr(exc, "code", "failed")
        self.add_status.setText(messages.hub_error(code))
        self.add_status.setProperty("role", "bad")
        self.add_status.style().polish(self.add_status)

    def _show_preview(self, spec: ModelSpec) -> None:
        self.recognize.setEnabled(True)
        self._preview_spec = spec
        self.add_status.setText(tr("Recognized. Check the details and add it to your models."))
        self.add_status.setProperty("role", "ok")
        self.add_status.style().polish(self.add_status)
        card = ModelCard(spec)
        card.primary.setVisible(False)
        card.page_button.setVisible(False)
        installed = spec.source == "local"
        card.set_state(installed, None, self.services.fit(spec), spec.download_gb)
        card.delete_button.setVisible(False)
        self.preview.addWidget(card)
        add = QPushButton(tr("Add to my models"))
        add.setProperty("role", "primary")
        add.clicked.connect(self._add_previewed)
        self.preview.addWidget(add)

    def _add_previewed(self) -> None:
        spec = self._preview_spec
        if spec is None:
            return
        self.services.catalog.add_user(spec)
        self._preview_spec = None
        self.add_panel.setVisible(False)
        _clear(self.preview)
        self.services.models_changed.emit()
        if self.toasts is not None:
            self.toasts.show(tr("{name} added", name=spec.name), "ok")
        self.tab.set_value("installed" if spec.source == "local" else "catalog")
        self._tab_changed(self.tab.value())
