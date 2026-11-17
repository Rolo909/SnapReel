from __future__ import annotations

import errno
import io
import urllib.error
from pathlib import Path

import pytest

from tvorka.core.hub import HubError, is_network_error
from tvorka.workers import download_proc
from tvorka.workers.download_proc import DownloadError, check_disk, error_code


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
    from tvorka.core.hub import DownloadPlan

    repo = tmp_path / "models--a--b"
    (repo / "snapshots" / "rev" / "unet").mkdir(parents=True)
    (repo / "blobs").mkdir()
    (repo / "snapshots" / "rev" / "unet" / "w.safetensors").write_bytes(b"x" * 100)
    (repo / "blobs" / "abc.part").write_bytes(b"x" * 30)  # ours: resumed next time
    (repo / "blobs" / "def").write_bytes(b"x" * 40)  # finished, not laid out yet
    (repo / "blobs" / "abc.1234abcd.incomplete").write_bytes(b"x" * 50)  # huggingface_hub's: never reused
    plan = DownloadPlan(files=["unet/w.safetensors", "vae/w.safetensors"], total_bytes=300,
                        sizes={"unet/w.safetensors": 100, "vae/w.safetensors": 200})
    assert download_proc._present_bytes(repo, plan) == 170
    download_proc._drop_stale_temp_files(repo)
    assert not list((repo / "blobs").glob("*.incomplete")) and (repo / "blobs" / "abc.part").exists()


def test_duplicate_blobs_are_dropped_after_layout(tmp_path: Path) -> None:
    repo = tmp_path / "models--a--b"
    (repo / "snapshots" / "rev" / "unet").mkdir(parents=True)
    (repo / "blobs").mkdir()
    (repo / "snapshots" / "rev" / "unet" / "w.safetensors").write_bytes(b"x" * 100)  # a copy, no symlinks
    (repo / "blobs" / "etag1").write_bytes(b"x" * 100)  # the same file again
    (repo / "blobs" / "etag2.part").write_bytes(b"x" * 100)  # unfinished: keep
    download_proc._drop_duplicate_blobs(repo)
    assert sorted(p.name for p in (repo / "blobs").iterdir()) == ["etag2.part"]


class RangeServer:
    """Serves one payload with HTTP ranges; can drop the connection after ``cut`` bytes."""

    def __init__(self, payload: bytes) -> None:
        import http.server
        import threading

        self.payload, self.cut, self.ranges = payload, 0, []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                start = int(self.headers.get("Range", "bytes=0-")[6:].split("-")[0])
                server.ranges.append(start)
                body = server.payload[start:]
                self.send_response(206 if start else 200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if server.cut:
                    self.wfile.write(body[:server.cut])
                    self.wfile.flush()
                    self.connection.shutdown(2)  # the network is gone
                    return
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/blob"


def test_fetch_resumes_after_a_lost_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)
    payload = bytes(range(256)) * 4000
    server = RangeServer(payload)
    partial = tmp_path / "blob.part"
    server.cut = 300_000
    with pytest.raises(Exception) as info:
        download_proc._fetch(server.url, partial, len(payload))
    assert error_code(info.value) == "network"
    kept = partial.stat().st_size
    assert kept >= 300_000
    server.cut = 0
    download_proc._fetch(server.url, partial, len(payload))
    assert server.ranges[-1] == kept and partial.read_bytes() == payload
    server.httpd.shutdown()
