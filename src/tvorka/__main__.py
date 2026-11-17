"""Tvorka entry point."""

from __future__ import annotations

import sys


def main() -> None:
    from tvorka import __version__

    args = sys.argv[1:]
    if "--home" in args:  # set by the release launcher and its shortcuts
        import os

        index = args.index("--home")
        if index + 1 < len(args):
            os.environ["TVORKA_HOME"] = args[index + 1]
        del args[index:index + 2]
        sys.argv[1:] = args
    if "--version" in args or "-V" in args:
        print(f"tvorka {__version__}")
        return
    if "--help" in args or "-h" in args:
        print(f"Tvorka {__version__} — local AI studio for images, video and speech\n")
        print("Usage: tvorka [OPTIONS]\n")
        print("  -V, --version    Show version and exit")
        print("  -h, --help       Show this help and exit")
        return
    if "--download" in args:
        # Internal worker mode used by the GUI for cancellable model downloads.
        from tvorka.workers.download_proc import main as download_main

        index = args.index("--download")
        sys.exit(download_main(args[index + 1]) if index + 1 < len(args) else 2)

    from tvorka.app import run_app

    sys.exit(run_app())


if __name__ == "__main__":
    main()
