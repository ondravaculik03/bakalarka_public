"""
Build script pro vytvoření .exe souborů pomocí PyInstaller
"""

import shutil
from pathlib import Path

import PyInstaller.__main__

# Cesty
project_root = Path(__file__).parent.parent
src_dir = project_root / "src"
dist_dir = project_root / "dist"

# Vyčisti dist složku
if dist_dir.exists():
    shutil.rmtree(dist_dir)

print("=== Building Agent Service ===")
PyInstaller.__main__.run(
    [
        str(src_dir / "main.py"),
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
        str(src_dir / "cli.py"),
        "--name=agent-cli",
        "--onefile",
        "--console",
        f"--distpath={dist_dir}",
        f'--add-data={src_dir / "config.py"};.',
        "--clean",
    ]
)

print("\n✓ Build dokončen!")
print(f"Soubory jsou v: {dist_dir}")
print("  - agent-service.exe")
print("  - agent-cli.exe")
