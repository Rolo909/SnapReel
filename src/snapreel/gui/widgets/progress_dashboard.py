"""Progress dashboard widget for SnapReel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class ProgressDashboard(QWidget):
    """Widget displaying progress for each pipeline node."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the progress dashboard."""
        super().__init__(parent)
        self._progress_bars: dict[str, QProgressBar] = {}
        self._status_labels: dict[str, QLabel] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.group_box = QGroupBox("Pipeline Progress")
        form_layout = QFormLayout(self.group_box)
        form_layout.setSpacing(12)

        nodes = ["Scenario", "Audio", "Visual", "Subtitle", "Assembly"]

        for node in nodes:
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setTextVisible(True)

            status_label = QLabel("Pending")
            status_label.setStyleSheet("color: #a6adc8;")

            # Combine progress bar and status label
            node_layout = QVBoxLayout()
            node_layout.addWidget(progress_bar)
            node_layout.addWidget(status_label)

            # Add to form layout
            form_layout.addRow(f"{node}:", node_layout)

            self._progress_bars[node.lower()] = progress_bar
            self._status_labels[node.lower()] = status_label

        layout.addWidget(self.group_box)
        layout.addStretch()

    def update_progress(self, node: str, value: int, status: str = "") -> None:
        """Update the progress bar and status for a specific node."""
        node_key = node.lower()
        if node_key in self._progress_bars:
            self._progress_bars[node_key].setValue(value)
            if status:
                self._status_labels[node_key].setText(status)
                if value >= 100:
                    self._status_labels[node_key].setStyleSheet("color: #a6e3a1;")  # Green
                else:
                    self._status_labels[node_key].setStyleSheet("color: #89b4fa;")  # Blue

    def reset(self) -> None:
        """Reset all progress bars to 0 and status to Pending."""
        for key in self._progress_bars:
            self._progress_bars[key].setValue(0)
            self._status_labels[key].setText("Pending")
            self._status_labels[key].setStyleSheet("color: #a6adc8;")
