"""A model in the Models page: what it is, whether it fits this computer, and what can be done."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from tvorka.core.advisor import Fit, LlmPlan
from tvorka.core.catalog import ModelSpec
from tvorka.gui import icons
from tvorka.gui.widgets.basic import label, tool_button
from tvorka.gui.widgets.fit import VERDICT_TOKEN
from tvorka.i18n import language, messages, tr

KIND_ICON = {"image": "image", "video": "video", "speech": "voice", "chat": "chat", "transcribe": "mic"}


def kind_name(kind: str) -> str:
    names = {"image": tr("Image"), "video": tr("Video"), "speech": tr("Voice"), "chat": tr("Chat"),
             "transcribe": tr("Speech recognition")}
    return names.get(kind, kind)


def chat_download_gb(spec: ModelSpec, fit: Fit | None) -> float:
    """What downloading a chat model takes: the quantization the advisor picked, projector, MTP head."""
    quant = spec.quant(fit.plan.quant) if fit is not None and isinstance(fit.plan, LlmPlan) else None
    return round(quant["gb"] + spec.mmproj_gb + spec.mtp_gb, 2) if quant else spec.download_gb


def chat_download_files(spec: ModelSpec, fit: Fit | None) -> list[str]:
    """Files of a chat model to download: the advisor's quantization, projector, MTP head.

    Empty until the advisor has judged this computer.
    """
    quant = spec.quant(fit.plan.quant) if fit is not None and isinstance(fit.plan, LlmPlan) else None
    if quant is None:
        return []
    return [*quant["files"], *([spec.mmproj] if spec.mmproj else []), *([spec.mtp] if spec.mtp else [])]


def chat_details(spec: ModelSpec, fit: Fit | None) -> str:
    """``Q4_K_M · remembers 8K tokens · sees images`` — what the user gets on this computer."""
    parts = []
    if fit is not None and isinstance(fit.plan, LlmPlan):
        if fit.plan.quant:
            parts.append(fit.plan.quant)
        parts.append(tr("remembers {count}K tokens of the conversation", count=fit.plan.ctx // 1024))
    if "vision" in spec.capabilities:
        parts.append(tr("sees images"))
    return "  ·  ".join(parts)


def size_text(gb: float) -> str:
    if gb < 1:
        return tr("{mb:.0f} MB", mb=gb * 1024)
    return tr("{gb:.1f} GB", gb=gb)


class ModelCard(QFrame):
    """States: not installed → downloading → installed. Emits user intentions; the page acts."""

    download = Signal(str)
    cancel = Signal(str)
    delete = Signal(str)
    use = Signal(str)
    open_page = Signal(str)

    def __init__(self, spec: ModelSpec) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.spec = spec
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        badge = QLabel()
        badge.setPixmap(icons.pixmap(KIND_ICON.get(spec.kind, "models"), 22, "muted"))
        badge.setFixedWidth(26)
        badge.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(badge)

        info = QVBoxLayout()
        info.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        name = label(spec.name)
        name.setProperty("role", "heading")
        title_row.addWidget(name)
        if spec.gated:
            lock = QLabel()
            lock.setPixmap(icons.pixmap("lock", 14, "warn"))
            lock.setToolTip(tr("Restricted access: needs a Hugging Face token"))
            title_row.addWidget(lock)
        title_row.addStretch(1)
        info.addLayout(title_row)
        meta = [spec.author, spec.license, kind_name(spec.kind)]
        info.addWidget(label("  ·  ".join(m for m in meta if m), "faint"))
        summary = spec.text(language())
        if summary:
            info.addWidget(label(summary, "muted", wrap=True))
        self.details = label("", "faint", wrap=True)
        self.details.setVisible(spec.kind == "chat")
        info.addWidget(self.details)
        self.verdict = label("", "muted")
        self.verdict.setWordWrap(True)
        info.addWidget(self.verdict)
        layout.addLayout(info, 1)

        side = QVBoxLayout()
        side.setSpacing(6)
        side.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.size = label("", "mono")
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self.size)
        self.primary = QPushButton()
        self.primary.setProperty("role", "accent")
        self.primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary.setMinimumWidth(150)
        self.primary.clicked.connect(self._primary_clicked)
        side.addWidget(self.primary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress_text = label("", "mono")
        self.progress_text.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self.progress)
        side.addWidget(self.progress_text)
        extras = QHBoxLayout()
        extras.setSpacing(2)
        extras.addStretch(1)
        self.page_button = tool_button("link", tr("Open the model page"))
        self.page_button.clicked.connect(lambda: self.open_page.emit(spec.id))
        self.page_button.setVisible(spec.source == "hf")
        self.cancel_button = tool_button("close", tr("Cancel the download"))
        self.cancel_button.clicked.connect(lambda: self.cancel.emit(spec.id))
        self.delete_button = tool_button("trash", tr("Delete from disk"))
        self.delete_button.clicked.connect(lambda: self.delete.emit(spec.id))
        for button in (self.page_button, self.cancel_button, self.delete_button):
            extras.addWidget(button)
        side.addLayout(extras)
        layout.addLayout(side)
        self._installed = False

    # ------------------------------------------------------------------
    def set_state(self, installed: bool, downloading: tuple[int, int, float] | None, fit: Fit | None,
                  on_disk_gb: float = 0.0) -> None:
        spec = self.spec
        self._installed = installed
        busy = downloading is not None
        self.progress.setVisible(busy)
        self.progress_text.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.delete_button.setVisible(installed and not busy and spec.source in ("hf", "url", "local"))
        self.delete_button.setToolTip(tr("Remove from the list") if spec.source == "local"
                                      else tr("Delete from disk"))
        download_gb = chat_download_gb(spec, fit) if spec.kind == "chat" else spec.download_gb
        if spec.source == "online":
            self.size.setText(tr("no download"))
        elif installed:
            self.size.setText(tr("installed · {size}", size=size_text(on_disk_gb or download_gb)))
        else:
            self.size.setText(size_text(download_gb))
        if busy:
            done, total, speed = downloading
            fraction = done / total if total else 0.0
            self.progress.setValue(round(fraction * 1000))
            text = f"{round(fraction * 100)} %"
            if speed > 0:
                text += f"  ·  {size_text(speed / 1024**3)}/{tr('s')}"
            self.progress_text.setText(text)
            self.primary.setText(tr("Downloading…"))
            self.primary.setEnabled(False)
        elif installed:
            self.primary.setText(tr("Use"))
            self.primary.setEnabled(True)
            self.primary.setIcon(icons.icon("check"))
        else:
            self.primary.setText(tr("Download"))
            self.primary.setIcon(icons.icon("download"))
            self.primary.setEnabled(fit is None or fit.ok)
        self._show_fit(fit)

    def _show_fit(self, fit: Fit | None) -> None:
        if self.spec.kind == "chat":
            self.details.setText(chat_details(self.spec, fit))
        if fit is None:
            self.verdict.setText(tr("Checking this computer…"))
            self._role("faint")
            return
        notes = [messages.advisor_note(code, params) for code, params in fit.notes]
        notes = [n for n in notes if n]
        text = messages.verdict(fit.verdict)
        if notes and fit.verdict in ("slow", "very_slow", "no"):
            text += " — " + notes[0]
        self.verdict.setText(text)
        self.verdict.setToolTip("\n".join(notes))
        self._role(VERDICT_TOKEN.get(fit.verdict, "muted"))

    def _role(self, role: str) -> None:
        self.verdict.setProperty("role", role)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)

    def _primary_clicked(self) -> None:
        if self._installed:
            self.use.emit(self.spec.id)
        else:
            self.download.emit(self.spec.id)
