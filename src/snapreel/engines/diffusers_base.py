"""Shared machinery for diffusers-based engines: loading, memory plans, cancellation."""

from __future__ import annotations

import inspect
import logging
import random
from pathlib import Path
from typing import Any

from snapreel.core.advisor import Plan
from snapreel.engines.base import (
    Cancelled,
    Context,
    Engine,
    EngineError,
    device_available,
    free_memory,
    quiet_libraries,
)

log = logging.getLogger(__name__)

SINGLE_FILE_EXT = (".safetensors", ".ckpt")


def torch_dtype(name: str) -> Any:
    import torch

    return {"fp16": torch.float16, "bf16": torch.bfloat16}.get(name, torch.float32)


def apply_plan(pipe: Any, plan: Plan) -> None:
    """Place pipeline components in memory exactly as the advisor decided."""
    import torch

    device = torch.device(plan.device)
    if plan.mode == "gpu":
        pipe.to(device)
    elif plan.mode == "offload":
        pipe.enable_model_cpu_offload(device=device)
    elif plan.mode == "hybrid":
        from diffusers.hooks import apply_group_offloading

        for name, component in pipe.components.items():
            if not isinstance(component, torch.nn.Module):
                continue
            if name in plan.stream:
                # low_cpu_mem_usage pins tensors on the fly: pre-pinning a 9 GB text encoder
                # fails on a 16 GB Windows machine (cuMemHostAlloc out of memory).
                options = {"onload_device": device, "offload_device": torch.device("cpu"),
                           "offload_type": "leaf_level", "low_cpu_mem_usage": True,
                           # Overlapped transfers are tuned (and verified) for CUDA streams only.
                           "use_stream": device.type == "cuda"}
                if hasattr(component, "enable_group_offload"):
                    component.enable_group_offload(**options)
                else:
                    apply_group_offloading(module=component, **options)
            else:
                component.to(device)
    elif plan.mode == "stream":
        pipe.enable_sequential_cpu_offload(device=device)
    else:
        pipe.to("cpu")

    vae = getattr(pipe, "vae", None)
    if plan.vae_tiling and vae is not None:
        for method in ("enable_tiling", "enable_slicing"):
            if hasattr(vae, method):
                try:
                    getattr(vae, method)()
                except Exception as exc:  # noqa: BLE001 - optional optimisation
                    log.debug("%s unavailable: %s", method, exc)
    if plan.attention_slicing and hasattr(pipe, "enable_attention_slicing"):
        try:
            pipe.enable_attention_slicing()
        except Exception as exc:  # noqa: BLE001 - not every attention processor supports it
            log.debug("attention slicing unavailable: %s", exc)


