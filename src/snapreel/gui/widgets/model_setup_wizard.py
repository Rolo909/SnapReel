"""Model setup wizard for first-launch downloads."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QMessageBox,
    QHBoxLayout,
)

from snapreel.infra.downloader import ModelDownloader, MODEL_REGISTRY


class DownloadWorker(QThread):
    """Worker thread for downloading models."""

    model_started = Signal(str, str) # key, name
    model_finished = Signal(str) # key
    all_finished = Signal()
    error = Signal(str)

    def __init__(self, downloader: ModelDownloader, missing_models: list[str], parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.missing_models = missing_models

    def run(self):
        try:
            for key in self.missing_models:
                spec = MODEL_REGISTRY.get(key)
                if not spec:
                    continue
                self.model_started.emit(key, spec.name)
                self.downloader.download_model(key)
                self.model_finished.emit(key)
            self.all_finished.emit()
        except Exception as e:
            self.error.emit(str(e))


class ModelSetupWizard(QDialog):
    """Dialog that shows up on first launch to download missing models."""

    def __init__(self, downloader: ModelDownloader, missing_models: list[str], parent=None):
        super().__init__(parent)
        self.downloader = downloader
        self.missing_models = missing_models
        self._progress_bars: dict[str, QProgressBar] = {}
        self._status_labels: dict[str, QLabel] = {}

        self.setWindowTitle(self.tr("SnapReel - Initial Setup"))
        self.resize(600, 400)
        self.setModal(True)
        # Prevent closing by 'X' or Escape while downloading
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        
        self._setup_ui()
        self._start_downloads()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        title = QLabel(self.tr("Downloading Required Models"))
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        desc = QLabel(self.tr("This is your first launch (or models are missing). We need to download AI models before you can generate videos. This may take a while depending on your internet connection."))
        desc.setWordWrap(True)
        layout.addWidget(desc)
        layout.addSpacing(20)

        for key in self.missing_models:
            spec = MODEL_REGISTRY.get(key)
            if not spec:
                continue
                
            h_layout = QHBoxLayout()
            name_label = QLabel(f"{spec.name} (~{spec.size_gb} GB)")
            name_label.setMinimumWidth(250)
            
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setValue(0)
            
            status = QLabel(self.tr("Pending"))
            status.setMinimumWidth(100)
            
            h_layout.addWidget(name_label)
            h_layout.addWidget(progress)
            h_layout.addWidget(status)
            
            layout.addLayout(h_layout)
            
            self._progress_bars[key] = progress
            self._status_labels[key] = status
            
        layout.addStretch()
        
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignRight)

    def _start_downloads(self):
        self.worker = DownloadWorker(self.downloader, self.missing_models, self)
        self.worker.model_started.connect(self._on_model_started)
        self.worker.model_finished.connect(self._on_model_finished)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_model_started(self, key: str, name: str):
        if key in self._progress_bars:
            self._progress_bars[key].setRange(0, 0) # Indeterminate
            self._status_labels[key].setText(self.tr("Downloading..."))
            self._status_labels[key].setStyleSheet("color: #89b4fa;")

    def _on_model_finished(self, key: str):
        if key in self._progress_bars:
            self._progress_bars[key].setRange(0, 100)
            self._progress_bars[key].setValue(100)
            self._status_labels[key].setText(self.tr("Done"))
            self._status_labels[key].setStyleSheet("color: #a6e3a1;")

    def _on_all_finished(self):
        QMessageBox.information(self, self.tr("Success"), self.tr("All models downloaded successfully!"))
        self.accept()

    def _on_error(self, error: str):
        QMessageBox.critical(self, self.tr("Download Error"), self.tr("An error occurred while downloading models:\n") + f"{error}")
        self.reject()
        
    def closeEvent(self, event):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        super().closeEvent(event)
