"""User engine plugins: ``<data>/plugins/*.py``.

A plugin is ordinary Python code that calls :func:`register_engine`. It runs with
the app's permissions, so plugins are only ever loaded from the user's own data
folder — never from a remote catalog or a download.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from snapreel.core import paths
from snapreel.engines import base

log = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    name: str
    path: str
    engines: list[str] = field(default_factory=list)
    error: str = ""  # empty when the plugin loaded


def plugins_dir() -> Path:
    return paths.data_dir() / "plugins"


def load_plugins(folder: Path | None = None) -> list[PluginInfo]:
    """Import every plugin file once; a broken plugin is reported, never fatal."""
    folder = folder or plugins_dir()
    folder.mkdir(parents=True, exist_ok=True)
    loaded: list[PluginInfo] = []
    for file in sorted(folder.glob("*.py")):
        if file.name.startswith("_"):
            continue
        info = PluginInfo(file.stem, str(file))
        module_name = f"snapreel_plugin_{file.stem}"
        before = set(base.registered_engines())
        try:
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec is None or spec.loader is None:
                raise ImportError("cannot load")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - user code: report the failure in the UI
            sys.modules.pop(module_name, None)
            info.error = f"{exc.__class__.__name__}: {exc}"
            log.warning("plugin %s failed: %s", file.name, info.error)
        info.engines = sorted(set(base.registered_engines()) - before)
        if not info.error and not info.engines:
            info.error = "no engine registered"
        loaded.append(info)
        log.info("plugin %s: engines=%s %s", file.name, info.engines, info.error)
    return loaded
