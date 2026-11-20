"""Who holds the video memory: the generation engine and the chat server share one graphics card.

Before a model is loaded onto the card its owner *claims* the memory it needs. If the
models already there would not fit next to it, their owners are asked to unload them;
when both fit, both stay. Without this, a chat model and an image model would overflow
the card together — on Windows not with an error but with a many-fold slowdown.

No deadlock: an owner claims before taking its own "busy" lock, and releasing another
owner only waits for that owner's busy lock (its current answer or picture).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

# release(cancelled) unloads the owner's model once it is idle; False when given up (cancelled)
Release = Callable[[Callable[[], bool]], bool]


@dataclass
class Holder:
    release: Release
    model: str = ""  # what it has on the card now, "" for nothing
    vram_gb: float = 0.0


class VideoMemory:
    def __init__(self, budget_gb: float = 0.0) -> None:
        self.budget_gb = budget_gb  # usable video memory; 0: no graphics card, nothing to share
        self._holders: dict[str, Holder] = {}
        self._claims = threading.Lock()  # one claim at a time
        self._state = threading.Lock()

    def register(self, who: str, release: Release) -> None:
        with self._state:
            self._holders[who] = Holder(release)

    def holders(self) -> dict[str, tuple[str, float]]:
        with self._state:
            return {who: (h.model, h.vram_gb) for who, h in self._holders.items() if h.model}

    def claim(self, who: str, model: str, vram_gb: float,
              cancelled: Callable[[], bool] = lambda: False) -> bool:
        """Make room for ``vram_gb`` of ``model``; False when cancelled while waiting for room."""
        with self._claims:
            with self._state:
                others = [(name, h) for name, h in self._holders.items() if name != who and h.model]
            used = sum(h.vram_gb for _name, h in others)
            if vram_gb > 0 and self.budget_gb > 0 and used + vram_gb > self.budget_gb:
                for name, holder in sorted(others, key=lambda item: -item[1].vram_gb):
                    if holder.vram_gb <= 0:
                        continue  # on the processor: in nobody's way
                    log.info("video memory: %s (%.1f GB) makes way for %s (%.1f GB)",
                             holder.model, holder.vram_gb, model, vram_gb)
                    if not holder.release(cancelled):
                        return False
                    self.released(name)
                    used -= holder.vram_gb
                    if used + vram_gb <= self.budget_gb:
                        break
            with self._state:
                if who in self._holders:
                    self._holders[who].model, self._holders[who].vram_gb = model, vram_gb
            return True

    def released(self, who: str) -> None:
        """``who`` has nothing on the card any more (it unloaded by itself or was asked to)."""
        with self._state:
            holder = self._holders.get(who)
            if holder is not None:
                holder.model, holder.vram_gb = "", 0.0
