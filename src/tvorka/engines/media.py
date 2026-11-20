"""Writing and reading media files (PyAV — no external ffmpeg needed)."""

from __future__ import annotations

import wave
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

IMAGE_FORMATS = ("png", "jpg", "webp")
VIDEO_FORMATS = ("mp4", "webm", "gif")
AUDIO_FORMATS = ("wav", "mp3", "flac")


def save_image(image: Image.Image, path: Path, meta: dict[str, Any] | None = None) -> None:
    ext = path.suffix.lower()
    if ext == ".png":
        info = PngInfo()
        for key, value in (meta or {}).items():
            info.add_text(key, str(value))
        image.save(path, pnginfo=info)
    elif ext in (".jpg", ".jpeg"):
        image.convert("RGB").save(path, quality=95, subsampling=0)
    else:
        image.save(path, quality=95, method=4)


def fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Center-crop to the target aspect ratio, then resize."""
    image = image.convert("RGB")
    src_ratio, dst_ratio = image.width / image.height, width / height
    if src_ratio > dst_ratio:
        new_w = round(image.height * dst_ratio)
        left = (image.width - new_w) // 2
        image = image.crop((left, 0, left + new_w, image.height))
    elif src_ratio < dst_ratio:
        new_h = round(image.width / dst_ratio)
        top = (image.height - new_h) // 2
        image = image.crop((0, top, image.width, top + new_h))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def frames_to_uint8(frames: Any) -> np.ndarray:
    """Normalize pipeline output (PIL list or float/uint8 array) to (F, H, W, 3) uint8."""
    if isinstance(frames, (list, tuple)) and frames and isinstance(frames[0], Image.Image):
        return np.stack([np.asarray(f.convert("RGB")) for f in frames])
    array = np.asarray(frames)
    if array.ndim == 5:
        array = array[0]
    if array.dtype != np.uint8:
        array = (np.clip(array.astype(np.float32), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return array[..., :3]


def resize_frames(frames: np.ndarray, width: int, height: int) -> np.ndarray:
    """Crop every frame to the target aspect and resize it (Lanczos)."""
    return np.stack([np.asarray(fit_image(Image.fromarray(f), width, height)) for f in frames])


def resample_frames(frames: np.ndarray, src_fps: float, dst_fps: float) -> np.ndarray:
    """Change the frame rate while keeping the clip's duration (drop or repeat frames)."""
    if src_fps == dst_fps or len(frames) < 2:
        return frames
    duration = len(frames) / src_fps
    count = max(1, round(duration * dst_fps))
    index = np.minimum((np.arange(count) * src_fps / dst_fps).astype(np.int64), len(frames) - 1)
    return frames[index]


