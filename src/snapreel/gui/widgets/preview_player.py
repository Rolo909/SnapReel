"""Preview player widget for playing generated videos."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class PreviewPlayer(QWidget):
    """Widget containing a video player for previewing generated videos."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the preview player."""
        super().__init__(parent)
        self._setup_ui()
        self._setup_player()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Video Widget
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(320, 180)

        # Controls
        controls_layout = QHBoxLayout()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self._toggle_playback)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self._set_position)

        controls_layout.addWidget(self.play_button)
        controls_layout.addWidget(self.position_slider)

        layout.addWidget(self.video_widget)
        layout.addLayout(controls_layout)

    def _setup_player(self) -> None:
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()

        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._update_buttons)

    def load_video(self, file_path: str | Path) -> None:
        """Load a video file into the player.

        Args:
            file_path: Path to the .mp4 file.
        """
        path = Path(file_path).resolve()
        if path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.play_button.setText("Play")

    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _update_buttons(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("Pause")
        else:
            self.play_button.setText("Play")

    def _position_changed(self, position: int) -> None:
        self.position_slider.setValue(position)

    def _duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, duration)

    def _set_position(self, position: int) -> None:
        self.player.setPosition(position)
