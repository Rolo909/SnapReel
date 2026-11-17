from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest

from tvorka.core.hub import HubError
from tvorka.core.local_import import (
    is_silero_package,
    single_file_family,
    spec_from_path,
)

MB = 1024**2


def write_safetensors(path: Path, tensors: dict[str, tuple[str, int]]) -> None:
    """Header-only safetensors file: {name: (dtype, nbytes)} plus zero data."""
    header: dict[str, object] = {"__metadata__": {"format": "pt"}}
    offset = 0
    for name, (dtype, nbytes) in tensors.items():
        header[name] = {"dtype": dtype, "shape": [nbytes], "data_offsets": [offset, offset + nbytes]}
        offset += nbytes
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(raw)))
        handle.write(raw)
        handle.write(b"\0" * offset)


SD15 = {"model.diffusion_model.input_blocks.0.weight": ("F16", 8 * MB),
        "cond_stage_model.transformer.text_model.x": ("F16", 2 * MB),
        "first_stage_model.decoder.x": ("F16", 1 * MB)}
SDXL = {"model.diffusion_model.input_blocks.0.weight": ("F16", 8 * MB),
        "conditioner.embedders.0.transformer.x": ("F16", 1 * MB),
        "conditioner.embedders.1.model.x": ("F16", 2 * MB),
        "first_stage_model.decoder.x": ("F16", 1 * MB)}
SD2 = {"model.diffusion_model.input_blocks.0.weight": ("F32", 8 * MB),
       "cond_stage_model.model.transformer.x": ("F32", 2 * MB)}
FLUX = {"double_blocks.0.img_attn.qkv.weight": ("BF16", 4 * MB)}


@pytest.mark.parametrize(("tensors", "family"), [
    (SD15, "sd15"), (SDXL, "sdxl"), (SD2, "sd2"), (FLUX, "transformer"),
])
def test_single_file_family_by_header(tmp_path: Path, tensors: dict, family: str) -> None:
    file = tmp_path / "model.safetensors"
    write_safetensors(file, tensors)
    assert single_file_family(file) == family


def test_single_sd15_checkpoint(tmp_path: Path) -> None:
    file = tmp_path / "My Model_v2.safetensors"
    write_safetensors(file, SD15)
    spec = spec_from_path(file)
    assert spec.source == "local" and spec.path == str(file) and spec.origin == "user"
    assert spec.id == "local/my-model_v2"
    assert spec.kind == "image" and spec.engine == "diffusers"
    assert spec.native == [512, 512] and "ip_adapter_sd15" in spec.reference
    assert set(spec.memory) == {"unet", "text_encoder", "vae"}
    assert spec.memory["unet"] >= spec.memory["text_encoder"] >= spec.memory["vae"]
    assert "sd15" in spec.tags


def test_fp32_checkpoint_memory_is_halved(tmp_path: Path) -> None:
    file = tmp_path / "sd2.safetensors"
    write_safetensors(file, {"model.diffusion_model.x": ("F32", 1024 * MB),
                             "cond_stage_model.model.y": ("F32", 512 * MB)})
    spec = spec_from_path(file)
    assert spec.memory["unet"] == pytest.approx(0.5)
    assert spec.memory["text_encoder"] == pytest.approx(0.25)
    assert spec.native == [768, 768] and spec.reference == ["img2img"]


def test_sdxl_checkpoint(tmp_path: Path) -> None:
    file = tmp_path / "xl.safetensors"
    write_safetensors(file, SDXL)
    spec = spec_from_path(file)
    assert spec.native == [1024, 1024] and "ip_adapter_sdxl" in spec.reference


def test_transformer_checkpoint_is_unsupported(tmp_path: Path) -> None:
    file = tmp_path / "flux.safetensors"
    write_safetensors(file, FLUX)
    with pytest.raises(HubError) as info:
        spec_from_path(file)
    assert info.value.code == "unsupported"


def test_diffusers_folder(tmp_path: Path) -> None:
    root = tmp_path / "dreamy"
    root.mkdir()
    (root / "model_index.json").write_text(json.dumps({"_class_name": "StableDiffusionPipeline"}))
    (root / "unet").mkdir()
    (root / "unet" / "config.json").write_text(json.dumps({"sample_size": 64, "cross_attention_dim": 768}))
    write_safetensors(root / "unet" / "diffusion_pytorch_model.safetensors", {"w": ("F32", 64 * MB)})
    write_safetensors(root / "vae" / "diffusion_pytorch_model.safetensors", {"w": ("F32", 8 * MB)})
    spec = spec_from_path(root)
    assert spec.kind == "image" and spec.native == [512, 512]
    assert spec.memory["unet"] == pytest.approx(0.03, abs=0.01)  # fp32 on disk, fp16 in memory
    assert set(spec.memory) == {"unet", "vae"}


def test_video_folder(tmp_path: Path) -> None:
    root = tmp_path / "wan"
    root.mkdir()
    (root / "model_index.json").write_text(json.dumps({"_class_name": "WanPipeline"}))
    write_safetensors(root / "transformer" / "diffusion_pytorch_model.safetensors", {"w": ("BF16", 4 * MB)})
    assert spec_from_path(root).kind == "video"


def test_vits_and_bark_folders(tmp_path: Path) -> None:
    vits = tmp_path / "mms"
    vits.mkdir()
    (vits / "config.json").write_text(json.dumps({"model_type": "vits"}))
    write_safetensors(vits / "model.safetensors", {"w": ("F32", 2 * MB)})
    spec = spec_from_path(vits)
    assert spec.kind == "speech" and spec.engine == "transformers_tts"

    bark = tmp_path / "bark"
    (bark / "speaker_embeddings" / "v2").mkdir(parents=True)
    (bark / "config.json").write_text(json.dumps({"model_type": "bark"}))
    (bark / "pytorch_model.bin").write_bytes(b"\0" * MB)
    for name in ("ru_speaker_3", "en_speaker_6"):
        for part in ("semantic", "coarse", "fine"):
            (bark / "speaker_embeddings" / "v2" / f"{name}_{part}_prompt.npy").write_bytes(b"")
    assert [v["id"] for v in spec_from_path(bark).voices] == ["v2/en_speaker_6", "v2/ru_speaker_3"]

    other = tmp_path / "whisper"
    other.mkdir()
    (other / "config.json").write_text(json.dumps({"model_type": "whisper"}))
    with pytest.raises(HubError):
        spec_from_path(other)


def test_silero_package(tmp_path: Path) -> None:
    file = tmp_path / "v4_ru.pt"
    with zipfile.ZipFile(file, "w") as archive:
        archive.writestr("v4_ru/tts_models/model.pkl", b"x")
    assert is_silero_package(file)
    spec = spec_from_path(file)
    assert spec.engine == "silero" and spec.languages == ["ru"]
    plain = tmp_path / "other.pt"
    plain.write_bytes(b"not a zip")
    assert not is_silero_package(plain)
    with pytest.raises(HubError):
        spec_from_path(plain)


def test_missing_path() -> None:
    with pytest.raises(HubError) as info:
        spec_from_path("Z:/definitely/missing/model")
    assert info.value.code == "not_found"
