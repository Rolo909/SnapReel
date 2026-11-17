"""The logo mark: drawn in code, simplified for small sizes, the same drawing as the icon files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from tvorka.gui.widgets import brand

ICONS = Path(__file__).resolve().parents[2] / "src" / "tvorka" / "assets" / "icons"


def ink_share(image) -> float:
    """Share of pixels painted in the ink colour (the drawing on the tile)."""
    ink = QColor(brand.ICON_INK)
    hits = sum(1 for y in range(image.height()) for x in range(image.width())
               if image.pixelColor(x, y).alpha() > 200
               and abs(image.pixelColor(x, y).green() - ink.green()) < 40)
    return hits / (image.width() * image.height())


@pytest.mark.parametrize("small", [False, True])
def test_figure_fits_the_tile_with_a_margin(small: bool, qapp) -> None:
    box = brand.mark_figure(small).boundingRect()
    assert QRectF(8, 8, 84, 84).contains(box)
    assert abs((box.left() + box.right()) / 2 - 50) < 1  # symmetric


def test_small_sizes_get_the_bolder_drawing(qapp) -> None:
    # Right at the switch, so anti-aliasing is the same: the simplified drawing is visibly bolder.
    assert ink_share(brand.render_mark(brand.SMALL)) > ink_share(brand.render_mark(brand.SMALL + 1)) * 1.15


def test_icon_files_match_the_drawing(qapp) -> None:
    from PIL import Image

    ico = Image.open(ICONS / "app_icon.ico")
    assert {(16, 16), (24, 24), (32, 32), (48, 48), (256, 256)} <= set(ico.info["sizes"])
    png = Image.open(ICONS / "app_icon.png").convert("RGBA")
    drawn = brand.render_mark(256)
    for x, y in ((128, 30), (128, 200), (40, 128), (5, 5)):  # spark, stem, hand, transparent corner
        assert png.getpixel((x, y))[3] // 64 == drawn.pixelColor(x, y).alpha() // 64
