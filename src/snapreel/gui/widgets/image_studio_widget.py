"""Image Studio widget for standalone image generation."""

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QProgressBar, QFileDialog, QMessageBox, QComboBox, QSpinBox, QGroupBox,
    QFormLayout
)

from snapreel.core.image_studio import ImageStudioOrchestrator
from snapreel.engines.diffusers_engine import DiffusersEngine
from snapreel.engines.base import ModelRegistry
from snapreel.infra.hardware import detect_hardware, compute_profile


class DropZoneLabel(QLabel):
    """A QLabel that accepts image drops."""

    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; background: #2b2b36; color: #aaa; }"
            "QLabel:hover { border-color: #89b4fa; color: #89b4fa; }"
        )
        self.setAcceptDrops(True)
        self.setMinimumSize(QSize(200, 200))
        self.image_path: Optional[Path] = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                ext = Path(urls[0].toLocalFile()).suffix.lower()
                if ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            path = Path(urls[0].toLocalFile())
            self.set_image(path)
            event.acceptProposedAction()

    def set_image(self, path: Path) -> None:
        self.image_path = path
        pixmap = QPixmap(str(path))
        self.setPixmap(pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.setStyleSheet("QLabel { border: 2px solid #89b4fa; border-radius: 8px; background: #2b2b36; }")

    def clear_image(self) -> None:
        self.image_path = None
        self.clear()
        self.setText(self.tr("Drag & Drop\nReference Image Here"))
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; background: #2b2b36; color: #aaa; }"
            "QLabel:hover { border-color: #89b4fa; color: #89b4fa; }"
        )


