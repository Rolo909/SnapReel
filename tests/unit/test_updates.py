from __future__ import annotations

import io
import json

import pytest

from snapreel.core import updates


@pytest.mark.parametrize(("candidate", "newer"), [("v1.0.1", True), ("1.1.0", True), ("v1.0.0", False),
                                                  ("0.9.9", False), ("v2", True)])
def test_is_newer(candidate: str, newer: bool) -> None:
    assert updates.is_newer(candidate, "1.0.0") is newer


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def serve(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr(updates.urllib.request, "urlopen",
                        lambda *a, **k: Response(json.dumps(payload).encode()))


def test_latest_release(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"tag_name": "v99.0.0",
                        "html_url": "https://github.com/Rolo909/SnapReel/releases/tag/v99.0.0"})
    release = updates.latest_release()
    assert release is not None and release.version == "99.0.0" and release.url.endswith("v99.0.0")


def test_same_or_prerelease_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"tag_name": "v1.0.0"})
    assert updates.latest_release() is None
    serve(monkeypatch, {"tag_name": "v9.0.0", "prerelease": True})
    assert updates.latest_release() is None
