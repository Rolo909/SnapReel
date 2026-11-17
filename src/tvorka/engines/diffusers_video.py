"""Video generation: text-to-video and image-to-video through diffusers pipelines."""

from __future__ import annotations

import inspect
import logging
import time
from pathlib import Path
from typing import Any

from PIL import Image

from tvorka.core import advisor, paths
from tvorka.core.jobs import Job, Result, output_file
from tvorka.engines import media
from tvorka.engines.base import Context, EngineError
from tvorka.engines.diffusers_base import DiffusersEngine

log = logging.getLogger(__name__)


class DiffusersVideoEngine(DiffusersEngine):
    def generate(self, job: Job, ctx: Context) -> list[Result]:
        spec = self.spec
        target = (int(job.get("width", spec.native[0])), int(job.get("height", spec.native[1])))
        width, height, _route = advisor.resolution_route(spec, *target)
        seconds = job.get("seconds")
        frames, _capped = advisor.video_frames(spec, job.get("frames"),
                                               float(seconds) if seconds else None)
        model_fps = max(1, int(spec.default("fps", 16)))
        fps = max(1, int(job.get("fps", model_fps)))
        steps = max(1, int(job.get("steps", spec.default("steps", 30))))
        seed = self.pick_seed(job.get("seed"))
        negative = (job.get("negative") or "").strip() or None
        reference = job.get("reference")
        fmt = job.get("format", "mp4")

        pipe = self.base_pipe()
        takes_image = "image" in inspect.signature(pipe.__call__).parameters
        image = None
        if reference:
            if not takes_image:
                if not spec.i2v_pipeline:
                    raise EngineError("reference_unsupported", spec.name)
                import diffusers

                cls = getattr(diffusers, spec.i2v_pipeline, None)
                if cls is None:
                    raise EngineError("reference_unsupported", spec.i2v_pipeline)
                pipe = self.switch_class(cls)
            try:
                image = media.fit_image(Image.open(reference), width, height)
            except OSError as exc:
                raise EngineError("reference_unreadable", str(reference)) from exc
        elif takes_image and spec.requires_reference:
            raise EngineError("needs_reference", spec.name)

        started = time.perf_counter()
        output = self.run(pipe, {
            "prompt": job.prompt, "negative_prompt": negative, "image": image,
            "width": width, "height": height, "num_frames": frames,
            "num_inference_steps": steps, "guidance_scale": float(job.get("guidance", 5.0)),
            "generator": self.generator(seed), "output_type": "np",
        }, ctx, 0.0, 0.92)

        ctx.progress(0.94, "encode")
        array = media.frames_to_uint8(output.frames[0] if hasattr(output, "frames") else output[0])
        generated = (int(array.shape[2]), int(array.shape[1]))
        if generated != target:
            array = media.resize_frames(array, *target)
        # The model's frames are spaced for its own fps; keep the duration at any output fps.
        array = media.resample_frames(array, model_fps, fps)
        path = output_file(ctx.settings.output_path(), "video", fmt)
        media.write_video(array, fps, path)
        thumb = self._poster(array, path)
        ctx.progress(1.0, "save")
        return [Result.make(job, path, spec.name, time.perf_counter() - started, str(thumb),
                            seed=seed, width=int(array.shape[2]), height=int(array.shape[1]),
                            frames=int(array.shape[0]), fps=fps, generated=list(generated),
                            duration=round(array.shape[0] / fps, 2))]

    @staticmethod
    def _poster(frames: Any, video: Path) -> Path:
        folder = paths.data_dir() / "thumbs"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{video.parent.name}-{video.stem}.jpg"
        poster = Image.fromarray(frames[min(len(frames) - 1, len(frames) // 4)])
        poster.thumbnail((640, 640))
        poster.save(target, quality=85)
        return target
