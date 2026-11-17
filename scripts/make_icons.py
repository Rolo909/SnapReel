"""Rebuild the app icon files from the logo drawn in code (gui/widgets/brand.py).

    python scripts/make_icons.py

Writes src/tvorka/assets/icons/app_icon.png (256 px) and app_icon.ico, where every size is
drawn on its own, so 16–24 px get the simplified mark instead of a blurred shrink.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from tvorka.gui.widgets.brand import render_mark  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TARGET = ROOT / "src" / "tvorka" / "assets" / "icons"


def mark(size: int) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    render_mark(size).save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data().data()))).convert("RGBA")


def main() -> None:
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    images = {size: mark(size) for size in SIZES}
    images[256].save(TARGET / "app_icon.png")
    largest = images[SIZES[-1]]
    largest.save(TARGET / "app_icon.ico", sizes=[(s, s) for s in SIZES],
                 append_images=[images[s] for s in SIZES[:-1]])
    print(f"wrote {TARGET / 'app_icon.png'} and app_icon.ico ({', '.join(map(str, SIZES))} px)")


if __name__ == "__main__":
    main()
