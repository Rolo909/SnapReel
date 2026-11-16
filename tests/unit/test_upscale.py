from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest
from PIL import Image

from snapreel.core import advisor
from snapreel.core.catalog import Catalog
from snapreel.engines import upscale


@pytest.mark.parametrize(("length", "tile"), [(512, 256), (1000, 256), (100, 256)])
def test_positions_cover_everything(length: int, tile: int) -> None:
    starts = upscale.positions(length, tile)
    assert starts[0] == 0
    assert all(b - a == tile for a, b in pairwise(starts))
    assert starts[-1] < length <= starts[-1] + tile


@pytest.mark.parametrize(("size", "target", "passes"), [
    ((680, 384), (3840, 2160), 1),   # 5.6×: one pass to 4×, Lanczos for the rest
    ((384, 680), (1080, 1920), 1),
    ((512, 512), (600, 600), 0),     # 1.17×: not worth a network pass
    ((256, 256), (8192, 8192), 2),   # 32×
])
def test_passes_needed(size: tuple[int, int], target: tuple[int, int], passes: int) -> None:
    assert upscale.passes_needed(size, target) == passes


def test_tiled_upscale_matches_whole_image() -> None:
    """Padded tiles must give the same result as one pass over the whole image (no seams)."""
    torch = pytest.importorskip("torch")
    from safetensors.torch import save_file

    net = upscale._build_net()
    torch.manual_seed(0)
    for p in net.parameters():
        torch.nn.init.normal_(p, std=0.02)
    import tempfile
    from pathlib import Path

    weights = Path(tempfile.mkdtemp()) / "w.safetensors"
    save_file({k: v.contiguous() for k, v in net.state_dict().items()}, str(weights))
    model = upscale.Upscaler(str(weights), device="cpu")
    rng = np.random.default_rng(0)
    image = Image.fromarray(rng.integers(0, 255, (40, 56, 3), dtype=np.uint8))
    whole = np.asarray(model.upscale(image, tile=1000), dtype=int)
    ticks: list[tuple[int, int]] = []
    tiled = np.asarray(model.upscale(image, tile=16, pad=24, tick=lambda d, n: ticks.append((d, n))),
                       dtype=int)
    assert whole.shape == (160, 224, 3)
    assert np.abs(whole - tiled).max() <= 1
    assert ticks[-1] == (12, 12)


def test_resolution_route() -> None:
    turbo = Catalog().get("stabilityai/sd-turbo")
    assert advisor.resolution_route(turbo, 512, 512) == (512, 512, "direct")
    assert advisor.resolution_route(turbo, 500, 300) == (504, 304, "direct")
    w, h, route = advisor.resolution_route(turbo, 3840, 2160)
    assert route == "upscale" and abs(w / h - 16 / 9) < 0.05 and max(w, h) <= turbo.max_side
    w, h, route = advisor.resolution_route(turbo, 1080, 1920)
    assert route == "upscale" and h > w
    w, h, _ = advisor.resolution_route(turbo, 4000, 300)
    assert min(w, h) >= 256
