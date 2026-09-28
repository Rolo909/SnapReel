"""Unit tests for GUI components using pytest-qt."""
# ruff: noqa: ANN401

import json
import logging
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt

from snapreel.gui.widgets.pipeline_control import PipelineControl
from snapreel.gui.widgets.preview_player import PreviewPlayer
from snapreel.gui.widgets.progress_dashboard import ProgressDashboard
from snapreel.gui.widgets.project_wizard import ProjectWizard
from snapreel.gui.widgets.settings_panel import SettingsPanel
from snapreel.gui.widgets.log_viewer import LogViewer

# Requires pytest-qt to be installed
pytestmark = pytest.mark.usefixtures("qapp")


def test_project_wizard_initial_state(qtbot: Any) -> None:
    """Test the initial state of the ProjectWizard widget."""
    widget = ProjectWizard()
    qtbot.addWidget(widget)

    assert widget.topic_input.text() == ""
    assert widget.style_selector.count() > 0
    assert widget.voice_picker.count() > 0
    assert widget.mode_static.isChecked() is True
    assert widget.mode_video.isChecked() is False
    assert widget.scene_count.value() == 5
    assert widget.music_path.text() == ""


def test_project_wizard_generate_signal(qtbot: Any) -> None:
    """Test that clicking generate emits the correct config signal."""
    widget = ProjectWizard()
    qtbot.addWidget(widget)

    # Set some values
    widget.topic_input.setText("Test Topic")
    widget.scene_count.setValue(10)
    widget.mode_video.setChecked(True)

    with qtbot.waitSignal(widget.generation_requested, timeout=1000) as blocker:
        qtbot.mouseClick(widget.generate_button, Qt.MouseButton.LeftButton)

    config = blocker.args[0]
    assert config["topic"] == "Test Topic"
    assert config["scene_count"] == 10
    assert config["mode"] == "video"


def test_pipeline_control(qtbot: Any) -> None:
    """Test start/stop button states."""
    widget = PipelineControl()
    qtbot.addWidget(widget)

    assert widget.start_button.isEnabled() is True
    assert widget.stop_button.isEnabled() is False

    with qtbot.waitSignal(widget.start_requested, timeout=1000):
        qtbot.mouseClick(widget.start_button, Qt.MouseButton.LeftButton)

    widget.set_running_state(True)
    assert widget.start_button.isEnabled() is False
    assert widget.stop_button.isEnabled() is True

    with qtbot.waitSignal(widget.stop_requested, timeout=1000):
        qtbot.mouseClick(widget.stop_button, Qt.MouseButton.LeftButton)


def test_progress_dashboard(qtbot: Any) -> None:
    """Test updating progress dashboard."""
    widget = ProgressDashboard()
    qtbot.addWidget(widget)

    # Initial state
    assert widget._progress_bars["scenario"].value() == 0
    assert widget._status_labels["scenario"].text() == "Pending"

    # Update
    widget.update_progress("scenario", 50, "Generating...")
    assert widget._progress_bars["scenario"].value() == 50
    assert widget._status_labels["scenario"].text() == "Generating..."

    # Reset
    widget.reset()
    assert widget._progress_bars["scenario"].value() == 0
    assert widget._status_labels["scenario"].text() == "Pending"


def test_settings_panel(qtbot: Any, tmp_path: Any) -> None:
    """Test saving and loading settings."""
    widget = SettingsPanel()
    widget.settings_file = tmp_path / "settings.json"
    qtbot.addWidget(widget)

    # Change settings
    widget.output_dir_input.setText("/custom/output")
    widget.language_selector.setCurrentIndex(1)  # RU
    widget.override_selector.setCurrentIndex(1)  # High

    # Save
    with patch("snapreel.gui.widgets.settings_panel.QMessageBox.information"):
        widget._save_settings()

    # Verify disk
    assert widget.settings_file.exists()
    with open(widget.settings_file, encoding="utf-8") as f:
        data = json.load(f)
        assert data["output_dir"] == "/custom/output"
        assert data["language"] == "ru"
        assert data["execution_override"] == "High"

    # Test loading
    widget2 = SettingsPanel()
    widget2.settings_file = widget.settings_file
    widget2._load_settings()

    assert widget2.output_dir_input.text() == "/custom/output"
    assert widget2.language_selector.currentIndex() == 1
    assert widget2.override_selector.currentText() == "High"


def test_preview_player(qtbot: Any, tmp_path: Any) -> None:
    """Test preview player loads files."""
    widget = PreviewPlayer()
    qtbot.addWidget(widget)

    assert widget.play_button.text() == "Play"

    # Create dummy file
    dummy_video = tmp_path / "test.mp4"
    dummy_video.touch()

    widget.load_video(dummy_video)

    assert widget.play_button.text() == "Play"


import logging
def test_log_viewer(qtbot: Any) -> None:
    """Test log viewer captures python logs."""
    widget = LogViewer()
    qtbot.addWidget(widget)

    logger = logging.getLogger("test_logger")

    with qtbot.waitSignal(widget.handler.emitter.new_log, timeout=1000):
        logger.warning("This is a test warning.")

    text = widget.text_edit.toPlainText()
    assert "This is a test warning." in text
