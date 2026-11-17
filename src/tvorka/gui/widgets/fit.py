"""How a model fits this computer: verdict, a memory scale and the advisor's notes."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tvorka.core.advisor import Fit
from tvorka.gui import icons, theme
from tvorka.gui.widgets.basic import label
from tvorka.i18n import messages, tr

VERDICT_TOKEN = {"great": "ok", "good": "ok", "slow": "warn", "very_slow": "warn", "no": "bad"}


class MeterBar(QWidget):
    """Thin rounded bar: how much of the available memory the job needs.

    When the need exceeds what is available, the bar spans the need and a mark shows
    where the available amount ends.
    """

    def __init__(self) -> None:
        super().__init__()
        self._need = 0.0
        self._have = 0.0
        self._token = "ok"
        self.setFixedHeight(10)

    def sizeHint(self) -> QSize:
        return QSize(200, 10)

    def set_values(self, need: float, have: float, token: str = "ok") -> None:
        self._need, self._have, self._token = max(0.0, need), max(0.0, have), token
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = float(self.width())
        top, height = 2.0, 6.0
        span = max(self._have, self._need, 0.001)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.color("line"))
        painter.drawRoundedRect(QRectF(0, top, width, height), 3, 3)
        fill = max(height, width * min(1.0, self._need / span))
        painter.setBrush(theme.color(self._token))
        painter.drawRoundedRect(QRectF(0, top, fill, height), 3, 3)
        if self._have and self._need > self._have:
            x = round(width * self._have / span) + 0.5
            painter.setPen(QPen(theme.color("text"), 1.5))
            painter.drawLine(QLineF(x, 0, x, top + height + 2))
        painter.end()


class FitBanner(QFrame):
    """Verdict line, memory meter and notes for the selected model and settings."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Banner")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.icon = QLabel()
        self.verdict = label("", "ok")
        self.verdict.setFont(theme.font("body", 9.5, QFont.Weight.DemiBold))
        self.figures = label("", "mono")
        head.addWidget(self.icon)
        head.addWidget(self.verdict)
        head.addStretch(1)
        head.addWidget(self.figures)
        layout.addLayout(head)
        self.meter = MeterBar()
        layout.addWidget(self.meter)
        self.notes = label("", "muted", wrap=True)
        layout.addWidget(self.notes)
        self.setVisible(False)

    def set_fit(self, fit: Fit | None) -> None:
        if fit is None:
            self.setVisible(False)
            return
        self.setVisible(True)
        token = VERDICT_TOKEN.get(fit.verdict, "muted")
        self.verdict.setText(messages.verdict(fit.verdict))
        self.verdict.setProperty("role", token)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.icon.setPixmap(icons.pixmap("check" if token == "ok" else "warning", 14, token))
        on_gpu = fit.plan.device in ("cuda", "xpu", "mps") and fit.have_vram_gb > 0
        if on_gpu:
            self.figures.setText(tr("VRAM {need:.1f} / {have:.1f} GB", need=fit.need_vram_gb,
                                    have=fit.have_vram_gb))
            self.meter.set_values(fit.need_vram_gb, fit.have_vram_gb, token)
        else:
            self.figures.setText(tr("RAM {need:.1f} / {have:.1f} GB", need=fit.need_ram_gb,
                                    have=fit.have_ram_gb))
            self.meter.set_values(fit.need_ram_gb, fit.have_ram_gb, token)
        self.meter.setVisible(fit.need_vram_gb > 0 or fit.need_ram_gb > 0)
        lines = [messages.advisor_note(code, params) for code, params in fit.notes]
        self.notes.setText("\n".join(line for line in lines if line))
        self.notes.setVisible(bool(self.notes.text()))
