"""Design tokens and the single application stylesheet ("Graphite & Mint", Task_plan 5.1).

Neutral graphite surfaces keep attention on the user's images; one fresh mint accent marks
what to do next. No gradients, glows or purple. Widgets never set colours inline: they get an
``objectName`` or a ``role`` property and the template below styles them; custom-painted
widgets read colours through :func:`color`.
"""

from __future__ import annotations

from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0D1015",          # window
        "panel": "#13171D",       # side bar, cards
        "raised": "#1A1F27",      # inputs, hover
        "line": "#262C36",        # 1 px borders
        "text": "#E8ECF1",
        "muted": "#9AA4B2",
        "faint": "#667080",       # disabled, placeholders
        "accent": "#34D3A6",      # primary actions, focus, progress
        "accent_hover": "#5BE0BB",
        "on_accent": "#04261D",   # text on accent
        "accent_text": "#34D3A6",  # accent used as text (links, active tab)
        "accent_soft": "#163029",  # selected chips / nav
        "ok": "#4CD69B", "warn": "#F2B84B", "bad": "#F2686A",
        "select": "#1E3A33",
    },
    "light": {
        "bg": "#F3F5F7",
        "panel": "#FFFFFF",
        "raised": "#F6F8FA",
        "line": "#E1E5EA",
        "text": "#161A20",
        "muted": "#5B6573",
        "faint": "#8A93A0",
        "accent": "#16C79A",
        "accent_hover": "#12B38A",
        "on_accent": "#04261D",
        "accent_text": "#0A7A5E",
        "accent_soft": "#E2F7F0",
        "ok": "#0E7A56", "warn": "#9A5E00", "bad": "#C4303A",
        "select": "#D6F3EA",
    },
}

# First installed family wins.
FONT_CANDIDATES = {
    "display": ["Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI", "system-ui"],
    "body": ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "system-ui"],
    "mono": ["Cascadia Mono", "Consolas", "Menlo", "monospace"],
}

_current = "dark"
_fonts: dict[str, str] = {}


class _KeyboardFocusOnly(QObject):
    """Buttons take focus from Tab, not from a mouse click.

    The focus ring then appears exactly when someone navigates with the keyboard and
    never lingers on a button that was just clicked.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() == QEvent.Type.Polish and isinstance(watched, QAbstractButton)
                and watched.focusPolicy() == Qt.FocusPolicy.StrongFocus):
            watched.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return False


_focus_filter: _KeyboardFocusOnly | None = None


def color(token: str) -> QColor:
    return QColor(PALETTES[_current][token])


def name() -> str:
    return _current


def font_family(kind: str) -> str:
    if kind not in _fonts:
        available = set(QFontDatabase.families())
        _fonts[kind] = next((f for f in FONT_CANDIDATES[kind] if f in available),
                            FONT_CANDIDATES[kind][-1])
    return _fonts[kind]


def font(kind: str = "body", size: float = 9.5, weight: QFont.Weight = QFont.Weight.Normal,
         spacing: float = 0.0) -> QFont:
    """A font of a role: ``display`` (headings), ``body`` or ``mono`` (numbers)."""
    result = QFont(font_family(kind))
    result.setPointSizeF(size)
    result.setWeight(weight)
    if spacing:
        result.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    if kind == "mono":
        result.setStyleHint(QFont.StyleHint.Monospace)
    return result


def stylesheet(theme: str, check_icon: str = "") -> str:
    tokens = {**PALETTES[theme], **{f"font_{k}": font_family(k) for k in FONT_CANDIDATES},
              "check_icon": check_icon}
    return QSS.substitute(tokens)


def _check_icon(theme: str) -> str:
    """QSS can only show images from files: render the checkbox tick once per theme."""
    from tvorka.core import paths
    from tvorka.gui import icons

    target = paths.data_dir() / "ui" / f"check-{theme}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    icons.pixmap("check", 14, QColor(PALETTES[theme]["on_accent"])).save(str(target))
    return target.as_posix()


def apply(app: QApplication, theme: str) -> None:
    global _current
    _current = theme if theme in PALETTES else "dark"
    p = PALETTES[_current]
    palette = QPalette()
    for role, token in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.Base, "raised"),
                        (QPalette.ColorRole.AlternateBase, "panel"), (QPalette.ColorRole.Text, "text"),
                        (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Button, "raised"),
                        (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                        (QPalette.ColorRole.HighlightedText, "on_accent"),
                        (QPalette.ColorRole.PlaceholderText, "faint"),
                        (QPalette.ColorRole.Link, "accent_text"),
                        (QPalette.ColorRole.ToolTipBase, "raised"), (QPalette.ColorRole.ToolTipText, "text")):
        palette.setColor(role, QColor(p[token]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(p["faint"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(p["faint"]))
    app.setPalette(palette)
    app.setFont(font("body", 9.5))
    app.setStyleSheet(stylesheet(_current, _check_icon(_current)))
    global _focus_filter
    if _focus_filter is None:
        _focus_filter = _KeyboardFocusOnly(app)
        app.installEventFilter(_focus_filter)


def contrast(foreground: str, background: str) -> float:
    """WCAG 2 contrast ratio between two hex colours."""
    def luminance(hex_color: str) -> float:
        channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (a + 0.05) / (b + 0.05)


# Placeholders are $token (QSS itself uses braces). 4 px grid, radius 8 (cards) / 6 (controls).
QSS = Template("""
* { outline: none; }
QWidget { color: $text; font-family: "$font_body"; }
QMainWindow, QDialog, #Page { background: $bg; }
QToolTip { background: $raised; color: $text; border: 1px solid $line; border-radius: 6px; padding: 5px 8px; }

