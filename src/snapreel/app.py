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
    from snapreel.core.config import AppConfig
    from snapreel.infra.downloader import ModelDownloader
    from snapreel.gui.widgets.model_setup_wizard import ModelSetupWizard
    from PySide6.QtWidgets import QDialog
    
    app = QApplication(sys.argv)

    # Configure global application settings
    app.setApplicationName("SnapReel")
    app.setApplicationVersion(__version__)

    # Load stylesheet
    load_stylesheet(app)

    # Load config
    config = AppConfig()

    # Model Setup Workflow
    downloader = ModelDownloader(config.get_models_dir())
    # By default, check models required for basic operations
    missing_models = downloader.get_missing_models(["llm_7b", "whisper", "sdxl_turbo"])
    
    if missing_models:
        wizard = ModelSetupWizard(downloader, missing_models)
        if wizard.exec() != QDialog.DialogCode.Accepted:
            # The user cancelled the download or it failed, so we can't start the app
            return 1

    # Create and show main window
    window = MainWindow(config)
    window.show()

    return app.exec()
