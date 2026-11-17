"""Turn a model the user already has on disk into a :class:`ModelSpec`.

Supported: a diffusers folder (``model_index.json``), a single Stable Diffusion
checkpoint (``.safetensors`` / ``.ckpt``), a transformers TTS folder (VITS / Bark)
and a Silero ``.pt`` package. Memory is estimated from the files on disk.
Local files are never modified or deleted by the app.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

from tvorka.core.catalog import ModelSpec
from tvorka.core.hub import (
    GB,
    TTS_MODEL_TYPES,
    HubError,
    _fill_diffusers_defaults,
    _fit_sd_generation,
    plan_files,
)

SINGLE_FILE_EXT = (".safetensors", ".ckpt")
# Families a single checkpoint can be loaded as (``from_single_file``).
SINGLE_FILE_PIPELINES = {
    "sd15": "StableDiffusionPipeline",
    "sd2": "StableDiffusionPipeline",
    "sdxl": "StableDiffusionXLPipeline",
}
_HALF_BYTES = {"F16": 2, "BF16": 2, "F32": 4, "F64": 8}


def spec_from_path(path: str | Path, kind_hint: str | None = None) -> ModelSpec:
    """Inspect ``path`` and describe it. Raises :class:`HubError` with a UI code."""
    target = Path(path).expanduser()
    if not target.exists():
        raise HubError("not_found", str(target))
    if target.is_dir():
        if (target / "model_index.json").is_file():
            return _diffusers_folder(target, kind_hint)
        if (target / "config.json").is_file():
            return _tts_folder(target)
        silero = sorted(target.glob("*.pt"))
        if len(silero) == 1 and is_silero_package(silero[0]):
            return _silero_file(silero[0])
        raise HubError("unsupported", str(target))
    suffix = target.suffix.lower()
    if suffix in SINGLE_FILE_EXT:
        return _single_file(target)
    if suffix == ".pt" and is_silero_package(target):
        return _silero_file(target)
    raise HubError("unsupported", str(target))


# ----------------------------------------------------------------------- helpers
def _base_spec(target: Path, kind: str) -> ModelSpec:
    name = target.stem if target.is_file() else target.name
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower() or "model"
    return ModelSpec(id=f"local/{slug}", name=name.replace("_", " "), kind=kind, source="local",
                     path=str(target), origin="user", tags=["local"])


def _listing(folder: Path) -> list[tuple[str, int]]:
    return [(p.relative_to(folder).as_posix(), p.stat().st_size)
            for p in folder.rglob("*") if p.is_file()]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def safetensors_header(path: Path) -> dict[str, Any]:
    """Tensor table of a ``.safetensors`` file, read without loading any weights."""
    with open(path, "rb") as handle:
        size = int.from_bytes(handle.read(8), "little")
        if not 0 < size < 200 * 1024**2:
            raise ValueError("not a safetensors file")
        header = json.loads(handle.read(size))
    if not isinstance(header, dict):
        raise ValueError("not a safetensors file")
    header.pop("__metadata__", None)
    return header


def _stored_dtype(header: dict[str, Any]) -> str:
    """Most common tensor dtype by bytes ("F16", "F32", ...)."""
    totals: dict[str, int] = {}
    for info in header.values():
        if isinstance(info, dict) and "dtype" in info:
            start, end = info.get("data_offsets", (0, 0))
            totals[info["dtype"]] = totals.get(info["dtype"], 0) + int(end) - int(start)
    return max(totals, key=totals.get) if totals else ""


def single_file_family(path: Path) -> str:
    """``sd15`` / ``sd2`` / ``sdxl`` for a checkpoint, judged by its tensor names.

    ``.ckpt`` files are pickles; opening one would execute code, so their family
    falls back to the file size.
    """
    if path.suffix.lower() == ".ckpt":
        return "sdxl" if path.stat().st_size > 4.5 * GB else "sd15"
    keys = safetensors_header(path).keys()
    if any(k.startswith("conditioner.embedders.1.") for k in keys):
        return "sdxl"
    if any(k.startswith("cond_stage_model.model.") for k in keys):
        return "sd2"  # OpenCLIP text encoder
    if any(k.startswith("cond_stage_model.transformer.") for k in keys):
        return "sd15"
    if any(k.startswith(("double_blocks.", "transformer_blocks.", "joint_blocks.")) for k in keys):
        return "transformer"  # FLUX / SD3 style: needs a base repo, see B2
    return ""


def is_silero_package(path: Path) -> bool:
    """Silero models are ``torch.package`` zip archives with a ``tts_models`` pickle."""
    try:
        with zipfile.ZipFile(path) as archive:
            return any("tts_models/" in name for name in archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


# ----------------------------------------------------------------------- formats
def _diffusers_folder(folder: Path, kind_hint: str | None) -> ModelSpec:
    plan = plan_files(_listing(folder))
    index = _read_json(folder / "model_index.json")
    cls = str(index.get("_class_name", ""))
    is_video = "Video" in cls or kind_hint == "video" or any(k in cls for k in ("Wan", "LTX", "Mochi"))
    spec = _base_spec(folder, "video" if is_video else "image")
    _fill_diffusers_defaults(spec, cls, folder.name)
    if "ip_adapter_sd15" in spec.reference:
        _fit_sd_generation(spec, _read_json(folder / "unet" / "config.json"))
    half = spec.dtype in ("fp16", "bf16")
    for component, size in plan.components.items():
        factor = 1.0
        if half and plan.variant is None:
            factor = _half_factor_local(folder / component)
        spec.memory[component] = round(size * factor / GB, 2)
    spec.download_gb = round(plan.total_bytes / GB, 2)
    if not spec.memory:
        raise HubError("unsupported", str(folder))
    return spec


def _half_factor_local(component_dir: Path) -> float:
    for file in sorted(component_dir.glob("*.safetensors")):
        try:
            return 0.5 if _stored_dtype(safetensors_header(file)) in ("F32", "F64") else 1.0
        except (OSError, ValueError):
            continue
    return 1.0


def _single_file(file: Path) -> ModelSpec:
    try:
        family = single_file_family(file)
    except (OSError, ValueError) as exc:
        raise HubError("unsupported", f"{file.name}: {exc}") from exc
    if family not in SINGLE_FILE_PIPELINES:
        raise HubError("unsupported", f"{file.name} ({family or 'unknown'})")
    spec = _base_spec(file, "image")
    _fill_diffusers_defaults(spec, SINGLE_FILE_PIPELINES[family], file.stem)
    if family == "sd2":
        spec.native, spec.max_side = [768, 768], 1536
        spec.reference = ["img2img"]
    spec.tags = ["local", family]
    spec.memory = _single_file_memory(file)
    spec.download_gb = round(file.stat().st_size / GB, 2)
    return spec


def _single_file_memory(file: Path) -> dict[str, float]:
    """Split a checkpoint into UNet / text encoder / VAE by tensor-name prefix."""
    size = file.stat().st_size
    if file.suffix.lower() != ".safetensors":
        half = 0.5 if size > 3 * GB and size < 4.5 * GB else 1.0  # 4 GB SD 1.5 ckpt = fp32
        return {"unet": round(size * 0.8 * half / GB, 2), "text_encoder": round(size * 0.15 * half / GB, 2),
                "vae": round(size * 0.05 * half / GB, 2)}
    parts = {"unet": 0, "text_encoder": 0, "vae": 0}
    for key, info in safetensors_header(file).items():
        if not isinstance(info, dict) or "dtype" not in info:
            continue
        start, end = info.get("data_offsets", (0, 0))
        nbytes = int(end) - int(start)
        if info["dtype"] in ("F32", "F64"):
            nbytes = nbytes * 2 // _HALF_BYTES[info["dtype"]]  # loaded in half precision
        if key.startswith("model.diffusion_model."):
            parts["unet"] += nbytes
        elif key.startswith("first_stage_model."):
            parts["vae"] += nbytes
        elif key.startswith(("cond_stage_model.", "conditioner.")):
            parts["text_encoder"] += nbytes
    return {k: round(v / GB, 2) for k, v in parts.items() if v}


def _tts_folder(folder: Path) -> ModelSpec:
    config = _read_json(folder / "config.json")
    model_type = str(config.get("model_type", ""))
    if model_type not in TTS_MODEL_TYPES:
        raise HubError("unsupported", f"{folder.name} ({model_type or '?'})")
    plan = plan_files(_listing(folder))
    spec = _base_spec(folder, "speech")
    spec.engine = "transformers_tts"
    spec.memory = {"model": round(max(plan.total_bytes / GB * 1.1, 0.2), 2)}
    spec.act_gb = 0.5
    spec.download_gb = round(plan.total_bytes / GB, 2)
    if model_type == "bark":
        presets = sorted({p.name.split("_semantic")[0]
                          for p in (folder / "speaker_embeddings" / "v2").glob("*_semantic_prompt.npy")})
        spec.voices = [{"id": f"v2/{p}", "name": p.replace("_", " ")} for p in presets]
    return spec


def _silero_file(file: Path) -> ModelSpec:
    spec = _base_spec(file, "speech")
    spec.engine = "silero"
    size = file.stat().st_size / GB
    spec.memory = {"model": round(max(size * 2.5, 0.2), 2)}
    spec.act_gb = 0.3
    spec.download_gb = round(size, 3)
    spec.defaults = {"sample_rate": 48000}
    lang = re.search(r"_(ru|en|de|es|fr|ua|uz|xal|indic|cyrillic)\b", file.stem)
    if lang:
        spec.languages = [lang.group(1)]
    return spec