/* --- side bar -------------------------------------------------------------- */
#Sidebar { background: $panel; border-right: 1px solid $line; }
#NavButton { background: transparent; border: none; border-radius: 8px; text-align: left;
             padding: 9px 12px; color: $muted; font-size: 10pt; }
#NavButton:hover { color: $text; background: $raised; }
#NavButton:checked { color: $text; background: $accent_soft; font-weight: 600; }
#SidebarFooter { border-top: 1px solid $line; }
#HardwareCard { background: $raised; border: 1px solid $line; border-radius: 8px; }
QLabel[role="credit"] { color: $faint; font-size: 8.5pt; }
QLabel[role="credit"] a { color: $accent_text; }

/* --- text roles ------------------------------------------------------------ */
QLabel[role="caption"] { color: $muted; font-size: 8.5pt; font-weight: 600; }
QLabel[role="title"] { font-family: "$font_display"; font-size: 17pt; font-weight: 600; }
QLabel[role="subtitle"] { color: $muted; font-size: 9.5pt; }
QLabel[role="heading"] { font-size: 10.5pt; font-weight: 600; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="faint"] { color: $faint; }
QLabel[role="mono"] { font-family: "$font_mono"; color: $muted; }
QLabel[role="ok"] { color: $ok; }
QLabel[role="warn"] { color: $warn; }
QLabel[role="bad"] { color: $bad; }
QLabel[role="link"] { color: $accent_text; }

