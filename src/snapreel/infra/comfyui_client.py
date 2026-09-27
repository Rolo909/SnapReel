"""ComfyUI headless server launcher and REST API client.

Manages a ComfyUI subprocess running in headless mode and provides
a typed interface for submitting workflows, polling results, and
downloading generated assets (images/videos).

ComfyUI API reference:
    POST /prompt          — submit a workflow for execution
    GET  /history/{id}    — retrieve results for a completed prompt
    GET  /queue           — inspect current execution queue
    GET  /view            — download a generated file by name
    GET  /system_stats    — health check / server readiness
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from snapreel.core.exceptions import ComfyUIError

logger = structlog.get_logger()

# Defaults
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8188
_HEALTH_CHECK_INTERVAL = 1.0  # seconds between readiness polls
_HEALTH_CHECK_TIMEOUT = 120.0  # max wait for server startup
_POLL_INTERVAL = 2.0  # seconds between result polls
_POLL_TIMEOUT = 600.0  # max wait for a single prompt to complete
_REQUEST_TIMEOUT = 30.0  # HTTP request timeout


@dataclass(frozen=True)
class ComfyUIResult:
    """Result from a completed ComfyUI workflow execution."""

    prompt_id: str
    output_files: list[Path]
    execution_time_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ComfyUIClient:
    """Manages a headless ComfyUI server and communicates via REST API.

    Lifecycle:
        1. ``start()``    — launch the ComfyUI subprocess and wait for readiness.
        2. ``submit()``   — send a workflow JSON and receive a prompt ID.
        3. ``wait_for()`` — poll until the prompt completes and return results.
        4. ``download()`` — fetch generated files to local disk.
        5. ``stop()``     — gracefully terminate the subprocess.

    Can also be used as a context manager::

        async with ComfyUIClient(comfyui_dir) as client:
            pid = client.submit(workflow)
            result = client.wait_for(pid, output_dir)
    """

    def __init__(
        self,
        comfyui_dir: Path,
        *,
        host: str = _DEFAULT_HOST,
        port: int = _DEFAULT_PORT,
        extra_args: list[str] | None = None,
    ) -> None:
        self._comfyui_dir = comfyui_dir
        self._host = host
        self._port = port
        self._extra_args = extra_args or []
        self._process: subprocess.Popen[bytes] | None = None
        self._log = logger.bind(component="comfyui", host=host, port=port)

    @property
    def base_url(self) -> str:
        """Base HTTP URL for the ComfyUI server."""
        return f"http://{self._host}:{self._port}"

    @property
    def is_running(self) -> bool:
        """Check if the ComfyUI subprocess is alive."""
        return self._process is not None and self._process.poll() is None

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self, *, timeout: float = _HEALTH_CHECK_TIMEOUT) -> None:
        """Launch the ComfyUI server and block until it is ready.

        Args:
            timeout: Maximum seconds to wait for the server to become healthy.

        Raises:
            ComfyUIError: If the server fails to start or doesn't become ready.
        """
        if self.is_running:
            self._log.info("server_already_running")
            return

        main_script = self._comfyui_dir / "main.py"
        if not main_script.exists():
            raise ComfyUIError(
                f"ComfyUI main.py not found at {main_script}. "
                "Ensure ComfyUI is installed correctly."
            )

        cmd = [
            "python",
            str(main_script),
            "--listen", self._host,
            "--port", str(self._port),
            "--dont-print-server",
            *self._extra_args,
        ]

        self._log.info("server_starting", cmd=" ".join(cmd))

        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(self._comfyui_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise ComfyUIError(f"Failed to launch ComfyUI process: {exc}", cause=exc) from exc

        self._wait_for_ready(timeout)
        self._log.info("server_ready", pid=self._process.pid)

    def stop(self) -> None:
        """Gracefully terminate the ComfyUI server process."""
        if self._process is None:
            return

        self._log.info("server_stopping", pid=self._process.pid)
        self._process.terminate()
        try:
            self._process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._log.warning("server_force_killing")
            self._process.kill()
            self._process.wait(timeout=5)
        self._process = None
        self._log.info("server_stopped")

    def __enter__(self) -> ComfyUIClient:
        """Context manager entry — starts the server."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit — stops the server."""
        self.stop()

    # ── API Methods ────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check if the ComfyUI server is responsive.

        Returns:
            True if the server responds to a health check request.
        """
        try:
            self._get("/system_stats")
            return True
        except (urllib.error.URLError, OSError, ComfyUIError):
            return False

    def get_queue_status(self) -> dict[str, Any]:
        """Get the current queue status.

        Returns:
            Dict with 'queue_running' and 'queue_pending' lists.

        Raises:
            ComfyUIError: If the request fails.
        """
        return self._get("/queue")

    def submit(self, workflow: dict[str, Any]) -> str:
        """Submit a workflow for execution.

        Args:
            workflow: ComfyUI workflow dict (node graph).

        Returns:
            The prompt_id assigned by the server.

        Raises:
            ComfyUIError: If submission fails.
        """
        payload = {"prompt": workflow}
        response = self._post("/prompt", payload)

        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"Server returned no prompt_id: {response}")

        self._log.info("workflow_submitted", prompt_id=prompt_id)
        return str(prompt_id)

    def wait_for(
        self,
        prompt_id: str,
        output_dir: Path,
        *,
        poll_interval: float = _POLL_INTERVAL,
        timeout: float = _POLL_TIMEOUT,
    ) -> ComfyUIResult:
        """Block until a prompt completes and download the results.

        Args:
            prompt_id: The prompt ID returned by ``submit()``.
            output_dir: Local directory to save downloaded files.
            poll_interval: Seconds between status polls.
            timeout: Maximum seconds to wait for completion.

        Returns:
            ComfyUIResult with paths to downloaded files.

        Raises:
            ComfyUIError: If the prompt fails or times out.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.monotonic()

        self._log.info("waiting_for_result", prompt_id=prompt_id)

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                raise ComfyUIError(
                    f"Prompt {prompt_id} timed out after {timeout:.0f}s"
                )

            history = self._get(f"/history/{prompt_id}")

            if prompt_id in history:
                prompt_data = history[prompt_id]

                # Check for execution errors
                status_data = prompt_data.get("status", {})
                if status_data.get("status_str") == "error":
                    messages = status_data.get("messages", [])
                    raise ComfyUIError(
                        f"Prompt {prompt_id} failed: {messages}"
                    )

                # Collect output files
                outputs = prompt_data.get("outputs", {})
                downloaded = self._download_outputs(outputs, output_dir)

                return ComfyUIResult(
                    prompt_id=prompt_id,
                    output_files=downloaded,
                    execution_time_s=elapsed,
                    metadata=status_data,
                )

            time.sleep(poll_interval)

    def download_file(
        self, filename: str, subfolder: str, output_path: Path
    ) -> Path:
        """Download a single generated file from the server.

        Args:
            filename: Name of the file on the server.
            subfolder: Subfolder on the server (e.g. '' or 'temp').
            output_path: Local path to save the file to.

        Returns:
            The output_path after successful download.

        Raises:
            ComfyUIError: If the download fails.
        """
        params = f"filename={filename}&subfolder={subfolder}&type=output"
        url = f"{self.base_url}/view?{params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with output_path.open("wb") as f:
                    while chunk := resp.read(8192):
                        f.write(chunk)
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyUIError(
                f"Failed to download {filename}: {exc}", cause=exc
            ) from exc

        self._log.debug("file_downloaded", filename=filename, path=str(output_path))
        return output_path

    # ── Internal Helpers ───────────────────────────────────────────

    def _wait_for_ready(self, timeout: float) -> None:
        """Poll the health endpoint until the server is ready.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            ComfyUIError: If the server doesn't become ready in time.
        """
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            # Check if process died
            if self._process is not None and self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode("utf-8", errors="replace")
                raise ComfyUIError(
                    f"ComfyUI process exited with code {self._process.returncode}: "
                    f"{stderr[:500]}"
                )

            if self.health_check():
                return

            time.sleep(_HEALTH_CHECK_INTERVAL)

        raise ComfyUIError(
            f"ComfyUI server did not become ready within {timeout:.0f}s"
        )

    def _download_outputs(
        self, outputs: dict[str, Any], output_dir: Path
    ) -> list[Path]:
        """Download all output files from a completed prompt.

        Args:
            outputs: The 'outputs' dict from the history response.
            output_dir: Local directory to save files into.

        Returns:
            List of local paths to downloaded files.
        """
        downloaded: list[Path] = []

        for _node_id, node_output in outputs.items():
            # Images
            for image_data in node_output.get("images", []):
                filename = image_data.get("filename", "")
                subfolder = image_data.get("subfolder", "")
                if filename:
                    local_path = output_dir / filename
                    self.download_file(filename, subfolder, local_path)
                    downloaded.append(local_path)

            # Videos / GIFs
            for video_data in node_output.get("gifs", []):
                filename = video_data.get("filename", "")
                subfolder = video_data.get("subfolder", "")
                if filename:
                    local_path = output_dir / filename
                    self.download_file(filename, subfolder, local_path)
                    downloaded.append(local_path)

        return downloaded

    def _get(self, endpoint: str) -> dict[str, Any]:
        """Send a GET request to the ComfyUI API.

        Args:
            endpoint: API endpoint path (e.g. '/queue').

        Returns:
            Parsed JSON response.

        Raises:
            ComfyUIError: If the request fails.
        """
        url = f"{self.base_url}{endpoint}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = resp.read().decode("utf-8")
                result: dict[str, Any] = json.loads(data)
                return result
        except json.JSONDecodeError as exc:
            raise ComfyUIError(f"Invalid JSON from {endpoint}: {exc}", cause=exc) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyUIError(f"GET {endpoint} failed: {exc}", cause=exc) from exc

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a POST request with JSON body to the ComfyUI API.

        Args:
            endpoint: API endpoint path (e.g. '/prompt').
            payload: Dict to serialize as JSON body.

        Returns:
            Parsed JSON response.

        Raises:
            ComfyUIError: If the request fails.
        """
        url = f"{self.base_url}{endpoint}"
        body = json.dumps(payload).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = resp.read().decode("utf-8")
                result: dict[str, Any] = json.loads(data)
                return result
        except json.JSONDecodeError as exc:
            raise ComfyUIError(
                f"Invalid JSON from POST {endpoint}: {exc}", cause=exc
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ComfyUIError(f"POST {endpoint} failed: {exc}", cause=exc) from exc
