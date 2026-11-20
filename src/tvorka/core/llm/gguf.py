"""GGUF files: header metadata, quantization names and memory estimates.

Only the key-value header is read. It is enough to size the KV cache and to tell
a model from a multimodal projector, and it is at the start of the file, so a
Hugging Face file can be inspected with one HTTP range request.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import IO, Any

GB = 1024**3
MAGIC = b"GGUF"

# value type -> struct format of a scalar
_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q",
            12: "<d"}
_STRING, _ARRAY = 8, 9

# Nominal bits per weight; used to rank quantizations by quality.
QUANT_BITS = {
    "IQ1_S": 1.6, "IQ1_M": 1.8, "IQ2_XXS": 2.1, "IQ2_XS": 2.3, "IQ2_S": 2.5, "IQ2_M": 2.7,
    "Q2_K": 2.6, "Q2_K_S": 2.6, "Q2_K_L": 2.9, "Q2_K_XL": 3.0, "IQ3_XXS": 3.1, "IQ3_XS": 3.3,
    "IQ3_S": 3.5, "IQ3_M": 3.7, "Q3_K_S": 3.4, "Q3_K_M": 3.9, "Q3_K_L": 4.3, "Q3_K_XL": 4.0,
    "IQ4_XS": 4.25, "IQ4_NL": 4.5, "MXFP4": 4.25, "MXFP4_MOE": 4.25, "Q4_0": 4.5, "Q4_1": 5.0,
    "Q4_K_S": 4.6, "Q4_K_M": 4.85, "Q4_K_L": 4.9, "Q4_K_XL": 5.0, "Q5_0": 5.5, "Q5_1": 6.0,
    "Q5_K_S": 5.5, "Q5_K_M": 5.7, "Q5_K_L": 5.8, "Q5_K_XL": 5.9, "Q6_K": 6.6, "Q6_K_L": 6.7,
    "Q6_K_XL": 7.0, "Q8_0": 8.5, "Q8_K_XL": 9.5, "BF16": 16.0, "F16": 16.0, "F32": 32.0,
}
# general.file_type -> name, for files whose name does not say it
_FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
               11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
               17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
               23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S",
               29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 38: "MXFP4_MOE"}
_QUANT_RE = re.compile(r"(?:^|[-_.])(UD-)?(IQ\d_[A-Z]+|Q\d_K(?:_[A-Z]+)?|Q\d_\d|MXFP4(?:_MOE)?|BF16|F16|F32)"
                       r"(?=$|[-_.])")
_SHARD_RE = re.compile(r"-(\d{5})-of-(\d{5})$")
# Files next to the weights that are not a model of their own.
_NOT_A_MODEL = ("mmproj", "mtp", "imatrix", "draft")


class GgufError(ValueError):
    """Not a GGUF file, or a header too damaged to read."""


class _Truncated(Exception):
    """The bytes ran out: the header continues beyond what was read."""


@dataclass
class GgufInfo:
    """What the header says. Fields stay at their defaults when the header does not say."""

    metadata: dict[str, Any] = field(default_factory=dict)
    complete: bool = True  # False when only the beginning of the header was available

    def get(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    @property
    def architecture(self) -> str:
        return str(self.get("general.architecture", ""))

    def arch(self, key: str, default: Any = None) -> Any:
        return self.get(f"{self.architecture}.{key}", default)

    @property
    def is_projector(self) -> bool:
        return self.get("general.type") == "mmproj" or self.architecture == "clip"

    @property
    def layers(self) -> int:
        return int(self.arch("block_count", 0) or 0)

    @property
    def context(self) -> int:
        return int(self.arch("context_length", 0) or 0)

    @property
    def quant(self) -> str:
        return _FILE_TYPES.get(int(self.get("general.file_type", -1)), "")

    @property
    def chat_template(self) -> str:
        return str(self.get("tokenizer.chat_template", "") or "")

    @property
    def experts(self) -> int:
        return int(self.arch("expert_count", 0) or 0)

    @property
    def experts_used(self) -> int:
        return int(self.arch("expert_used_count", 0) or 0)

    def expert_share(self, file_gb: float = 0.0, bits: float = 0.0) -> float:
        """Fraction of the weights in routed experts: the part ``--n-cpu-moe`` keeps in RAM.

        The total comes from ``general.size_label`` ("35B-A3B"), else from the file size and
        bits per weight. 0.0 for a dense model or a header without the sizes.
        """
        if self.experts < 2:
            return 0.0
        width = _largest(self.arch("embedding_length"))
        ffn = _largest(self.arch("expert_feed_forward_length")) or _largest(self.arch("feed_forward_length"))
        routed = self.layers * self.experts * 3 * width * ffn  # gate, up and down of every expert
        label = re.match(r"(\d+(?:\.\d+)?)([BM])", str(self.get("general.size_label", "")))
        if label:
            total = float(label.group(1)) * (1e9 if label.group(2) == "B" else 1e6)
        else:
            total = file_gb * GB * 8 / bits if file_gb and bits else 0.0
        return round(min(0.95, routed / total), 3) if routed and total else 0.0

    def kv_cache(self) -> tuple[float, float]:
        """KV cache at f16 as ``(GB per 1024 tokens of context, GB that does not grow with it)``.

        Sliding-window layers keep only their window, hybrid models (``full_attention_interval``)
        cache only their attention layers. (0.0, 0.0) when the header lacks the sizes.
        """
        layers = self.layers
        heads = _per_layer(self.arch("attention.head_count"), layers)
        kv_heads = _per_layer(self.arch("attention.head_count_kv"), layers)
        if not layers or not any(heads):
            return 0.0, 0.0
        width = int(self.arch("embedding_length", 0) or 0)
        top_heads = max(heads)
        key = int(self.arch("attention.key_length", 0) or 0) or width // top_heads
        value = int(self.arch("attention.value_length", 0) or 0) or key
        key_swa = int(self.arch("attention.key_length_swa", 0) or 0) or key
        value_swa = int(self.arch("attention.value_length_swa", 0) or 0) or value
        window = int(self.arch("attention.sliding_window", 0) or 0)
        pattern = self.arch("attention.sliding_window_pattern")
        interval = int(self.arch("full_attention_interval", 0) or 0)
        per_token = fixed = 0.0
        for i in range(layers):
            count = kv_heads[i] if any(kv_heads) else heads[i]
            if not count or (interval > 1 and (i + 1) % interval):
                continue  # no attention in this layer
            swa = window > 0 and (pattern[i] if isinstance(pattern, list) and i < len(pattern) else False)
            if swa:
                fixed += count * (key_swa + value_swa) * 2 * (window + 512)  # window + one batch
            else:
                per_token += count * (key + value) * 2
        return per_token * 1024 / GB, fixed / GB


def _largest(value: Any) -> int:
    """A size that may be given per layer."""
    if isinstance(value, list):
        return int(max((v or 0 for v in value), default=0))
    return int(value or 0)


def _per_layer(value: Any, layers: int) -> list[float]:
    """Head counts are a number, or a list with one entry per layer."""
    if isinstance(value, list):
        return [float(v or 0) for v in value[:layers]] + [0.0] * max(0, layers - len(value))
    return [float(value or 0)] * layers


# ------------------------------------------------------------------ reading
class _Reader:
    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream

    def take(self, size: int) -> bytes:
        data = self._stream.read(size)
        if len(data) != size:
            raise _Truncated
        return data

    def scalar(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self) -> str:
        return self.take(self.scalar("<Q")).decode("utf-8", "replace")

    def value(self, kind: int, keep: bool = True) -> Any:
        if kind in _SCALARS:
            return self.scalar(_SCALARS[kind])
        if kind == _STRING:
            return self.string()
        if kind == _ARRAY:
            item, count = self.scalar("<I"), self.scalar("<Q")
            if item in _SCALARS and not keep:  # vocabulary scores and the like: skip in one read
                self.take(struct.calcsize(_SCALARS[item]) * count)
                return None
            items = [self.value(item, keep) for _ in range(count)]
            return items if keep else None
        raise GgufError(f"unknown value type {kind}")


# Arrays worth keeping; the vocabulary (hundreds of thousands of strings) is not.
_KEEP_ARRAYS = ("head_count", "head_count_kv", "sliding_window_pattern")


def read_header(stream: IO[bytes]) -> GgufInfo:
    """Parse the key-value header. A cut-off header yields what was read with ``complete=False``."""
    reader = _Reader(stream)
    info = GgufInfo()
    try:
        if reader.take(4) != MAGIC:
            raise GgufError("not a GGUF file")
        version = reader.scalar("<I")
        if version not in (2, 3):
            raise GgufError(f"unsupported GGUF version {version}")
        reader.scalar("<Q")  # tensor count
        for _ in range(reader.scalar("<Q")):
            key = reader.string()
            kind = reader.scalar("<I")
            keep = kind != _ARRAY or key.endswith(_KEEP_ARRAYS)
            value = reader.value(kind, keep)
            if keep:
                info.metadata[key] = value
    except _Truncated:
        if not info.metadata:
            raise GgufError("the file is too short to be a GGUF model") from None
        info.complete = False
    except (struct.error, UnicodeDecodeError, MemoryError, OverflowError) as exc:
        raise GgufError(str(exc)) from exc
    return info


# ------------------------------------------------------------------ file names
def quant_name(filename: str) -> str:
    """``Qwen3.5-9B-UD-Q4_K_XL-00001-of-00002.gguf`` → ``UD-Q4_K_XL``; "" when the name does not say."""
    stem = _SHARD_RE.sub("", PurePosixPath(filename).name.removesuffix(".gguf"))
    found = list(_QUANT_RE.finditer(stem.upper()))
    if not found:
        return ""
    prefix, name = found[-1].groups()
    return (prefix or "") + name


def quant_bits(name: str) -> float:
    return QUANT_BITS.get(name.removeprefix("UD-"), 0.0)


def is_model_file(filename: str) -> bool:
    low = filename.lower()
    return low.endswith(".gguf") and not any(word in low for word in _NOT_A_MODEL)


def is_projector_file(filename: str) -> bool:
    low = PurePosixPath(filename).name.lower()
    return low.endswith(".gguf") and "mmproj" in low


def group_quants(files: list[tuple[str, int]]) -> list[dict[str, Any]]:
    """Model files grouped by quantization (shards of one model together), smallest first.

    Each entry: ``{"name": "Q4_K_M", "files": [...], "gb": 5.3}``; unnamed files keep their stem.
    """
    groups: dict[str, dict[str, Any]] = {}
    for name, size in files:
        if not is_model_file(name):
            continue
        quant = quant_name(name) or _SHARD_RE.sub("", PurePosixPath(name).name.removesuffix(".gguf"))
        entry = groups.setdefault(quant, {"name": quant, "files": [], "bytes": 0})
        entry["files"].append(name)
        entry["bytes"] += size
    out = []
    for entry in groups.values():
        out.append({"name": entry["name"], "files": sorted(entry["files"]),
                    "gb": round(entry.pop("bytes") / GB, 2)})
    return sorted(out, key=lambda q: q["gb"])


def pick_projector(files: list[tuple[str, int]]) -> tuple[str, float]:
    """The projector to download: half precision when there is a choice. ("", 0.0) when none."""
    found = [(n, s) for n, s in files if is_projector_file(n)]
    if not found:
        return "", 0.0

    def rank(item: tuple[str, int]) -> tuple[int, int]:
        upper = item[0].upper()
        return (0 if "F16" in upper and "BF16" not in upper else 1 if "BF16" in upper
                else 3 if "F32" in upper else 2, item[1])

    name, size = min(found, key=rank)
    return name, round(size / GB, 2)


def is_mtp_file(filename: str) -> bool:
    low = PurePosixPath(filename).name.lower()
    return low.endswith(".gguf") and low.startswith("mtp")


def pick_mtp(files: list[tuple[str, int]]) -> tuple[str, float]:
    """The multi-token prediction head to download: the smallest (Q8_0 is as good as F16 here)."""
    found = [(n, s) for n, s in files if is_mtp_file(n)]
    if not found:
        return "", 0.0
    name, size = min(found, key=lambda item: (item[1], len(item[0]), item[0]))
    return name, round(size / GB, 2)


def capabilities(template: str, has_projector: bool) -> list[str]:
    """What the model can do beyond plain text, judged by its chat template."""
    out = ["vision"] if has_projector else []
    if "tools" in template:
        out.append("tools")
    if "<think>" in template or "enable_thinking" in template or "reasoning" in template:
        out.append("reasoning")
    return out
