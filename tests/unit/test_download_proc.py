from __future__ import annotations

import errno
import io
import urllib.error
from pathlib import Path

import pytest

from snapreel.core.hub import HubError, is_network_error
from snapreel.workers import download_proc
from snapreel.workers.download_proc import DownloadError, check_disk, error_code


class GatedRepoError(Exception):
    pass


class RepositoryNotFoundError(Exception):
    pass


@pytest.mark.parametrize(("exc", "code"), [
    (HubError("gated", "x"), "gated"),
    (DownloadError("disk"), "disk"),
    (GatedRepoError("401 Client Error"), "gated"),
    (RepositoryNotFoundError("nope"), "not_found"),
    (urllib.error.HTTPError("https://x", 404, "Not Found", {}, io.BytesIO()), "not_found"),
    (urllib.error.HTTPError("https://x", 503, "Busy", {}, io.BytesIO()), "network"),
    (urllib.error.URLError("handshake timed out"), "network"),
    (ConnectionResetError(), "network"),
    (TimeoutError(), "network"),
    (OSError(errno.ENOSPC, "No space left on device"), "disk"),
    (ValueError("bug"), "failed"),
])
def test_error_code(exc: Exception, code: str) -> None:
    assert error_code(exc) == code


def test_httpx_errors_count_as_network() -> None:
    httpx = pytest.importorskip("httpx")
    assert is_network_error(httpx.ConnectError("refused"))
    assert not is_network_error(ValueError())


def test_check_disk(tmp_path: Path) -> None:
    check_disk(tmp_path / "not" / "created" / "yet", 1024)
    with pytest.raises(DownloadError) as info:
        check_disk(tmp_path, 2 * 1024**5)
    assert info.value.code == "disk"


def test_present_bytes_counts_partial_and_complete(tmp_path: Path) -> None:
    from snapreel.core.hub import DownloadPlan

    repo = tmp_path / "models--a--b"
    (repo / "snapshots" / "rev" / "unet").mkdir(parents=True)
    (repo / "blobs").mkdir()
    (repo / "snapshots" / "rev" / "unet" / "w.safetensors").write_bytes(b"x" * 100)
    (repo / "blobs" / "abc.incomplete").write_bytes(b"x" * 30)
    plan = DownloadPlan(files=["unet/w.safetensors", "vae/w.safetensors"], total_bytes=300,
                        sizes={"unet/w.safetensors": 100, "vae/w.safetensors": 200})
    assert download_proc._present_bytes(repo, plan) == 130
