"""Platform-aware path resolution utilities."""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_dir() -> Path:
    """Get the application's root directory.

    In development, this is the project root (where pyproject.toml lives).
    When packaged with PyInstaller/Nuitka, this is the directory containing
    the executable.

    Returns:
        Absolute path to the application directory.
    """
    if getattr(sys, "frozen", False):
        # Running as a packaged executable
        return Path(sys.executable).parent
    # Running in development
    return Path(__file__).resolve().parent.parent.parent.parent


def get_models_dir() -> Path:
    """Get the default models directory.

    Returns:
        Path to the models directory.
    """
    return get_app_dir() / "models"


def get_assets_dir() -> Path:
    """Get the assets directory.

    Returns:
        Path to the assets directory.
    """
    return get_app_dir() / "assets"


def get_output_dir() -> Path:
    """Get the default output directory.

    Returns:
        Path to the output directory.
    """
    d = get_app_dir() / "output"
    d.mkdir(exist_ok=True)
    return d


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure.

    Returns:
        The same path (for chaining).
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
