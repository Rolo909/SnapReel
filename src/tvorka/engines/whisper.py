"""Speech recognition with Whisper (transformers): a recording or the sound of a video becomes text."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from tvorka.engines.base import EngineError, device_available, free_memory, quiet_libraries

log = logging.getLogger(__name__)

RATE = 16_000  # Whisper listens at 16 kHz
SILENCE = 0.003  # mean absolute level below which a recording holds no speech
MAX_SECONDS = 4 * 3600.0


def load_speech(path: Path) -> np.ndarray:
    """Mono 16 kHz samples of any audio file or of a video's sound track."""
    from tvorka.engines.media import read_audio

    try:
        samples, _rate = read_audio(path, MAX_SECONDS, rate=RATE)
    except IndexError as exc:  # a video without sound
        raise EngineError("no_sound", path.name) from exc
    except Exception as exc:
        raise EngineError("unreadable", f"{path.name}: {exc}") from exc
    return samples.astype(np.float32, copy=False)


class WhisperEngine:
    """One loaded Whisper model; ``transcribe`` is called from a worker thread."""

    def __init__(self, path: Path, device: str = "cpu") -> None:
        self.path = path
        self.device = device if device_available(device) else "cpu"
        self.pipe: Any = None

    def load(self) -> None:
        import torch
        import transformers

        quiet_libraries()
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        try:
            processor = transformers.AutoProcessor.from_pretrained(str(self.path))
            model = transformers.AutoModelForSpeechSeq2Seq.from_pretrained(str(self.path), dtype=dtype)
            model.to(self.device).eval()
            self.pipe = transformers.pipeline("automatic-speech-recognition", model=model,
                                              tokenizer=processor.tokenizer,
                                              feature_extractor=processor.feature_extractor,
                                              device=self.device, dtype=dtype)
        except Exception as exc:
            raise EngineError("load_failed", f"{exc.__class__.__name__}: {exc}") from exc

    def transcribe(self, path: Path) -> str:
        """The words spoken in ``path``; "" when nothing was said."""
        samples = load_speech(path)
        if samples.size < RATE // 4 or float(np.abs(samples).mean()) < SILENCE:
            return ""
        result = self.pipe({"raw": samples, "sampling_rate": RATE}, chunk_length_s=30,
                           batch_size=8 if self.device == "cuda" else 1,
                           generate_kwargs={"task": "transcribe"})
        return " ".join(str(result.get("text", "")).split())

    def unload(self) -> None:
        self.pipe = None
        free_memory()
