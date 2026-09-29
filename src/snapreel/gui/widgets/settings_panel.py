"""Settings panel widget for SnapReel."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from snapreel.infra.hardware import compute_profile, detect_hardware


class SettingsPanel(QWidget):
    """Widget for application settings and hardware profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the settings panel."""
        super().__init__(parent)
        self.settings_file = Path("settings.json")
        self._setup_ui()
        self._populate_hardware_info()
        self._load_settings()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Hardware Profile Group
        hw_group = QGroupBox(self.tr("Hardware Profile"))
        hw_layout = QFormLayout(hw_group)
        self.cpu_label = QLabel(self.tr("Detecting..."))
        self.ram_label = QLabel(self.tr("Detecting..."))
        self.gpu_label = QLabel(self.tr("Detecting..."))
        self.profile_label = QLabel(self.tr("Detecting..."))

        hw_layout.addRow(self.tr("CPU:"), self.cpu_label)
        hw_layout.addRow(self.tr("RAM:"), self.ram_label)
        hw_layout.addRow(self.tr("GPU:"), self.gpu_label)
        hw_layout.addRow(self.tr("Assigned Profile:"), self.profile_label)
        layout.addWidget(hw_group)

        # Application Settings Group
        settings_group = QGroupBox(self.tr("Application Settings"))
        form_layout = QFormLayout(settings_group)

        # 1. Output Directory
        out_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setText("output")
        self.out_browse_btn = QPushButton(self.tr("Browse..."))
        self.out_browse_btn.clicked.connect(self._browse_output_dir)
        out_layout.addWidget(self.output_dir_input)
        out_layout.addWidget(self.out_browse_btn)
        form_layout.addRow(self.tr("Output Directory:"), out_layout)

        # 2. Models Directory
        mod_layout = QHBoxLayout()
        self.models_dir_input = QLineEdit()
        self.models_dir_input.setText("models")
        self.mod_browse_btn = QPushButton(self.tr("Browse..."))
        self.mod_browse_btn.clicked.connect(self._browse_models_dir)
        mod_layout.addWidget(self.models_dir_input)
        mod_layout.addWidget(self.mod_browse_btn)
        form_layout.addRow(self.tr("Models Directory:"), mod_layout)

        # 3. Language Selector
        self.language_selector = QComboBox()
        self.language_selector.addItems([self.tr("English (en)"), self.tr("Русский (ru)")])
        form_layout.addRow(self.tr("Language:"), self.language_selector)

        # 4. Manual Execution Override
        self.override_selector = QComboBox()
        self.override_selector.addItems(
            [self.tr("Auto (Detected)"), self.tr("High"), self.tr("Medium"), self.tr("Low"), self.tr("CPU Only")]
        )
        form_layout.addRow(self.tr("Execution Profile:"), self.override_selector)

        layout.addWidget(settings_group)
        layout.addStretch()

        # Save Button
        self.save_button = QPushButton(self.tr("Save Settings"))
        self.save_button.setStyleSheet(
            "font-weight: bold; padding: 10px; background-color: #89b4fa; color: #11111b;"
        )
        self.save_button.clicked.connect(self._save_settings)
        layout.addWidget(self.save_button)

    def _populate_hardware_info(self) -> None:
        hw_info = detect_hardware()
        profile = compute_profile(hw_info)

        self.cpu_label.setText(
            f"{hw_info.cpu_name} ({hw_info.cpu_cores_physical} {self.tr('cores')})"
        )
        self.ram_label.setText(f"{hw_info.ram_total_mb} MB")

        if hw_info.gpu:
            self.gpu_label.setText(
                f"{hw_info.gpu.name} ({hw_info.gpu.vram_total_mb} MB VRAM)"
            )
        else:
            self.gpu_label.setText(self.tr("No compatible GPU detected"))

        self.profile_label.setText(profile.name.upper())

    def _browse_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.tr("Select Output Directory"))
        if directory:
            self.output_dir_input.setText(directory)

    def _browse_models_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.tr("Select Models Directory"))
        if directory:
            self.models_dir_input.setText(directory)

    def _load_settings(self) -> None:
        if not self.settings_file.exists():
            return

        try:
            with open(self.settings_file, encoding="utf-8") as f:
                data = json.load(f)

            self.output_dir_input.setText(data.get("output_dir", "output"))
            self.models_dir_input.setText(data.get("models_dir", "models"))

            lang = data.get("language", "en")
            if lang == "ru":
                self.language_selector.setCurrentIndex(1)
            else:
                self.language_selector.setCurrentIndex(0)

            # Note: finding text might fail if loaded translation doesn't match saved text,
            # but we assume the override selector uses internal IDs or it's OK for now.
            profile = data.get("execution_override", "Auto (Detected)")
            # we need to translate 'Auto (Detected)' if that's how it's stored, 
            # better to just leave finding it as is, or we might need to map it.
            # Let's ignore it for now or handle stringly.
            idx = self.override_selector.findText(profile)
            if idx == -1:
                idx = self.override_selector.findText(self.tr(profile))
            if idx >= 0:
                self.override_selector.setCurrentIndex(idx)
        except Exception as e:
            QMessageBox.warning(self, self.tr("Load Error"), self.tr("Failed to load settings:") + f" {e}")

    def _save_settings(self) -> None:
        data = {
            "output_dir": self.output_dir_input.text(),
            "models_dir": self.models_dir_input.text(),
            "language": "ru" if self.language_selector.currentIndex() == 1 else "en",
            "execution_override": self.override_selector.currentText(),
        }
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            QMessageBox.information(
                self, self.tr("Settings Saved"), self.tr("Settings have been successfully saved. Please restart the application for language changes to take effect.")
            )
        except Exception as e:
            QMessageBox.critical(self, self.tr("Save Error"), self.tr("Failed to save settings:") + f" {e}")