def write_video(frames: np.ndarray, fps: int, path: Path, quality: int = 18) -> None:
    """Encode frames to mp4 (H.264), webm (VP9) or gif depending on the suffix."""
    ext = path.suffix.lower()
    if ext == ".gif":
        images = [Image.fromarray(f) for f in frames]
        images[0].save(path, save_all=True, append_images=images[1:], loop=0,
                       duration=max(20, round(1000 / fps)), optimize=False)
        return
    import av

    height, width = frames.shape[1] // 2 * 2, frames.shape[2] // 2 * 2  # yuv420p needs even sizes
    codec, options = ("libvpx-vp9", {"crf": str(quality + 12), "b": "0"}) if ext == ".webm" else (
        "libx264", {"crf": str(quality), "preset": "medium"})
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=Fraction(fps))
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.options = options
        for frame in frames:
            packet_frame = av.VideoFrame.from_ndarray(
                np.ascontiguousarray(frame[:height, :width]), format="rgb24")
            for packet in stream.encode(packet_frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def write_audio(samples: np.ndarray, rate: int, path: Path) -> None:
    """Save mono float audio in [-1, 1] as wav, mp3 or flac."""
    samples = np.clip(np.asarray(samples, dtype=np.float32).reshape(-1), -1.0, 1.0)
    pcm = (samples * 32767.0).astype(np.int16)
    ext = path.suffix.lower()
    if ext == ".wav":
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(pcm.tobytes())
        return
    import av

    codec = "libmp3lame" if ext == ".mp3" else "flac"
    out_rate = rate if codec == "flac" or rate in (8000, 16000, 22050, 24000, 32000, 44100, 48000) else 44100
    with av.open(str(path), "w") as container:
        stream = container.add_stream(codec, rate=out_rate)
        stream.layout = "mono"
        if codec == "libmp3lame":
            stream.bit_rate = 192_000
        resampler = av.AudioResampler(format=stream.format, layout="mono", rate=out_rate)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = rate
        for chunk in [*resampler.resample(frame), *resampler.resample(None)]:
            for packet in stream.encode(chunk):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def read_audio(path: Path, max_seconds: float = 3600.0, rate: int | None = None) -> tuple[np.ndarray, int]:
    """Decode any audio file (or the sound of a video) to mono float32.

    ``rate`` resamples to that many samples per second (speech recognition needs 16000).
    """
    if path.suffix.lower() == ".wav" and rate is None:
        try:
            with wave.open(str(path), "rb") as handle:
                rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
                raw = handle.readframes(min(handle.getnframes(), int(max_seconds * rate)))
            if width == 2:
                data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                return (data.reshape(-1, channels).mean(axis=1) if channels > 1 else data), rate
        except (wave.Error, EOFError, ValueError):
            pass
    import av

    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = rate or stream.rate or 44100
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        limit, have = int(max_seconds * rate), 0
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
                have += chunks[-1].size
            if have >= limit:
                break
        for out in resampler.resample(None):  # what the resampler still holds
            chunks.append(out.to_ndarray().reshape(-1))
    data = np.concatenate(chunks)[: int(max_seconds * rate)] if chunks else np.zeros(1, dtype=np.float32)
    return data, rate


def peaks(samples: np.ndarray, buckets: int) -> np.ndarray:
    """Peak amplitude per bucket, normalised to [0, 1]."""
    if samples.size == 0:
        return np.zeros(buckets, dtype=np.float32)
    edges = np.linspace(0, samples.size, buckets + 1, dtype=np.int64)
    out = np.array([np.abs(samples[a:b]).max() if b > a else 0.0
                    for a, b in pairwise(edges)], dtype=np.float32)
    top = float(out.max())
    return out / top if top > 0 else out


# ------------------------------------------------------------------ frames and voice-over for videos
def video_frame(path: Path, seconds: float | None = None) -> Image.Image:
    """The frame shown at ``seconds`` (the last one when None), as a picture."""
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        last = None
        if seconds is not None and stream.time_base:
            container.seek(int(max(0.0, seconds) / stream.time_base), stream=stream)
        for frame in container.decode(stream):
            last = frame
            if seconds is not None and frame.time is not None and frame.time >= seconds - 0.001:
                break
    if last is None:
        raise ValueError(f"{path.name}: no frames")
    return last.to_image()


def read_video(path: Path) -> tuple[np.ndarray, float]:
    """All frames (RGB) and the frame rate; for short generated clips."""
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or stream.guessed_rate or 24)
        frames = [frame.to_ndarray(format="rgb24") for frame in container.decode(stream)]
    if not frames:
        raise ValueError(f"{path.name}: no frames")
    return np.stack(frames), fps


def mux_audio(video: Path, audio: Path, out: Path) -> float:
    """Lay ``audio`` over ``video`` as a new MP4; returns its length in seconds.

    When the speech is longer, the picture holds its last frame until the speech ends;
    when it is shorter, the rest is silent.
    """
    import math

    import av

    frames, fps = read_video(video)
    samples, rate = read_audio(audio, rate=48_000)
    seconds = max(len(frames) / fps, samples.size / rate)
    total = math.ceil(seconds * fps)
    if total > len(frames):
        frames = np.concatenate([frames, np.repeat(frames[-1:], total - len(frames), axis=0)])
    samples = np.pad(samples, (0, max(0, round(seconds * rate) - samples.size)))
    height, width = frames.shape[1] // 2 * 2, frames.shape[2] // 2 * 2
    with av.open(str(out), "w") as container:
        picture = container.add_stream("libx264", rate=Fraction(fps).limit_denominator(1001))
        picture.width, picture.height, picture.pix_fmt = width, height, "yuv420p"
        picture.options = {"crf": "18", "preset": "medium"}
        try:
            sound = container.add_stream("aac", rate=rate)
        except ValueError:  # UnknownCodecError: an FFmpeg build without AAC; MP3 also plays in MP4
            sound = container.add_stream("libmp3lame", rate=rate)
        sound.layout = "mono"
        for frame in frames:
            for packet in picture.encode(av.VideoFrame.from_ndarray(
                    np.ascontiguousarray(frame[:height, :width]), format="rgb24")):
                container.mux(packet)
        for packet in picture.encode():
            container.mux(packet)
        resampler = av.AudioResampler(format=sound.format, layout="mono", rate=rate)
        chunk = av.AudioFrame.from_ndarray(np.clip(samples, -1, 1).astype(np.float32).reshape(1, -1),
                                           format="flt", layout="mono")
        chunk.sample_rate = rate
        for piece in [*resampler.resample(chunk), *resampler.resample(None)]:
            for packet in sound.encode(piece):
                container.mux(packet)
        for packet in sound.encode():
            container.mux(packet)
    return seconds
