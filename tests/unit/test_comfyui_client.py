"""Unit tests for ComfyUIClient with mocked HTTP and subprocess."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from snapreel.core.exceptions import ComfyUIError
from snapreel.infra.comfyui_client import ComfyUIClient, ComfyUIResult


@pytest.fixture()
def comfyui_dir(tmp_path: Path) -> Path:
    """Create a fake ComfyUI directory with a main.py stub."""
    main_py = tmp_path / "comfyui" / "main.py"
    main_py.parent.mkdir(parents=True)
    main_py.write_text("# stub", encoding="utf-8")
    return main_py.parent


@pytest.fixture()
def client(comfyui_dir: Path) -> ComfyUIClient:
    """Create a ComfyUIClient instance for testing."""
    return ComfyUIClient(comfyui_dir, host="127.0.0.1", port=18188)


class TestComfyUIClientInit:
    """Tests for client initialization and properties."""

    def test_base_url(self, client: ComfyUIClient) -> None:
        """Base URL is constructed from host and port."""
        assert client.base_url == "http://127.0.0.1:18188"

    def test_is_running_when_no_process(self, client: ComfyUIClient) -> None:
        """is_running is False before start()."""
        assert client.is_running is False

    def test_missing_main_py_raises(self, tmp_path: Path) -> None:
        """Start raises ComfyUIError when main.py is absent."""
        c = ComfyUIClient(tmp_path / "nonexistent")
        with pytest.raises(ComfyUIError, match="main.py not found"):
            c.start(timeout=1)


class TestHealthCheck:
    """Tests for the health_check method."""

    def test_healthy_server(self, client: ComfyUIClient) -> None:
        """Returns True when server responds."""
        mock_response = _mock_urlopen_response({"system": "ok"})
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_response):
            assert client.health_check() is True

    def test_unhealthy_server(self, client: ComfyUIClient) -> None:
        """Returns False when server is unreachable."""
        with patch(
            "snapreel.infra.comfyui_client.urllib.request.urlopen",
            side_effect=OSError("Connection refused"),
        ):
            assert client.health_check() is False


class TestSubmit:
    """Tests for workflow submission."""

    def test_submit_returns_prompt_id(self, client: ComfyUIClient) -> None:
        """submit() returns the prompt_id from the server response."""
        mock_resp = _mock_urlopen_response({"prompt_id": "abc-123"})
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            prompt_id = client.submit({"nodes": {}})
        assert prompt_id == "abc-123"

    def test_submit_no_prompt_id_raises(self, client: ComfyUIClient) -> None:
        """submit() raises when server returns no prompt_id."""
        mock_resp = _mock_urlopen_response({"error": "invalid"})
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ComfyUIError, match="no prompt_id"):
                client.submit({"nodes": {}})

    def test_submit_network_error_raises(self, client: ComfyUIClient) -> None:
        """submit() raises ComfyUIError on network failure."""
        with patch(
            "snapreel.infra.comfyui_client.urllib.request.urlopen",
            side_effect=OSError("Connection refused"),
        ):
            with pytest.raises(ComfyUIError, match="POST /prompt failed"):
                client.submit({"nodes": {}})


class TestWaitFor:
    """Tests for polling and result retrieval."""

    def test_wait_for_completed_prompt(
        self, client: ComfyUIClient, tmp_path: Path
    ) -> None:
        """wait_for() returns result when prompt is immediately complete."""
        history_resp = {
            "test-id": {
                "status": {"status_str": "success"},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "output_001.png", "subfolder": ""}
                        ]
                    }
                },
            }
        }

        # First call = history GET, second call = file download
        mock_history = _mock_urlopen_response(history_resp)
        mock_file = _mock_urlopen_response(b"fake image data", raw_bytes=True)

        call_count = 0
        def mock_urlopen(req: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_history
            return mock_file

        output_dir = tmp_path / "downloads"
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", side_effect=mock_urlopen):
            result = client.wait_for("test-id", output_dir, poll_interval=0.01, timeout=5)

        assert isinstance(result, ComfyUIResult)
        assert result.prompt_id == "test-id"
        assert len(result.output_files) == 1
        assert result.output_files[0].name == "output_001.png"

    def test_wait_for_error_prompt_raises(
        self, client: ComfyUIClient, tmp_path: Path
    ) -> None:
        """wait_for() raises when the prompt execution failed on server."""
        history_resp = {
            "err-id": {
                "status": {
                    "status_str": "error",
                    "messages": [["execution_error", {"message": "OOM"}]],
                },
                "outputs": {},
            }
        }
        mock_resp = _mock_urlopen_response(history_resp)
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ComfyUIError, match="failed"):
                client.wait_for("err-id", tmp_path, poll_interval=0.01, timeout=5)

    def test_wait_for_timeout_raises(
        self, client: ComfyUIClient, tmp_path: Path
    ) -> None:
        """wait_for() raises on timeout when prompt never completes."""
        # Return empty history every time → the prompt_id is never found
        mock_resp = _mock_urlopen_response({})
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(ComfyUIError, match="timed out"):
                client.wait_for("never-id", tmp_path, poll_interval=0.01, timeout=0.05)


class TestGetQueueStatus:
    """Tests for queue status retrieval."""

    def test_returns_queue_data(self, client: ComfyUIClient) -> None:
        """get_queue_status() returns parsed queue dict."""
        queue_data = {"queue_running": [], "queue_pending": [["abc", 1]]}
        mock_resp = _mock_urlopen_response(queue_data)
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            result = client.get_queue_status()
        assert result == queue_data


class TestDownloadFile:
    """Tests for individual file downloads."""

    def test_download_creates_file(
        self, client: ComfyUIClient, tmp_path: Path
    ) -> None:
        """download_file() saves content to disk."""
        content = b"PNG FAKE DATA"
        mock_resp = _mock_urlopen_response(content, raw_bytes=True)
        out = tmp_path / "subdir" / "image.png"
        with patch("snapreel.infra.comfyui_client.urllib.request.urlopen", return_value=mock_resp):
            result = client.download_file("image.png", "", out)
        assert result == out
        assert out.read_bytes() == content

    def test_download_failure_raises(
        self, client: ComfyUIClient, tmp_path: Path
    ) -> None:
        """download_file() raises ComfyUIError on network failure."""
        with patch(
            "snapreel.infra.comfyui_client.urllib.request.urlopen",
            side_effect=OSError("timeout"),
        ):
            with pytest.raises(ComfyUIError, match="Failed to download"):
                client.download_file("x.png", "", tmp_path / "x.png")


class TestServerLifecycle:
    """Tests for start/stop lifecycle."""

    def test_stop_terminates_process(self, client: ComfyUIClient) -> None:
        """stop() calls terminate on the subprocess."""
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        client._process = mock_proc

        client.stop()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()
        assert client._process is None

    def test_stop_noop_when_no_process(self, client: ComfyUIClient) -> None:
        """stop() does nothing when no process was started."""
        client.stop()  # Should not raise

    def test_context_manager_calls_stop(
        self, comfyui_dir: Path
    ) -> None:
        """__exit__ calls stop() even on error."""
        c = ComfyUIClient(comfyui_dir)
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None
        mock_proc.pid = 999

        # Simulate an already-started client
        c._process = mock_proc

        # Use __exit__ directly
        c.__exit__(None, None, None)
        mock_proc.terminate.assert_called_once()

    def test_is_running_with_live_process(self, client: ComfyUIClient) -> None:
        """is_running returns True when process is alive."""
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = None  # Still running
        client._process = mock_proc
        assert client.is_running is True

    def test_is_running_with_dead_process(self, client: ComfyUIClient) -> None:
        """is_running returns False when process has exited."""
        mock_proc = MagicMock(spec=subprocess.Popen)
        mock_proc.poll.return_value = 1  # Exited
        client._process = mock_proc
        assert client.is_running is False


# ── Test Helpers ──────────────────────────────────────────────────


def _mock_urlopen_response(
    data: dict[str, Any] | bytes,
    *,
    raw_bytes: bool = False,
) -> MagicMock:
    """Create a mock urllib response that acts as a context manager.

    Args:
        data: JSON-serializable dict or raw bytes.
        raw_bytes: If True, treat data as raw bytes instead of JSON.

    Returns:
        MagicMock simulating an HTTP response with proper read() behavior.
    """
    if raw_bytes:
        content = data if isinstance(data, bytes) else str(data).encode("utf-8")
    else:
        content = json.dumps(data).encode("utf-8")

    mock_resp = MagicMock()

    if raw_bytes:
        # Simulate streaming: return content on first read(n), then b""
        mock_resp.read = Mock(side_effect=[content, b""])
    else:
        # For JSON responses, read() is called without args
        mock_resp.read = Mock(return_value=content)

    mock_resp.__enter__ = Mock(return_value=mock_resp)
    mock_resp.__exit__ = Mock(return_value=False)
    return mock_resp
