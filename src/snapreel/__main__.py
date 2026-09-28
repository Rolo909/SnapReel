"""SnapReel application entry point."""

from __future__ import annotations

import sys


def main() -> None:
    """Launch the SnapReel application."""
    from snapreel import __version__

    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"snapreel {__version__}")
        sys.exit(0)

    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"SnapReel v{__version__} — Content Factory")
        print("\nUsage: python -m snapreel [OPTIONS]")
        print("\nOptions:")
        print("  -V, --version    Show version and exit")
        print("  -h, --help       Show this help and exit")
        sys.exit(0)

    # Full GUI launch
    from snapreel.app import run_app

    sys.exit(run_app())


if __name__ == "__main__":
    main()
