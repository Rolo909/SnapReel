"""Is there a newer SnapReel release on GitHub? One small request, only when allowed."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from snapreel import __version__

RELEASES_API = "https://api.github.com/repos/Rolo909/SnapReel/releases/latest"


@dataclass(frozen=True)
class Release:
    version: str
    url: str


def parse_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_release(timeout: float = 8.0) -> Release | None:
    """The latest published release if it is newer than this app, else None."""
    request = urllib.request.Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "SnapReel"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read(200_000).decode("utf-8"))
    tag = str(data.get("tag_name") or "")
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    return Release(tag.lstrip("v"), str(data.get("html_url") or ""))
