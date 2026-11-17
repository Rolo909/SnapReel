"""Small building blocks: card, captions, segmented control, slider with value, seed field."""

from __future__ import annotations

import random
from collections.abc import Sequence

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QIcon, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tvorka.gui import icons
from tvorka.i18n import tr


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def caption(text: str) -> QLabel:
    """Small semibold label above a group of controls."""
    return label(text, "caption")


def rule() -> QFrame:
    line = QFrame()
    line.setProperty("role", "rule")
    return line


def tool_button(icon_name: str, tip: str, role: str = "ghost") -> QToolButton:
    button = QToolButton()
    button.setIcon(icons.icon(icon_name))
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.setProperty("role", role)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class Card(QFrame):
    """Panel with an optional caption; children go into ``body``."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 10, 12, 12)
        self.body.setSpacing(8)
        if title:
            self.body.addWidget(caption(title))


class Field(QWidget):
    """Caption above a control, the standard form row."""

    def __init__(self, title: str, control: QWidget, hint: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(caption(title))
        layout.addWidget(control)
        self.hint = label(hint, "faint", wrap=True)
        self.hint.setVisible(bool(hint))
        layout.addWidget(self.hint)


class Disclosure(QWidget):
    """A titled section that folds away; keeps rarely used settings out of sight."""

    def __init__(self, title: str, expanded: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.toggle = QToolButton()
        self.toggle.setProperty("role", "disclosure")
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(expanded)
        self.toggle.blockSignals(False)
        self.toggle.setIcon(QIcon(icons.pixmap("chevron", 14, "muted", rotate=0 if expanded else -90)))
        self.content.setVisible(expanded)


class Segmented(QFrame):
    """Mutually exclusive options shown side by side."""

    changed = Signal(str)

    def __init__(self, options: Sequence[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons: dict[str, QPushButton] = {}
        self.set_options(options)
        self._group.buttonClicked.connect(lambda b: self.changed.emit(b.property("value")))

    def set_options(self, options: Sequence[tuple[str, str]]) -> None:
        current = self.value()
        for button in self._buttons.values():
            self._group.removeButton(button)
            button.deleteLater()
        self._buttons.clear()
        for value, text in options:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("value", value)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # The checked option is drawn semibold; reserve that width so the text never clips.
            bold = QFont(button.font())
            bold.setWeight(QFont.Weight.DemiBold)
            button.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 24)
            self._group.addButton(button)
            self.layout().addWidget(button)
            self._buttons[value] = button
        if options:
            self.set_value(current if current in self._buttons else options[0][0])

    def value(self) -> str:
        checked = self._group.checkedButton() if hasattr(self, "_group") else None
        return checked.property("value") if checked else ""

    def set_value(self, value: str) -> None:
        button = self._buttons.get(value)
        if button is not None:
            button.setChecked(True)


class SliderField(QWidget):
    """Slider plus an exact numeric box; both stay in sync."""

    changed = Signal(float)

    def __init__(self, minimum: float, maximum: float, step: float = 1.0, decimals: int = 0,
                 suffix: str = "") -> None:
        super().__init__()
        self._step = step
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.box = QDoubleSpinBox()
        self.box.setDecimals(decimals)
        self.box.setSingleStep(step)
        self.box.setSuffix(suffix)
        self.box.setFixedWidth(72)
        self.box.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.box)
        self.set_range(minimum, maximum)
        self.slider.valueChanged.connect(lambda v: self.box.setValue(v * self._step))
        self.box.valueChanged.connect(self._from_box)

    def set_range(self, minimum: float, maximum: float) -> None:
        self.box.setRange(minimum, maximum)
        self.slider.setRange(round(minimum / self._step), round(maximum / self._step))

    def _from_box(self, value: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(value / self._step))
        self.slider.blockSignals(False)
        self.changed.emit(value)

    def value(self) -> float:
        return self.box.value()

    def set_value(self, value: float) -> None:
        self.box.setValue(value)


class SeedField(QWidget):
    """Seed entry: empty means random; buttons for a new random seed and the last used one."""

    def __init__(self) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setProperty("role", "mono")
        self.edit.setPlaceholderText(tr("random"))
        self.edit.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), self.edit))
        self.random = tool_button("dice", tr("New random seed"))
        self.repeat = tool_button("refresh", tr("Use the last seed"))
        self.repeat.setEnabled(False)
        self._last: int | None = None
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.random)
        layout.addWidget(self.repeat)
        self.random.clicked.connect(lambda: self.edit.setText(str(random.randint(0, 2**31 - 1))))
        self.repeat.clicked.connect(lambda: self._last is not None and self.edit.setText(str(self._last)))

    def value(self) -> int | None:
        text = self.edit.text().strip()
        return int(text) if text.isdigit() else None

    def set_value(self, value: int | None) -> None:
        self.edit.setText("" if value is None else str(value))

    def remember(self, seed: int) -> None:
        self._last = seed
        self.repeat.setEnabled(True)
        self.repeat.setToolTip(tr("Use the last seed ({seed})", seed=seed))
