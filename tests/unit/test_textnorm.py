from __future__ import annotations

import pytest

from snapreel.engines import textnorm


@pytest.mark.parametrize(("value", "words"), [
    (0, "ноль"),
    (7, "семь"),
    (21, "двадцать один"),
    (115, "сто пятнадцать"),
    (1001, "одна тысяча один"),
    (2000, "две тысячи"),
    (2026, "две тысячи двадцать шесть"),
    (11000, "одиннадцать тысяч"),
    (5_000_000, "пять миллионов"),
    (-3, "минус три"),
])
def test_russian_numbers(value: int, words: str) -> None:
    assert textnorm.number_to_words(value, "ru") == words


@pytest.mark.parametrize(("value", "words"), [
    (0, "zero"),
    (13, "thirteen"),
    (40, "forty"),
    (1234, "one thousand two hundred thirty-four"),
    (2_000_005, "two million five"),
])
def test_english_numbers(value: int, words: str) -> None:
    assert textnorm.number_to_words(value, "en") == words


def test_normalize() -> None:
    assert textnorm.normalize("В 2026 году") == "В две тысячи двадцать шесть году"
    assert textnorm.normalize("рост 5%") == "рост пять процентов"
    assert textnorm.normalize("10 000 человек") == "десять тысяч человек"
    assert textnorm.normalize("3,5 литра") == "три и пять литра"
    assert textnorm.normalize("Room №4", "en") == "Room number four"
    assert not any(ch.isdigit() for ch in textnorm.normalize("1 2 3 456 7.8 90%"))


def test_detect_lang() -> None:
    assert textnorm.detect_lang("Привет, мир") == "ru"
    assert textnorm.detect_lang("Hello world") == "en"
    assert textnorm.detect_lang("123", fallback="en") == "en"


def test_split_sentences_respects_limit() -> None:
    text = " ".join(f"Предложение номер {i}." for i in range(200))
    chunks = textnorm.split_sentences(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == text


def test_split_sentences_breaks_giant_sentence() -> None:
    text = ", ".join(["слово"] * 300)
    chunks = textnorm.split_sentences(text, 120)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_split_sentences_keeps_paragraphs() -> None:
    assert textnorm.split_sentences("Один.\n\nДва.") == ["Один.", "Два."]
    assert textnorm.split_sentences("   ") == []
