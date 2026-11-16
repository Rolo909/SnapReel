"""Model download subprocess.

Runs as ``python -m snapreel --download <task.json>`` so the GUI can cancel a
multi-gigabyte download instantly by killing the process; partial files stay
on disk and the next attempt resumes. Progress is reported as JSON lines.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Keep some space free after the download so the system and the app keep working.
DISK_RESERVE = 512 * 1024**2


class DownloadError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def check_disk(path: Path, need: int) -> None:
    """Fail before downloading anything when ``need`` more bytes will not fit."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if need + DISK_RESERVE > free:
        raise DownloadError("disk", f"need {need} bytes, {free} free")


def emit(event: str, **payload: Any) -> None:
    sys.stdout.write(json.dumps({"event": event, **payload}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                full = os.path.join(root, name)
                if not os.path.islink(full):
                    total += os.path.getsize(full)
            except OSError:
                continue
    return total


def _poll(path: Path, total: int, done_before: int, stop: threading.Event) -> None:
    # Count only growth since the start: the folder may hold files of other variants.
    base = _dir_bytes(path)
    while not stop.wait(0.5):
        emit("progress", done=min(done_before + _dir_bytes(path) - base, total), total=total)


def _present_bytes(repo_dir: Path, plan: Any) -> int:
    """Bytes of planned files already on disk: complete in a snapshot or partially downloaded."""
    sizes = dict(plan.sizes)
    found: dict[str, int] = {}
    for snapshot in (repo_dir / "snapshots").glob("*"):
        for name, size in sizes.items():
            if name not in found and (snapshot / name).is_file():
                found[name] = size
    partial = sum(_size(p) for p in (repo_dir / "blobs").glob("*.incomplete"))
    return min(plan.total_bytes, sum(found.values()) + partial)


def _download_hf(task: dict[str, Any]) -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    from snapreel.core.hub import plan_files, repo_siblings

    token = os.environ.get("HF_TOKEN") or None
    _info, siblings = repo_siblings(task["repo"], token)
    plan = plan_files(siblings, prefer_half=bool(task.get("prefer_half", True)))
    if not plan.files:
        raise RuntimeError("repository has no downloadable model files")
    repo_dir = Path(task["hub_dir"]) / f"models--{task['repo'].replace('/', '--')}"
    present = _present_bytes(repo_dir, plan)
    check_disk(repo_dir, plan.total_bytes - present)
    emit("plan", total=plan.total_bytes, files=len(plan.files), variant=plan.variant)

    stop = threading.Event()
    watcher = threading.Thread(target=_poll, args=(repo_dir, plan.total_bytes, present, stop),
                               daemon=True)
    watcher.start()
    try:
        path = snapshot_download(
            task["repo"], cache_dir=task["hub_dir"], allow_patterns=plan.files, token=token,
            max_workers=4,
        )
    finally:
        stop.set()
    return {"path": path, "variant": plan.variant, "bytes": plan.total_bytes,
            "files": plan.files, "components": plan.components}


def _size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _download_urls(task: dict[str, Any]) -> dict[str, Any]:
    dest = Path(task["files_dir"])
    dest.mkdir(parents=True, exist_ok=True)
    files = task["files"]
    total = sum(int(f.get("size") or 0) for f in files)
    present = sum(_size(dest / f["name"]) + _size(dest / f"{f['name']}.part") for f in files)
    check_disk(dest, total - present)
    emit("plan", total=total, files=len(files), variant=None)
    done_before = 0
    for item in files:
        target = dest / item["name"]
        partial = target.with_suffix(target.suffix + ".part")
        size = int(item.get("size") or 0)
        if target.exists() and (not size or target.stat().st_size == size):
            done_before += target.stat().st_size
            continue
        have = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(item["url"], headers={"User-Agent": "SnapReel"})
        if have:
            request.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(request, timeout=30) as response:
            if have and response.status != 206:
                have = 0  # server ignored the range, start over
            last = 0.0
            with open(partial, "ab" if have else "wb") as handle:
                while chunk := response.read(1 << 18):
                    handle.write(chunk)
                    have += len(chunk)
                    if time.monotonic() - last > 0.4:
                        last = time.monotonic()
                        emit("progress", done=done_before + have, total=total or have)
        if size and have != size:
            raise RuntimeError(f"incomplete download of {item['name']}")
        partial.replace(target)
        done_before += have
    first = dest / files[0]["name"]
    return {"path": str(first if len(files) == 1 else dest), "variant": None,
            "bytes": done_before, "files": [f["name"] for f in files], "components": {}}


def _exit_when_parent_closes_stdin() -> None:
    """The parent cancels by closing our stdin; also covers the parent crashing.

    Killing the process from outside is not enough on Windows: a venv's
    ``python.exe`` is a launcher that runs the real interpreter as a child.
    """
    def watch(fd: int) -> None:
        # os.read, not sys.stdin: a daemon thread blocked inside a buffered reader
        # makes the interpreter abort at shutdown.
        try:
            while os.read(fd, 1):
                pass
        except OSError:
            return  # no usable stdin: nothing to watch
        os._exit(3)

    if sys.stdin is not None and not sys.stdin.isatty():
        threading.Thread(target=watch, args=(sys.stdin.fileno(),), daemon=True).start()


def main(task_file: str) -> int:
    _exit_when_parent_closes_stdin()
    try:
        task = json.loads(Path(task_file).read_text(encoding="utf-8"))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        # Xet assembles each file in its own cache and writes it to the model folder only
        # at the end, so progress would sit at 0 for minutes. Plain HTTP writes as it goes
        # (same speed in tests) and resumes partial files.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        result = _download_urls(task) if task["source"] == "url" else _download_hf(task)
        manifest = Path(task["manifest"])
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps({"id": task["id"], "source": task["source"], "repo": task["repo"], **result},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit("done", path=result["path"])
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level boundary of the subprocess
        emit("error", code=error_code(exc), message=f"{exc.__class__.__name__}: {exc}"[:600])
        return 1


def error_code(exc: BaseException) -> str:
    """Map an exception to a code the UI explains (see HubError codes)."""
    from snapreel.core.hub import is_network_error

    code = getattr(exc, "code", "")
    if isinstance(code, str) and code:  # HubError / DownloadError; HTTPError.code is an int
        return code
    name, text = exc.__class__.__name__, str(exc)
    if "Gated" in name or " 401 " in text or " 403 " in text:
        return "gated"
    if "NotFound" in name or (isinstance(exc, urllib.error.HTTPError) and exc.code == 404):
        return "not_found"
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "disk"
    if is_network_error(exc) or isinstance(exc, urllib.error.HTTPError):
        return "network"
    return "failed"
