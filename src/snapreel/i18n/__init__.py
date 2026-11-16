"""Interface language: English source strings, translated by dictionary lookup.

``tr("Generate")`` returns the Russian text when the language is ``ru`` and a
translation exists, otherwise the English source. Placeholders are filled after
translation: ``tr("{count} images", count=3)``.
"""

from __future__ import annotations

from typing import Any

LANGUAGES = ("ru", "en")
_language = "ru"


def set_language(lang: str) -> None:
    global _language
    _language = lang if lang in LANGUAGES else "ru"


def language() -> str:
    return _language


def tr(text: str, **fmt: Any) -> str:
    if _language == "ru":
        from snapreel.i18n.ru import RU

        text = RU.get(text, text)
    return text.format(**fmt) if fmt else text
