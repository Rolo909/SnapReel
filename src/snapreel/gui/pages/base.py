"""What every section of the window has in common."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from snapreel.gui.services import Services
from snapreel.gui.widgets.feedback import ToastHost


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

    def focus_widget(self) -> QWidget:
        """Where typing should go when the page opens (the prompt, the text…)."""
        for name in ("prompt", "text"):
            widget = getattr(self, name, None)
            if isinstance(widget, QWidget):
                return widget
        return self

