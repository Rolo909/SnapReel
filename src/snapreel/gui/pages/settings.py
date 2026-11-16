"""Settings: appearance, performance, this computer, folders, formats, catalog, Hugging Face,
plugins and about."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from snapreel import __version__
from snapreel.core import hardware, logging_setup, paths
from snapreel.core.hardware import Hardware
from snapreel.core.settings import DEFAULT_CATALOG_URL, PERFORMANCE_MODES
from snapreel.engines.media import AUDIO_FORMATS, IMAGE_FORMATS, VIDEO_FORMATS
from snapreel.engines.plugins import plugins_dir
from snapreel.gui import icons
from snapreel.gui.pages.base import Page
from snapreel.gui.services import Services
from snapreel.gui.widgets.basic import Card, Field, Segmented, caption, label, rule
from snapreel.gui.widgets.brand import AUTHOR, AUTHOR_URL, PROJECT_URL, LogoMark
from snapreel.gui.widgets.feedback import ToastHost
from snapreel.gui.widgets.model_card import size_text
from snapreel.i18n import tr
from snapreel.workers.downloads import run_async

log = logging.getLogger(__name__)
GB = 1024**3


def mode_text(mode: str) -> tuple[str, str]:
    return {
        "auto": (tr("Automatic"), tr("SnapReel picks the fastest mode that fits this computer.")),
        "speed": (tr("Speed"), tr("The whole model stays on the graphics card. "
                                  "Needs the most video memory.")),
        "balanced": (tr("Balanced"), tr("Model parts take turns on the graphics card: a little slower, "
                                        "much less memory.")),
        "low_memory": (tr("Low memory"), tr("The model is streamed piece by piece. Slow, but runs on small "
                                            "graphics cards.")),
        "cpu": (tr("Processor only"), tr("No graphics card is used. Works everywhere, but very slowly.")),
    }[mode]


def issue_text(code: str, hw: Hardware) -> str:
    gpu = hw.gpus[0].name if hw.gpus else ""
    return {
        "torch_missing": tr("PyTorch is not installed, so nothing can be generated. Reinstall SnapReel."),
        "torch_cpu_build": tr("PyTorch without NVIDIA graphics card support is installed: generation runs on "
                              "the processor, tens of times slower."),
        "gpu_unsupported": tr("{gpu} is not supported yet: SnapReel uses NVIDIA (CUDA) and Apple Silicon "
                              "graphics. Models will run on the processor.", gpu=gpu),
        "no_gpu": tr("No graphics card found: models will run on the processor. Prefer the lightest models."),
        "low_ram": tr("Less than 16 GB of RAM: heavy models may not fit."),
    }.get(code, code)


def can_install_gpu_torch() -> bool:
    """Only from source (a frozen build cannot pip-install) and before torch is imported."""
    return not paths.is_frozen() and "torch" not in sys.modules


class SettingsPage(Page):
    key = "settings"
    icon = "settings"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        settings = services.settings
        self._install: QProcess | None = None
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        row = QHBoxLayout(inner)
        row.setContentsMargins(32, 24, 32, 32)
        column_widget = QWidget()
        column_widget.setMinimumWidth(560)
        column_widget.setMaximumWidth(720)
        column = QVBoxLayout(column_widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)
        # Stretches, not alignment flags: with flags Qt sizes the column by its unwrapped
        # size hint and wrapped labels get clipped.
        row.addStretch(1)
        row.addWidget(column_widget)
        row.addStretch(1)

        column.addWidget(label(tr("Settings"), "title"))
        column.addWidget(label(tr("Changes are saved automatically."), "subtitle"))

        # --- appearance --------------------------------------------------------------
        look = Card(tr("Appearance"))
        self.language = Segmented([("ru", "Русский"), ("en", "English")])
        self.language.set_value(settings.language)
        self.language.changed.connect(self._language_changed)
        self.theme = Segmented([("dark", tr("Dark")), ("light", tr("Light"))])
        self.theme.set_value(settings.theme)
        self.theme.changed.connect(self._theme_changed)
        pair = QHBoxLayout()
        pair.setSpacing(16)
        pair.addWidget(Field(tr("Language"), self.language), 1)
        pair.addWidget(Field(tr("Theme"), self.theme), 1)
        look.body.addLayout(pair)
        column.addWidget(look)

        # --- performance -------------------------------------------------------------
        perf = Card(tr("Performance"))
        self.mode = QComboBox()
        for mode in PERFORMANCE_MODES:
            self.mode.addItem(mode_text(mode)[0], mode)
        self.mode.setCurrentIndex(max(0, self.mode.findData(settings.performance_mode)))
        self.mode_field = Field(tr("Memory mode"), self.mode, mode_text(settings.performance_mode)[1])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.keep_loaded = QCheckBox(tr("Keep the model in memory between generations"))
        self.keep_loaded.setChecked(settings.keep_model_loaded)
        self.keep_loaded.toggled.connect(self._keep_loaded_changed)
        perf.body.addWidget(self.mode_field)
        perf.body.addWidget(self.keep_loaded)
        perf.body.addWidget(label(tr("Faster repeats; turn off to free memory for other programs."), "faint",
                                  wrap=True))
        column.addWidget(perf)

        column.addWidget(self._build_computer())
        column.addWidget(self._build_folders())
        column.addWidget(self._build_formats())
        column.addWidget(self._build_catalog())

        # --- hugging face ------------------------------------------------------------
        hub = Card("Hugging Face")
        self.token = QLineEdit(settings.hf_token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("hf_…")
        self.token.editingFinished.connect(self._token_changed)
        hub.body.addWidget(Field(tr("Access token"), self.token,
                                 tr("Needed only for models with restricted access. Stored on this computer "
                                    "in plain text in settings.json.")))
        column.addWidget(hub)

        column.addWidget(self._build_plugins())
        column.addWidget(self._build_about())
        column.addStretch(1)

        services.hardware_ready.connect(self._show_hardware)
        if services.hardware is not None:
            self._show_hardware(services.hardware)

    def title(self) -> str:
        return tr("Settings")

    # ============================================================ this computer
    def _build_computer(self) -> QWidget:
        card = Card(tr("This computer"))
        self.hw_summary = label(tr("Detecting hardware…"), "muted", wrap=True)
        self.hw_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.body.addWidget(self.hw_summary)
        card.body.addWidget(rule())
        card.body.addWidget(caption(tr("Diagnostics")))
        self.diagnostics = QVBoxLayout()
        self.diagnostics.setSpacing(6)
        card.body.addLayout(self.diagnostics)
        self.install_button = QPushButton(tr("Install the GPU version of PyTorch (about 3 GB)"))
        self.install_button.setProperty("role", "accent")
        self.install_button.setIcon(icons.icon("download"))
        self.install_button.clicked.connect(self._install_gpu_torch)
        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 0)
        self.install_status = label("", "faint", wrap=True)
        for widget in (self.install_button, self.install_progress, self.install_status):
            widget.setVisible(False)
            card.body.addWidget(widget)
        return card

    def _show_hardware(self, hw: Hardware) -> None:
        lines = [hw.os_name, tr("Processor: {name} · {cores} cores / {threads} threads", name=hw.cpu_name,
                                cores=hw.cpu_cores, threads=hw.cpu_threads),
                 tr("Memory: {total:.1f} GB, {free:.1f} GB free", total=hw.ram_total_gb, free=hw.ram_free_gb)]
        for gpu in hw.gpus:
            vram = tr("{gb:.1f} GB of video memory", gb=gpu.vram_total_gb) if gpu.vram_total_gb else ""
            driver = tr("driver {version}", version=gpu.driver) if gpu.driver else ""
            extras = "".join(f" · {part}" for part in (vram, driver) if part)
            lines.append(tr("Graphics: {name}", name=gpu.name) + extras)
        if not hw.gpus:
            lines.append(tr("Graphics: none found"))
        torch = hw.torch
        if torch.installed:
            build = tr("with CUDA {version}", version=torch.cuda) if torch.has_cuda else tr("without CUDA")
            lines.append(f"PyTorch {torch.version} · {build}")
        else:
            lines.append(tr("PyTorch: not installed"))
        free = hardware.disk_free_gb(self.services.settings.models_path())
        lines.append(tr("Free space for models: {size}", size=size_text(free)))
        self.hw_summary.setText("\n".join(lines))

        while self.diagnostics.count():
            item = self.diagnostics.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        issues = hw.issues
        if not issues:
            fine = tr("No problems found. SnapReel uses this computer to the full.")
            self.diagnostics.addWidget(label(fine, "ok", wrap=True))
        for code in issues:
            severe = code in ("torch_missing", "torch_cpu_build", "gpu_unsupported")
            self.diagnostics.addWidget(label(issue_text(code, hw), "warn" if severe else "muted", wrap=True))
        cpu_build = "torch_cpu_build" in issues
        self.install_button.setVisible(cpu_build)
        if cpu_build and not can_install_gpu_torch():
            self.install_button.setEnabled(False)
            self.install_status.setVisible(True)
            self.install_status.setText(
                tr("Download the SnapReel build for NVIDIA graphics cards from the project page.")
                if paths.is_frozen() else
                tr("PyTorch is already loaded in this session. Restart SnapReel and press the button "
                   "before creating anything."))

    def _install_gpu_torch(self) -> None:
        if not can_install_gpu_torch() or self._install is not None:
            return
        command, extra_env = hardware.cuda_install_command()
        process = QProcess(self)
        environment = QProcessEnvironment.systemEnvironment()
        for key, value in extra_env.items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self._install_output(process))
        process.finished.connect(lambda code, _status: self._install_finished(code))
        self._install = process
        self.install_button.setEnabled(False)
        self.install_progress.setVisible(True)
        self.install_status.setVisible(True)
        self.install_status.setText(tr("Downloading and installing… This takes several minutes."))
        log.info("installing GPU PyTorch: %s", " ".join(command))
        process.start(command[0], command[1:])

    def _install_output(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardOutput().data()).decode("utf-8", "replace").strip()
        if text:
            log.info("pip: %s", text[-500:])
            self.install_status.setText(text.splitlines()[-1][:160])

    def _install_finished(self, code: int) -> None:
        self._install = None
        self.install_progress.setVisible(False)
        if code == 0:
            self.install_status.setText(tr("Installed. Restart SnapReel to use the graphics card."))
            self.install_status.setProperty("role", "ok")
            if self.toasts is not None:
                self.toasts.show(tr("The GPU version of PyTorch is installed. Restart SnapReel."), "ok",
                                 timeout_ms=0)
        else:
            self.install_button.setEnabled(True)
            self.install_status.setText(tr("Installation failed. Check the internet connection; details are "
                                           "in the log."))
            self.install_status.setProperty("role", "bad")
        self.install_status.style().polish(self.install_status)

    # ============================================================ folders
    def _build_folders(self) -> QWidget:
        card = Card(tr("Folders"))
        settings = self.services.settings
        self.output_value = self._folder_row(card, tr("Results"), str(settings.output_path()),
                                             lambda: self._change_folder("output"))
        self.models_value = self._folder_row(card, tr("Models"), str(settings.models_path()),
                                             lambda: self._change_folder("models"))
        self.folder_note = label("", "warn", wrap=True)
        self.folder_note.setVisible(False)
        card.body.addWidget(self.folder_note)
        self._folder_row(card, tr("Data and logs"), str(paths.data_dir()), None)
        return card

    def _folder_row(self, card: Card, title: str, path: str, change: object) -> QWidget:
        card.body.addWidget(caption(title))
        line = QHBoxLayout()
        line.setSpacing(6)
        value = label(path, "mono")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        line.addWidget(value, 1)
        if change is not None:
            edit = QPushButton(tr("Change…"))
            edit.setCursor(Qt.CursorShape.PointingHandCursor)
            edit.clicked.connect(change)
            line.addWidget(edit)
        button = QPushButton(tr("Open"))
        button.setIcon(icons.icon("folder"))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(value.text())))
        line.addWidget(button)
        card.body.addLayout(line)
        return value

    def _change_folder(self, which: str) -> None:
        settings = self.services.settings
        if which == "models" and (self.services.downloads.active_ids() or self.services.worker.current_job):
            if self.toasts is not None:
                self.toasts.show(tr("Wait until downloads and generation finish, then change the folder."),
                                 "warn")
            return
        current = settings.models_path() if which == "models" else settings.output_path()
        chosen = QFileDialog.getExistingDirectory(self, tr("Choose a folder"), str(current))
        if not chosen or Path(chosen) == current:
            return
        if not paths.is_writable(Path(chosen)):
            if self.toasts is not None:
                self.toasts.show(tr("SnapReel cannot write to this folder. Choose another one."), "bad")
            return
        if which == "models":
            settings.models_dir = chosen
            self.models_value.setText(chosen)
            self.services.worker.unload_model()
            self.folder_note.setText(tr("Models from the previous folder were not moved: {old}. Copy its "
                                        "contents here or download the models again.", old=str(current)))
            self.folder_note.setVisible(True)
            self.services.models_changed.emit()
        else:
            settings.output_dir = chosen
            self.output_value.setText(chosen)
        self._save()

    # ============================================================ formats
    def _build_formats(self) -> QWidget:
        card = Card(tr("Default file formats"))
        settings = self.services.settings
        self.image_format = Segmented([(f, f.upper()) for f in IMAGE_FORMATS])
        self.video_format = Segmented([(f, f.upper()) for f in VIDEO_FORMATS])
        self.audio_format = Segmented([(f, f.upper()) for f in AUDIO_FORMATS])
        self.image_format.set_value(settings.image_format)
        self.video_format.set_value(settings.video_format)
        self.audio_format.set_value(settings.audio_format)
        self.image_format.changed.connect(lambda v: self._set_format("image_format", v))
        self.video_format.changed.connect(lambda v: self._set_format("video_format", v))
        self.audio_format.changed.connect(lambda v: self._set_format("audio_format", v))
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Field(tr("Images"), self.image_format), 1)
        row.addWidget(Field(tr("Video"), self.video_format), 1)
        row.addWidget(Field(tr("Voice"), self.audio_format), 1)
        card.body.addLayout(row)
        hint = tr("PNG keeps the generation settings inside the file. MP4 plays everywhere; "
                  "WebM is smaller; GIF suits messengers. WAV is lossless, MP3 is compact.")
        card.body.addWidget(label(hint, "faint", wrap=True))
        return card

    def _set_format(self, key: str, value: str) -> None:
        setattr(self.services.settings, key, value)
        self._save()

    # ============================================================ catalog
    def _build_catalog(self) -> QWidget:
        card = Card(tr("Model catalog"))
        settings = self.services.settings
        self.catalog_url = QLineEdit(settings.catalog_url)
        self.catalog_url.setPlaceholderText(DEFAULT_CATALOG_URL)
        self.catalog_url.editingFinished.connect(self._catalog_url_changed)
        card.body.addWidget(Field(tr("Catalog address"), self.catalog_url,
                                  tr("A YAML list of models. Only Hugging Face repositories and trusted "
                                     "hosts are accepted from it; it never contains code.")))
        self.check_updates = QCheckBox(tr("Tell me when a new version of SnapReel is released"))
        self.check_updates.setChecked(settings.check_updates)
        self.check_updates.toggled.connect(self._check_updates_changed)
        card.body.addWidget(self.check_updates)
        self.auto_update = QCheckBox(tr("Check for new models when SnapReel starts"))
        self.auto_update.setChecked(settings.auto_update_catalog)
        self.auto_update.toggled.connect(self._auto_update_changed)
        row = QHBoxLayout()
        row.addWidget(self.auto_update, 1)
        self.update_now = QPushButton(tr("Update now"))
        self.update_now.setIcon(icons.icon("refresh"))
        self.update_now.clicked.connect(self._update_catalog)
        reset = QPushButton(tr("Default address"))
        reset.setProperty("role", "ghost")
        reset.clicked.connect(self._reset_catalog_url)
        row.addWidget(reset)
        row.addWidget(self.update_now)
        card.body.addLayout(row)
        self.catalog_status = label("", "faint", wrap=True)
        self.catalog_status.setVisible(False)
        card.body.addWidget(self.catalog_status)
        return card

    def _catalog_status_text(self, text: str) -> None:
        self.catalog_status.setText(text)
        self.catalog_status.setVisible(bool(text))

    def _catalog_url_changed(self) -> None:
        url = self.catalog_url.text().strip() or DEFAULT_CATALOG_URL
        if urlparse(url).scheme != "https":
            self._catalog_status_text(tr("The address must start with https://"))
            self.catalog_status.setProperty("role", "bad")
            self.catalog_status.style().polish(self.catalog_status)
            return
        self.services.settings.catalog_url = url
        self.catalog_url.setText(url)
        self._catalog_status_text("")
        self._save()

    def _reset_catalog_url(self) -> None:
        self.catalog_url.setText(DEFAULT_CATALOG_URL)
        self._catalog_url_changed()

    def _check_updates_changed(self, checked: bool) -> None:
        self.services.settings.check_updates = checked
        self._save()

    def _auto_update_changed(self, checked: bool) -> None:
        self.services.settings.auto_update_catalog = checked
        self._save()

    def _update_catalog(self) -> None:
        self._catalog_url_changed()
        url = self.services.settings.catalog_url
        self.update_now.setEnabled(False)
        self.catalog_status.setProperty("role", "faint")
        self._catalog_status_text(tr("Checking…"))
        run_async(lambda: self.services.catalog.update_from_url(url), self._catalog_updated,
                  self._catalog_failed)

    def _catalog_updated(self, count: int) -> None:
        self.update_now.setEnabled(True)
        self._catalog_status_text(tr("Catalog updated: {count} models.", count=count))
        self.catalog_status.setProperty("role", "ok")
        self.catalog_status.style().polish(self.catalog_status)
        self.services.models_changed.emit()

    def _catalog_failed(self, exc: Exception) -> None:
        self.update_now.setEnabled(True)
        self._catalog_status_text(tr("Could not update the catalog: {reason}", reason=str(exc)[:160]))
        self.catalog_status.setProperty("role", "bad")
        self.catalog_status.style().polish(self.catalog_status)

    # ============================================================ plugins
    def _build_plugins(self) -> QWidget:
        card = Card(tr("Plugins"))
        plugins = self.services.plugins
        if not plugins:
            empty = tr("No plugins. A plugin adds a new engine for models that SnapReel cannot run yet.")
            card.body.addWidget(label(empty, "muted", wrap=True))
        for info in plugins:
            if info.error:
                text = tr("{name}: not loaded — {reason}", name=info.name, reason=info.error)
                card.body.addWidget(label(text, "bad", wrap=True))
            else:
                text = tr("{name}: engines {engines}", name=info.name, engines=", ".join(info.engines))
                card.body.addWidget(label(text, "ok", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label(tr("Plugins are Python code: put only files you trust in this folder. Changes "
                               "apply after a restart."), "faint", wrap=True), 1)
        folder = QPushButton(tr("Plugins folder"))
        folder.setIcon(icons.icon("folder"))
        folder.clicked.connect(self._open_plugins)
        row.addWidget(folder)
        card.body.addLayout(row)
        return card

    @staticmethod
    def _open_plugins() -> None:
        target = plugins_dir()
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ============================================================ about
    def _build_about(self) -> QWidget:
        about = Card(tr("About"))
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(LogoMark(40))
        head.addWidget(label(f"SnapReel {__version__}", "title"), 1)
        about.body.addLayout(head)
        about.body.addWidget(label(tr("A free studio for images, video and voice made by AI models that run "
                                      "on your own computer."), "muted", wrap=True))
        about.body.addWidget(rule())
        author = QHBoxLayout()
        author.setSpacing(8)
        author.addWidget(label(tr("Author of the implementation:"), "muted"))
        author.addWidget(label(AUTHOR))
        author.addStretch(1)
        about.body.addLayout(author)
        links = QHBoxLayout()
        links.setSpacing(8)
        for text, url in ((tr("Author on GitHub"), AUTHOR_URL), (tr("Project page"), PROJECT_URL)):
            button = QPushButton(text)
            button.setIcon(icons.icon("link"))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(url)
            button.clicked.connect(lambda _c=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links.addWidget(button)
        welcome = QPushButton(tr("Welcome screen"))
        welcome.setIcon(icons.icon("info"))
        welcome.clicked.connect(self._open_welcome)
        links.addWidget(welcome)
        log_button = QPushButton(tr("Open log"))
        log_button.setIcon(icons.icon("info"))
        log_button.clicked.connect(self._open_log)
        links.addWidget(log_button)
        links.addStretch(1)
        about.body.addLayout(links)
        url_label = label(f'<a href="{AUTHOR_URL}">{AUTHOR_URL}</a>', "faint")
        url_label.setTextFormat(Qt.TextFormat.RichText)
        url_label.setOpenExternalLinks(True)
        about.body.addWidget(url_label)
        about.body.addWidget(label(tr("Model licenses are set by their authors; some allow only "
                                      "non-commercial use. The license is shown on each model's card."),
                                   "faint", wrap=True))
        return about

    # ============================================================ simple settings
    def _save(self) -> None:
        self.services.settings.save()

    def _language_changed(self, lang: str) -> None:
        self.services.settings.language = lang
        self._save()
        self._rebuild()

    def _theme_changed(self, theme_name: str) -> None:
        self.services.settings.theme = theme_name
        self._save()
        self._rebuild()

    def _rebuild(self) -> None:
        window = self.window()
        signal = getattr(window, "rebuild_requested", None)
        if signal is not None:
            signal.emit()

    def _mode_changed(self, _index: int) -> None:
        mode = self.mode.currentData()
        self.services.settings.performance_mode = mode
        self.mode_field.hint.setText(mode_text(mode)[1])
        self._save()
        self.services.models_changed.emit()  # pages re-evaluate the fit for the new mode

    def _keep_loaded_changed(self, checked: bool) -> None:
        self.services.settings.keep_model_loaded = checked
        self._save()

    def _token_changed(self) -> None:
        self.services.settings.hf_token = self.token.text().strip()
        self._save()

    def _open_welcome(self) -> None:
        window = self.window()
        page = getattr(window, "page", lambda _k: None)("welcome")
        if page is not None:
            window.open_page(window.pages.index(page))

    @staticmethod
    def _open_log() -> None:
        target = logging_setup.log_file()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target if target.exists() else target.parent)))
