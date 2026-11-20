"""Decides how (and whether) a model can run on this machine.

The advisor turns a model's memory footprint and the detected hardware into
a concrete execution :class:`Plan` plus a human-facing verdict. Engines apply
the plan verbatim, so what the UI promises is what actually happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from tvorka.core.catalog import ModelSpec
from tvorka.core.hardware import GpuInfo, Hardware
from tvorka.core.llm import gguf

# Verdicts, best to worst.
GREAT, GOOD, SLOW, VERY_SLOW, NO = "great", "good", "slow", "very_slow", "no"
_ORDER = [GREAT, GOOD, SLOW, VERY_SLOW, NO]

DENOISERS = ("transformer", "unet", "transformer_2")
# Image encoders IP-Adapter loads next to the model, GB at fp16
# (SD 1.5: CLIP ViT-H/14, 632M parameters; SDXL: ViT-bigG/14, 1.8B parameters).
IP_ENCODER_GB = {"ip_adapter_sd15": 1.3, "ip_adapter_sdxl": 3.7}
# Excluded from CPU offload by diffusers (``_exclude_from_cpu_offload``).
ALWAYS_RESIDENT = ("safety_checker",)


@dataclass(frozen=True)
class Plan:
    """How an engine should place a model in memory."""

    device: str = "cpu"  # cuda | mps | cpu
    mode: str = "cpu"  # gpu | offload | hybrid | stream | cpu
    dtype: str = "fp32"  # fp16 | bf16 | fp32
    stream: tuple[str, ...] = ()  # components streamed layer by layer in hybrid mode
    vae_tiling: bool = False
    attention_slicing: bool = False

    def downgraded(self) -> Plan | None:
        """The next more conservative plan, used to retry after an out-of-memory error."""
        if self.mode == "gpu":
            return Plan(self.device, "offload", self.dtype, (), True, self.attention_slicing)
        if self.mode in ("offload", "hybrid"):
            return Plan(self.device, "stream", self.dtype, (), True, True)
        return None


@dataclass(frozen=True)
class LlmPlan:
    """How the llama.cpp server should run a chat model."""

    quant: str = ""
    ctx: int = 4096
    gpu_layers: int = 0  # transformer blocks on the GPU
    all_on_gpu: bool = False  # every block and the output layer
    projector_on_gpu: bool = False
    cpu_moe_layers: int = 0  # mixture of experts: layers whose experts stay in RAM (--n-cpu-moe)
    kv_type: str = "f16"  # KV cache precision: f16 or q8_0 (half the memory, nearly the same answers)
    mtp: bool = False  # multi-token prediction head on the GPU drafts the next words

    @property
    def device(self) -> str:
        return "gpu" if self.gpu_layers or self.all_on_gpu else "cpu"


@dataclass(frozen=True)
class Fit:
    verdict: str
    plan: Plan | LlmPlan
    need_vram_gb: float = 0.0
    have_vram_gb: float = 0.0
    need_ram_gb: float = 0.0
    have_ram_gb: float = 0.0
    # (code, params) pairs; the UI owns the wording.
    notes: tuple[tuple[str, dict[str, Any]], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.verdict != NO


def _worse(a: str, b: str) -> str:
    return a if _ORDER.index(a) >= _ORDER.index(b) else b


def _better(a: str, b: str) -> str:
    return a if _ORDER.index(a) <= _ORDER.index(b) else b


def run_dtype(spec: ModelSpec, device: str) -> str:
    if device == "cpu":
        return "fp32"
    if spec.dtype in ("fp16", "bf16", "fp32"):
        return "fp16" if (device == "mps" and spec.dtype == "bf16") else spec.dtype
    return "bf16" if "transformer" in spec.memory else "fp16"


def work_scale(spec: ModelSpec, width: int, height: int, frames: int = 1) -> float:
    """Requested workload relative to the model's native one."""
    native_frames = int(spec.default("frames", 1)) if spec.kind == "video" else 1
    native = max(1, spec.native[0] * spec.native[1] * max(native_frames, 1))
    return (width * height * max(frames, 1)) / native


