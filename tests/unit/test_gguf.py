from __future__ import annotations

import io

import pytest
from conftest import LLAMA_HEADER, gguf_bytes

from tvorka.core.llm import gguf


def test_header_of_a_llama_model() -> None:
    info = gguf.read_header(io.BytesIO(gguf_bytes(LLAMA_HEADER)))
    assert info.complete
    assert info.architecture == "llama"
    assert (info.layers, info.context, info.quant) == (32, 131072, "Q4_K_M")
    assert "tokenizer.ggml.tokens" not in info.metadata  # the vocabulary is skipped
    assert not info.is_projector
    per_1k, fixed = info.kv_cache()
    # Llama 3 8B: 32 layers x 8 KV heads x (128 + 128) x 2 bytes = 128 KiB per token.
    assert per_1k == pytest.approx(0.125)
    assert fixed == 0.0


def test_cut_off_header_keeps_what_was_read() -> None:
    data = gguf_bytes(LLAMA_HEADER)
    info = gguf.read_header(io.BytesIO(data[: len(data) - 20]))
    assert not info.complete
    assert info.layers == 32 and info.chat_template == ""


@pytest.mark.parametrize("data", [b"", b"GGML" + b"\0" * 40, b"GGUF" + b"\x09\0\0\0" + b"\0" * 16])
def test_not_a_gguf_file(data: bytes) -> None:
    with pytest.raises(gguf.GgufError):
        gguf.read_header(io.BytesIO(data))


def test_sliding_window_layers_cache_only_their_window() -> None:
    meta: dict[str, object] = {
        "general.architecture": "gemma4", "gemma4.block_count": 6, "gemma4.embedding_length": 3840,
        "gemma4.attention.head_count": 16, "gemma4.attention.head_count_kv": [8, 8, 8, 8, 8, 1],
        "gemma4.attention.key_length": 512, "gemma4.attention.value_length": 512,
        "gemma4.attention.key_length_swa": 256, "gemma4.attention.value_length_swa": 256,
        "gemma4.attention.sliding_window": 1024,
        "gemma4.attention.sliding_window_pattern": [True, True, True, True, True, False],
    }
    per_1k, fixed = gguf.read_header(io.BytesIO(gguf_bytes(meta))).kv_cache()
    assert per_1k == pytest.approx(1 * 1024 * 2 * 1024 / gguf.GB)  # one global layer
    assert fixed == pytest.approx(5 * 8 * 512 * 2 * (1024 + 512) / gguf.GB)


def test_hybrid_model_caches_only_attention_layers() -> None:
    meta: dict[str, object] = {
        "general.architecture": "qwen35", "qwen35.block_count": 32, "qwen35.embedding_length": 4096,
        "qwen35.attention.head_count": 16, "qwen35.attention.head_count_kv": 4,
        "qwen35.attention.key_length": 256, "qwen35.full_attention_interval": 4,
    }
    per_1k, _fixed = gguf.read_header(io.BytesIO(gguf_bytes(meta))).kv_cache()
    assert per_1k == pytest.approx(8 * 4 * 512 * 2 * 1024 / gguf.GB)


def test_projector_is_recognized() -> None:
    meta: dict[str, object] = {"general.architecture": "clip", "general.type": "mmproj"}
    assert gguf.read_header(io.BytesIO(gguf_bytes(meta))).is_projector


@pytest.mark.parametrize(("name", "quant"), [
    ("Qwen3.5-9B-Q4_K_M.gguf", "Q4_K_M"),
    ("Qwen3.5-9B-UD-Q4_K_XL.gguf", "UD-Q4_K_XL"),
    ("gemma-4-12b-it-IQ4_XS.gguf", "IQ4_XS"),
    ("BF16/gemma-4-26B-A4B-it-BF16-00001-of-00002.gguf", "BF16"),
    ("model.Q8_0.gguf", "Q8_0"),
    ("Qwen3.6-35B-A3B-MXFP4_MOE.gguf", "MXFP4_MOE"),
    ("my-finetune.gguf", ""),
])
def test_quant_name(name: str, quant: str) -> None:
    assert gguf.quant_name(name) == quant


