from __future__ import annotations

import pytest

from tvorka.core import advisor
from tvorka.core.advisor import NO, Plan
from tvorka.core.catalog import Catalog, ModelSpec
from tvorka.core.hardware import GpuInfo, Hardware, TorchBuild

CUDA = TorchBuild(True, "2.14.0+cu130", "13.0")
CPU_TORCH = TorchBuild(True, "2.14.0+cpu", "")


def machine(vram: float | None = 8.0, ram: float = 16.0, torch: TorchBuild = CUDA,
            vendor: str = "nvidia") -> Hardware:
    gpus = () if vram is None else (GpuInfo("Test GPU", vendor, vram, vram - 0.3),)
    return Hardware("Test OS", "Test CPU", 6, 12, ram, ram * 0.6, 8.0, gpus, torch)


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return Catalog()


def spec(catalog: Catalog, model_id: str) -> ModelSpec:
    found = catalog.get(model_id)
    assert found is not None, model_id
    return found


def codes(fit: advisor.Fit) -> list[str]:
    return [code for code, _ in fit.notes]


def test_light_model_fits_fully_on_8gb(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/sd-turbo"), machine(8))
    assert fit.verdict == "great"
    assert fit.plan == Plan("cuda", "gpu", "fp16", (), False)
    assert fit.need_vram_gb <= fit.have_vram_gb


@pytest.mark.parametrize("vram", [4.0, 8.0, 12.0, 24.0])
def test_every_catalog_model_gets_a_plan(catalog: Catalog, vram: float) -> None:
    hw = machine(vram, ram=32)
    for model in catalog.all():
        fit = advisor.assess(model, hw)
        assert fit.verdict in ("great", "good", "slow", "very_slow", "no")
        if fit.ok and model.kind in ("image", "video") and model.source != "online":
            assert fit.plan.device == "cuda"
            assert fit.need_vram_gb <= vram


def test_more_vram_never_makes_things_worse(catalog: Catalog) -> None:
    order = ["great", "good", "slow", "very_slow", "no"]
    for model in catalog.all("image") + catalog.all("video"):
        verdicts = [advisor.assess(model, machine(v, ram=64)).verdict for v in (4, 8, 12, 24)]
        ranks = [order.index(v) for v in verdicts]
        assert ranks == sorted(ranks, reverse=True), (model.id, verdicts)


def test_sdxl_on_4gb_streams_everything_but_the_vae(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/sdxl-turbo"), machine(4))
    assert fit.plan.mode == "hybrid"
    assert "unet" in fit.plan.stream and "vae" not in fit.plan.stream
    assert fit.verdict == "slow"


def test_hybrid_never_streams_the_vae(catalog: Catalog) -> None:
    for model in catalog.all("video") + catalog.all("image"):
        for vram in (4, 6, 8, 12):
            fit = advisor.assess(model, machine(vram, ram=64))
            assert "vae" not in fit.plan.stream, (model.id, vram)


def test_offload_when_only_the_largest_part_fits(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/stable-diffusion-xl-base-1.0"), machine(8))
    assert fit.plan.mode == "offload"
    assert fit.verdict == "good"


def test_hybrid_streams_text_encoder_first(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "THUDM/CogVideoX-2b"), machine(8))
    assert fit.plan.mode == "hybrid"
    # The text encoder goes first; the denoiser stays resident on the GPU.
    assert fit.plan.stream[0] == "text_encoder"
    assert "transformer" not in fit.plan.stream


def test_no_gpu_runs_on_cpu(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/sd-turbo"), machine(None))
    assert fit.plan.device == "cpu" and fit.plan.dtype == "fp32"
    assert fit.verdict == "slow"
    assert "cpu_only" in codes(fit)


def test_cpu_torch_build_is_reported(catalog: Catalog) -> None:
    hw = machine(8, torch=CPU_TORCH)
    assert "torch_cpu_build" in hw.issues
    fit = advisor.assess(spec(catalog, "stabilityai/sd-turbo"), hw)
    assert fit.plan.device == "cpu"
    assert "torch_cpu_build" in codes(fit)


def test_amd_gpu_is_not_used(catalog: Catalog) -> None:
    hw = machine(16, vendor="amd")
    assert hw.device == "cpu"
    fit = advisor.assess(spec(catalog, "stabilityai/sd-turbo"), hw)
    assert "gpu_unsupported" in codes(fit)


def test_low_ram_rejects_heavy_model(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "black-forest-labs/FLUX.1-schnell"), machine(8, ram=16))
    assert fit.verdict == NO
    assert "ram" in codes(fit)


def test_ram_pressure_downgrades_verdict(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"), machine(8, ram=16))
    assert fit.verdict == "very_slow"
    assert "ram_swap" in codes(fit)


def test_low_disk_blocks_download(catalog: Catalog) -> None:
    model = spec(catalog, "stabilityai/sdxl-turbo")
    fit = advisor.assess(model, machine(24), disk_free_gb=3.0, installed=False)
    assert fit.verdict == NO and "disk" in codes(fit)
    # Already installed: free space does not matter.
    assert advisor.assess(model, machine(24), disk_free_gb=3.0, installed=True).ok


@pytest.mark.parametrize(("mode", "expected"), [
    ("speed", "gpu"), ("balanced", "offload"), ("low_memory", "stream"), ("cpu", "cpu"),
])
def test_forced_modes(catalog: Catalog, mode: str, expected: str) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/sd-turbo"), machine(8), mode=mode)
    assert fit.plan.mode == expected


def test_forcing_gpu_on_a_model_that_does_not_fit_warns(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "stabilityai/sdxl-turbo"), machine(4), mode="speed")
    assert fit.plan.mode == "gpu"
    assert "forced_risky" in codes(fit)


def test_online_model_is_always_fine(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "edge/online"), machine(None, ram=4))
    assert fit.verdict == "great" and codes(fit) == ["online"]


def test_small_speech_model_stays_on_cpu(catalog: Catalog) -> None:
    fit = advisor.assess(spec(catalog, "silero/v4_ru"), machine(8, torch=CPU_TORCH))
    assert fit.verdict == "great"
    assert fit.plan.device == "cpu"
    assert "torch_cpu_build" not in codes(fit)


def test_large_resolution_is_flagged(catalog: Catalog) -> None:
    model = spec(catalog, "stabilityai/sd-turbo")
    scale = advisor.work_scale(model, 768, 768)
    assert scale == pytest.approx(2.25)
    fit = advisor.assess(model, machine(24), scale=scale)
    assert "above_native" in codes(fit)
    assert fit.plan.vae_tiling


def test_ip_adapter_encoder_is_counted(catalog: Catalog) -> None:
    model = spec(catalog, "Lykon/dreamshaper-8")
    plain = advisor.assess(model, machine(8))
    with_ip = advisor.assess(model, machine(8), reference="ip_adapter_sd15")
    assert with_ip.need_vram_gb == pytest.approx(plain.need_vram_gb + 1.3)
    assert "image_encoder" not in model.memory  # the catalog entry is not modified
    assert advisor.assess(model, machine(8), reference="img2img").need_vram_gb == plain.need_vram_gb


def test_plan_downgrade_chain() -> None:
    plan = Plan("cuda", "gpu", "fp16")
    modes = []
    while plan is not None:
        modes.append(plan.mode)
        plan = plan.downgraded()
    assert modes == ["gpu", "offload", "stream"]
    assert Plan("cuda", "hybrid", "fp16", ("text_encoder",)).downgraded().mode == "stream"


def test_size_for_aspect(catalog: Catalog) -> None:
    turbo = spec(catalog, "stabilityai/sd-turbo")
    assert advisor.size_for_aspect(turbo, 1, 1) == (512, 512)
    width, height = advisor.size_for_aspect(turbo, 16, 9)
    assert width % 8 == 0 and height % 8 == 0
    assert abs(width / height - 16 / 9) < 0.03
    assert abs(width * height - 512 * 512) / (512 * 512) < 0.05
    # Limited by max_side.
    width, height = advisor.size_for_aspect(turbo, 4, 1, quality=1.5)
    assert max(width, height) <= turbo.max_side
    sana = spec(catalog, "Efficient-Large-Model/Sana_Sprint_0.6B_1024px_diffusers")
    assert all(v % 32 == 0 for v in advisor.size_for_aspect(sana, 9, 16))
    cog = spec(catalog, "THUDM/CogVideoX-2b")
    assert advisor.size_for_aspect(cog, 1, 1) == (720, 480)


def test_video_frames(catalog: Catalog) -> None:
    cog = spec(catalog, "THUDM/CogVideoX-2b")  # 8 fps, 4k+1, max 49
    assert advisor.video_frames(cog) == (49, False)
    assert advisor.video_frames(cog, seconds=3) == (25, False)
    assert advisor.video_frames(cog, seconds=60) == (49, True)
    assert advisor.video_frames(cog, frames=200) == (49, True)
    ltx = spec(catalog, "Lightricks/LTX-Video")  # 24 fps, 8k+1, max 257
    frames, capped = advisor.video_frames(ltx, seconds=4)
    assert (frames - 1) % 8 == 0 and abs(frames - 97) <= 8 and not capped
    frames, capped = advisor.video_frames(ltx, seconds=30)
    assert frames <= 257 and (frames - 1) % 8 == 0 and capped


def test_snap_frames(catalog: Catalog) -> None:
    wan = spec(catalog, "Wan-AI/Wan2.1-T2V-1.3B-Diffusers")  # 4k + 1
    assert advisor.snap_frames(wan, 81) == 81
    assert advisor.snap_frames(wan, 50) == 49
    assert advisor.snap_frames(wan, 1) == 5
    ltx = spec(catalog, "Lightricks/LTX-Video")  # 8k + 1
    assert (advisor.snap_frames(ltx, 100) - 1) % 8 == 0
    turbo = spec(catalog, "stabilityai/sd-turbo")
    assert advisor.snap_frames(turbo, 7) == 7


# ------------------------------------------------------------------ chat models
def chat_spec(**extra: object) -> ModelSpec:
    quants = [{"name": n, "gb": gb, "files": [f"m-{n}.gguf"]}
              for n, gb in (("Q3_K_M", 4.4), ("IQ4_XS", 4.8), ("Q4_K_M", 5.3), ("Q5_K_M", 6.1),
                            ("Q6_K", 7.0), ("Q8_0", 8.9))]
    return ModelSpec.from_dict({"id": "test/chat-9b", "name": "Chat 9B", "kind": "chat", "engine": "llama",
                                "quants": quants, "layers": 32, "kv_gb_per_1k": 0.0312, "context": 262144,
                                "mmproj": "mmproj-F16.gguf", "mmproj_gb": 0.86, **extra})


def test_chat_model_picks_the_best_quant_that_fits_the_gpu() -> None:
    fit = advisor.assess(chat_spec(), machine(8))
    assert fit.verdict == "great"
    assert fit.plan.quant == "Q4_K_M" and fit.plan.all_on_gpu and fit.plan.projector_on_gpu
    assert fit.plan.ctx == advisor.DEFAULT_CTX
    assert fit.need_vram_gb <= 8 - 0.8
    # More memory buys quality, up to Q6_K: Q8_0 would halve the speed for little gain.
    assert advisor.assess(chat_spec(), machine(12)).plan.quant == "Q6_K"
    assert advisor.assess(chat_spec(), machine(24, ram=64)).plan.quant == "Q6_K"


def test_chat_model_splits_between_gpu_and_processor() -> None:
    fit = advisor.assess(chat_spec(), machine(4))
    assert fit.plan.device == "gpu" and not fit.plan.all_on_gpu
    assert 0 < fit.plan.gpu_layers < 32
    assert "llm_partial" in codes(fit)
    assert fit.verdict in ("slow", "very_slow")
    # Split between GPU and processor: a 4-bit file at most — a bigger one only slows it down further.
    assert fit.plan.quant in ("IQ4_XS", "Q4_K_M")


def test_chat_model_on_the_processor() -> None:
    fit = advisor.assess(chat_spec(), machine(None))
    assert fit.plan.device == "cpu" and fit.plan.gpu_layers == 0
    assert codes(fit) == ["llm_cpu"]
    assert fit.verdict == "slow"
    assert advisor.assess(chat_spec(), machine(8), mode="cpu").plan.device == "cpu"


def test_chat_model_uses_a_gpu_pytorch_cannot() -> None:
    radeon = Hardware("Test OS", "Test CPU", 6, 12, 16, 10, 8,
                      (GpuInfo("Radeon RX 5700", "amd", 8, 7.5),), CPU_TORCH)
    assert radeon.device == "cpu"  # no PyTorch build for this card
    assert advisor.assess(chat_spec(), radeon).plan.all_on_gpu  # llama.cpp reaches it through Vulkan


def test_chat_model_does_not_fit_in_ram() -> None:
    fit = advisor.assess(chat_spec(), machine(None, ram=4))
    assert fit.verdict == "no" and "ram" in codes(fit)


def test_installed_chat_quant_is_kept() -> None:
    fit = advisor.assess(chat_spec(), machine(24, ram=64), quant="Q3_K_M")
    assert fit.plan.quant == "Q3_K_M"


def test_chat_model_needs_disk_space() -> None:
    fit = advisor.assess(chat_spec(), machine(8), disk_free_gb=3.0, installed=False)
    assert fit.verdict == "no" and "disk" in codes(fit)


def test_more_memory_never_makes_a_chat_model_worse(catalog: Catalog) -> None:
    order = ["great", "good", "slow", "very_slow", "no"]
    for model in catalog.all("chat"):
        verdicts = [advisor.assess(model, machine(v, ram=r)).verdict
                    for v, r in ((None, 16), (4, 16), (8, 16), (12, 32), (24, 64))]
        ranks = [order.index(v) for v in verdicts]
        assert ranks == sorted(ranks, reverse=True), (model.id, verdicts)


# ------------------------------------------------------------------ chat models: faster answers
def moe_spec(**extra: object) -> ModelSpec:
    quants = [{"name": "UD-Q3_K_XL", "gb": 12.0, "files": ["m-q3.gguf"]},
              {"name": "UD-Q4_K_XL", "gb": 15.8, "files": ["m-q4.gguf"]}]
    moe = {"experts": 128, "experts_used": 8, "expert_share": 0.88, **extra}
    return chat_spec(quants=quants, layers=30, kv_gb_per_1k=0.0195, kv_fixed_gb=0.29, mmproj_gb=1.1, **moe)


def test_mixture_of_experts_keeps_experts_in_ram() -> None:
    fit = advisor.assess(moe_spec(), machine(8))
    plan = fit.plan
    assert plan.all_on_gpu and 0 < plan.cpu_moe_layers < 30  # attention on the card, some experts too
    assert "llm_moe" in codes(fit) and "llm_partial" not in codes(fit)
    assert fit.verdict == "good"  # each word reads only 8 of 128 experts from RAM
    assert fit.need_vram_gb <= 8 - 0.8
    weights = moe_spec().quant(plan.quant)["gb"]
    in_ram = weights * 0.88 * plan.cpu_moe_layers / 30
    assert fit.need_ram_gb == pytest.approx(in_ram + 1.0, abs=0.05)
    # More video memory keeps more experts on the card.
    assert advisor.assess(moe_spec(), machine(12, ram=32)).plan.cpu_moe_layers < plan.cpu_moe_layers
    assert advisor.assess(moe_spec(), machine(24, ram=64)).plan.cpu_moe_layers == 0


def test_mixture_of_experts_is_faster_than_a_dense_model_of_its_size() -> None:
    dense = advisor.assess(moe_spec(experts=0, expert_share=0.0), machine(8))
    moe = advisor.assess(moe_spec(), machine(8))
    order = ["great", "good", "slow", "very_slow", "no"]
    assert order.index(moe.verdict) < order.index(dense.verdict)
    assert dense.plan.cpu_moe_layers == 0 and not dense.plan.all_on_gpu  # split by layers instead
    on_cpu = advisor.assess(moe_spec(), machine(None, ram=32))
    assert on_cpu.plan.device == "cpu" and on_cpu.verdict == "slow"  # not very_slow: few experts per word


def test_kv_cache_is_compressed_only_when_it_helps() -> None:
    assert advisor.assess(chat_spec(), machine(24, ram=64)).plan.kv_type == "f16"  # fits as it is
    assert advisor.assess(chat_spec(), machine(4)).plan.kv_type == "q8_0"  # frees room for layers
    long = advisor.assess_llm(chat_spec(), machine(24, ram=64), ctx=32768)
    assert long.plan.kv_type == "q8_0"
    q4 = advisor.assess_llm(chat_spec(), machine(24, ram=64), ctx=32768, quant="Q4_K_M")
    compute = 0.35 + 0.15 * 4
    cache = 0.0312 * 32 * advisor.KV_Q8  # the cache counts at 8 bits
    assert q4.need_vram_gb == pytest.approx(5.3 + 0.86 + compute + cache)


def test_multi_token_prediction_when_it_fits() -> None:
    spec = chat_spec(mtp="mtp-model.gguf", mtp_gb=0.43)
    roomy = advisor.assess(spec, machine(24, ram=64))
    assert roomy.plan.mtp
    assert roomy.need_vram_gb == pytest.approx(advisor.assess(chat_spec(), machine(24, ram=64)).need_vram_gb
                                               + 0.43 + advisor.MTP_CACHE_GB)
    assert not advisor.assess(chat_spec(), machine(24, ram=64)).plan.mtp  # no head, no drafting
    assert not advisor.assess(spec, machine(4)).plan.mtp  # split between GPU and processor
    assert not advisor.assess(spec, machine(None)).plan.mtp
    moe = advisor.assess(moe_spec(mtp="mtp-model.gguf", mtp_gb=0.43), machine(8))
    assert moe.plan.mtp and moe.plan.cpu_moe_layers  # the head goes before one more layer of experts
    assert moe.need_vram_gb <= 8 - 0.8


def test_multi_token_head_needs_disk_space() -> None:
    spec = chat_spec(mtp="mtp-model.gguf", mtp_gb=0.43)
    q4 = 5.3 + 0.86  # the 4-bit file and the projector
    assert advisor.assess(chat_spec(), machine(8), disk_free_gb=q4 + 1.2, installed=False).verdict != "no"
    fit = advisor.assess(spec, machine(8), disk_free_gb=q4 + 1.2, quant="Q4_K_M", installed=False)
    assert fit.verdict == "no" and "disk" in codes(fit)