def assess(
    spec: ModelSpec,
    hw: Hardware,
    *,
    mode: str = "auto",
    scale: float = 1.0,
    disk_free_gb: float | None = None,
    installed: bool = True,
    reference: str = "",
    quant: str = "",
    ctx: int = 0,
) -> Fit:
    """Pick the best plan for ``spec`` on ``hw`` and grade the result.

    ``reference`` is the job's reference mode; IP-Adapter adds an image encoder.
    ``quant`` pins a chat model's quantization (the one on disk); otherwise the best one is picked.
    ``ctx`` is the context a chat model should keep in mind; 0 for the usual 8K.
    """
    if spec.kind == "chat":
        return assess_llm(spec, hw, mode=mode, ctx=ctx, quant=quant, disk_free_gb=disk_free_gb,
                          installed=installed)
    notes: list[tuple[str, dict[str, Any]]] = []
    if reference in IP_ENCODER_GB:
        spec = replace(spec, memory={**spec.memory, "image_encoder": IP_ENCODER_GB[reference]})
    if spec.source == "online":
        return Fit(GREAT, Plan(), notes=(("online", {}),))

    device = "cpu" if mode == "cpu" else hw.device
    if "torch_cpu_build" in hw.issues:
        notes.append(("torch_cpu_build", {}))
    elif "gpu_unsupported" in hw.issues:
        notes.append(("gpu_unsupported", {"gpu": hw.gpus[0].name}))

    dtype = run_dtype(spec, device)
    weights = spec.weights_gb or max(spec.download_gb, 0.3)
    largest = max(spec.memory.values(), default=weights)
    act = spec.act_gb * max(scale, 0.3)
    ram_have = hw.ram_total_gb
    # Above ram_soft the page file gets involved; above ram_hard it is hopeless.
    ram_soft = ram_have * 0.82
    ram_tight = ram_have * 1.05
    ram_hard = ram_have * 1.5

    if not installed and disk_free_gb is not None and spec.download_gb + 1.5 > disk_free_gb:
        notes.append(("disk", {"need": spec.download_gb, "have": disk_free_gb}))
        return Fit(NO, Plan(device, "cpu", dtype), 0, 0, 0, ram_have, tuple(notes))

    if spec.kind in ("speech", "transcribe"):  # small models run on the processor, big ones on the GPU
        return _assess_speech(spec, hw, device, dtype, weights, act, notes)

    if device == "cpu":
        need_ram = weights * (2.0 if spec.dtype != "fp32" else 1.0) + act + 2.0
        heavy = spec.kind == "video" or weights > 4.0
        verdict = VERY_SLOW if heavy else SLOW
        notes.append(("cpu_only", {}))
        if need_ram > ram_hard:
            notes.append(("ram", {"need": need_ram, "have": ram_have}))
            verdict = NO
        return Fit(verdict, Plan("cpu", "cpu", "fp32", (), True, True),
                   0, 0, need_ram, ram_have, tuple(notes))

    gpu = hw.gpu
    assert gpu is not None
    vram = gpu.vram_total_gb
    usable = vram - (0.5 if vram <= 6.5 else 0.8)
    tiling = scale > 1.3 or spec.kind == "video"

    # diffusers never offloads some components; they stay on the GPU in every mode.
    pinned = sum(gb for name, gb in spec.memory.items() if name in ALWAYS_RESIDENT)
    # Measured on SD 1.5 / SD 2.1 (A7): in offload and stream modes only part of the working
    # memory is live at once, because the VAE decodes alone and tiled. Video is not measured yet.
    image = spec.kind == "image"
    offload_need = largest + pinned + (act * 0.5 if image else act)
    stream_need = pinned + (act * 0.7 + 0.4 if image else act + 1.0)

    candidates: list[tuple[str, Plan, float, float]] = []  # verdict, plan, vram, ram
    if weights + act <= usable:
        candidates.append((GREAT, Plan(device, "gpu", dtype, (), tiling), weights + act, largest + 3))
    if offload_need <= usable:
        candidates.append(
            (GOOD, Plan(device, "offload", dtype, (), True), offload_need, weights + 2.5)
        )
    if stream_need <= usable:
        # Hybrid: keep as much as fits resident on the GPU, stream the largest parts.
        # Text encoders go first — they run once, so streaming them costs little. The VAE
        # is never streamed: tiled decoding through per-layer streaming takes minutes (A6).
        # The engine parks the resident denoiser in RAM before decoding, so the two
        # phases peak separately: denoising with everything resident, decoding without
        # the denoiser.
        def hybrid_need(streamed: list[str]) -> float:
            resident = sum(gb for n, gb in spec.memory.items() if n not in streamed)
            parked = sum(gb for n, gb in spec.memory.items() if n in DENOISERS and n not in streamed)
            return max(resident + act * 0.5, resident - parked + act) + 0.5

        order = sorted(((n, gb) for n, gb in spec.memory.items() if n != "vae"),
                       key=lambda kv: (kv[0] in DENOISERS, -kv[1]))
        picked: list[str] = []
        for name, _gb in order:
            if hybrid_need(picked) <= usable:
                break
            picked.append(name)
        streamed = tuple(picked)
        need_hybrid = hybrid_need(picked)
        if streamed and len(streamed) < len(spec.memory) and need_hybrid <= usable:
            slow = any(n in DENOISERS for n in streamed)
            candidates.append((
                SLOW if slow else GOOD,
                Plan(device, "hybrid", dtype, streamed, True, slow),
                need_hybrid, weights + 2.5,
            ))
        candidates.append(
            (SLOW, Plan(device, "stream", dtype, (), True, True), stream_need, weights + 2.5)
        )

    forced = {"speed": "gpu", "balanced": "offload", "low_memory": "stream"}.get(mode)
    if forced and device != "mps":
        picked = [c for c in candidates if c[1].mode == forced]
        if picked:
            candidates = picked
        elif forced == "gpu":
            notes.append(("forced_risky", {}))
            candidates = [(SLOW, Plan(device, "gpu", dtype, (), True), weights + act, largest + 3)]
    if device == "mps":  # offload hooks are CUDA-oriented; unified memory makes them moot
        candidates = [c for c in candidates if c[1].mode == "gpu"]

    if not candidates:
        notes.append(("vram", {"need": stream_need, "have": vram}))
        return Fit(NO, Plan(device, "stream", dtype), stream_need, vram, weights + 2.5, ram_have,
                   tuple(notes))

    verdict, plan, need_vram, need_ram = candidates[0]
    if plan.mode == "hybrid":
        notes.append(("hybrid", {"parts": ", ".join(plan.stream)}))
    elif plan.mode == "stream":
        notes.append(("stream", {}))
    elif plan.mode == "offload":
        notes.append(("offload", {}))
    if need_ram > ram_hard:
        notes.append(("ram", {"need": need_ram, "have": ram_have}))
        verdict = NO
    elif need_ram > ram_soft:
        notes.append(("ram_swap", {"need": need_ram, "have": ram_have}))
        verdict = _worse(verdict, VERY_SLOW if need_ram > ram_tight else SLOW)
    if scale > 1.6 and verdict in (GREAT, GOOD):
        notes.append(("above_native", {}))
    if gpu.vram_free_gb + 1.0 < need_vram and need_vram <= vram:
        notes.append(("vram_busy", {"free": gpu.vram_free_gb}))
    return Fit(verdict, plan, need_vram, vram, need_ram, ram_have, tuple(notes))


