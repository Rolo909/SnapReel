from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tvorka.engines import media


def tone(seconds: float = 0.5, rate: int = 24000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


@pytest.mark.parametrize("ext", ["wav", "mp3", "flac"])
def test_audio_roundtrip(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"a.{ext}"
    media.write_audio(tone(), 24000, path)
    data, rate = media.read_audio(path)
    assert rate == 24000
    assert abs(data.size / rate - 0.5) < 0.08  # mp3 adds encoder padding
    assert 0.3 < float(np.abs(data).max()) < 0.7


def test_audio_unusual_rate_still_encodes_mp3(tmp_path: Path) -> None:
    path = tmp_path / "a.mp3"
    media.write_audio(tone(rate=16500), 16500, path)
    data, rate = media.read_audio(path)
    assert rate == 44100 and data.size > 0


def test_peaks() -> None:
    p = media.peaks(np.array([0.0, 0.5, -1.0, 0.25]), 2)
    assert p.tolist() == [0.5, 1.0]
    assert media.peaks(np.zeros(0), 4).tolist() == [0, 0, 0, 0]


def frames(count: int = 9, h: int = 66, w: int = 98) -> np.ndarray:
    out = np.zeros((count, h, w, 3), dtype=np.uint8)
    for i in range(count):
        out[i, :, : (i + 1) * w // count] = (200, 80, 40)
    return out


@pytest.mark.parametrize("ext", ["mp4", "webm"])
def test_video_roundtrip(tmp_path: Path, ext: str) -> None:
    import av

    path = tmp_path / f"v.{ext}"
    media.write_video(frames(), 8, path)
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        decoded = list(container.decode(stream))
    assert len(decoded) == 9
    assert (decoded[0].width, decoded[0].height) == (98, 66)


def test_odd_video_size_is_cropped_even(tmp_path: Path) -> None:
    import av

    path = tmp_path / "v.mp4"
    media.write_video(frames(h=65, w=97), 8, path)
    with av.open(str(path)) as container:
        frame = next(container.decode(video=0))
    assert (frame.width, frame.height) == (96, 64)


def test_gif(tmp_path: Path) -> None:
    path = tmp_path / "v.gif"
    media.write_video(frames(), 10, path)
    with Image.open(path) as gif:
        assert gif.n_frames == 9


def test_resize_and_resample_frames() -> None:
    clip = frames(count=49, h=48, w=72)
    big = media.resize_frames(clip, 160, 90)
    assert big.shape == (49, 90, 160, 3)
    faster = media.resample_frames(clip, 8, 24)  # same 6.1 s, three times the frames
    assert len(faster) == 147 and np.array_equal(faster[0], clip[0])
    assert np.array_equal(faster[-1], clip[-1])
    slower = media.resample_frames(clip, 24, 8)
    assert len(slower) == 16
    assert media.resample_frames(clip, 16, 16) is clip


def test_frames_to_uint8() -> None:
    floats = np.random.rand(1, 3, 8, 8, 3).astype(np.float32)
    out = media.frames_to_uint8(floats)
    assert out.shape == (3, 8, 8, 3) and out.dtype == np.uint8
    pil = [Image.new("RGBA", (4, 4))] * 2
    assert media.frames_to_uint8(pil).shape == (2, 4, 4, 3)


@pytest.mark.parametrize("ext", ["png", "jpg", "webp"])
def test_save_image(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"i.{ext}"
    media.save_image(Image.new("RGB", (32, 16), "red"), path, {"prompt": "кот", "seed": 5})
    with Image.open(path) as image:
        assert image.size == (32, 16)
        if ext == "png":
            assert image.text["prompt"] == "кот"
            assert image.text["seed"] == "5"


def test_fit_image_crops_to_aspect() -> None:
    wide = Image.new("RGB", (400, 100))
    assert media.fit_image(wide, 64, 64).size == (64, 64)
    tall = Image.new("L", (100, 400))
    out = media.fit_image(tall, 160, 90)
    assert out.size == (160, 90) and out.mode == "RGB"
