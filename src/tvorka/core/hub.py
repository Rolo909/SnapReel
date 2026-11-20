"""Hugging Face Hub integration: search, repo inspection, download planning."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from tvorka.core.catalog import ModelSpec
from tvorka.core.llm import gguf

log = logging.getLogger(__name__)

GB = 1024**3
WEIGHT_EXT = (".safetensors", ".bin", ".pt", ".pth")
SKIP_EXT = (
    ".onnx", ".onnx_data", ".msgpack", ".h5", ".ot", ".tflite", ".gguf", ".ckpt", ".pb", ".xml",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".md", ".pdf", ".ipynb", ".zip",
)
KIND_BY_TAG = {
    "text-to-image": "image", "image-to-image": "image",
    "text-to-video": "video", "image-to-video": "video",
    "text-to-speech": "speech", "text-to-audio": "speech",
}
TTS_MODEL_TYPES = ("vits", "bark")


class HubError(Exception):
    """A user-facing problem with a repository; ``code`` is translated by the UI."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class DownloadPlan:
    files: list[str] = field(default_factory=list)
    total_bytes: int = 0
    variant: str | None = None
    components: dict[str, int] = field(default_factory=dict)  # name -> weight bytes
    has_index: bool = False
    sizes: dict[str, int] = field(default_factory=dict)  # file -> bytes


@dataclass
class HubHit:
    id: str
    kind: str
    downloads: int = 0
    likes: int = 0
    gated: bool = False
    tags: list[str] = field(default_factory=list)


def plan_files(siblings: list[tuple[str, int]], prefer_half: bool = True) -> DownloadPlan:
    """Choose the minimal set of files needed to run a repo.

    Repos routinely ship the same weights several times (fp32 + fp16, ONNX,
    Flax, single-file checkpoints); downloading everything can triple the size.
    """
    names = {name for name, _ in siblings}
    has_index = "model_index.json" in names
    kept: list[tuple[str, int]] = []
    for name, size in siblings:
        path = PurePosixPath(name)
        low = name.lower()
        if low.endswith(SKIP_EXT) or path.name.startswith(".") or "openvino" in low:
            continue
        if has_index and len(path.parts) == 1 and low.endswith(WEIGHT_EXT):
            continue  # single-file checkpoint duplicating the component folders
        kept.append((name, size))

    folders: dict[str, list[tuple[str, int]]] = {}
    for name, size in kept:
        if name.lower().endswith(WEIGHT_EXT):
            folders.setdefault(str(PurePosixPath(name).parent), []).append((name, size))

    def is_fp16(name: str) -> bool:
        return ".fp16." in name or ".fp16-" in name

    heavy = {f: w for f, w in folders.items() if sum(s for _, s in w) > 50 * 1024**2}
    use_fp16 = prefer_half and bool(heavy) and all(
        any(is_fp16(n) and n.endswith(".safetensors") for n, _ in w) for w in heavy.values()
    )

    drop: set[str] = set()
    for weights in folders.values():
        has_st = any(n.endswith(".safetensors") for n, _ in weights)
        folder_fp16 = any(is_fp16(n) for n, _ in weights)
        for name, _ in weights:
            duplicate_format = has_st and not name.endswith(".safetensors")
            wrong_precision = is_fp16(name) != (use_fp16 and folder_fp16)
            ema = ".ema." in name or "non_ema" in name
            if duplicate_format or wrong_precision or ema:
                drop.add(name)

    plan = DownloadPlan(variant="fp16" if use_fp16 else None, has_index=has_index)
    for name, size in kept:
        if name in drop:
            continue
        plan.files.append(name)
        plan.sizes[name] = size
        plan.total_bytes += size
        if name.lower().endswith(WEIGHT_EXT):
            parent = PurePosixPath(name).parent
            key = parent.parts[0] if (has_index and parent.parts) else "model"
            plan.components[key] = plan.components.get(key, 0) + size
    return plan


def plan_named(siblings: list[tuple[str, int]], names: list[str]) -> DownloadPlan:
    """Exactly ``names`` (one quantization of a GGUF repo and its projector)."""
    sizes = dict(siblings)
    missing = [n for n in names if n not in sizes]
    if missing:
        raise HubError("not_found", ", ".join(missing))
    plan = DownloadPlan(files=list(names), has_index=False)
    for name in names:
        plan.sizes[name] = sizes[name]
        plan.total_bytes += sizes[name]
    plan.components["model"] = plan.total_bytes
    return plan


def _api(token: str | None) -> Any:
    from huggingface_hub import HfApi

    return HfApi(token=token)