def _assess_speech(
    spec: ModelSpec, hw: Hardware, device: str, dtype: str, weights: float, act: float,
    notes: list[tuple[str, dict[str, Any]]],
) -> Fit:
    need = weights + act
    gpu = hw.gpu
    light = weights < 1.0
    if device != "cpu" and gpu is not None and need + 0.8 <= gpu.vram_total_gb and not light:
        return Fit(GREAT, Plan(device, "gpu", "fp32"), need, gpu.vram_total_gb,
                   weights + 1.5, hw.ram_total_gb, tuple(notes))
    # Small TTS models are real-time on a CPU; moving them to the GPU buys nothing.
    notes = [n for n in notes if n[0] not in ("torch_cpu_build", "gpu_unsupported")] if light else notes
    verdict = GREAT if light else SLOW
    if not light:
        notes.append(("cpu_only", {}))
    need_ram = weights * 1.5 + 1.5
    if need_ram > hw.ram_total_gb * 0.82:
        notes.append(("ram", {"need": need_ram, "have": hw.ram_total_gb}))
        verdict = NO
    return Fit(verdict, Plan("cpu", "cpu", "fp32"), 0, 0, need_ram, hw.ram_total_gb, tuple(notes))


# ------------------------------------------------------------------ chat models
DEFAULT_CTX = 8192  # tokens of conversation the model keeps in mind unless asked for more
MIN_BITS = 3.5  # below this, answers degrade noticeably; such files are a last resort
SWEET_BITS = 4.9  # Q4_K_M: the usual balance of quality and speed
MAX_BITS = 6.6  # Q6_K: beyond it quality barely grows while speed halves
KV_Q8 = 8.5 / 16  # q8_0 KV cache relative to f16
MTP_CACHE_GB = 0.1  # the draft head's own KV cache


