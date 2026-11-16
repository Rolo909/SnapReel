"""Speech engines: Silero and Transformers (VITS / Bark) run locally, Edge is online."""

from __future__ import annotations

import json
import logging
import time
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

from snapreel.core.jobs import Job, Result, output_file
from snapreel.engines import media, textnorm
from snapreel.engines.base import Context, Engine, EngineError, free_memory, quiet_libraries

log = logging.getLogger(__name__)


class SpeechEngine(Engine):
    """Common flow: normalise text, synthesise chunk by chunk, join, save."""

    pause_seconds = 0.28
    chunk_limit = 700

    def generate(self, job: Job, ctx: Context) -> list[Result]:
        started = time.perf_counter()
        text = job.prompt.strip()
        if not text:
            raise EngineError("empty_text")
        lang = (self.spec.languages[0] if len(self.spec.languages) == 1
                else textnorm.detect_lang(text))
        chunks = textnorm.split_sentences(textnorm.normalize(text, lang), self.chunk_limit)
        pieces: list[np.ndarray] = []
        rate = 0
        for index, chunk in enumerate(chunks):
            ctx.check()
            ctx.progress(index / len(chunks), "speech")
            audio, rate = self.synthesize(chunk, job)
            pieces.append(np.asarray(audio, dtype=np.float32).reshape(-1))
            pieces.append(np.zeros(int(rate * self.pause_seconds), dtype=np.float32))
        if not pieces or rate <= 0:
            raise EngineError("empty_text")
        samples = np.concatenate(pieces[:-1])
        peak = float(np.abs(samples).max()) if samples.size else 0.0
        if peak > 0:
            samples = samples / peak * 0.95
        ctx.progress(0.97, "save")
        path = output_file(ctx.settings.output_path(), "speech", job.get("format", "wav"))
        media.write_audio(samples, rate, path)
        return [Result.make(job, path, self.spec.name, time.perf_counter() - started,
                            duration=round(samples.size / rate, 2), sample_rate=rate)]

    def synthesize(self, text: str, job: Job) -> tuple[np.ndarray, int]:
        raise NotImplementedError

    def voice(self, job: Job) -> str:
        voices = [v["id"] for v in self.spec.voices]
        wanted = job.get("voice")
        return wanted if wanted in voices or not voices else voices[0]


class SileroEngine(SpeechEngine):
    def __init__(self, spec: Any, plan: Any) -> None:
        super().__init__(spec, plan)
        self.model: Any = None

    def load(self, ctx: Context) -> None:
        ctx.progress(0.0, "import")
        import torch

        path = self.model_path(ctx)
        if path.is_dir():
            files = sorted(path.glob("*.pt"))
            if not files:
                raise EngineError("not_installed", self.spec.name)
            path = files[0]
        ctx.progress(0.3, "load")
        try:
            self.model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
            self.model.to(torch.device("cpu"))
        except Exception as exc:
            raise EngineError("load_failed", f"{exc.__class__.__name__}: {exc}") from exc
        ctx.progress(1.0, "ready")

    def synthesize(self, text: str, job: Job) -> tuple[np.ndarray, int]:
        rate = int(self.spec.default("sample_rate", 48000))
        speakers = list(getattr(self.model, "speakers", []) or [])
        voice = self.voice(job)
        if speakers and voice not in speakers:
            voice = speakers[0]
        speed = float(job.get("speed", 1.0))
        names = [(0.7, "x-slow"), (0.9, "slow"), (1.1, "medium"), (1.3, "fast")]
        prosody = next((name for limit, name in names if speed < limit), "x-fast")
        try:
            if prosody == "medium":
                audio = self.model.apply_tts(text=text, speaker=voice, sample_rate=rate)
            else:
                ssml = f'<speak><prosody rate="{prosody}">{escape(text)}</prosody></speak>'
                audio = self.model.apply_tts(ssml_text=ssml, speaker=voice, sample_rate=rate)
        except ValueError as exc:  # nothing pronounceable in this chunk (e.g. only symbols)
            log.info("silero skipped a chunk: %s", exc)
            return np.zeros(1, dtype=np.float32), rate
        return audio.detach().cpu().numpy(), rate

    def unload(self) -> None:
        self.model = None
        free_memory()


class TransformersTtsEngine(SpeechEngine):
    """VITS / MMS and Bark checkpoints from the Hugging Face Hub."""

    def __init__(self, spec: Any, plan: Any) -> None:
        super().__init__(spec, plan)
        self.model: Any = None
        self.processor: Any = None
        self.kind = "vits"

    def load(self, ctx: Context) -> None:
        ctx.progress(0.0, "import")
        import torch
        import transformers

        quiet_libraries()
        path = self.model_path(ctx)
        try:
            config = json.loads((Path(path) / "config.json").read_text(encoding="utf-8"))
            self.kind = str(config.get("model_type", "vits"))
            ctx.progress(0.3, "load")
            if self.kind == "bark":
                self.chunk_limit = 180  # Bark generates ~13 s per call
                self.processor = transformers.AutoProcessor.from_pretrained(str(path))
                self.model = transformers.BarkModel.from_pretrained(str(path))
            elif self.kind == "vits":
                self.processor = transformers.AutoTokenizer.from_pretrained(str(path))
                self.model = transformers.VitsModel.from_pretrained(str(path))
            else:
                raise EngineError("unsupported", self.kind)
            device = self.plan.device if (self.plan.device != "cuda" or torch.cuda.is_available()) else "cpu"
            self.model.to(device).eval()
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError("load_failed", f"{exc.__class__.__name__}: {exc}") from exc
        ctx.progress(1.0, "ready")

    def synthesize(self, text: str, job: Job) -> tuple[np.ndarray, int]:
        import torch

        device = self.model.device
        with torch.inference_mode():
            if self.kind == "bark":
                voice = self.voice(job) or None
                inputs = self.processor(text, voice_preset=voice, return_tensors="pt")
                inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
                audio = self.model.generate(**inputs, do_sample=True)
                return audio[0].float().cpu().numpy(), int(self.model.generation_config.sample_rate)
            self.model.speaking_rate = float(job.get("speed", 1.0))
            inputs = self.processor(text.lower(), return_tensors="pt").to(device)
            if inputs["input_ids"].shape[-1] == 0:
                return np.zeros(1, dtype=np.float32), int(self.model.config.sampling_rate)
            wave = self.model(**inputs).waveform[0]
        return wave.float().cpu().numpy(), int(self.model.config.sampling_rate)

    def unload(self) -> None:
        self.model = self.processor = None
        free_memory()


class EdgeEngine(SpeechEngine):
    """Microsoft Edge online voices — the only engine that sends text over the network."""

    chunk_limit = 3000

    def load(self, ctx: Context) -> None:
        try:
            import edge_tts  # noqa: F401
        except ImportError as exc:
            raise EngineError("edge_missing") from exc
        ctx.progress(1.0, "ready")

    def synthesize(self, text: str, job: Job) -> tuple[np.ndarray, int]:
        import asyncio
        import tempfile

        import edge_tts

        speed = float(job.get("speed", 1.0))
        rate = f"{round((speed - 1.0) * 100):+d}%"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "speech.mp3"
            try:
                asyncio.run(edge_tts.Communicate(text, self.voice(job), rate=rate).save(str(target)))
            except Exception as exc:
                raise EngineError("network", f"{exc.__class__.__name__}: {exc}") from exc
            return media.read_audio(target)