def is_network_error(exc: BaseException) -> bool:
    """Connection problems; huggingface_hub 1.x raises httpx errors, which are not OSError."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    module = type(exc).__module__.split(".")[0]
    if module in ("httpx", "httpcore", "requests", "urllib3"):
        return True
    import urllib.error

    return isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)


def repo_siblings(repo_id: str, token: str | None = None) -> tuple[Any, list[tuple[str, int]]]:
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

    try:
        info = _api(token).model_info(repo_id, files_metadata=True)
    except GatedRepoError as exc:
        raise HubError("gated", repo_id) from exc
    except RepositoryNotFoundError as exc:
        raise HubError("not_found", repo_id) from exc
    except HfHubHTTPError as exc:
        raise HubError("network", str(exc)) from exc
    except Exception as exc:
        if is_network_error(exc) or isinstance(exc, OSError):
            raise HubError("network", str(exc)) from exc
        raise
    return info, [(s.rfilename, int(s.size or 0)) for s in info.siblings or []]


SEARCH_TTL = 3600.0
_search_cache: dict[tuple[str, str, int], tuple[float, list[HubHit]]] = {}


def search(kind: str, query: str = "", limit: int = 40, token: str | None = None) -> list[HubHit]:
    """Most-downloaded runnable models of a kind, optionally filtered by text (cached for an hour)."""
    key = (kind, query.strip().lower(), limit)
    cached = _search_cache.get(key)
    if cached and time.monotonic() - cached[0] < SEARCH_TTL:
        return list(cached[1])
    hits = _search(kind, query.strip(), limit, token)
    _search_cache[key] = (time.monotonic(), hits)
    return list(hits)


def _search(kind: str, query: str, limit: int, token: str | None) -> list[HubHit]:
    api = _api(token)
    if kind == "chat":
        requests = [("text-generation", "gguf"), ("image-text-to-text", "gguf")]
    elif kind == "speech":
        requests = [("text-to-speech", "vits"), ("text-to-speech", "bark")]
    elif kind == "video":
        requests = [("text-to-video", "diffusers"), ("image-to-video", "diffusers")]
    else:
        requests = [("text-to-image", "diffusers")]
    hits: dict[str, HubHit] = {}
    try:
        for tag, library in requests:
            for m in api.list_models(
                pipeline_tag=tag, filter=library, search=query or None, sort="downloads", limit=limit
            ):
                tags = list(m.tags or [])
                if kind == "chat":
                    if "gguf" not in m.id.lower():  # the library tag alone also marks the originals
                        continue
                elif _is_addon(tags) or _is_quantized_export(m.id):
                    continue
                hits[m.id] = HubHit(m.id, kind, int(m.downloads or 0), int(m.likes or 0),
                                    bool(m.gated), tags)
    except Exception as exc:
        if is_network_error(exc) or isinstance(exc, OSError):
            raise HubError("network", str(exc)) from exc
        raise
    return sorted(hits.values(), key=lambda h: h.downloads, reverse=True)[:limit]


def _is_addon(tags: list[str]) -> bool:
    """LoRAs, adapters, ControlNets and GGUF exports cannot be run standalone.

    ONNX is not a marker: full diffusers repos often ship ONNX copies next to the
    PyTorch weights, and ``plan_files`` skips those files anyway.
    """
    joined = " ".join(tags).lower()
    return any(k in joined for k in ("lora", "adapter", "controlnet", "gguf", "template:"))


def _is_quantized_export(repo_id: str) -> bool:
    """FP8 / NF4 / INT4 re-uploads need special loaders that plain diffusers lacks."""
    low = repo_id.lower()
    return any(k in low for k in ("fp8", "nf4", "nvfp4", "int4", "int8", "awq", "gguf"))


def _read_json(repo_id: str, filename: str, token: str | None, cache_dir: str | None) -> dict:
    from huggingface_hub import hf_hub_download

    try:
        path = hf_hub_download(repo_id, filename, token=token, cache_dir=cache_dir)
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _half_factor(repo_id: str, filename: str, token: str | None) -> float:
    """0.5 when a file stores fp32 weights that will be loaded in half precision."""
    try:
        meta = _api(token).parse_safetensors_file_metadata(repo_id, filename)
        counts = meta.parameter_count
        if counts and max(counts, key=counts.get) in ("F32", "F64"):
            return 0.5
    except Exception:  # noqa: BLE001 - metadata is optional, fall back to the stored size
        log.debug("no safetensors metadata for %s/%s", repo_id, filename)
    return 1.0


def spec_from_repo(
    repo_id: str, token: str | None = None, kind_hint: str | None = None,
    cache_dir: str | None = None,
) -> ModelSpec:
    """Inspect an arbitrary Hub repo and build a runnable :class:`ModelSpec`."""
    repo_id = repo_id.strip().removeprefix("https://huggingface.co/").strip("/")
    if repo_id.count("/") != 1:
        raise HubError("bad_id", repo_id)
    info, siblings = repo_siblings(repo_id, token)
    if "model_index.json" not in dict(siblings) and any(n.endswith(".gguf") for n, _ in siblings):
        return _chat_spec_from_repo(repo_id, info, siblings, token)
    plan = plan_files(siblings)
    tags = list(info.tags or [])
    kind = KIND_BY_TAG.get(info.pipeline_tag or "") or kind_hint
    if _is_addon(tags) and not plan.has_index:
        raise HubError("addon", repo_id)

    spec = ModelSpec(
        id=repo_id, name=repo_id.split("/")[1].replace("_", " "), kind=kind or "image",
        author=repo_id.split("/")[0], origin="user", gated=bool(info.gated),
        download_gb=round(plan.total_bytes / GB, 2), tags=["custom"],
        license=str((info.card_data or {}).get("license") or "") if info.card_data else "",
    )

    if plan.has_index:
        index = _read_json(repo_id, "model_index.json", token, cache_dir)
        cls = str(index.get("_class_name", ""))
        if "Video" in cls or kind == "video" or any(k in cls for k in ("Wan", "LTX", "Mochi")):
            spec.kind = "video"
        elif kind not in ("image", "video"):
            spec.kind = "image"
        _fill_diffusers_defaults(spec, cls, repo_id)
        if "ip_adapter_sd15" in spec.reference:
            _fit_sd_generation(spec, _read_json(repo_id, "unet/config.json", token, cache_dir))
        first: dict[str, str] = {}
        for name in plan.files:
            if name.endswith(".safetensors") and "/" in name:
                first.setdefault(name.split("/")[0], name)
        half = spec.dtype in ("fp16", "bf16")
        for comp, size in plan.components.items():
            factor = 1.0
            if half and plan.variant is None and size > GB and comp in first:
                factor = _half_factor(repo_id, first[comp], token)
            spec.memory[comp] = round(size * factor / GB, 2)
    else:
        config = _read_json(repo_id, "config.json", token, cache_dir)
        model_type = str(config.get("model_type", ""))
        if model_type not in TTS_MODEL_TYPES:
            raise HubError("unsupported", f"{repo_id} ({model_type or info.library_name or '?'})")
        spec.kind, spec.engine = "speech", "transformers_tts"
        spec.memory = {"model": round(max(plan.total_bytes / GB * 1.1, 0.2), 2)}
        spec.act_gb = 0.5
        if model_type == "bark":
            spec.voices = [{"id": f"v2/en_speaker_{i}", "name": f"English {i}"} for i in (6, 9)]
    if not spec.memory:
        raise HubError("unsupported", repo_id)
    return spec


# ------------------------------------------------------------------ chat models (GGUF)
HEADER_BYTES = 4 * 1024**2  # enough for the model keys; the vocabulary that follows is not needed


def fill_chat_spec(spec: ModelSpec, quants: list[dict[str, Any]], info: gguf.GgufInfo,
                   template: str = "", projector: str = "", projector_gb: float = 0.0,
                   mtp: str = "", mtp_gb: float = 0.0) -> ModelSpec:
    """Describe a GGUF chat model from its quantizations (``gguf.group_quants``) and header.

    ``info`` is the header of the first file of ``quants[0]``.
    """
    spec.kind, spec.engine = "chat", "llama"
    spec.quants = quants
    spec.mmproj, spec.mmproj_gb = projector, projector_gb
    spec.mtp, spec.mtp_gb = mtp, mtp_gb
    spec.layers, spec.context = info.layers, info.context
    spec.kv_gb_per_1k, spec.kv_fixed_gb = (round(v, 4) for v in info.kv_cache())
    spec.experts, spec.experts_used = info.experts, info.experts_used
    first = quants[0]
    spec.expert_share = info.expert_share(first["gb"], gguf.quant_bits(first["name"]) or 4.9)
    spec.capabilities = gguf.capabilities(template or info.chat_template, bool(projector))
    spec.memory = {}
    usual = [q for q in spec.quants if gguf.quant_bits(q["name"]) <= 4.9] or spec.quants[:1]
    spec.download_gb = round(usual[-1]["gb"] + projector_gb + mtp_gb, 2)
    return spec


def remote_header(repo_id: str, filename: str, token: str | None = None) -> gguf.GgufInfo:
    """The start of a GGUF file on the Hub, read with one range request."""
    import io
    import urllib.request
    from urllib.parse import quote

    url = f"https://huggingface.co/{repo_id}/resolve/main/{quote(filename)}"
    headers = {"Range": f"bytes=0-{HEADER_BYTES - 1}", "User-Agent": "Tvorka"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            data = response.read(HEADER_BYTES)
    except Exception as exc:
        if is_network_error(exc) or isinstance(exc, OSError):
            raise HubError("network", str(exc)) from exc
        raise
    try:
        return gguf.read_header(io.BytesIO(data))
    except gguf.GgufError as exc:
        raise HubError("unsupported", f"{repo_id}/{filename}: {exc}") from exc


def _chat_spec_from_repo(repo_id: str, info: Any, siblings: list[tuple[str, int]],
                         token: str | None) -> ModelSpec:
    files = [(n, s) for n, s in siblings if n.endswith(".gguf")]
    quants = gguf.group_quants(files)
    projector, projector_gb = gguf.pick_projector(files)
    mtp, mtp_gb = gguf.pick_mtp(files)
    if not quants:
        raise HubError("projector" if projector else "unsupported", repo_id)
    header = remote_header(repo_id, quants[0]["files"][0], token)
    meta = getattr(info, "gguf", None) or {}
    card = info.card_data or {}
    name = repo_id.split("/")[1]
    for suffix in ("-GGUF", "_GGUF", "-gguf", "_gguf"):
        name = name.removesuffix(suffix)
    spec = ModelSpec(
        id=repo_id, name=name.replace("_", " "), kind="chat", engine="llama", author=repo_id.split("/")[0],
        origin="user", gated=bool(info.gated), tags=["custom"],
        license=str(card.get("license") or "") if card else "",
    )
    fill_chat_spec(spec, quants, header, str(meta.get("chat_template") or ""), projector, projector_gb,
                   mtp, mtp_gb)
    spec.context = int(meta.get("context_length") or 0) or spec.context
    return spec


def _fit_sd_generation(spec: ModelSpec, unet: dict[str, Any]) -> None:
    """``StableDiffusionPipeline`` serves both SD 1.x and 2.x; the UNet config tells them apart."""
    sample = unet.get("sample_size")
    if isinstance(sample, int) and sample > 0:
        side = sample * 8
        spec.native = [side, side]
        spec.max_side = max(spec.max_side, side * 2)
    if unet.get("cross_attention_dim", 768) != 768:  # SD 2.x: the SD 1.5 IP-Adapter does not fit
        spec.reference = [r for r in spec.reference if r != "ip_adapter_sd15"]


def _fill_diffusers_defaults(spec: ModelSpec, cls: str, repo_id: str) -> None:
    name = repo_id.lower()
    few_step = any(k in name for k in ("turbo", "schnell", "lightning", "lcm", "distill", "sprint",
                                      "hyper", "klein"))
    if spec.kind == "video":
        spec.dtype, spec.native, spec.multiple, spec.frame_rule = "bf16", [832, 480], 32, 4
        spec.max_side, spec.act_gb = 1280, 3.5
        spec.defaults = {"steps": 8 if few_step else 30, "guidance": 1.0 if few_step else 5.0,
                         "negative": True, "frames": 49, "fps": 16, "max_frames": 161}
        if "ImageToVideo" in cls or "Image2Video" in cls or "I2V" in repo_id.upper():
            spec.reference, spec.requires_reference = ["i2v"], True
        return
    if cls.startswith("StableDiffusionXL"):
        spec.dtype, spec.native, spec.act_gb = "fp16", [1024, 1024], 2.2
        spec.reference = ["img2img", "ip_adapter_sdxl"]
        spec.defaults = {"steps": 28, "guidance": 6.5, "negative": True}
    elif cls.startswith("StableDiffusion") and "3" not in cls:
        spec.dtype, spec.native, spec.max_side, spec.act_gb = "fp16", [512, 512], 1024, 1.0
        spec.reference = ["img2img", "ip_adapter_sd15"]
        spec.defaults = {"steps": 25, "guidance": 7.0, "negative": True}
    else:
        spec.dtype, spec.native, spec.multiple, spec.act_gb = "bf16", [1024, 1024], 16, 2.0
        spec.reference = ["img2img"]
        spec.defaults = {"steps": 28, "guidance": 3.5, "negative": False}
    if few_step:
        spec.defaults.update({"steps": 4, "guidance": 0.0, "negative": False, "max_steps": 12})