def llm_gpu(hw: Hardware) -> GpuInfo | None:
    """The GPU llama.cpp would use. Unlike PyTorch it reaches any GPU through Vulkan."""
    return max(hw.gpus, key=lambda g: (not g.integrated, g.vram_total_gb), default=None)


def assess_llm(
    spec: ModelSpec, hw: Hardware, *, mode: str = "auto", ctx: int = 0, quant: str = "",
    disk_free_gb: float | None = None, installed: bool = True,
) -> Fit:
    """Grade a chat model: picks the quantization (unless ``quant`` is given) and the GPU share."""
    ctx = ctx or min(spec.context or DEFAULT_CTX, DEFAULT_CTX)
    gpu = None if mode == "cpu" else llm_gpu(hw)
    pinned = spec.quant(quant) if quant else None
    if pinned is not None or not spec.quants:
        options = [pinned or {"name": quant, "gb": spec.download_gb}]
    else:
        options = [q for q in spec.quants if gguf.quant_bits(q["name"]) >= MIN_BITS] or spec.quants
    graded = [(q, _fit_quant(spec, q, hw, gpu, ctx, disk_free_gb, installed)) for q in options]
    best = min(_ORDER.index(fit.verdict) for _q, fit in graded)
    top = [(q, fit) for q, fit in graded if _ORDER.index(fit.verdict) == best]
    if len(top) == 1:
        return top[0][1]
    cap = MAX_BITS if _ORDER[best] == GREAT else SWEET_BITS

    def bits(q: dict[str, Any]) -> float:
        return gguf.quant_bits(q["name"]) or SWEET_BITS

    within = [item for item in top if bits(item[0]) <= cap]
    if within:
        return max(within, key=lambda item: (bits(item[0]), -item[0]["gb"]))[1]
    return min(top, key=lambda item: item[0]["gb"])[1]


