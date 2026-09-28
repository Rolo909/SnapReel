"""Project Wizard widget for SnapReel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class ProjectWizard(QWidget):
    """Wizard for configuring a new video generation project."""

    # Emitted when the user is ready to generate
    generation_requested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the project wizard."""
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Title
        title_label = QLabel("New Project")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(title_label)

        # Config Group
        config_group = QGroupBox("Project Settings")
        form_layout = QFormLayout(config_group)
        form_layout.setSpacing(12)

        # 1. Topic input
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText(
            "e.g. History of the Roman Empire, 10 facts about space..."
        )
        form_layout.addRow("Topic:", self.topic_input)

        # 2. Style selector
        self.style_selector = QComboBox()
        self.style_selector.addItems(
            [
                "Cinematic",
                "Anime / Manga",
                "Documentary / Realistic",
                "Cyberpunk",
                "Cartoon / 3D Animation",
            ]
        )
        form_layout.addRow("Visual Style:", self.style_selector)

        # 3. Voice picker
        self.voice_picker = QComboBox()
        self.voice_picker.addItems(
            [
                "en-US-ChristopherNeural (Male)",
                "en-US-AriaNeural (Female)",
                "ru-RU-DmitryNeural (Male)",
                "ru-RU-SvetlanaNeural (Female)",
            ]
        )
        form_layout.addRow("Voice:", self.voice_picker)

        # 4. Visual mode toggle
        mode_layout = QHBoxLayout()
        self.mode_static = QRadioButton("Static (Ken Burns)")
        self.mode_video = QRadioButton("Video (AI Generated)")
        self.mode_static.setChecked(True)
        mode_layout.addWidget(self.mode_static)
        mode_layout.addWidget(self.mode_video)
        mode_layout.addStretch()
        form_layout.addRow("Visual Mode:", mode_layout)

        # 5. Scene count
        self.scene_count = QSpinBox()
        self.scene_count.setRange(3, 15)
        self.scene_count.setValue(5)
        form_layout.addRow("Scene Count:", self.scene_count)

        # 6. Music file browser
        music_layout = QHBoxLayout()
        self.music_path = QLineEdit()
        self.music_path.setPlaceholderText("Select background music...")
        self.music_path.setReadOnly(True)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_music)
        music_layout.addWidget(self.music_path)
        music_layout.addWidget(self.browse_button)
        form_layout.addRow("Background Music:", music_layout)

        layout.addWidget(config_group)
        layout.addStretch()

        # Generate Button
        self.generate_button = QPushButton("Generate Video")
        self.generate_button.setStyleSheet("font-size: 16px; padding: 12px;")
        self.generate_button.clicked.connect(self._on_generate_clicked)
        layout.addWidget(self.generate_button)

    def _browse_music(self) -> None:
        """Open a file dialog to select background music."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Background Music",
            "",
            "Audio Files (*.mp3 *.wav *.aac);;All Files (*)",
        )
        if file_path:
            self.music_path.setText(file_path)

    def _on_generate_clicked(self) -> None:
        """Collect config and emit the generate signal."""
        config = {
            "topic": self.topic_input.text(),
            "style": self.style_selector.currentText(),
            "voice": self.voice_picker.currentText(),
            "mode": "static" if self.mode_static.isChecked() else "video",
            "scene_count": self.scene_count.value(),
            "music_path": self.music_path.text(),
        }
        self.generation_requested.emit(config)
