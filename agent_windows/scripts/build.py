"""
Build script pro vytvoření .exe souborů pomocí PyInstaller
"""

import platform
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

# Cesty
project_root = Path(__file__).parent.parent
src_dir = project_root / "src"
dist_dir = project_root / "dist"

sys.path.insert(0, str(project_root))
from src import __version__  # noqa: E402

arch = platform.machine().lower()

# Vyčisti dist složku
if dist_dir.exists():
    shutil.rmtree(dist_dir)

print("=== Building Agent Service ===")
PyInstaller.__main__.run(
    [
        str(src_dir / "agent-service.py"),
        "--name=agent-service",
        "--onefile",
        "--noconsole",
        f"--distpath={dist_dir}",
        f'--add-data={src_dir / "config.py"};.',
        f'--add-data={src_dir / "lib"};lib',
        "--hidden-import=lib.system_info",
        "--clean",
    ]
)

print("\n=== Building CLI Tool ===")
PyInstaller.__main__.run(
    [
        str(src_dir / "agent-cli.py"),
        "--name=agent-cli",
        "--onefile",
        "--console",
        f"--distpath={dist_dir}",
        f'--add-data={src_dir / "config.py"};.',
        "--clean",
    ]
)

print("\n=== Building Updater Helper ===")
PyInstaller.__main__.run(
    [
        str(src_dir / "agent-updater.py"),
        "--name=agent-updater",
        "--onefile",
        "--console",
        f"--distpath={dist_dir}",
        "--clean",
    ]
)

print("\n=== Renaming built files ===")
for name in ("agent-service", "agent-cli", "agent-updater"):
    src_exe = dist_dir / f"{name}.exe"
    versioned_exe = dist_dir / f"{name}-{__version__}-{arch}.exe"
    src_exe.rename(versioned_exe)
    print(f"  {src_exe.name} -> {versioned_exe.name}")

print("\nBuild dokončen!")
print(f"Soubory jsou v: {dist_dir}")
