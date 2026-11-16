"""First run: what SnapReel is, this computer, and one recommended model per kind.

Not a blocking wizard: it is a page inside the window, can be skipped, and opens again
from Settings → About.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from snapreel.core import hardware
from snapreel.core.advisor import Fit
from snapreel.core.catalog import ModelSpec
from snapreel.core.hardware import Hardware
from snapreel.gui import icons
from snapreel.gui.pages.base import Page
from snapreel.gui.services import Services
from snapreel.gui.widgets.basic import label
from snapreel.gui.widgets.brand import LogoMark
from snapreel.gui.widgets.feedback import ToastHost
from snapreel.gui.widgets.fit import VERDICT_TOKEN
from snapreel.gui.widgets.model_card import KIND_ICON, kind_name, size_text
from snapreel.i18n import language, messages, tr

RANK = {"great": 0, "good": 1, "slow": 2, "very_slow": 3, "no": 4}
KINDS = ("image", "video", "speech")


@dataclass
class Recommendation:
    spec: ModelSpec
    fit: Fit | None
    installed: bool

    @property
    def suggested(self) -> bool:
        """Ticked by default: already here, or runs well on this computer."""
        return self.installed or (self.fit is not None and self.fit.verdict in ("great", "good"))


def recommend(specs: list[ModelSpec], fit: Callable[[ModelSpec], Fit | None],
              installed: Callable[[ModelSpec], bool], lang: str = "ru") -> dict[str, Recommendation]:
    """Best model per kind for this computer: for speech the interface language first, then the
    best verdict, then already installed, then the smallest download.

    Online engines are never recommended: SnapReel is about local models.
    """
    out: dict[str, Recommendation] = {}
    for kind in KINDS:
        candidates = []
        for spec in specs:
            if spec.kind != kind or spec.source == "online" or spec.gated:
                continue
            result = fit(spec)
            if result is not None and not result.ok:
                continue
            rank = RANK.get(result.verdict, 5) if result is not None else 5
            foreign = kind == "speech" and bool(spec.languages) and lang not in spec.languages
            candidates.append((foreign, rank, not installed(spec), spec.download_gb, spec, result))
        if candidates:
            *_order, missing, _size, spec, result = min(candidates, key=lambda c: c[:4])
            out[kind] = Recommendation(spec, result, not missing)
    return out


class WelcomePage(Page):
    key = "welcome"
    icon = "info"
    in_nav = False  # reached on first run and from Settings → About, not from the side bar

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._checks: dict[str, QCheckBox] = {}
        self._recommended: dict[str, Recommendation] = {}

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        row = QHBoxLayout(inner)
        row.setContentsMargins(32, 40, 32, 32)
        column_widget = QWidget()
        column_widget.setMinimumWidth(560)
        column_widget.setMaximumWidth(760)
        column = QVBoxLayout(column_widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(18)
        row.addStretch(1)
        row.addWidget(column_widget)
        row.addStretch(1)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(LogoMark(56), 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        title = label(tr("Welcome to SnapReel"), "title")
        titles.addWidget(title)
        intro = tr("Create images, video and voice-overs with AI models right on your computer — "
                   "free, and your ideas never leave it.")
        titles.addWidget(label(intro, "subtitle", wrap=True))
        head.addLayout(titles, 1)
        column.addLayout(head)

        features = QHBoxLayout()
        features.setSpacing(12)
        for icon, title_text, text in (
            ("image", tr("Images"), tr("From a prompt or a reference, in any size up to 4K and beyond.")),
            ("video", tr("Video"), tr("Short clips from a description, or bring a picture to life.")),
            ("voice", tr("Voice"), tr("Natural speech from text, numbers are read as words.")),
        ):
            features.addWidget(self._feature(icon, title_text, text), 1)
        column.addLayout(features)

        self.computer = label(tr("Detecting hardware…"), "muted", wrap=True)
        column.addWidget(self.computer)

        column.addWidget(label(tr("Recommended to start"), "heading"))
        column.addWidget(label(tr("SnapReel picked one model of each kind that suits this computer best. "
                                  "You can add more any time on the Models page."), "muted", wrap=True))
        self.models_box = QVBoxLayout()
        self.models_box.setSpacing(8)
        column.addLayout(self.models_box)
        self.total = label("", "mono")
        column.addWidget(self.total)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.start = QPushButton()
        self.start.setProperty("role", "primary")
        self.start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start.clicked.connect(self._start)
        skip = QPushButton(tr("Skip for now"))
        skip.setProperty("role", "ghost")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.clicked.connect(self._skip)
        buttons.addWidget(self.start, 1)
        buttons.addWidget(skip)
        column.addLayout(buttons)
        column.addStretch(1)

        services.hardware_ready.connect(self._on_hardware)
        services.models_changed.connect(self._fill)
        self._on_hardware(services.hardware)

    def title(self) -> str:
        return tr("Welcome")

    def shown(self) -> None:
        self._fill()

    # ============================================================ layout pieces
    @staticmethod
    def _feature(icon: str, title: str, text: str) -> QWidget:
        tile = QFrame()
        tile.setObjectName("Card")
        box = QVBoxLayout(tile)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(6)
        mark = QLabel()
        mark.setPixmap(icons.pixmap(icon, 22, "accent_text"))
        box.addWidget(mark)
        box.addWidget(label(title, "heading"))
        box.addWidget(label(text, "muted", wrap=True))
        box.addStretch(1)
        return tile

    def _model_row(self, rec: Recommendation) -> QWidget:
        spec = rec.spec
        row = QFrame()
        row.setObjectName("Card")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)
        check = QCheckBox()
        check.setChecked(rec.suggested)
        check.setEnabled(not rec.installed)
        check.toggled.connect(self._update_total)
        check.setAccessibleName(spec.name)
        self._checks[spec.kind] = check
        layout.addWidget(check, 0, Qt.AlignmentFlag.AlignTop)
        mark = QLabel()
        mark.setPixmap(icons.pixmap(KIND_ICON.get(spec.kind, "models"), 20, "muted"))
        layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(f"{kind_name(spec.kind)} · {spec.name}", "heading"))
        texts.addWidget(label(spec.text(language()), "muted", wrap=True))
        if rec.fit is not None:
            verdict = rec.fit.verdict
            texts.addWidget(label(messages.verdict(verdict), VERDICT_TOKEN.get(verdict, "muted")))
        layout.addLayout(texts, 1)
        size = label(tr("installed") if rec.installed else size_text(spec.download_gb), "mono")
        layout.addWidget(size, 0, Qt.AlignmentFlag.AlignTop)
        return row

    # ============================================================ state
    def _on_hardware(self, hw: Hardware | None) -> None:
        if hw is not None:
            gpu = hw.gpu or (hw.gpus[0] if hw.gpus else None)
            graphics = (tr("{name}, {vram:.0f} GB of video memory", name=gpu.name, vram=gpu.vram_total_gb)
                        if gpu else tr("no graphics card"))
            text = tr("Your computer: {graphics} · {ram:.0f} GB of RAM", graphics=graphics,
                      ram=hw.ram_total_gb)
            if hw.issues and any(i in hw.issues for i in ("torch_cpu_build", "gpu_unsupported", "no_gpu")):
                text += "\n" + tr("Generation will run on the processor; see Settings → This computer.")
            self.computer.setText(text)
        self._fill()

    def _fill(self) -> None:
        while self.models_box.count():
            item = self.models_box.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        self._checks.clear()
        if self.services.hardware is None:
            self.models_box.addWidget(label(tr("Choosing models for this computer…"), "faint"))
            self._recommended = {}
            self._update_total()
            return
        self._recommended = recommend(self.services.catalog.all(), self.services.fit, self.services.installed,
                                      language())
        for kind in KINDS:
            rec = self._recommended.get(kind)
            if rec is not None:
                self.models_box.addWidget(self._model_row(rec))
        self._update_total()

    def _selected(self) -> list[ModelSpec]:
        chosen = []
        for kind, rec in self._recommended.items():
            check = self._checks.get(kind)
            if not rec.installed and check is not None and check.isChecked():
                chosen.append(rec.spec)
        return chosen

    def _update_total(self) -> None:
        chosen = self._selected()
        size = sum(spec.download_gb for spec in chosen)
        free = hardware.disk_free_gb(self.services.settings.models_path())
        if chosen:
            self.total.setText(tr("To download: {size} · {free} free on disk", size=size_text(size),
                                  free=size_text(free)))
            self.start.setText(tr("Download selected and start"))
        else:
            self.total.setText("")
            self.start.setText(tr("Start creating"))
        self.start.setEnabled(size + 1.5 < free or not chosen)

    # ============================================================ actions
    def _finish(self) -> None:
        self.services.settings.welcome_done = True
        self.services.settings.save()

    def _start(self) -> None:
        chosen = self._selected()
        for spec in chosen:
            self.services.downloads.start(spec)
        self._finish()
        image = self._recommended.get("image")
        window = self.window()
        page = getattr(window, "page", lambda _k: None)("image")
        if page is not None:
            if image is not None and hasattr(page, "select_model"):
                page.select_model(image.spec.id)
            window.open_page(window.pages.index(page))
        if chosen and self.toasts is not None:
            self.toasts.show(tr("Downloads started. Progress is shown on the Create button and on the Models "
                                "page."), "info")

    def _skip(self) -> None:
        self._finish()
        window = self.window()
        if hasattr(window, "open_page"):
            window.open_page(0)
