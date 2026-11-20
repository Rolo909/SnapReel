"""Application bootstrap. Nothing heavy is imported here: torch loads in the worker on first use."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from tvorka import __version__
from tvorka.core import logging_setup, paths
from tvorka.core.settings import Settings

log = logging.getLogger(__name__)


def build_pages(services: object, toasts: object) -> list:
    from tvorka.gui.pages.chat import ChatPage
    from tvorka.gui.pages.gallery import GalleryPage
    from tvorka.gui.pages.image import ImagePage
    from tvorka.gui.pages.models import ModelsPage
    from tvorka.gui.pages.settings import SettingsPage
    from tvorka.gui.pages.speech import SpeechPage
    from tvorka.gui.pages.video import VideoPage
    from tvorka.gui.pages.welcome import WelcomePage

    pages = [ImagePage(services, toasts)]
    pages.append(VideoPage(services, toasts))
    pages.append(SpeechPage(services, toasts))
    pages.append(ChatPage(services, toasts))
    pages.append(ModelsPage(services, toasts))
    pages.append(GalleryPage(services, toasts))
    pages.append(SettingsPage(services, toasts))
    pages.append(WelcomePage(services, toasts))  # not in the side bar
    return pages


def open_window(app: QApplication, services: object, previous: object = None) -> object:
    """Build the main window; a language or theme change rebuilds it around the same services."""
    from tvorka.gui import theme
    from tvorka.gui.main_window import MainWindow
    from tvorka.i18n import set_language

    settings = services.settings
    if previous is not None:
        previous.save_pages()  # before the new pages read the settings
        settings.save()
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
    from tvorka.core import migrate

    copied = migrate.copy_old_data()  # before anything creates the new data folder
    log_file = logging_setup.setup()
    log.info("Tvorka %s starting, log: %s", __version__, log_file)
    app = QApplication(sys.argv)
    app.setApplicationName("Tvorka")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Tvorka")
    icon = paths.assets_dir() / "icons" / "app_icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from tvorka.i18n import set_language, tr

    settings = Settings.load()
    if copied is not None:
        log.info("copied the SnapReel data folder %s", copied)
        adopted = migrate.adopt_old_folders(settings, paths.data_dir() / "history.json")
        if adopted:
            log.info("using the SnapReel folders: %s", "; ".join(adopted))
            settings.save()
    set_language(settings.language)

    lock = QLockFile(str(paths.data_dir() / "tvorka.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Tvorka", tr("Tvorka is already running."))
        return 0

    from tvorka.engines.plugins import load_plugins
    from tvorka.gui.services import Services

    plugins = load_plugins()  # before the catalog: plugin engines must be known when it loads
    services = Services(settings, plugins)
    open_window(app, services)
    services.start()
    code = app.exec()
    lock.unlock()
    log.info("Tvorka stopped (%s)", code)
    return code
