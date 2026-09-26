"""Shared test fixtures for SnapReel."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory structure for tests."""
    (tmp_path / "models" / "llm").mkdir(parents=True)
    (tmp_path / "models" / "whisper").mkdir(parents=True)
    (tmp_path / "models" / "diffusion").mkdir(parents=True)
    (tmp_path / "output").mkdir()
    (tmp_path / "work").mkdir()
    return tmp_path
