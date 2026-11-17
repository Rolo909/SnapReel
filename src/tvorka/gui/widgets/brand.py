"""App identity: the logo mark and the author credit.

The mark is "a spark in open hands": a soft letter T whose arms are cupped palms holding a
four-point spark — you create, the AI helps. It is drawn in code (a 100 × 100
grid scaled to any size), so the window, the welcome screen and the app icon files
(``scripts/make_icons.py``) all come from this one drawing.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPainterPathStroker, QPaintEvent
from PySide6.QtWidgets import QWidget

from tvorka.gui import theme

AUTHOR = "Rolo909"
AUTHOR_URL = "https://github.com/Rolo909"
PROJECT_URL = "https://github.com/Rolo909/Tvorka"

# The app icon keeps the dark theme's colours in every theme: it is the product's face.
ICON_TILE = "#34D3A6"
ICON_INK = "#04261D"

# At this size and below the drawing is simplified: thicker strokes, a bolder spark.
SMALL = 24


def _spark(cx: float, cy: float, rx: float, ry: float, pinch: float) -> QPainterPath:
    """A four-point star with concave sides; ``pinch`` is how close the sides bend to the centre."""
    path = QPainterPath(QPointF(cx, cy - ry))
    for (x, y), (px, py) in (((cx + rx, cy), (1, -1)), ((cx, cy + ry), (1, 1)),
                             ((cx - rx, cy), (-1, 1)), ((cx, cy - ry), (-1, -1))):
        path.quadTo(QPointF(cx + px * pinch, cy + py * pinch), QPointF(x, y))
    path.closeSubpath()
    return path


def _soften(shape: QPainterPath, radius: float) -> QPainterPath:
    """Round every sharp corner of ``shape`` (and grow it by ``radius``)."""
    stroker = QPainterPathStroker()
    stroker.setWidth(radius * 2)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    return shape.united(stroker.createStroke(shape))


def _palms(lift: float, sag: float) -> QPainterPath:
    """Two open hands rising from the stem, fingertips turned up.

    ``lift`` is the fingertip height, ``sag`` how low the underside hangs (the hands' fullness).
    """
    hands = QPainterPath()
    for side in (-1, 1):
        hand = QPainterPath(QPointF(50, 52))
        hand.cubicTo(QPointF(50 + side * 5, 41), QPointF(50 + side * 18, 35.5), QPointF(50 + side * 32, lift))
        hand.cubicTo(QPointF(50 + side * 29, sag - 4), QPointF(50 + side * 16, sag + 2), QPointF(50, 52))
        hand.closeSubpath()
        hands = hands.united(hand)
    return hands


def mark_figure(small: bool = False) -> QPainterPath:
    """The dark drawing on the tile, on a 100 × 100 grid, optically centred."""
    stem = QPainterPath()
    if small:
        # Fewer, fatter shapes: at 16–24 px thin parts vanish and gaps fill in.
        stem.addRoundedRect(QRectF(43.5, 48, 13, 35), 6.5, 6.5)
        figure = _soften(_palms(35, 52), 3).united(stem)
        return figure.united(_soften(_spark(50, 27, 12, 13, 4), 1.5))
    stem.addRoundedRect(QRectF(44.5, 48, 11, 35), 5.5, 5.5)
    figure = _soften(_palms(35, 51), 1.6).united(stem)
    return figure.united(_soften(_spark(50, 28, 12, 15, 2.4), 0.6))


def paint_mark(painter: QPainter, rect: QRectF, tile: QColor, ink: QColor) -> None:
    """Draw the whole mark (rounded tile and drawing) into ``rect``."""
    side = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side / 100, side / 100)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(tile)
    painter.drawRoundedRect(QRectF(0, 0, 100, 100), 28, 28)
    painter.setBrush(ink)
    painter.drawPath(mark_figure(small=side <= SMALL))
    painter.restore()


def render_mark(size: int, tile: str = ICON_TILE, ink: str = ICON_INK) -> QImage:
    """The mark as a transparent ``size`` × ``size`` image (for icon files)."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_mark(painter, QRectF(0, 0, size, size), QColor(tile), QColor(ink))
    painter.end()
    return image


class LogoMark(QWidget):
    """The logo mark in the current theme's colours."""

    def __init__(self, size: int = 30) -> None:
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_mark(painter, QRectF(self.rect()), theme.color("accent"), theme.color("on_accent"))
        painter.end()