def _fit_quant(
    spec: ModelSpec, q: dict[str, Any], hw: Hardware, gpu: GpuInfo | None, ctx: int,
    disk_free_gb: float | None, installed: bool,
) -> Fit:
    notes: list[tuple[str, dict[str, Any]]] = []
    name, weights = str(q.get("name", "")), float(q.get("gb") or spec.download_gb or 0.5)
    kv = spec.kv_gb_per_1k * ctx / 1024 + spec.kv_fixed_gb
    if not (spec.kv_gb_per_1k or spec.kv_fixed_gb):
        kv = weights * 0.03 * ctx / 1024  # header without sizes: about 0.12 GB per 1K for an 8B model
    compute = 0.35 + 0.15 * ctx / 8192  # llama.cpp scratch buffers (logits, attention)
    proj = spec.mmproj_gb
    draft = spec.mtp_gb + MTP_CACHE_GB if spec.mtp else 0.0
    ram_have = hw.ram_total_gb
    plan = LlmPlan(name, ctx)

    if not installed and disk_free_gb is not None and weights + proj + spec.mtp_gb + 1.0 > disk_free_gb:
        notes.append(("disk", {"need": weights + proj + spec.mtp_gb, "have": disk_free_gb}))
        return Fit(NO, plan, 0, 0, 0, ram_have, tuple(notes))

    vram = gpu.vram_total_gb if gpu else 0.0
    usable = vram - (0.5 if vram <= 6.5 else 0.8)
    kv_type = "f16"
    # A long conversation, or a cache that keeps the model off the card: keep it at 8 bits.
    if ctx > DEFAULT_CTX or (gpu is not None and weights + kv + compute + proj > usable):
        kv_type, kv = "q8_0", kv * KV_Q8
    # Mixture of experts: each word goes through only a few experts, the rest of the weights always.
    experts = weights * spec.expert_share if spec.experts > 1 and spec.layers else 0.0
    dense, used = weights - experts, (spec.experts_used or spec.experts) / max(spec.experts, 1)
    per_word = dense + experts * used  # what the processor reads for each word when it runs alone
    need_vram, verdict = 0.0, NO
    if gpu is not None and weights + kv + compute + proj <= usable:
        verdict, need_vram = GREAT, weights + kv + compute + proj
        mtp = bool(draft) and need_vram + draft <= usable
        need_vram += draft if mtp else 0.0
        plan = LlmPlan(name, ctx, spec.layers, True, bool(spec.mmproj), kv_type=kv_type, mtp=mtp)
        need_ram = 1.0 + (weights if gpu.integrated else 0.3)  # integrated GPUs share the RAM
    elif gpu is not None and experts and dense + kv + compute <= usable:
        # Everything but the experts on the card; the experts of the first layers stay in RAM.
        on_gpu_proj = bool(proj) and dense + kv + compute + proj <= usable
        base = dense + kv + compute + (proj if on_gpu_proj else 0.0)
        mtp = bool(draft) and base + draft <= usable  # worth more than one more layer of experts
        base += draft if mtp else 0.0
        per_layer = experts / spec.layers
        cpu_layers = max(0, spec.layers - int((usable - base) / per_layer))
        in_ram = per_layer * cpu_layers
        verdict = GREAT if not cpu_layers else GOOD if in_ram * used <= 1.5 else \
            SLOW if in_ram * used <= 5.0 else VERY_SLOW
        need_vram = base + experts - in_ram
        plan = LlmPlan(name, ctx, spec.layers, True, on_gpu_proj, cpu_layers, kv_type, mtp)
        if cpu_layers:
            notes.append(("llm_moe", {"layers": cpu_layers, "total": spec.layers}))
        need_ram = in_ram + 1.0 + (0.0 if on_gpu_proj else proj)
    else:
        share, on_gpu_proj = 0.0, False
        if gpu is not None and spec.layers:
            on_gpu_proj = bool(proj) and usable - compute - proj > weights * 0.3
            room = usable - compute - (proj if on_gpu_proj else 0.0)
            share = max(0.0, min(1.0, room / (weights + kv)))
        on_cpu = GOOD if per_word <= 1.5 else SLOW if per_word <= 5.0 else VERY_SLOW
        layers = int(share * spec.layers)
        if layers:
            share = layers / spec.layers
            # Every layer moved to the GPU only helps: never grade it below the processor alone.
            verdict = _better(GOOD if share >= 0.85 else SLOW if share >= 0.5 else VERY_SLOW, on_cpu)
            need_vram = (weights + kv) * share + compute + (proj if on_gpu_proj else 0.0)
            plan = LlmPlan(name, ctx, layers, False, on_gpu_proj, kv_type=kv_type)
            notes.append(("llm_partial", {"share": round(share * 100)}))
        else:
            share, verdict = 0.0, on_cpu
            notes.append(("llm_cpu", {}))
        need_ram = (weights + kv) * (1 - share) + compute + 1.0 + (0.0 if plan.projector_on_gpu else proj)

    # Weights are memory-mapped: past the RAM size every token reads the disk.
    if need_ram > ram_have * 1.05:
        notes.append(("ram", {"need": need_ram, "have": ram_have}))
        verdict = NO
    elif need_ram > ram_have * 0.82:
        notes.append(("ram_swap", {"need": need_ram, "have": ram_have}))
        verdict = _worse(verdict, VERY_SLOW if need_ram > ram_have * 0.95 else SLOW)
    if gpu is not None and plan.device == "gpu" and gpu.vram_free_gb + 1.0 < need_vram <= vram:
        notes.append(("vram_busy", {"free": gpu.vram_free_gb}))
    return Fit(verdict, plan, need_vram, vram, need_ram, ram_have, tuple(notes))


