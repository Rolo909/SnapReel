"""Application bootstrap for SnapReel."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from snapreel import __version__
from snapreel.gui.main_window import MainWindow


def load_stylesheet(app: QApplication) -> None:
    """Load the application dark theme stylesheet."""
    from snapreel.utils.paths import get_app_dir
    style_path = get_app_dir() / "src" / "snapreel" / "gui" / "styles" / "dark_theme.qss"
    if getattr(sys, "frozen", False):
        style_path = get_app_dir() / "src" / "snapreel" / "gui" / "styles" / "dark_theme.qss"
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

    from snapreel.utils.paths import get_assets_dir, get_app_dir
    from PySide6.QtGui import QIcon, QFontDatabase
    
    assets_dir = get_assets_dir()
    icon_path = assets_dir / "icons" / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
        
    font_path = assets_dir / "fonts" / "Roboto-Regular.ttf"
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))

    # Load stylesheet
    load_stylesheet(app)

    # Setup translations
    import json
    from PySide6.QtCore import QTranslator
    
    settings_file = Path("settings.json")
    language = "en"
    if settings_file.exists():
        try:
            with open(settings_file, encoding="utf-8") as f:
                data = json.load(f)
                language = data.get("language", "en")
        except Exception:
            pass

    translator = QTranslator()
    i18n_path = get_app_dir() / "src" / "snapreel" / "i18n"
    if language == "ru":
        qm_path = i18n_path / "ru_RU.qm"
        if qm_path.exists():
            translator.load(str(qm_path))
            app.installTranslator(translator)
    else:
        qm_path = i18n_path / "en_US.qm"
        if qm_path.exists():
            translator.load(str(qm_path))
            app.installTranslator(translator)

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
