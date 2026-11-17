from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tvorka.gui import theme


@pytest.mark.parametrize("name", ["dark", "light"])
def test_text_contrast(name: str) -> None:
    p = theme.PALETTES[name]
    for surface in ("bg", "panel", "raised"):
        for token in ("text", "muted"):
            assert theme.contrast(p[token], p[surface]) >= 4.5, (name, token, surface)
        for token in ("ok", "warn", "bad"):  # verdicts are text too
            assert theme.contrast(p[token], p[surface]) >= 4.5, (name, token, surface)
        assert theme.contrast(p["accent_text"], p[surface]) >= 4.5, (name, "accent_text", surface)
    assert theme.contrast(p["on_accent"], p["accent"]) >= 4.5, name
    assert theme.contrast(p["on_accent"], p["accent_hover"]) >= 4.5, name
    assert theme.contrast(p["text"], p["accent_soft"]) >= 4.5, name  # selected nav / chips


def test_palettes_have_the_same_tokens() -> None:
    assert set(theme.PALETTES["dark"]) == set(theme.PALETTES["light"])


def test_stylesheet_has_no_unfilled_tokens(qapp) -> None:
    for name in theme.PALETTES:
        qss = theme.stylesheet(name)
        assert "$" not in qss
        assert theme.PALETTES[name]["accent"] in qss


def test_fonts_fall_back(qapp) -> None:
    for kind in theme.FONT_CANDIDATES:
        assert theme.font_family(kind)
