"""What every section of the window has in common."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from tvorka.gui.handoff import Asset, Route
from tvorka.gui.services import Services
from tvorka.gui.widgets.feedback import ToastHost


class Page(QWidget):
    """A section of the main window. Pages that create content override ``generate``."""

    key = ""
    icon = ""

    def __init__(self, services: Services, toasts: ToastHost) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # can hold focus when it has no input
        self.services = services
        self.toasts = toasts

    def title(self) -> str:
        return ""

    def generate(self) -> None:
        """Ctrl+Enter."""

    def cancel(self) -> None:
        """Esc."""

    def shown(self) -> None:
        """Called every time the page becomes visible."""

    def save_state(self) -> None:
        """Keep what was typed but not sent: the window is about to close or be rebuilt."""

    def routes(self, asset: Asset) -> list[Route]:
        """How this page can take ``asset`` (see ``gui/handoff.py``); [] when it cannot."""
        return []

    def receive(self, asset: Asset, role: str) -> None:
        """Take ``asset`` in ``role`` (one of the routes this page offered)."""

    def note_received(self, asset: Asset, value: str) -> None:
        """Remember what came in (the path or text put into a field), for the lineage of new works."""
        self._received = (asset, value)

    def parent_for(self, *values: str) -> str:
        """The work this page's next result comes from: the received asset, if it is still in use."""
        received = getattr(self, "_received", None)
        if received is None or not received[0].parent:
            return ""
        asset, value = received
        return asset.parent if value and any(v.strip() == value.strip() for v in values if v) else ""

    def send_menu(self, asset: Asset, anchor: QWidget | None = None) -> None:
        """Show "Send to…" for ``asset`` under ``anchor`` (or at the cursor)."""
        window = self.window()
        if hasattr(window, "send_menu"):
            window.send_menu(asset, anchor)

    def send(self, asset: Asset, page: str, role: str) -> None:
        """Hand ``asset`` to ``page`` directly (the buttons that do one thing)."""
        window = self.window()
        if hasattr(window, "send"):
            window.send(asset, Route(page, role, ""))

    def focus_widget(self) -> QWidget:
        """Where typing should go when the page opens (the prompt, the text…)."""
        for name in ("prompt", "text"):
            widget = getattr(self, name, None)
            if isinstance(widget, QWidget):
                return widget
        return self

