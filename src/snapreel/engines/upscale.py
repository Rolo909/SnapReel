"""Super-resolution with Real-ESRGAN x4plus (BSD-3, xinntao/Real-ESRGAN).

Used when the requested image is larger than the model can draw. Weights are a
64 MB safetensors file (no pickle, nothing executes on load) fetched from the
Hugging Face Hub on first use. torch is imported lazily, inside functions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

REPO = "Comfy-Org/Real-ESRGAN_repackaged"
WEIGHTS = "RealESRGAN_x4plus.safetensors"
SCALE = 4
# Upscale again only while the remaining factor is worth a network pass; Lanczos finishes the rest.
MIN_PASS_FACTOR = 1.3


def positions(length: int, tile: int) -> list[int]:
    """Start offsets of non-overlapping tiles covering ``length`` (the last one may be shorter)."""
    return list(range(0, length, tile))


def _build_net() -> Any:
    import torch
    from torch import nn
    from torch.nn import functional as F

    class ResidualDenseBlock(nn.Module):
        def __init__(self, feat: int = 64, grow: int = 32) -> None:
            super().__init__()
            self.conv1 = nn.Conv2d(feat, grow, 3, 1, 1)
            self.conv2 = nn.Conv2d(feat + grow, grow, 3, 1, 1)
            self.conv3 = nn.Conv2d(feat + 2 * grow, grow, 3, 1, 1)
            self.conv4 = nn.Conv2d(feat + 3 * grow, grow, 3, 1, 1)
            self.conv5 = nn.Conv2d(feat + 4 * grow, feat, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, inplace=True)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, feat: int = 64) -> None:
            super().__init__()
            self.rdb1, self.rdb2, self.rdb3 = (ResidualDenseBlock(feat) for _ in range(3))

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self, feat: int = 64, blocks: int = 23) -> None:
            super().__init__()
            self.conv_first = nn.Conv2d(3, feat, 3, 1, 1)
            self.body = nn.Sequential(*(RRDB(feat) for _ in range(blocks)))
            self.conv_body = nn.Conv2d(feat, feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(feat, feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(feat, feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(feat, feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(feat, 3, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(0.2, inplace=True)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            feat = self.conv_first(x)
            feat = feat + self.conv_body(self.body(feat))
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            return self.conv_last(self.lrelu(self.conv_hr(feat)))

    return RRDBNet()


class Upscaler:
    """Real-ESRGAN x4 that processes the image in padded tiles to bound memory use."""

    def __init__(self, weights: str, device: str = "cuda", half: bool = True) -> None:
        import torch
        from safetensors.torch import load_file

        self.device = torch.device(device)
        self.dtype = torch.float16 if (half and self.device.type in ("cuda", "xpu")) else torch.float32
        net = _build_net()
        net.load_state_dict(load_file(weights))
        self.net = net.eval().to(self.device, self.dtype)

    def upscale(self, image: Image.Image, tile: int = 256, pad: int = 16,
                tick: Callable[[int, int], None] | None = None) -> Image.Image:
        """4× enlargement. ``tick(done, total)`` is called after every tile (raise to cancel)."""
        import torch

        source = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        height, width = source.shape[:2]
        tensor = torch.from_numpy(source).permute(2, 0, 1)[None].to(self.device, self.dtype)
        out = np.empty((height * SCALE, width * SCALE, 3), dtype=np.uint8)
        layout = [(x, y) for y in positions(height, tile) for x in positions(width, tile)]
        with torch.inference_mode():
            for index, (x, y) in enumerate(layout):
                x1, y1 = min(x + tile, width), min(y + tile, height)
                # Context around the tile; only its centre is kept, so tiles meet without seams.
                px0, py0 = max(0, x - pad), max(0, y - pad)
                px1, py1 = min(width, x1 + pad), min(height, y1 + pad)
                result = self.net(tensor[:, :, py0:py1, px0:px1])
                top, left = (y - py0) * SCALE, (x - px0) * SCALE
                crop = result[0, :, top:top + (y1 - y) * SCALE, left:left + (x1 - x) * SCALE]
                out[y * SCALE:y1 * SCALE, x * SCALE:x1 * SCALE] = (
                    crop.clamp(0, 1).mul(255).round().byte().permute(1, 2, 0).cpu().numpy())
                if tick is not None:
                    tick(index + 1, len(layout))
        return Image.fromarray(out)

    def to_size(self, image: Image.Image, width: int, height: int,
                tick: Callable[[float], None] | None = None) -> Image.Image:
        """Enlarge with as many 4× passes as needed; the caller resizes / trims to the exact size.

        ``tick(fraction)`` reports overall progress in [0, 1]; raise inside it to cancel.
        """
        passes = passes_needed(image.size, (width, height))
        for index in range(passes):
            per_tile = None if tick is None else (
                lambda done, total, p=index: tick((p + done / total) / passes))
            image = self.upscale(image, tick=per_tile)
        return image

    def close(self) -> None:
        self.net = None


def passes_needed(size: tuple[int, int], target: tuple[int, int]) -> int:
    """Network passes for an enlargement: the first above 1.3×, further ones only above 2×.

    Up to 2× after Real-ESRGAN, Lanczos is indistinguishable; a second 4× pass costs
    four times longer and makes textures look plastic.
    """
    factor = max(target[0] / size[0], target[1] / size[1])
    passes = 0
    while factor > (MIN_PASS_FACTOR if passes == 0 else 2.0) and passes < 3:
        factor /= SCALE
        passes += 1
    return passes
