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
        if fit.ok and model.kind != "speech" and model.source != "online":
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
