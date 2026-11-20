"""Passing work between sections: a picture to the video page, an answer to the voice page, and so on.

An :class:`Asset` is what is passed; a :class:`Route` is where it can go and in which role.
Every page says what it accepts (``Page.routes``) and takes it (``Page.receive``); the
"Send to…" menu is built from all pages, so a new link needs no change to the senders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tvorka.core.attachments import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT

KIND_OF_RESULT = {"image": "image", "video": "video", "speech": "audio"}


@dataclass(frozen=True)
class Asset:
    kind: str  # text | image | video | audio
    path: str = ""
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)  # prompt, result id…
    source: str = ""  # key of the page it comes from

    @property
    def parent(self) -> str:
        """What the work made from this asset descends from (a result id, ``chat:<id>``)."""
        return str(self.meta.get("result_id") or self.meta.get("parent") or "")


@dataclass(frozen=True)
class Route:
    page: str  # where to
    role: str  # prompt | reference | first_frame | settings | text | attachment | voiceover
    label: str  # what the menu says
    icon: str = "link"


def from_result(result: Any, source: str = "") -> Asset:
    """A finished work (``Result`` or its dict) as an asset."""
    data = result if isinstance(result, dict) else asdict(result)
    return Asset(KIND_OF_RESULT.get(data.get("kind", ""), "file"), data.get("path", ""),
                 data.get("prompt", ""), {"result_id": data.get("id", ""), "result": data}, source)


def from_path(path: str | Path, source: str = "") -> Asset | None:
    """A file dropped from outside or dragged between sections; None when no section takes it."""
    suffix = Path(path).suffix.lower()
    for kind, extensions in (("image", IMAGE_EXT), ("video", VIDEO_EXT), ("audio", AUDIO_EXT)):
        if suffix in extensions:
            return Asset(kind, str(path), source=source)
    return None


def text(content: str, source: str = "", parent: str = "") -> Asset:
    return Asset("text", text=content, meta={"parent": parent} if parent else {}, source=source)