def snap(value: float, multiple: int) -> int:
    return max(multiple, round(value / multiple) * multiple)


def size_for_aspect(spec: ModelSpec, aspect_w: int, aspect_h: int, quality: float = 1.0) -> tuple[int, int]:
    """Resolution with the requested aspect ratio and the model's native pixel budget."""
    if spec.fixed_size:
        return spec.native[0], spec.native[1]
    budget = spec.native[0] * spec.native[1] * quality * quality
    ratio = aspect_w / aspect_h
    width = (budget * ratio) ** 0.5
    height = width / ratio
    limit = spec.max_side
    if max(width, height) > limit:
        factor = limit / max(width, height)
        width, height = width * factor, height * factor
    return snap(width, spec.multiple), snap(height, spec.multiple)


def resolution_route(spec: ModelSpec, width: int, height: int) -> tuple[int, int, str]:
    """How to produce exactly ``width`` × ``height``: ``(gen_w, gen_h, route)``.

    ``direct``  — the model draws that size itself (snapped to its multiple, then trimmed);
    ``upscale`` — the model draws the same aspect at its native pixel budget, then the
    image is enlarged and trimmed to the exact size.
    """
    width, height = max(1, int(width)), max(1, int(height))
    if not spec.fixed_size and max(width, height) <= spec.max_side:
        # Round up: trimming a few pixels is invisible, stretching is not.
        m = spec.multiple
        return -(-width // m) * m, -(-height // m) * m, "direct"
    gen_w, gen_h = size_for_aspect(spec, width, height)
    # Extreme strips (e.g. 4000×300) would leave a few dozen pixels on the short side;
    # keep at least half the native side and let the final crop restore the aspect.
    floor = snap(min(spec.native) / 2, spec.multiple)
    if not spec.fixed_size and min(gen_w, gen_h) < floor:
        if gen_w < gen_h:
            gen_w = floor
        else:
            gen_h = floor
    return gen_w, gen_h, "upscale"


def video_frames(spec: ModelSpec, frames: int | None = None,
                 seconds: float | None = None) -> tuple[int, bool]:
    """Frame count the model will generate, and whether the request was cut to its limit.

    ``seconds`` wins over ``frames``; the model's own fps turns seconds into frames.
    """
    if seconds is not None and seconds > 0:
        frames = round(float(seconds) * int(spec.default("fps", 16))) + 1
    wanted = int(frames or spec.default("frames", 49))
    limit = int(spec.default("max_frames", wanted))
    snapped = snap_frames(spec, min(wanted, limit))
    while snapped > limit and snapped > 1:  # snapping may round past the limit
        snapped = snap_frames(spec, snapped - max(1, spec.frame_rule))
    return snapped, wanted > limit


def snap_frames(spec: ModelSpec, frames: int) -> int:
    rule = max(1, spec.frame_rule)
    if rule == 1:
        return max(1, frames)
    return max(rule + 1, round((frames - 1) / rule) * rule + 1)
