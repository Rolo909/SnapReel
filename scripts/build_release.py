import os
import subprocess
import sys
from pathlib import Path

def main():
    print("Building SnapReel (Release / Nuitka)...")
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)
    
    nuitka_args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--plugin-enable=pyside6",
        "--include-data-dir=assets=assets",
        "--include-data-dir=src/snapreel/i18n=src/snapreel/i18n",
        "--include-data-dir=src/snapreel/gui/styles=src/snapreel/gui/styles",
        "--output-dir=dist",
        "--windows-icon-from-ico=assets/icons/app_icon.ico",
        "src/snapreel/__main__.py"
    ]
    
    try:
        subprocess.run(nuitka_args, check=True)
        print("Build complete! Executable is in 'dist/__main__.dist/__main__.exe'")
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
