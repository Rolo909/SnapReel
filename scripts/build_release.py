import os
import subprocess
import sys
import shutil
import zipfile
from pathlib import Path

def main():
    print("Building SnapReel (Release / Nuitka)...")
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)
    
    # Optional: we can run nsis installer if Nuitka supports it, but portable ZIP is very convenient.
    nuitka_args = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--plugin-enable=pyside6",
        "--include-data-dir=assets=assets",
        "--include-data-dir=src/snapreel/i18n=src/snapreel/i18n",
        "--include-data-dir=src/snapreel/gui/styles=src/snapreel/gui/styles",
        "--output-dir=dist",
        "--output-filename=SnapReel.exe",
        "--windows-icon-from-ico=assets/icons/app_icon.ico",
        "src/snapreel/__main__.py"
    ]
    
    try:
        subprocess.run(nuitka_args, check=True)
        print("Build complete! Executable is in 'dist/__main__.dist/SnapReel.exe'")
        
        # Package into a portable ZIP
        dist_folder = project_root / "dist" / "__main__.dist"
        zip_path = project_root / "dist" / "SnapReel-Windows-Portable.zip"
        
        if dist_folder.exists():
            print(f"Creating portable ZIP archive at {zip_path}...")
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root_dir, dirs, files in os.walk(dist_folder):
                    for file in files:
                        file_path = os.path.join(root_dir, file)
                        arcname = os.path.relpath(file_path, dist_folder)
                        # Put everything inside a SnapReel/ folder in the ZIP
                        zipf.write(file_path, arcname=f"SnapReel/{arcname}")
            print(f"Packaging complete! Distribution ready at {zip_path}")
        else:
            print("Error: Nuitka dist folder not found.")
            
    except subprocess.CalledProcessError as e:
        print(f"Build failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
