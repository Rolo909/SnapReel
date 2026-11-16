"""Generation requests and results passed between the UI and the engines."""

from __future__ import annotations

import itertools
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_counter = itertools.count(1)


@dataclass
class Job:
    """One generation request. ``params`` is engine-specific but JSON-serializable."""

    kind: str  # image | video | speech
    model_id: str
    prompt: str
    params: dict[str, Any] = field(default_factory=dict)
    id: int = field(default_factory=lambda: next(_counter))

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


@dataclass
class Result:
    """A finished artefact, also the record stored in the history."""

    id: str
    kind: str
    path: str
    model_id: str
    model_name: str
    prompt: str
    params: dict[str, Any]
    created: float
    seconds: float = 0.0
    thumb: str = ""

    @classmethod
    def make(cls, job: Job, path: Path, model_name: str, seconds: float, thumb: str = "",
             **extra: Any) -> Result:
        return cls(uuid.uuid4().hex[:12], job.kind, str(path), job.model_id, model_name,
                   job.prompt, {**job.params, **extra}, time.time(), seconds, thumb)


class History:
    """Append-only record of everything generated, newest first."""

    def __init__(self, file: Path) -> None:
        self._file = file
        self._items: list[Result] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in raw if isinstance(raw, list) else []:
            try:
                self._items.append(Result(**item))
            except TypeError:
                continue

    def _save(self) -> None:
        try:
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(r) for r in self._items], ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self._file)
        except OSError as exc:
            log.error("history not saved: %s", exc)

    def add(self, result: Result) -> None:
        self._items.insert(0, result)
        self._save()

    def items(self, kind: str | None = None) -> list[Result]:
        """Entries whose files still exist (the user may have deleted some by hand)."""
        return [r for r in self._items
                if (kind is None or r.kind == kind) and Path(r.path).exists()]

    def remove(self, result_id: str, delete_file: bool = True) -> None:
        for item in list(self._items):
            if item.id == result_id:
                self._items.remove(item)
                if delete_file:
                    for target in (item.path, item.thumb):
                        if target:
                            Path(target).unlink(missing_ok=True)
        self._save()


def output_file(root: Path, kind: str, ext: str) -> Path:
    """``<output>/<kind>/<date>/<time>-<n>.<ext>`` — sortable and collision-free."""
    folder = root / {"image": "images", "video": "videos", "speech": "audio"}[kind] / time.strftime(
        "%Y-%m-%d"
    )
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M%S")
    for n in itertools.count(1):
        candidate = folder / f"{stamp}-{n:02d}.{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("unreachable")
