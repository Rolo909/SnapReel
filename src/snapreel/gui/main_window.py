"""Main window for the SnapReel GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget

from snapreel.core.context import PipelineContext
from snapreel.core.orchestrator import PipelineOrchestrator
from snapreel.nodes import ScenarioNode, AudioNode, VisualStaticNode, VisualVideoNode, SubtitleNode, AssemblyNode

from snapreel.gui.widgets.pipeline_control import PipelineControl
from snapreel.gui.widgets.preview_player import PreviewPlayer
from snapreel.gui.widgets.progress_dashboard import ProgressDashboard
from snapreel.gui.widgets.project_wizard import ProjectWizard
from snapreel.gui.widgets.settings_panel import SettingsPanel
from snapreel.gui.widgets.log_viewer import LogViewer

from pathlib import Path
from typing import TYPE_CHECKING
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget, QVBoxLayout, QWidget, QMessageBox

if TYPE_CHECKING:
    from snapreel.core.config import AppConfig

class MainWindow(QMainWindow):
    """The main application window for SnapReel."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the main window."""
        super().__init__()
        self.config = config
        self.orchestrator: PipelineOrchestrator | None = None

        self.setWindowTitle("SnapReel")
        self.resize(1024, 768)

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self._setup_tabs()

    def _setup_tabs(self) -> None:
        """Create and add tabs to the main window."""
        self.wizard_tab = ProjectWizard()
        self.wizard_tab.generation_requested.connect(self._start_generation)

        self.pipeline_tab = QWidget()
        pipeline_layout = QVBoxLayout(self.pipeline_tab)

        self.progress_dashboard = ProgressDashboard()
        self.pipeline_control = PipelineControl()

        self.pipeline_control.stop_requested.connect(self._stop_generation)
        self.pipeline_control.start_requested.connect(
            lambda: self.tab_widget.setCurrentWidget(self.wizard_tab)
        )

        self.preview_player = PreviewPlayer()

        pipeline_layout.addWidget(self.progress_dashboard)
        pipeline_layout.addWidget(self.pipeline_control)
        pipeline_layout.addWidget(self.preview_player)
        pipeline_layout.addStretch()

        self.settings_tab = SettingsPanel()
        self.logs_tab = LogViewer()

        self.tab_widget.addTab(self.wizard_tab, "Project")
        self.tab_widget.addTab(self.pipeline_tab, "Pipeline")
        self.tab_widget.addTab(self.logs_tab, "Logs")
        self.tab_widget.addTab(self.settings_tab, "Settings")

    def _start_generation(self, user_config: dict) -> None:
        """Start the generation pipeline with the given config."""
        music_path = Path(user_config["music_path"]) if user_config.get("music_path") else None
        
        ctx = PipelineContext(
            topic=user_config["topic"],
            style=user_config["style"],
            voice=user_config["voice"],
            visual_mode=user_config["mode"],
            scene_count=user_config["scene_count"],
            music_path=music_path,
            work_dir=self.config.get_output_dir() / "work",
            output_dir=self.config.get_output_dir() / "final",
        )

        nodes = [
            ScenarioNode(config=self.config),
            AudioNode(),
        ]
        
        if ctx.visual_mode == "static":
            nodes.append(VisualStaticNode(config=self.config))
        else:
            nodes.append(VisualVideoNode(config=self.config))
            
        nodes.append(SubtitleNode(config=self.config))
        nodes.append(AssemblyNode(ffmpeg_path=self.config.ffmpeg_path))

        self.orchestrator = PipelineOrchestrator(context=ctx, nodes=nodes, parent=self)
        
        self.orchestrator.pipeline_started.connect(self._on_pipeline_started)
        self.orchestrator.pipeline_finished.connect(self._on_pipeline_finished)
        self.orchestrator.pipeline_failed.connect(self._on_pipeline_failed)
        self.orchestrator.pipeline_cancelled.connect(self._on_pipeline_cancelled)
        self.orchestrator.node_started.connect(self._on_node_started)
        self.orchestrator.node_progress.connect(self._on_node_progress)
        self.orchestrator.node_finished.connect(self._on_node_finished)

        self.tab_widget.setCurrentWidget(self.pipeline_tab)
        self.orchestrator.start()

    def _stop_generation(self) -> None:
        if self.orchestrator and self.orchestrator.isRunning():
            self.orchestrator.cancel()

    def _on_pipeline_started(self) -> None:
        self.pipeline_control.set_running_state(True)
        self.progress_dashboard.reset()

    def _on_pipeline_finished(self, ctx: PipelineContext) -> None:
        self.pipeline_control.set_running_state(False)
        if ctx.final_video_path and ctx.final_video_path.exists():
            self.preview_player.load_video(QUrl.fromLocalFile(str(ctx.final_video_path.absolute())))
            QMessageBox.information(self, "Success", "Video generation completed successfully!")
        
    def _on_pipeline_failed(self, error: str) -> None:
        self.pipeline_control.set_running_state(False)
        QMessageBox.critical(self, "Error", f"Pipeline failed:\n{error}")

    def _on_pipeline_cancelled(self) -> None:
        self.pipeline_control.set_running_state(False)
        QMessageBox.warning(self, "Cancelled", "Pipeline execution was cancelled.")

    def _on_node_started(self, index: int, name: str) -> None:
        simple_name = name.replace("Node", "")
        if simple_name in ("VisualStatic", "VisualVideo"):
            simple_name = "Visual"
        self.progress_dashboard.update_progress(simple_name, 0, "Running...")

    def _on_node_progress(self, index: int, percent: int, message: str) -> None:
        if self.orchestrator and index < len(self.orchestrator.nodes):
            name = self.orchestrator.nodes[index].name
            simple_name = name.replace("Node", "")
            if simple_name in ("VisualStatic", "VisualVideo"):
                simple_name = "Visual"
            self.progress_dashboard.update_progress(simple_name, percent, message)

    def _on_node_finished(self, index: int, name: str, result: object) -> None:
        simple_name = name.replace("Node", "")
        if simple_name in ("VisualStatic", "VisualVideo"):
            simple_name = "Visual"
        self.progress_dashboard.update_progress(simple_name, 100, "Done")
