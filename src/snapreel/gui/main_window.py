"""Main window: navigation side bar with a live hardware summary, and the pages."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from snapreel import __version__
from snapreel.core import hardware
from snapreel.gui import icons, theme
from snapreel.gui.pages.base import Page
from snapreel.gui.services import Services
from snapreel.gui.widgets.basic import caption, label, rule, tool_button
from snapreel.gui.widgets.brand import AUTHOR, AUTHOR_URL, LogoMark
from snapreel.gui.widgets.feedback import ToastHost
from snapreel.gui.widgets.fit import MeterBar
from snapreel.i18n import tr


class Sidebar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(236)


class MainWindow(QMainWindow):
    # Language or theme changed: the app builds a new window around the same services.
    rebuild_requested = Signal()

    def __init__(self, services: Services, pages: list[Page]) -> None:
        super().__init__()
        self._retired = False
        self.services = services
        self.setWindowTitle("SnapReel")
        # 1024×640 fits a 1920×1080 laptop at 150 % scaling (1280×720 logical minus the taskbar).
        self.setMinimumSize(1024, 640)
        self.toasts = ToastHost(self)
        for page in pages:
            page.toasts = self.toasts

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        side = Sidebar()
        nav = QVBoxLayout(side)
        nav.setContentsMargins(14, 18, 14, 14)
        nav.setSpacing(3)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        brand_row.addWidget(LogoMark())
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand = label("SnapReel")
        brand.setFont(theme.font("display", 13, QFont.Weight.DemiBold))
        brand_text.addWidget(brand)
        brand_text.addWidget(label(tr("Local AI studio"), "faint"))
        brand_row.addLayout(brand_text, 1)
        nav.addLayout(brand_row)
        nav.addSpacing(22)

        self.stack = QStackedWidget()
        self.pages = pages
        self._buttons = QButtonGroup(self)
        for index, page in enumerate(pages):
            self.stack.addWidget(page)
            if not getattr(page, "in_nav", True):
                continue
            button = QPushButton("  " + page.title())
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setIcon(icons.icon(page.icon))
            button.setIconSize(QSize(18, 18))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"{page.title()} · Ctrl+{index + 1}")
            self._buttons.addButton(button, index)
            nav.addWidget(button)
        self._buttons.idClicked.connect(self.open_page)
        nav.addStretch(1)
        nav.addWidget(self._build_footer())
        layout.addWidget(side)
        layout.addWidget(self.stack, 1)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._generate)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._generate)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, lambda: self.current_page().cancel())
        for index in range(min(9, len(pages))):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, lambda i=index: self.open_page(i))

        services.hardware_ready.connect(self._on_hardware)
        services.update_available.connect(self._on_update)
        services.worker.model_changed.connect(self._on_model_changed)
        services.worker.queue_changed.connect(self._on_queue)
        self._live = QTimer(self)
        self._live.setInterval(2000)
        self._live.timeout.connect(self._refresh_memory)
        self._restore()
        # A rebuilt window joins a running session: show what is already known.
        if services.hardware is not None:
            self._on_hardware(services.hardware)
        if services.worker.loaded_model:
            self._on_model_changed(services.worker.loaded_model)

    # --- footer --------------------------------------------------------------------
    def _build_footer(self) -> QWidget:
        footer = QWidget()
        box = QVBoxLayout(footer)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        card = QFrame()
        card.setObjectName("HardwareCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 10, 12, 12)
        inner.setSpacing(6)
        inner.addWidget(caption(tr("This computer")))
        self.gpu_label = label(tr("Detecting hardware…"), "", wrap=True)
        inner.addWidget(self.gpu_label)
        self.vram = MeterBar()
        self.vram.setVisible(False)
        inner.addWidget(self.vram)
        self.vram_label = label("", "mono")
        inner.addWidget(self.vram_label)
        inner.addWidget(rule())
        row = QHBoxLayout()
        row.setSpacing(4)
        self.model_label = label(tr("No model loaded"), "faint", wrap=True)
        self.unload_button = tool_button("close", tr("Unload the model and free memory"))
        self.unload_button.setVisible(False)
        self.unload_button.clicked.connect(self.services.worker.unload_model)
        row.addWidget(self.model_label, 1)
        row.addWidget(self.unload_button)
        inner.addLayout(row)
        self.queue_label = label("", "muted")
        self.queue_label.setVisible(False)
        inner.addWidget(self.queue_label)
        box.addWidget(card)
        credit = label(tr("v{version} · by {author}", version=__version__,
                          author=f'<a href="{AUTHOR_URL}">{AUTHOR}</a>'), "credit")
        credit.setTextFormat(Qt.TextFormat.RichText)
        credit.setOpenExternalLinks(True)
        credit.setToolTip(AUTHOR_URL)
        box.addWidget(credit)
        return footer

    def _on_hardware(self, hw: hardware.Hardware) -> None:
        gpu = hw.gpu or (hw.gpus[0] if hw.gpus else None)
        if gpu is None:
            self.gpu_label.setText(tr("No graphics card — the processor will be used"))
        else:
            self.gpu_label.setText(gpu.name.replace("NVIDIA GeForce ", ""))
        if hw.issues and ("torch_cpu_build" in hw.issues or "gpu_unsupported" in hw.issues):
            self.gpu_label.setProperty("role", "warn")
            self.gpu_label.setToolTip(tr("See Settings → This computer"))
            self.gpu_label.style().polish(self.gpu_label)
        self._refresh_memory()
        self._live.start()

    def _refresh_memory(self) -> None:
        hw = self.services.hardware
        if hw is None or hw.gpu is None or not self.isActiveWindow():
            return
        _ram, free = hardware.free_memory()
        if free is None:
            return
        total = hw.gpu.vram_total_gb
        used = max(0.0, total - free)
        self.vram.setVisible(True)
        self.vram.set_values(used, total, "warn" if used / total > 0.85 else "ok")
        self.vram_label.setText(tr("VRAM {used:.1f} / {total:.1f} GB", used=used, total=total))

    def _on_model_changed(self, model_id: str) -> None:
        spec = self.services.catalog.get(model_id) if model_id else None
        self.model_label.setText(tr("In memory: {name}", name=spec.name) if spec else tr("No model loaded"))
        self.model_label.setProperty("role", "muted" if spec else "faint")
        self.model_label.style().polish(self.model_label)
        self.unload_button.setVisible(spec is not None)
        self._refresh_memory()

    def _on_update(self, release: object) -> None:
        url = getattr(release, "url", "")
        text = tr("SnapReel {version} is available.", version=getattr(release, "version", ""))
        self.toasts.show(text, "info", (tr("Open the page"), lambda: QDesktopServices.openUrl(QUrl(url))),
                         timeout_ms=0)

    def _on_queue(self, pending: int) -> None:
        self.queue_label.setText(tr("Queue: {count}", count=pending))
        self.queue_label.setVisible(pending > 1)

    # --- navigation ------------------------------------------------------------------
    def current_page(self) -> Page:
        return self.pages[self.stack.currentIndex()]

    def open_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        self.stack.setCurrentIndex(index)
        button = self._buttons.button(index)
        self._buttons.setExclusive(button is not None)
        for other in self._buttons.buttons():
            other.setChecked(other is button)
        self._buttons.setExclusive(True)
        self.pages[index].focus_widget().setFocus(Qt.FocusReason.OtherFocusReason)
        self.pages[index].shown()

    def page(self, key: str) -> Page | None:
        return next((p for p in self.pages if p.key == key), None)

    def _generate(self) -> None:
        self.current_page().generate()

    # --- state -------------------------------------------------------------------------
    def _restore(self) -> None:
        window = self.services.settings.window
        geometry = window.get("geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        else:
            self.resize(1360, 860)
        keys = [p.key for p in self.pages]
        if not self.services.settings.welcome_done and "welcome" in keys:
            self.open_page(keys.index("welcome"))
            return
        last = window.get("page")
        self.open_page(keys.index(last) if last in keys else 0)

    def retire(self) -> None:
        """Close this window without stopping the session (it is being replaced)."""
        self._retired = True
        self._live.stop()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._retired:
            event.accept()
            return
        if self.services.busy():
            answer = QMessageBox.question(
                self, tr("Quit SnapReel"),
                tr("Generation or a download is in progress. Stop it and quit?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.services.settings.window = {
            "geometry": bytes(self.saveGeometry().toBase64().data()).decode(),
            "page": self.current_page().key,
        }
        self._live.stop()
        self.hide()
        self.services.shutdown()
        event.accept()