def test_quants_are_grouped_and_extras_skipped() -> None:
    gb = 1024**3
    files = [
        ("m-Q4_K_M.gguf", 5 * gb), ("m-Q8_0.gguf", 9 * gb),
        ("BF16/m-BF16-00001-of-00002.gguf", 10 * gb), ("BF16/m-BF16-00002-of-00002.gguf", 6 * gb),
        ("mmproj-F16.gguf", gb), ("mmproj-F32.gguf", 2 * gb), ("MTP/mtp-m-Q8_0.gguf", gb),
        ("imatrix_unsloth.gguf", gb), ("README.md", 1),
    ]
    quants = gguf.group_quants(files)
    assert [q["name"] for q in quants] == ["Q4_K_M", "Q8_0", "BF16"]
    assert quants[2] == {"name": "BF16", "gb": 16.0,
                         "files": ["BF16/m-BF16-00001-of-00002.gguf", "BF16/m-BF16-00002-of-00002.gguf"]}
    assert gguf.pick_projector(files) == ("mmproj-F16.gguf", 1.0)
    assert gguf.pick_projector(files[:2]) == ("", 0.0)


def test_capabilities_from_the_template() -> None:
    assert gguf.capabilities("{% if tools %}<think>", True) == ["vision", "tools", "reasoning"]
    assert gguf.capabilities("plain", False) == []


MOE_HEADER: dict[str, object] = {
    "general.architecture": "qwen35moe", "general.size_label": "35B-A3B",
    "qwen35moe.block_count": 40, "qwen35moe.embedding_length": 2048,
    "qwen35moe.attention.head_count": 16, "qwen35moe.attention.head_count_kv": 2,
    "qwen35moe.expert_count": 256, "qwen35moe.expert_used_count": 8,
    "qwen35moe.expert_feed_forward_length": 512, "qwen35moe.feed_forward_length": 4096,
}


def test_mixture_of_experts_from_the_header() -> None:
    info = gguf.read_header(io.BytesIO(gguf_bytes(MOE_HEADER)))
    assert (info.experts, info.experts_used) == (256, 8)
    routed = 40 * 256 * 3 * 2048 * 512  # gate, up and down of every expert
    assert info.expert_share() == pytest.approx(routed / 35e9, abs=0.001)
    # Without a size label the total comes from the file: 20 GB at 4 bits per weight.
    unlabeled = {k: v for k, v in MOE_HEADER.items() if k != "general.size_label"}
    info = gguf.read_header(io.BytesIO(gguf_bytes(unlabeled)))
    assert info.expert_share(20.0, 4.0) == pytest.approx(routed / (20 * 1024**3 * 2), abs=0.001)
    assert info.expert_share(10.0, 4.0) == 0.95  # an implausible file size is capped
    assert info.expert_share() == 0.0  # nothing to compare with
    dense = gguf.read_header(io.BytesIO(gguf_bytes(LLAMA_HEADER)))
    assert (dense.experts, dense.expert_share(5.0, 4.85)) == (0, 0.0)


def test_multi_token_prediction_head() -> None:
    gb = 1024**3
    files = [("m-Q4_K_M.gguf", 5 * gb), ("MTP/mtp-m-BF16.gguf", gb), ("MTP/mtp-m-Q8_0.gguf", gb // 2),
             ("mtp-m.gguf", gb // 2), ("mmproj-F16.gguf", gb)]
    assert gguf.pick_mtp(files) == ("mtp-m.gguf", 0.5)  # smallest, then the shortest path
    assert gguf.pick_mtp(files[:1]) == ("", 0.0)
    assert not gguf.is_model_file("mtp-m.gguf") and gguf.is_mtp_file("MTP/mtp-m-Q8_0.gguf")
    assert not gguf.is_mtp_file("m-Q4_K_M.gguf")
