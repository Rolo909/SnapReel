"""Application bootstrap for SnapReel."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from snapreel import __version__
from snapreel.gui.main_window import MainWindow


def load_stylesheet(app: QApplication) -> None:
    """Load the application dark theme stylesheet."""
    # Load the stylesheet from the styles directory
    style_path = Path(__file__).parent / "gui" / "styles" / "dark_theme.qss"
    if style_path.exists():
        try:
            with open(style_path, encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as e:
            print(f"Failed to load stylesheet: {e}")
    else:
        print(f"Stylesheet not found at {style_path}")


def run_app() -> int:
    """Initialize and run the QApplication."""
    app = QApplication(sys.argv)

    # Configure global application settings
    app.setApplicationName("SnapReel")
    app.setApplicationVersion(__version__)

    # Load stylesheet
    load_stylesheet(app)

    # Create and show main window
    window = MainWindow()
    window.show()

    return app.exec()
