"""Line icons drawn with QPainterPath on a 20×20 grid, 1.6 px stroke, palette colours.

No emoji, no icon fonts: every glyph is geometry, so it stays crisp at 125 % / 150 %
scaling and follows the theme.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from tvorka.gui import theme

GRID = 20.0
STROKE = 1.6


def _p(*points: tuple[float, float]) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    return path


def _rect(x: float, y: float, w: float, h: float, r: float = 1.5) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), r, r)
    return path


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _join(*paths: QPainterPath) -> QPainterPath:
    out = QPainterPath()
    for path in paths:
        out.addPath(path)
    return out


def _image() -> QPainterPath:
    return _join(_rect(3, 4, 14, 12), _p((3.5, 14), (8, 9.5), (11.5, 13), (13.5, 11), (16.5, 14)),
                 _circle(13, 7.6, 1.2))


def _video() -> QPainterPath:
    return _join(_rect(2.5, 5, 11, 10), _p((13.5, 8.5), (17.5, 6), (17.5, 14), (13.5, 11.5)))


def _voice() -> QPainterPath:
    bars = [(4, 8, 12), (7, 5, 15), (10, 3, 17), (13, 6, 14), (16, 8.5, 11.5)]
    return _join(*(_p((x, a), (x, b)) for x, a, b in bars))


def _models() -> QPainterPath:  # stacked layers
    return _join(_p((10, 3), (17, 6.5), (10, 10), (3, 6.5), (10, 3)),
                 _p((3, 10), (10, 13.5), (17, 10)), _p((3, 13.5), (10, 17), (17, 13.5)))


def _gallery() -> QPainterPath:
    return _join(_rect(3, 3, 6, 6, 1), _rect(11, 3, 6, 6, 1), _rect(3, 11, 6, 6, 1), _rect(11, 11, 6, 6, 1))


def _settings() -> QPainterPath:  # three sliders
    return _join(_p((3, 5.5), (17, 5.5)), _p((3, 10), (17, 10)), _p((3, 14.5), (17, 14.5)),
                 _circle(7, 5.5, 1.8), _circle(13, 10, 1.8), _circle(8.5, 14.5, 1.8))


def _download() -> QPainterPath:
    return _join(_p((10, 3), (10, 12.5)), _p((6, 8.5), (10, 12.5), (14, 8.5)), _p((4, 16.5), (16, 16.5)))


def _trash() -> QPainterPath:
    return _join(_p((3.5, 5.5), (16.5, 5.5)), _p((8, 5.5), (8, 3.5), (12, 3.5), (12, 5.5)),
                 _p((5, 5.5), (6, 16.5), (14, 16.5), (15, 5.5)), _p((8.5, 8.5), (8.5, 13.5)),
                 _p((11.5, 8.5), (11.5, 13.5)))


def _folder() -> QPainterPath:
    return _p((2.5, 15.5), (2.5, 4.5), (8, 4.5), (9.5, 6.5), (17.5, 6.5), (17.5, 15.5), (2.5, 15.5))


def _check() -> QPainterPath:
    return _p((4, 10.5), (8, 14.5), (16, 5.5))


def _close() -> QPainterPath:
    return _join(_p((5, 5), (15, 15)), _p((15, 5), (5, 15)))


def _play() -> QPainterPath:
    return _p((6, 4), (16, 10), (6, 16), (6, 4))


def _pause() -> QPainterPath:
    return _join(_p((7, 4.5), (7, 15.5)), _p((13, 4.5), (13, 15.5)))


def _stop() -> QPainterPath:
    return _rect(5, 5, 10, 10, 1)


def _copy() -> QPainterPath:
    return _join(_rect(7, 7, 10, 10), _p((13, 7), (13, 3), (3, 3), (3, 13), (7, 13)))


def _refresh() -> QPainterPath:
    path = QPainterPath()
    path.arcMoveTo(QRectF(4, 4, 12, 12), 60)
    path.arcTo(QRectF(4, 4, 12, 12), 60, 280)
    return _join(path, _p((13, 2.8), (13.2, 5.6), (10.4, 5.9)))


def _plus() -> QPainterPath:
    return _join(_p((10, 4), (10, 16)), _p((4, 10), (16, 10)))


def _search() -> QPainterPath:
    return _join(_circle(8.5, 8.5, 5), _p((12.2, 12.2), (16.5, 16.5)))


def _dice() -> QPainterPath:
    dots = [(7, 7), (13, 7), (10, 10), (7, 13), (13, 13)]
    return _join(_rect(3.5, 3.5, 13, 13, 2.5), *(_circle(x, y, 0.4) for x, y in dots))


def _link() -> QPainterPath:
    return _join(_rect(2.5, 7.5, 8, 5, 2.5), _rect(9.5, 7.5, 8, 5, 2.5))


def _warning() -> QPainterPath:
    return _join(_p((10, 3), (17.5, 16.5), (2.5, 16.5), (10, 3)), _p((10, 8), (10, 11.5)),
                 _circle(10, 14, 0.3))


def _info() -> QPainterPath:
    return _join(_circle(10, 10, 7), _p((10, 9), (10, 14)), _circle(10, 6.3, 0.3))


def _chevron() -> QPainterPath:  # points down; rotate for other directions
    return _p((6, 8), (10, 12), (14, 8))


def _upscale() -> QPainterPath:
    return _join(_p((3, 17), (3, 11)), _p((3, 17), (9, 17)), _p((3, 17), (16.5, 3.5)),
                 _p((11, 3), (17, 3), (17, 9)))


def _lock() -> QPainterPath:
    arc = QPainterPath()
    arc.moveTo(6.5, 9)
    arc.lineTo(6.5, 6.5)
    arc.arcTo(QRectF(6.5, 3, 7, 7), 180, -180)
    arc.lineTo(13.5, 9)
    return _join(_rect(4.5, 9, 11, 8), arc)


GLYPHS: dict[str, Callable[[], QPainterPath]] = {
    "image": _image, "video": _video, "voice": _voice, "models": _models, "gallery": _gallery,
    "settings": _settings, "download": _download, "trash": _trash, "folder": _folder,
    "check": _check, "close": _close, "play": _play, "pause": _pause, "stop": _stop, "copy": _copy,
    "refresh": _refresh, "plus": _plus, "search": _search, "dice": _dice, "link": _link,
    "warning": _warning, "info": _info, "chevron": _chevron, "upscale": _upscale, "lock": _lock,
}


def pixmap(name: str, size: int = 20, color: QColor | str = "text", ratio: float = 2.0,
           rotate: float = 0.0) -> QPixmap:
    """Render a glyph; ``color`` is a palette token or a QColor."""
    pen_color = theme.color(color) if isinstance(color, str) else color
    image = QPixmap(QSize(round(size * ratio), round(size * ratio)))
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / GRID
    painter.scale(scale, scale)
    if rotate:
        painter.translate(GRID / 2, GRID / 2)
        painter.rotate(rotate)
        painter.translate(-GRID / 2, -GRID / 2)
    pen = QPen(pen_color, STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(GLYPHS[name]())
    painter.end()
    return image


def icon(name: str, color: str = "text", size: int = 20) -> QIcon:
    """Icon with a muted normal state and a full-colour active state."""
    result = QIcon()
    result.addPixmap(pixmap(name, size, "muted" if color == "text" else color), QIcon.Mode.Normal)
    result.addPixmap(pixmap(name, size, color), QIcon.Mode.Active)
    result.addPixmap(pixmap(name, size, color), QIcon.Mode.Selected)
    result.addPixmap(pixmap(name, size, "faint"), QIcon.Mode.Disabled)
    return result
