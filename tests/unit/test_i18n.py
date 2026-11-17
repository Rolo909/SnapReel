from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

import tvorka
from tvorka import i18n
from tvorka.i18n import messages
from tvorka.i18n.ru import RU

SRC = Path(tvorka.__file__).parent


def tr_literals() -> dict[str, str]:
    """Every string literal passed as the first argument of ``tr(...)`` -> file:line."""
    found: dict[str, str] = {}
    for file in SRC.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "func", None)
            name = getattr(name, "id", getattr(name, "attr", ""))
            if (isinstance(node, ast.Call) and name == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{file.relative_to(SRC)}:{node.lineno}")
    return found


@pytest.fixture(autouse=True)
def russian() -> None:
    i18n.set_language("ru")
    yield
    i18n.set_language("ru")


def test_every_tr_string_is_translated() -> None:
    literals = tr_literals()
    assert literals, "the scanner found no tr() calls"
    missing = {text: where for text, where in literals.items() if text not in RU}
    assert not missing, "untranslated strings:\n" + "\n".join(f"{w}: {t!r}" for t, w in missing.items())


def test_no_stale_translations() -> None:
    stale = set(RU) - set(tr_literals())
    assert not stale, f"translations for strings no longer in the code: {sorted(stale)}"


def test_placeholders_match() -> None:
    fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}  # noqa: E731
    for source, target in RU.items():
        assert fields(source) == fields(target), source


def test_tr_switches_language() -> None:
    assert i18n.tr("Slow") == "Медленно"
    i18n.set_language("en")
    assert i18n.tr("Slow") == "Slow"
    assert i18n.tr("Not in the dictionary {n}", n=2) == "Not in the dictionary 2"
    i18n.set_language("de")
    assert i18n.language() == "ru"


ENGINE_CODES = ["not_installed", "load_failed", "cuda_unavailable", "reference_unsupported",
                "reference_unreadable", "needs_reference", "ip_adapter_failed", "lora_unsupported",
                "lora_failed", "empty_text", "unsupported", "edge_missing", "network", "model_missing",
                "does_not_fit", "out_of_memory", "failed"]
STAGES = ["import", "load", "place", "ready", "steps", "save", "encode", "speech", "download_extra",
          "retry_low_memory"]
NOTES = {"online": {}, "torch_cpu_build": {}, "gpu_unsupported": {"gpu": "Radeon"},
         "disk": {"need": 7.0, "have": 2.5}, "cpu_only": {}, "ram": {"need": 30, "have": 16},
         "ram_swap": {"need": 15, "have": 16}, "vram": {"need": 4.0, "have": 2.0},
         "hybrid": {"parts": "text_encoder"}, "stream": {}, "offload": {}, "forced_risky": {},
         "above_native": {}, "vram_busy": {"free": 1.2}}
HUB = ["gated", "not_found", "network", "bad_id", "addon", "unsupported", "disk", "failed"]


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_code_has_a_text(lang: str) -> None:
    i18n.set_language(lang)
    unknown = messages.engine_error("no_such_code")
    for code in ENGINE_CODES:
        text = messages.engine_error(code)
        assert text and (code == "failed" or text != unknown), code
    for code in STAGES:
        assert messages.stage(code), code
    for code in ("great", "good", "slow", "very_slow", "no"):
        assert messages.verdict(code) != code
    for code, params in NOTES.items():
        text = messages.advisor_note(code, params)
        assert text and "{" not in text, code
    for code in HUB:
        assert messages.hub_error(code), code
    if lang == "ru":
        assert "ГБ" in messages.advisor_note("disk", NOTES["disk"])
