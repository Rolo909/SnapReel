"""Tvorka was called SnapReel up to version 1.0: carry its data over on the first start.

* Settings, history, plugins and logs: ``%APPDATA%\\SnapReel`` is copied to ``%APPDATA%\\Tvorka``
  (copied, not moved: the old folder stays as a backup).
* Models and results live next to the old ``SnapReel.cmd``. A new version unpacks into a new
  ``Tvorka`` folder, so without help gigabytes of models would seem to vanish: Tvorka finds the
  old folder (through the history, or next to its own folder) and keeps using it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from tvorka.core import paths

log = logging.getLogger(__name__)

OLD_NAME = "SnapReel"
OLD_LAUNCHER = "SnapReel.cmd"


def copy_old_data() -> Path | None:
    """Copy the old data folder if Tvorka has none yet. Returns the old folder when copied."""
    if os.environ.get("TVORKA_DATA_DIR"):
        return None  # an explicit data folder (tests, portable use): leave it alone
    new = paths.data_base()
    old = new.with_name(OLD_NAME)
    if new.exists() or not old.is_dir():
        return None
    shutil.copytree(old, new, ignore=shutil.ignore_patterns("*.lock", "*.tmp"))
    return old


def find_old_home(history_file: Path, near: Path) -> Path | None:
    """The old release folder (the one holding ``SnapReel.cmd``), if it is still on disk."""
    candidates: list[Path] = [near.parent / OLD_NAME, near]
    try:
        works = json.loads(history_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        works = []
    for work in works if isinstance(works, list) else []:
        path = Path(str(work.get("path", ""))) if isinstance(work, dict) else None
        if path is not None:
            candidates.extend(list(path.parents)[:4])
    for folder in candidates:
        if (folder / OLD_LAUNCHER).is_file():
            return folder
    return None


def _empty(folder: Path) -> bool:
    return not folder.exists() or not any(folder.iterdir())


def adopt_old_folders(settings: object, history_file: Path) -> list[str]:
    """Point the models and results folders at the old release folder when the new ones are empty.

    Only fills settings that were never changed by the user. Returns what was adopted.
    """
    home = find_old_home(history_file, paths.app_dir())
    if home is None:
        return []
    adopted = []
    for name, sub in (("models_dir", "models"), ("output_dir", "output")):
        current = getattr(settings, name)
        default = paths.app_dir() / sub
        if not current and (home / sub).is_dir() and _empty(default) and home / sub != default:
            setattr(settings, name, str(home / sub))
            adopted.append(f"{name} = {home / sub}")
    return adopted
