"""Filesystem locations used by the application."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "Tvorka"


def is_frozen() -> bool:
    """True when running from a packaged executable (PyInstaller / Nuitka)."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def package_dir() -> Path:
    """Directory of the ``tvorka`` package (bundled data lives here)."""
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Directory the app lives in: the release folder, the exe folder, or the repo root in dev.

    The release launcher passes ``--home <folder>`` (stored in ``TVORKA_HOME``) so models
    and results sit next to "Tvorka.cmd", not inside the internal ``app`` folder.
    """
    home = os.environ.get("TVORKA_HOME")
    if home:
        return Path(home)
    if is_frozen():
        return Path(sys.executable).resolve().parent
    root = package_dir().parent.parent
    return root if (root / "pyproject.toml").exists() else package_dir()


def data_base() -> Path:
    """Where the per-user directory is (it may not exist yet)."""
    override = os.environ.get("TVORKA_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


def data_dir() -> Path:
    """Per-user directory for settings, history, caches and logs."""
    base = data_base()
    base.mkdir(parents=True, exist_ok=True)
    return base


def is_writable(path: Path) -> bool:
    """Check that files can actually be created inside ``path``."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path):
            pass
        return True
    except OSError:
        return False


def default_models_dir() -> Path:
    """Models live next to the app when possible (portable), else in the user data dir."""
    local = app_dir() / "models"
    return local if is_writable(local) else data_dir() / "models"


def default_output_dir() -> Path:
    local = app_dir() / "output"
    if is_writable(local):
        return local
    return Path.home() / "Documents" / APP_NAME


def assets_dir() -> Path:
    for candidate in (package_dir() / "assets", app_dir() / "assets"):
        if candidate.exists():
            return candidate
    return package_dir() / "assets"
