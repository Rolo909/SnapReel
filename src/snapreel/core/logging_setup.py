"""Application logging: rotating file in the data directory plus a quiet console."""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from snapreel.core import paths

log = logging.getLogger("snapreel")

# Libraries that log or warn a lot during normal operation.
NOISY_LOGGERS = ("huggingface_hub", "diffusers", "transformers", "urllib3", "httpx", "PIL",
                 "accelerate", "torch")


def log_file() -> Path:
    return paths.data_dir() / "logs" / "snapreel.log"


def setup(level: int = logging.INFO, console: bool = True) -> Path:
    """Configure the root logger once. Returns the log file path."""
    target = log_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_snapreel", False):
            root.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(target, maxBytes=2_000_000, backupCount=3,
                                       encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s"))
    file_handler.setLevel(level)
    file_handler._snapreel = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if console and sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        stream.setLevel(logging.WARNING)
        # Library warnings go to the file only; the console stays readable.
        stream.addFilter(lambda record: record.name != "py.warnings")
        stream._snapreel = True  # type: ignore[attr-defined]
        root.addHandler(stream)

    root.setLevel(level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    _quiet_libraries()

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    return target


def _quiet_libraries() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("DIFFUSERS_VERBOSITY", "error")
    logging.captureWarnings(True)


def _excepthook(kind: type[BaseException], value: BaseException,
                tb: TracebackType | None) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, value, tb)
        return
    log.critical("unhandled exception", exc_info=(kind, value, tb))


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    log.critical("unhandled exception in thread %s",
                 args.thread.name if args.thread else "?",
                 exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
