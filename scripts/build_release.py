"""Build the Windows release archive: a small zip that installs itself on the first start.

    python scripts/build_release.py [--uv path\\to\\uv.exe] [--out dist]

Layout of the archive (everything inside one "SnapReel" folder):

    SnapReel/
      SnapReel.cmd            double-click to start (installs on the first start)
      Как установить.txt      short instructions, Russian and English
      app/                    the application: pyproject.toml, uv.lock, src/, LICENSE, README
        setup/launcher.ps1    first-run installer and launcher
        setup/uv.exe          downloads Python and the components into SnapReel/runtime
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("pyproject.toml", "uv.lock", ".python-version", "README.md", "LICENSE")
SKIP = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def version() -> str:
    text = (ROOT / "src" / "snapreel" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("version not found in src/snapreel/__init__.py")
    return match.group(1)


def copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        if any(part in SKIP for part in path.parts) or path.suffix in (".pyc", ".pyo"):
            continue
        destination = target / path.relative_to(source)
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def find_uv(explicit: str | None) -> Path:
    candidate = Path(explicit) if explicit else Path(shutil.which("uv") or "")
    if not candidate.is_file():
        raise SystemExit("uv.exe not found: install uv or pass --uv path\\to\\uv.exe")
    return candidate


def build(out: Path, uv: Path) -> Path:
    name = f"SnapReel-{version()}-windows"
    stage = out / name
    shutil.rmtree(stage, ignore_errors=True)
    root = stage / "SnapReel"
    app = root / "app"
    setup = app / "setup"
    setup.mkdir(parents=True)

    for file in APP_FILES:
        if not (ROOT / file).exists():
            raise SystemExit(f"missing {file}")
        shutil.copy2(ROOT / file, app / file)
    copy_tree(ROOT / "src", app / "src")
    packaging = ROOT / "packaging" / "windows"
    shutil.copy2(packaging / "launcher.ps1", setup / "launcher.ps1")
    shutil.copy2(uv, setup / "uv.exe")
    shutil.copy2(packaging / "SnapReel.cmd", root / "SnapReel.cmd")
    shutil.copy2(packaging / "install.txt", root / "Как установить.txt")

    archive = out / f"{name}.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(stage).as_posix())
    shutil.rmtree(stage)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uv", help="uv.exe to bundle (default: the one on PATH)")
    parser.add_argument("--out", default=str(ROOT / "dist"), help="output folder")
    args = parser.parse_args()
    archive = build(Path(args.out), find_uv(args.uv))
    print(f"{archive}  ({archive.stat().st_size / 1024**2:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