/* --- surfaces -------------------------------------------------------------- */
#Card { background: $panel; border: 1px solid $line; border-radius: 10px; }
#Banner { background: $raised; border: 1px solid $line; border-radius: 8px; }
#Stage { background: $panel; border: 1px solid $line; border-radius: 12px; }
#ChatList { background: $panel; border-right: 1px solid $line; }
#ChatBubble[who="user"] { background: $raised; border: 1px solid $line; border-radius: 12px; }
#Composer { background: $panel; border: 1px solid $line; border-radius: 12px; }
#Composer QPlainTextEdit { background: transparent; border: none; font-size: 11pt; padding: 4px 2px; }
QLabel[role="chat"] { font-size: 10.5pt; }
#Chip { background: $raised; border: 1px solid $line; border-radius: 8px; }
QToolButton[recording="true"] { color: $bad; border: 1px solid $bad; border-radius: 6px; }
#Page[dropping="true"] #Composer { border: 1px dashed $accent; }
QLabel[role="group"] { color: $faint; font-size: 8.5pt; font-weight: 600; padding: 8px 4px 2px 4px; }
QFrame[role="rule"] { background: $line; max-height: 1px; min-height: 1px; border: none; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QListWidget { background: transparent; border: none; }
QListWidget::item { color: $faint; border-radius: 6px; padding: 3px; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QListWidget::item:hover { background: $raised; }

/* --- inputs ---------------------------------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $raised; border: 1px solid $line; border-radius: 6px; padding: 6px 9px;
    selection-background-color: $select; selection-color: $text; }
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {
    border-color: $faint; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus { border-color: $accent; }
#PromptEdit { font-size: 11pt; padding: 10px 12px; border-radius: 10px; background: $panel; }
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $faint; }
QSpinBox, QDoubleSpinBox, QLineEdit[role="mono"] { font-family: "$font_mono"; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button { width: 0; border: none; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: $panel; border: 1px solid $line; border-radius: 6px;
                              outline: none; selection-background-color: $accent_soft;
                              selection-color: $text; padding: 4px; }

/* --- buttons --------------------------------------------------------------- */
QPushButton, QToolButton { background: $raised; border: 1px solid $line; border-radius: 6px;
                           padding: 6px 12px; color: $text; }
QPushButton:hover, QToolButton:hover { border-color: $faint; }
QPushButton:pressed, QToolButton:pressed { background: $panel; }
QPushButton:disabled, QToolButton:disabled { color: $faint; border-color: $line; }
QPushButton[role="primary"] { background: $accent; border: none; color: $on_accent;
                              font-size: 11pt; font-weight: 600; padding: 11px 18px; border-radius: 8px; }
QPushButton[role="primary"]:hover { background: $accent_hover; }
QPushButton[role="primary"]:disabled { background: $raised; color: $faint; }
QPushButton[role="accent"] { background: $accent_soft; border: 1px solid $accent_soft; color: $accent_text;
                             font-weight: 600; padding: 7px 14px; }
QPushButton[role="accent"]:hover { background: $accent; border-color: $accent; color: $on_accent; }
QPushButton[role="accent"]:disabled { background: $raised; border-color: $line; color: $faint; }
QPushButton[role="ghost"], QToolButton[role="ghost"] { background: transparent; border-color: transparent; }
QPushButton[role="ghost"]:hover, QToolButton[role="ghost"]:hover { background: $raised; }
QPushButton[role="link"] { background: transparent; border: none; color: $accent_text; padding: 2px 0;
                           text-align: left; }
QPushButton[role="link"]:hover { text-decoration: underline; }
QPushButton[role="chip"] { background: $raised; border: 1px solid $line; border-radius: 14px;
                           padding: 6px 12px; color: $muted; text-align: left; }
QPushButton[role="chip"]:hover { border-color: $accent; color: $text; background: $accent_soft; }
QToolButton[role="disclosure"] { background: transparent; border: none; color: $muted; font-weight: 600;
                                 font-size: 9pt; padding: 2px 0; }
QToolButton[role="disclosure"]:hover { color: $text; }

/* keyboard focus: buttons only take focus from Tab (see _KeyboardFocusOnly) */
QPushButton:focus, QToolButton:focus { border: 1px solid $accent; }
QPushButton[role="primary"]:focus { border: 2px solid $text; }
QPushButton[role="ghost"]:focus, QToolButton[role="ghost"]:focus, QPushButton[role="link"]:focus,
QToolButton[role="disclosure"]:focus { border: 1px solid $accent; }
#NavButton:focus { border: 1px solid $accent; }
#Segmented QPushButton:focus { border: 1px solid $accent; }
QCheckBox::indicator:focus { border: 1px solid $accent; }
QListWidget:focus { border: 1px solid $accent; border-radius: 6px; }

/* segmented control: QPushButtons inside #Segmented */
#Segmented { background: $raised; border: 1px solid $line; border-radius: 8px; }
#Segmented QPushButton { background: transparent; border: none; border-radius: 6px; padding: 5px 10px;
                         color: $muted; }
#Segmented QPushButton:hover { color: $text; }
#Segmented QPushButton:checked { background: $panel; color: $text; font-weight: 600; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid $faint; border-radius: 4px;
                       background: $raised; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check_icon"); }

QSlider::groove:horizontal { height: 4px; background: $line; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
                             background: $text; }
QSlider::handle:horizontal:hover { background: $accent_hover; }

QProgressBar { background: $raised; border: none; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: $accent; border-radius: 2px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $line; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $line; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    width: 0; height: 0; background: none; }

QTabBar::tab { background: transparent; border: none; border-bottom: 2px solid transparent;
               padding: 7px 12px; color: $muted; }
QTabBar::tab:selected { color: $text; border-bottom-color: $accent; }
QTabWidget::pane { border: none; border-top: 1px solid $line; }

QMenu { background: $panel; border: 1px solid $line; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background: $accent_soft; }

#Toast { background: $panel; border: 1px solid $line; border-left: 3px solid $accent; border-radius: 8px; }
#Toast[level="bad"] { border-left-color: $bad; }
#Toast[level="ok"] { border-left-color: $ok; }
""")