class DiffusersEngine(Engine):
    """Loads any diffusers pipeline from a local folder or single-file checkpoint."""

    def __init__(self, spec: Any, plan: Plan) -> None:
        super().__init__(spec, plan)
        self.pipe: Any = None
        self._base_cls: type | None = None

    # --- lifecycle -----------------------------------------------------
    def load(self, ctx: Context) -> None:
        ctx.progress(0.0, "import")
        import diffusers

        quiet_libraries()
        if not device_available(self.plan.device):
            raise EngineError("cuda_unavailable")
        path = self.model_path(ctx)
        dtype = torch_dtype(self.plan.dtype)
        ctx.progress(0.1, "load")
        try:
            if path.is_file() and path.suffix.lower() in SINGLE_FILE_EXT:
                self.pipe = self._load_single_file(diffusers, path, dtype)
            else:
                self.pipe = self._load_folder(diffusers, path, dtype, ctx.store.variant(self.spec))
        except EngineError:
            raise
        except Exception as exc:
            raise EngineError("load_failed", f"{exc.__class__.__name__}: {exc}") from exc
        ctx.check()
        self._base_cls = type(self.pipe)
        self.pipe.set_progress_bar_config(disable=True)
        ctx.progress(0.8, "place")
        apply_plan(self.pipe, self.plan)
        ctx.progress(1.0, "ready")

    @staticmethod
    def _load_folder(diffusers: Any, path: Path, dtype: Any, variant: str | None) -> Any:
        kwargs: dict[str, Any] = {"dtype": dtype, "local_files_only": True}
        if variant:
            kwargs["variant"] = variant
        try:
            return diffusers.DiffusionPipeline.from_pretrained(str(path), **kwargs)
        except (OSError, ValueError):
            if not variant:
                raise
            kwargs.pop("variant")  # folder mixes variants; let diffusers pick what exists
            return diffusers.DiffusionPipeline.from_pretrained(str(path), **kwargs)

    @staticmethod
    def _load_single_file(diffusers: Any, path: Path, dtype: Any) -> Any:
        from snapreel.core.local_import import SINGLE_FILE_PIPELINES, single_file_family

        family = single_file_family(path)
        if family not in SINGLE_FILE_PIPELINES:
            raise EngineError("unsupported", f"{path.name} ({family or 'unknown'})")
        cls = getattr(diffusers, SINGLE_FILE_PIPELINES[family])
        return cls.from_single_file(str(path), dtype=dtype)

    def unload(self) -> None:
        pipe, self.pipe = self.pipe, None
        if pipe is not None:
            try:
                pipe.remove_all_hooks()
            except Exception:  # noqa: BLE001 - teardown must not fail
                pass
            del pipe
        free_memory()

    # --- helpers -------------------------------------------------------
    def switch_class(self, cls: type) -> Any:
        """Re-wrap the loaded components in another pipeline class (e.g. img2img)."""
        if type(self.pipe) is cls:
            return self.pipe
        offload = self.plan.mode == "offload"
        if offload:
            self.pipe.remove_all_hooks()
        try:
            # Without an explicit dtype from_pipe casts every component to float32,
            # doubling memory use and slowing generation several times.
            new = cls.from_pipe(self.pipe, dtype=torch_dtype(self.plan.dtype))
        except Exception as exc:
            if offload:
                apply_plan(self.pipe, self.plan)
            raise EngineError("reference_unsupported", str(exc)) from exc
        new.set_progress_bar_config(disable=True)
        if offload:
            new.remove_all_hooks()
            new.enable_model_cpu_offload(device=self.plan.device)
        self.pipe = new
        return new

    def base_pipe(self) -> Any:
        assert self._base_cls is not None
        return self.switch_class(self._base_cls)

    def run(self, pipe: Any, kwargs: dict[str, Any], ctx: Context,
            lo: float = 0.0, hi: float = 1.0) -> Any:
        """Call a pipeline with only the arguments it accepts, reporting step progress."""
        import torch

        params = inspect.signature(pipe.__call__).parameters
        call = {k: v for k, v in kwargs.items() if v is not None and k in params}
        dropped = sorted(k for k, v in kwargs.items() if v is not None and k not in params)
        if dropped:
            log.info("%s ignores: %s", type(pipe).__name__, ", ".join(dropped))
        total = max(1, int(kwargs.get("num_inference_steps") or 1))
        park = self.plan.mode == "hybrid"
        if park:
            self._unpark(pipe)

        if "callback_on_step_end" in params:
            def on_step(p: Any, step: int, _t: Any, state: dict) -> dict:
                steps = max(1, int(getattr(p, "num_timesteps", total) or total))
                ctx.progress(lo + (hi - lo) * min(1.0, (step + 1) / steps), "steps")
                if ctx.cancelled:
                    # Not ``p._interrupt``: that only skips the remaining steps and still runs
                    # the VAE decode, which for video takes minutes (A6: 513 s to cancel).
                    raise Cancelled
                if park and step + 1 >= steps:
                    self._park(p)
                return state

            call["callback_on_step_end"] = on_step
        ctx.progress(lo, "steps")
        with torch.inference_mode():
            output = pipe(**call)
        ctx.check()
        return output

    def _park(self, pipe: Any) -> None:
        """Move the resident denoiser to RAM once denoising is done (hybrid mode).

        The VAE decode that follows needs several GB for video; with the idle denoiser
        still on the GPU, Windows silently spills into system RAM and decoding takes
        minutes instead of seconds (A6: 34 s alone vs 8–12 min in the pipeline).
        """
        import torch

        from snapreel.core.advisor import DENOISERS

        for name in DENOISERS:
            component = getattr(pipe, name, None)
            if isinstance(component, torch.nn.Module) and name not in self.plan.stream:
                component.to("cpu")
        free_memory()

    def _unpark(self, pipe: Any) -> None:
        """Bring components parked by :meth:`_park` back before the next run."""
        import torch

        for name, component in pipe.components.items():
            if (isinstance(component, torch.nn.Module) and name not in self.plan.stream
                    and next(component.parameters(), torch.empty(0)).device.type == "cpu"):
                component.to(self.plan.device)

    @staticmethod
    def generator(seed: int) -> Any:
        import torch

        # A CPU generator gives the same image for the same seed on any device.
        return torch.Generator("cpu").manual_seed(int(seed))

    @staticmethod
    def pick_seed(value: Any) -> int:
        try:
            seed = int(value)
            if seed >= 0:
                return seed
        except (TypeError, ValueError):
            pass
        return random.randint(0, 2**31 - 1)
