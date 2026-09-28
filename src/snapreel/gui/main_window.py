"""Main window for the SnapReel GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from snapreel.gui.widgets.pipeline_control import PipelineControl
from snapreel.gui.widgets.preview_player import PreviewPlayer
from snapreel.gui.widgets.progress_dashboard import ProgressDashboard
from snapreel.gui.widgets.project_wizard import ProjectWizard
from snapreel.gui.widgets.settings_panel import SettingsPanel
from snapreel.gui.widgets.log_viewer import LogViewer


class MainWindow(QMainWindow):
    """The main application window for SnapReel."""

    def __init__(self) -> None:
        """Initialize the main window."""
        super().__init__()

        self.setWindowTitle("SnapReel")
        self.resize(1024, 768)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        # Setup tabs (placeholders for now)
        self._setup_tabs()

    def _setup_tabs(self) -> None:
        """Create and add tabs to the main window."""
        # Project Wizard Tab (D2)
        self.wizard_tab = ProjectWizard()
        # For now, just print the config when generation is requested
        self.wizard_tab.generation_requested.connect(
            lambda config: print(f"Generation requested with config: {config}")
        )

        # Pipeline Control Tab (D3)
        self.pipeline_tab = QWidget()
        pipeline_layout = QVBoxLayout(self.pipeline_tab)

        self.progress_dashboard = ProgressDashboard()
        self.pipeline_control = PipelineControl()

        # Connect start/stop buttons for demonstration
        self.pipeline_control.start_requested.connect(
            lambda: [self.pipeline_control.set_running_state(True), print("Pipeline started")]
        )
        self.pipeline_control.stop_requested.connect(
            lambda: [self.pipeline_control.set_running_state(False), print("Pipeline stopped")]
        )

        self.preview_player = PreviewPlayer()

        pipeline_layout.addWidget(self.progress_dashboard)
        pipeline_layout.addWidget(self.pipeline_control)
        pipeline_layout.addWidget(self.preview_player)
        pipeline_layout.addStretch()

        # Settings Tab (D4)
        self.settings_tab = SettingsPanel()

        # Logs Tab (D6)
        self.logs_tab = LogViewer()

        self.tab_widget.addTab(self.wizard_tab, "Project")
        self.tab_widget.addTab(self.pipeline_tab, "Pipeline")
        self.tab_widget.addTab(self.logs_tab, "Logs")
        self.tab_widget.addTab(self.settings_tab, "Settings")
