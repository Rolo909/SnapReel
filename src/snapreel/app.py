"""Application bootstrap. Nothing heavy is imported here: torch loads in the worker on first use."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from snapreel import __version__
from snapreel.core import logging_setup, paths
from snapreel.core.settings import Settings

log = logging.getLogger(__name__)


def build_pages(services: object, toasts: object) -> list:
    from snapreel.gui.pages.gallery import GalleryPage
    from snapreel.gui.pages.image import ImagePage
    from snapreel.gui.pages.models import ModelsPage
    from snapreel.gui.pages.settings import SettingsPage
    from snapreel.gui.pages.speech import SpeechPage
    from snapreel.gui.pages.video import VideoPage
    from snapreel.gui.pages.welcome import WelcomePage

    pages = [ImagePage(services, toasts)]
    pages.append(VideoPage(services, toasts))
    pages.append(SpeechPage(services, toasts))
    pages.append(ModelsPage(services, toasts))
    pages.append(GalleryPage(services, toasts))
    pages.append(SettingsPage(services, toasts))
    pages.append(WelcomePage(services, toasts))  # not in the side bar
    return pages


def open_window(app: QApplication, services: object, previous: object = None) -> object:
    """Build the main window; a language or theme change rebuilds it around the same services."""
    from snapreel.gui import theme
    from snapreel.gui.main_window import MainWindow
    from snapreel.i18n import set_language

    settings = services.settings
    theme.apply(app, settings.theme)
    set_language(settings.language)
    window = MainWindow(services, build_pages(services, None))
    if previous is not None:
        window.restoreGeometry(previous.saveGeometry())
        window.open_page(next(i for i, p in enumerate(window.pages) if p.key == previous.current_page().key))
    window.rebuild_requested.connect(lambda: open_window(app, services, window))
    window.show()
    if previous is not None:
        previous.retire()
        previous.deleteLater()
    app.setProperty("main_window", window)
    return window


def run_app() -> int:
    log_file = logging_setup.setup()
    log.info("SnapReel %s starting, log: %s", __version__, log_file)
    app = QApplication(sys.argv)
    app.setApplicationName("SnapReel")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("SnapReel")
    icon = paths.assets_dir() / "icons" / "app_icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from snapreel.i18n import set_language, tr

    settings = Settings.load()
    set_language(settings.language)

    lock = QLockFile(str(paths.data_dir() / "snapreel.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "SnapReel", tr("SnapReel is already running."))
        return 0

    from snapreel.engines.plugins import load_plugins
    from snapreel.gui.services import Services

    plugins = load_plugins()  # before the catalog: plugin engines must be known when it loads
    services = Services(settings, plugins)
    open_window(app, services)
    services.start()
    code = app.exec()
    lock.unlock()
    log.info("SnapReel stopped (%s)", code)
    return code
