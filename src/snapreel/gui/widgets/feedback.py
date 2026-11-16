"""Non-blocking notifications (toasts) shown at the bottom right of the window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

from snapreel.gui import icons
from snapreel.gui.widgets.basic import tool_button
from snapreel.i18n import tr

ICON = {"info": ("info", "muted"), "ok": ("check", "ok"), "bad": ("warning", "bad"),
        "warn": ("warning", "warn")}


class Toast(QFrame):
    def __init__(self, parent: QWidget, text: str, level: str, action: tuple[str, Callable[[], None]] | None,
                 timeout_ms: int) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("level", level)
        self.setMaximumWidth(420)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 6, 8)
        layout.setSpacing(8)
        glyph, token = ICON.get(level, ICON["info"])
        mark = QLabel()
        mark.setPixmap(icons.pixmap(glyph, 16, token))
        mark.setAlignment(Qt.AlignmentFlag.AlignTop)
        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(mark)
        layout.addWidget(text_label, 1)
        if action is not None:
            button = QPushButton(action[0])
            button.setProperty("role", "ghost")
            button.clicked.connect(action[1])
            button.clicked.connect(self.dismiss)
            layout.addWidget(button)
        close = tool_button("close", tr("Close"))
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, self.dismiss)

    def appear(self) -> None:
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self.show()
        self._fade.start()

    def dismiss(self) -> None:
        if self._fade.endValue() == 0.0:
            return
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


class ToastHost(QObject):
    """Stacks toasts in the bottom-right corner of ``window`` and keeps them there on resize."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._toasts: list[Toast] = []
        window.installEventFilter(self)

    def show(self, text: str, level: str = "info", action: tuple[str, Callable[[], None]] | None = None,
             timeout_ms: int | None = None) -> Toast:
        if timeout_ms is None:
            timeout_ms = 0 if level == "bad" else 5000  # errors stay until read
        toast = Toast(self._window, text, level, action, timeout_ms)
        toast.destroyed.connect(lambda: self._forget(toast))
        self._toasts.append(toast)
        toast.adjustSize()
        self._layout()
        toast.appear()
        return toast

    def _forget(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        y = self._window.height() - 16
        for toast in reversed(self._toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self._window.width() - toast.width() - 16, y)
            toast.raise_()
            y -= 8

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window and event.type() == QEvent.Type.Resize:
            self._layout()
        return False
