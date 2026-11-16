"""Image generation: text-to-image, image-to-image and IP-Adapter references."""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any

from PIL import Image

from snapreel.core import advisor
from snapreel.core.jobs import Job, Result, output_file
from snapreel.engines import media, upscale
from snapreel.engines.base import Context, EngineError
from snapreel.engines.diffusers_base import DiffusersEngine, apply_plan

log = logging.getLogger(__name__)

IP_ADAPTERS = {
    "ip_adapter_sdxl": ("sdxl_models", "ip-adapter_sdxl.safetensors"),
    "ip_adapter_sd15": ("models", "ip-adapter_sd15.safetensors"),
}


class DiffusersImageEngine(DiffusersEngine):
    def __init__(self, spec: Any, plan: Any) -> None:
        super().__init__(spec, plan)
        self._ip_loaded = False
        self._loras: list[tuple[str, float]] = []  # (file, weight) currently attached
        self._upscaler: upscale.Upscaler | None = None

    def generate(self, job: Job, ctx: Context) -> list[Result]:
        spec = self.spec
        target = (int(job.get("width", spec.native[0])), int(job.get("height", spec.native[1])))
        width, height, route = advisor.resolution_route(spec, *target)
        steps = max(1, int(job.get("steps", spec.default("steps", 20))))
        count = max(1, min(8, int(job.get("count", 1))))
        seed = self.pick_seed(job.get("seed"))
        negative = (job.get("negative") or "").strip() or None
        reference = job.get("reference")
        mode = job.get("reference_mode") or (spec.reference[0] if spec.reference else "")
        strength = float(job.get("strength", 0.6))
        fmt = job.get("format", "png")

        kwargs: dict[str, Any] = {
            "prompt": job.prompt, "negative_prompt": negative, "width": width, "height": height,
            "num_inference_steps": steps, "guidance_scale": float(job.get("guidance", 0.0)),
        }
        ref_image = None
        if reference:
            if not spec.reference or mode not in spec.reference:
                raise EngineError("reference_unsupported", spec.name)
            try:
                ref_image = Image.open(reference)
                ref_image.load()
            except OSError as exc:
                raise EngineError("reference_unreadable", str(reference)) from exc

        self._apply_loras(job.get("loras") or [])
        pipe = self._prepare(ref_image, mode, strength, width, height, steps, kwargs, ctx)

        results: list[Result] = []
        for index in range(count):
            ctx.check()
            started = time.perf_counter()
            image_seed = seed + index
            kwargs["generator"] = self.generator(image_seed)
            lo, hi = index / count, (index + 0.95) / count
            quality = route == "upscale" and job.get("upscale_mode", "quality") == "quality"
            mid = lo + (hi - lo) * (0.6 if quality else 1.0)
            image = self.run(pipe, kwargs, ctx, lo, mid).images[0]
            upscaler = "lanczos" if route == "upscale" else ""
            if quality:
                image, upscaler = self._super_resolve(image, target, ctx, mid, hi)
            if image.size != target:
                image = media.fit_image(image, *target)
            ctx.progress(hi, "save")
            path = output_file(ctx.settings.output_path(), "image", fmt)
            media.save_image(image, path, {
                "prompt": job.prompt, "negative_prompt": negative or "", "model": spec.id,
                "seed": image_seed, "steps": steps, "guidance": kwargs["guidance_scale"],
                "software": "SnapReel",
            })
            results.append(Result.make(job, path, spec.name, time.perf_counter() - started,
                                       seed=image_seed, width=image.width, height=image.height,
                                       route=route, generated=[width, height], upscaler=upscaler))
        return results

    def _super_resolve(self, image: Image.Image, target: tuple[int, int], ctx: Context,
                       lo: float, hi: float) -> tuple[Image.Image, str]:
        """Enlarge with Real-ESRGAN; without its weights (offline) fall back to Lanczos."""
        if self._upscaler is None:
            ctx.progress(lo, "download_extra")
            try:
                from huggingface_hub import hf_hub_download

                weights = hf_hub_download(upscale.REPO, upscale.WEIGHTS,
                                          cache_dir=str(ctx.settings.hub_path()),
                                          token=ctx.settings.token())
                device = self.plan.device if self.plan.device in ("cuda", "mps") else "cpu"
                self._upscaler = upscale.Upscaler(weights, device)
            except Exception as exc:  # noqa: BLE001 - enlarging still works, just plainer
                log.warning("Real-ESRGAN unavailable, using Lanczos: %s", exc)
                return image, "lanczos"
        def tick(fraction: float) -> None:
            ctx.check()
            ctx.progress(lo + (hi - lo) * fraction, "upscale")

        return self._upscaler.to_size(image, *target, tick=tick), "realesrgan"

    def unload(self) -> None:
        if self._upscaler is not None:
            self._upscaler.close()
            self._upscaler = None
        super().unload()

    # ------------------------------------------------------------------
    def _apply_loras(self, loras: list[dict[str, Any]]) -> None:
        """Attach exactly the LoRAs this job lists; detach the previous job's set if it differs.

        LoRA layers live in the shared UNet / text encoder, so they also apply to the
        img2img and IP-Adapter flavours of the pipeline.
        """
        wanted = [(str(Path(item["path"])), float(item.get("weight", 1.0))) for item in loras]
        if wanted == self._loras:
            return
        if self._loras:
            self.pipe.unload_lora_weights()
            self._loras = []
        if not wanted:
            return
        if not hasattr(self.pipe, "load_lora_weights"):
            raise EngineError("lora_unsupported", self.spec.name)
        names = []
        for index, (file, _weight) in enumerate(wanted):
            path = Path(file)
            name = f"lora{index}"
            try:
                self.pipe.load_lora_weights(str(path.parent), weight_name=path.name, adapter_name=name)
            except Exception as exc:
                self.pipe.unload_lora_weights()
                raise EngineError("lora_failed", f"{path.name}: {exc.__class__.__name__}: {exc}") from exc
            names.append(name)
        self.pipe.set_adapters(names, adapter_weights=[weight for _, weight in wanted])
        self._loras = wanted

    def _prepare(self, ref: Image.Image | None, mode: str, strength: float, width: int,
                 height: int, steps: int, kwargs: dict[str, Any], ctx: Context) -> Any:
        """Select the pipeline flavour for this job and add reference arguments."""
        want_ip = ref is not None and mode in IP_ADAPTERS
        if self._ip_loaded and not want_ip:
            self.pipe.unload_ip_adapter()
            self._ip_loaded = False

        if ref is None:
            return self.base_pipe()

        if mode == "img2img":
            pipe = self.switch_class(self._img2img_class())
            kwargs["image"] = media.fit_image(ref, width, height)
            kwargs["strength"] = max(0.05, min(1.0, strength))
            # Turbo-style schedules run steps * strength iterations; keep at least one.
            if int(steps * kwargs["strength"]) < 1:
                kwargs["num_inference_steps"] = int(1 / kwargs["strength"]) + 1
            return pipe

        if mode == "native":
            pipe = self.base_pipe()
            kwargs["image"] = media.fit_image(ref, width, height)
            return pipe

        pipe = self.base_pipe()
        if not self._ip_loaded:
            ctx.progress(0.0, "download_extra")
            self._load_ip_adapter(pipe, mode, ctx)
        pipe.set_ip_adapter_scale(max(0.0, min(1.0, strength)))
        kwargs["ip_adapter_image"] = ref.convert("RGB")
        return pipe

    def _img2img_class(self) -> type:
        import diffusers

        if self.spec.i2i_pipeline:
            cls = getattr(diffusers, self.spec.i2i_pipeline, None)
            if cls is None:
                raise EngineError("reference_unsupported", self.spec.i2i_pipeline)
            return cls
        try:
            from diffusers.pipelines.auto_pipeline import (
                AUTO_IMAGE2IMAGE_PIPELINES_MAPPING,
                _get_task_class,
            )

            assert self._base_cls is not None
            return _get_task_class(AUTO_IMAGE2IMAGE_PIPELINES_MAPPING, self._base_cls.__name__)
        except Exception as exc:
            raise EngineError("reference_unsupported", str(exc)) from exc

    def _load_ip_adapter(self, pipe: Any, mode: str, ctx: Context) -> None:
        subfolder, weight = IP_ADAPTERS[mode]
        stateful = self.plan.mode in ("offload", "stream")
        if stateful:
            pipe.remove_all_hooks()
        if self.plan.attention_slicing:
            # IP-Adapter installs its own attention processors; sliced ones break loading.
            pipe.disable_attention_slicing()
        try:
            pipe.load_ip_adapter(
                "h94/IP-Adapter", subfolder=subfolder, weight_name=weight,
                cache_dir=str(ctx.settings.hub_path()), token=ctx.settings.token(),
            )
        except Exception as exc:
            if stateful:
                apply_plan(pipe, self.plan)
            raise EngineError("ip_adapter_failed", f"{exc.__class__.__name__}: {exc}") from exc
        self._ip_loaded = True
        if stateful or self.plan.mode in ("gpu", "cpu"):
            # Re-enabling sliced attention would replace the IP-Adapter processors.
            apply_plan(pipe, dataclasses.replace(self.plan, attention_slicing=False))
        else:  # hybrid: streamed parts keep their hooks, the new encoder just moves over
            encoder = getattr(pipe, "image_encoder", None)
            if encoder is not None:
                encoder.to(self.plan.device)
