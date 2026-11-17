from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from tvorka.core import logging_setup


def test_setup_writes_rotating_file(data_dir: Path) -> None:
    old_hook, old_thread_hook = sys.excepthook, threading.excepthook
    try:
        path = logging_setup.setup()
        assert path == data_dir / "logs" / "tvorka.log"
        logging.getLogger("tvorka.test").info("hello log")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        thread = threading.Thread(target=lambda: 1 / 0, name="crasher")
        thread.start()
        thread.join()
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
        assert "hello log" in text
        assert "RuntimeError: boom" in text
        assert "crasher" in text and "ZeroDivisionError" in text
        # A second setup must not duplicate handlers.
        count = len(logging.getLogger().handlers)
        logging_setup.setup()
        assert len(logging.getLogger().handlers) == count
    finally:
        for handler in list(logging.getLogger().handlers):
            if getattr(handler, "_tvorka", False):
                logging.getLogger().removeHandler(handler)
                handler.close()
        logging.captureWarnings(False)
        sys.excepthook, threading.excepthook = old_hook, old_thread_hook
