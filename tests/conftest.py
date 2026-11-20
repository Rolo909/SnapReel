"""Shared test setup: every test gets its own data directory."""

from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("TVORKA_DATA_DIR", str(target))
    return target


# ---------------------------------------------------------------- GGUF files
LLAMA_HEADER: dict[str, object] = {
    "general.architecture": "llama",
    "general.name": "Tiny Llama",
    "general.file_type": 15,
    "llama.block_count": 32,
    "llama.context_length": 131072,
    "llama.embedding_length": 4096,
    "llama.attention.head_count": 32,
    "llama.attention.head_count_kv": 8,
    "tokenizer.ggml.tokens": ["<s>", "</s>", "hello"],
    "tokenizer.ggml.scores": [0.0, 0.0, 1.5],
    "tokenizer.chat_template": "{% if tools %}{{ tools }}{% endif %}<think>",
}


def gguf_bytes(metadata: dict[str, object]) -> bytes:
    """A GGUF v3 header with the given key-value pairs and no tensors."""

    def string(text: str) -> bytes:
        raw = text.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    def value(item: object) -> tuple[int, bytes]:
        if isinstance(item, bool):
            return 7, struct.pack("<?", item)
        if isinstance(item, int):
            return 4, struct.pack("<I", item)
        if isinstance(item, float):
            return 6, struct.pack("<f", item)
        if isinstance(item, str):
            return 8, string(item)
        if isinstance(item, list):
            kind = value(item[0])[0] if item else 4
            return 9, struct.pack("<IQ", kind, len(item)) + b"".join(value(v)[1] for v in item)
        raise TypeError(item)

    out = b"GGUF" + struct.pack("<IQQ", 3, 0, len(metadata))
    for key, item in metadata.items():
        kind, raw = value(item)
        out += string(key) + struct.pack("<I", kind) + raw
    return out


@pytest.fixture
def make_gguf(tmp_path: Path) -> Callable[..., Path]:
    """Write a GGUF header file: ``make_gguf("dir/name.gguf", {...}, padding=0) -> Path``."""

    def make(name: str, metadata: dict[str, object] | None = None, padding: int = 0) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gguf_bytes(LLAMA_HEADER if metadata is None else metadata) + b"\0" * padding)
        return path

    return make
