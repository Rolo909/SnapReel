import os
import subprocess
import sys
from pathlib import Path

def main():
    print("Building SnapReel (Dev / PyInstaller)...")
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)
    
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "snapreel.spec"],
            check=True
        )
        print("Build complete! Executable is in 'dist/snapreel/snapreel.exe'")
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