class ImageStudioWidget(QWidget):
    """Widget for the Image Studio tab."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.orchestrator: Optional[ImageStudioOrchestrator] = None
        self.current_result_path: Optional[Path] = None
        
        self.registry = ModelRegistry()
        self.image_models = self.registry.list_models(model_type="image")
        
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        
        # Left Panel: Controls
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Settings Group
        settings_group = QGroupBox(self.tr("Generation Settings"))
        form_layout = QFormLayout(settings_group)
        
        self.model_combo = QComboBox()
        for model in self.image_models:
            self.model_combo.addItem(f"{model.name} ({model.engine})", userData=model.id)
            
        form_layout.addRow(self.tr("Model:"), self.model_combo)
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(256, 4096)
        self.width_spin.setSingleStep(64)
        self.width_spin.setValue(1024)
        
        self.height_spin = QSpinBox()
        self.height_spin.setRange(256, 4096)
        self.height_spin.setSingleStep(64)
        self.height_spin.setValue(1024)
        
        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 150)
        self.steps_spin.setValue(20)
        
        size_layout = QHBoxLayout()
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(QLabel("x"))
        size_layout.addWidget(self.height_spin)
        
        form_layout.addRow(self.tr("Resolution:"), size_layout)
        form_layout.addRow(self.tr("Steps:"), self.steps_spin)
        
        left_layout.addWidget(settings_group)
        
        # Prompts
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(self.tr("Enter positive prompt here..."))
        self.prompt_edit.setMaximumHeight(100)
        left_layout.addWidget(QLabel(self.tr("Prompt:")))
        left_layout.addWidget(self.prompt_edit)
        
        self.neg_prompt_edit = QTextEdit()
        self.neg_prompt_edit.setPlaceholderText(self.tr("Enter negative prompt here..."))
        self.neg_prompt_edit.setMaximumHeight(60)
        left_layout.addWidget(QLabel(self.tr("Negative Prompt:")))
        left_layout.addWidget(self.neg_prompt_edit)
        
        # Reference Image Drop Zone
        left_layout.addWidget(QLabel(self.tr("Reference Image (Optional):")))
        self.drop_zone = DropZoneLabel(self.tr("Drag & Drop\nReference Image Here"))
        left_layout.addWidget(self.drop_zone)
        
        clear_btn = QPushButton(self.tr("Clear Reference Image"))
        clear_btn.clicked.connect(self.drop_zone.clear_image)
        left_layout.addWidget(clear_btn)
        
        left_layout.addStretch()
        
        # Actions
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        
        self.status_label = QLabel(self.tr("Ready."))
        left_layout.addWidget(self.status_label)
        
        self.generate_btn = QPushButton(self.tr("Generate"))
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 12px; background-color: #a6e3a1; color: #11111b;")
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        left_layout.addWidget(self.generate_btn)
        
        main_layout.addWidget(left_panel, stretch=1)
        
        # Right Panel: Result Viewer
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.result_viewer = QLabel(self.tr("No image generated yet."))
        self.result_viewer.setAlignment(Qt.AlignCenter)
        self.result_viewer.setStyleSheet("background: #1e1e2e; border: 1px solid #45475a; border-radius: 8px;")
        self.result_viewer.setMinimumSize(512, 512)
        right_layout.addWidget(self.result_viewer, stretch=1)
        
        self.export_btn = QPushButton(self.tr("Export with Metadata"))
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export_clicked)
        right_layout.addWidget(self.export_btn)
        
        main_layout.addWidget(right_panel, stretch=2)

    def _on_generate_clicked(self) -> None:
        if self.orchestrator and self.orchestrator.isRunning():
            self.orchestrator.cancel()
            self.generate_btn.setText(self.tr("Generate"))
            self.generate_btn.setStyleSheet("font-weight: bold; padding: 12px; background-color: #a6e3a1; color: #11111b;")
            return

        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, self.tr("Input Error"), self.tr("Please enter a prompt."))
            return
            
        model_id = self.model_combo.currentData()
        model_config = self.registry.get_model(model_id)
        if not model_config:
            QMessageBox.critical(self, self.tr("Error"), self.tr("Selected model configuration not found."))
            return

        hw_info = detect_hardware()
        profile = compute_profile(hw_info)
        
        if model_config.engine != "diffusers":
            QMessageBox.warning(self, self.tr("Unsupported"), self.tr("Only 'diffusers' engine is supported in this UI for now."))
            return
            
        engine = DiffusersEngine(profile, model_config)
        
        self.orchestrator = ImageStudioOrchestrator(
            engine=engine,
            prompt=prompt,
            negative_prompt=self.neg_prompt_edit.toPlainText().strip(),
            width=self.width_spin.value(),
            height=self.height_spin.value(),
            steps=self.steps_spin.value(),
            reference_image=self.drop_zone.image_path,
            parent=self
        )
        
        self.orchestrator.generation_started.connect(self._on_generation_started)
        self.orchestrator.generation_progress.connect(self._on_generation_progress)
        self.orchestrator.generation_finished.connect(self._on_generation_finished)
        self.orchestrator.generation_failed.connect(self._on_generation_failed)
        self.orchestrator.generation_cancelled.connect(self._on_generation_cancelled)
        
        self.orchestrator.start()

    def _on_generation_started(self) -> None:
        self.generate_btn.setText(self.tr("Cancel"))
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 12px; background-color: #f38ba8; color: #11111b;")
        self.progress_bar.setValue(0)
        self.status_label.setText(self.tr("Starting..."))
        self.export_btn.setEnabled(False)

    def _on_generation_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_generation_finished(self, out_path: Path) -> None:
        self.current_result_path = out_path
        self._reset_button()
        self.status_label.setText(self.tr("Finished."))
        self.progress_bar.setValue(100)
        
        pixmap = QPixmap(str(out_path))
        self.result_viewer.setPixmap(pixmap.scaled(
            self.result_viewer.size(), 
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        ))
        self.export_btn.setEnabled(True)

    def _on_generation_failed(self, error: str) -> None:
        self._reset_button()
        self.status_label.setText(self.tr("Failed."))
        QMessageBox.critical(self, self.tr("Generation Failed"), error)

    def _on_generation_cancelled(self) -> None:
        self._reset_button()
        self.status_label.setText(self.tr("Cancelled."))

    def _reset_button(self) -> None:
        self.generate_btn.setText(self.tr("Generate"))
        self.generate_btn.setStyleSheet("font-weight: bold; padding: 12px; background-color: #a6e3a1; color: #11111b;")
        
    def _on_export_clicked(self) -> None:
        if not self.current_result_path or not self.current_result_path.exists():
            return
            
        save_path, _ = QFileDialog.getSaveFileName(
            self, 
            self.tr("Export Image"), 
            f"exported_{self.current_result_path.name}",
            self.tr("Images (*.png *.jpg *.webp)")
        )
        
        if save_path:
            import shutil
            shutil.copy2(self.current_result_path, save_path)
            
            meta_path = Path(save_path).with_suffix(".json")
            metadata = {
                "prompt": self.prompt_edit.toPlainText().strip(),
                "negative_prompt": self.neg_prompt_edit.toPlainText().strip(),
                "width": self.width_spin.value(),
                "height": self.height_spin.value(),
                "steps": self.steps_spin.value(),
                "model": self.model_combo.currentText(),
                "reference_image": str(self.drop_zone.image_path) if self.drop_zone.image_path else None
            }
            
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4)
                
            QMessageBox.information(self, self.tr("Export Successful"), self.tr("Image and metadata exported successfully."))
            
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.current_result_path and self.current_result_path.exists():
            pixmap = QPixmap(str(self.current_result_path))
            self.result_viewer.setPixmap(pixmap.scaled(
                self.result_viewer.size(), 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            ))
