"""``hub.plan_files`` on real repository layouts (sizes from the Hub, in GB)."""

from __future__ import annotations

import pytest

from snapreel.core.hub import plan_files

GB = 1024**3
SMALL = 2048


def repo(entries: dict[str, float]) -> list[tuple[str, int]]:
    return [(name, int(size * GB) if size else SMALL) for name, size in entries.items()]


def gb(value: int) -> float:
    return value / GB


DIFFUSERS_META = {
    "model_index.json": 0, "scheduler/scheduler_config.json": 0,
    "tokenizer/vocab.json": 0, "tokenizer/merges.txt": 0, "tokenizer/tokenizer_config.json": 0,
    "README.md": 0, ".gitattributes": 0, "unet/config.json": 0, "vae/config.json": 0,
    "text_encoder/config.json": 0,
}

SDXL_TURBO = {
    **DIFFUSERS_META,
    "sd_xl_turbo_1.0.safetensors": 13.88, "sd_xl_turbo_1.0_fp16.safetensors": 6.94,
    "unet/diffusion_pytorch_model.fp16.safetensors": 5.14,
    "unet/diffusion_pytorch_model.safetensors": 10.27,
    "unet/model.onnx": 0, "unet/model.onnx_data": 10.27,
    "text_encoder/model.fp16.safetensors": 0.25, "text_encoder/model.safetensors": 0.49,
    "text_encoder/model.onnx": 0.49,
    "text_encoder_2/config.json": 0,
    "text_encoder_2/model.fp16.safetensors": 1.39, "text_encoder_2/model.safetensors": 2.78,
    "text_encoder_2/model.onnx": 0, "text_encoder_2/model.onnx_data": 2.78,
    "vae/diffusion_pytorch_model.fp16.safetensors": 0.17,
    "vae/diffusion_pytorch_model.safetensors": 0.33,
    "vae_decoder/model.onnx": 0.2, "vae_encoder/model.onnx": 0.13,
    "tokenizer_2/vocab.json": 0,
}


def test_sdxl_turbo_picks_fp16_folders() -> None:
    plan = plan_files(repo(SDXL_TURBO))
    assert plan.variant == "fp16"
    assert plan.has_index
    assert gb(plan.total_bytes) == pytest.approx(6.95, abs=0.02)
    assert "sd_xl_turbo_1.0.safetensors" not in plan.files
    assert not any(f.endswith((".onnx", ".onnx_data")) for f in plan.files)
    assert "model_index.json" in plan.files
    assert "tokenizer/vocab.json" in plan.files
    assert set(plan.components) == {"unet", "text_encoder", "text_encoder_2", "vae"}
    assert gb(plan.components["unet"]) == pytest.approx(5.14, abs=0.01)


def test_full_precision_when_half_not_wanted() -> None:
    plan = plan_files(repo(SDXL_TURBO), prefer_half=False)
    assert plan.variant is None
    assert not any(".fp16." in f for f in plan.files)
    assert gb(plan.total_bytes) == pytest.approx(13.87, abs=0.03)


def test_dreamshaper_fp16() -> None:
    plan = plan_files(repo({
        **DIFFUSERS_META, "safety_checker/config.json": 0,
        "unet/diffusion_pytorch_model.fp16.safetensors": 1.72,
        "unet/diffusion_pytorch_model.safetensors": 3.44,
        "text_encoder/model.fp16.safetensors": 0.25, "text_encoder/model.safetensors": 0.49,
        "vae/diffusion_pytorch_model.fp16.safetensors": 0.17,
        "vae/diffusion_pytorch_model.safetensors": 0.33,
        "safety_checker/model.fp16.safetensors": 0.61, "safety_checker/model.safetensors": 1.22,
        "dreamshaper_8.safetensors": 2.13,
    }))
    assert plan.variant == "fp16"
    assert gb(plan.total_bytes) == pytest.approx(2.75, abs=0.02)


def test_flux_schnell_drops_root_checkpoints() -> None:
    plan = plan_files(repo({
        **DIFFUSERS_META,
        "flux1-schnell.safetensors": 23.78, "ae.safetensors": 0.34,
        "transformer/config.json": 0,
        "transformer/diffusion_pytorch_model.safetensors.index.json": 0,
        "transformer/diffusion_pytorch_model-00001-of-00003.safetensors": 9.96,
        "transformer/diffusion_pytorch_model-00002-of-00003.safetensors": 9.95,
        "transformer/diffusion_pytorch_model-00003-of-00003.safetensors": 3.87,
        "text_encoder_2/model-00001-of-00002.safetensors": 4.99,
        "text_encoder_2/model-00002-of-00002.safetensors": 4.53,
        "text_encoder_2/model.safetensors.index.json": 0,
        "text_encoder/model.safetensors": 0.25,
        "vae/diffusion_pytorch_model.safetensors": 0.17,
        "schnell_grid.jpeg": 0.001,
    }))
    assert plan.variant is None
    assert "flux1-schnell.safetensors" not in plan.files
    assert "ae.safetensors" not in plan.files
    assert "transformer/diffusion_pytorch_model.safetensors.index.json" in plan.files
    assert gb(plan.total_bytes) == pytest.approx(33.72, abs=0.03)


def test_ltx_video_drops_every_root_checkpoint() -> None:
    roots = {f"ltx-video-2b-v0.9.{i}.safetensors": 5.0 + i * 3 for i in range(8)}
    plan = plan_files(repo({
        **DIFFUSERS_META, **roots,
        "transformer/diffusion_pytorch_model-00001-of-00002.safetensors": 4.94,
        "transformer/diffusion_pytorch_model-00002-of-00002.safetensors": 2.75,
        "text_encoder/model-00001-of-00004.safetensors": 4.99,
        "text_encoder/model-00002-of-00004.safetensors": 5.0,
        "text_encoder/model-00003-of-00004.safetensors": 4.87,
        "text_encoder/model-00004-of-00004.safetensors": 4.19,
        "vae/diffusion_pytorch_model.safetensors": 1.68,
    }))
    assert not any(name in plan.files for name in roots)
    assert gb(plan.total_bytes) == pytest.approx(28.42, abs=0.03)
    assert set(plan.components) == {"transformer", "text_encoder", "vae"}


def test_mms_keeps_only_safetensors() -> None:
    plan = plan_files(repo({
        "config.json": 0, "vocab.json": 0, "tokenizer_config.json": 0,
        "model.safetensors": 0.15, "pytorch_model.bin": 0.15, "README.md": 0,
    }))
    assert "model.safetensors" in plan.files
    assert "pytorch_model.bin" not in plan.files
    assert plan.components == {"model": int(0.15 * GB)}


def test_bark_keeps_bin_and_voice_presets() -> None:
    plan = plan_files(repo({
        "config.json": 0, "generation_config.json": 0, "tokenizer_config.json": 0,
        "pytorch_model.bin": 1.68, "speaker_embeddings_path.json": 0,
        "speaker_embeddings/v2/ru_speaker_3_semantic_prompt.npy": 0,
        "speaker_embeddings/v2/ru_speaker_3_coarse_prompt.npy": 0,
        "speaker_embeddings/v2/ru_speaker_3_fine_prompt.npy": 0,
    }))
    assert "pytorch_model.bin" in plan.files
    assert "speaker_embeddings_path.json" in plan.files
    assert sum(f.startswith("speaker_embeddings/") for f in plan.files) == 3
