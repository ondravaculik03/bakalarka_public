import argparse
import ctypes
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _wait_for_process_exit(process_id, timeout_seconds=300):
    """Waits until the process with the given PID exits."""
    if os.name != "nt":
        return

    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, int(process_id))
    except Exception:
        return

    if not handle:
        return

    try:
        ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout_seconds * 1000))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _backup_and_replace(target_path, source_path):
    """Backs up the original file and replaces it with the new version."""
    target_path = Path(target_path)
    source_path = Path(source_path)
    backup_path = target_path.with_suffix(target_path.suffix + ".bak")

    if target_path.exists():
        if backup_path.exists():
            backup_path.unlink()
        target_path.replace(backup_path)
    elif backup_path.exists():
        backup_path.unlink()

    shutil.copy2(source_path, target_path)


def _restart_service(service_exe):
    """Starts the new version of the service after the update."""
    service_exe = Path(service_exe)
    subprocess.Popen([str(service_exe)], cwd=str(service_exe.parent))


def _find_file(root_dir, file_name):
    """Finds a file by name, also in the package's subfolders."""
    matches = list(Path(root_dir).rglob(file_name))
    return matches[0] if matches else None


def _cleanup_temp_files(package_dir):
    """Removes the downloaded package folder after the update."""
    # jen package_dir, jeho rodič je instalační složka. Vlastní exe updateru může být zamčené,
    # proto ignore_errors - další aktualizace složku stejně nejdřív vyprázdní
    shutil.rmtree(Path(package_dir), ignore_errors=True)


def run_update(install_dir, package_dir, process_id):
    """Replaces the files and restarts the service."""
    install_dir = Path(install_dir)
    package_dir = Path(package_dir)

    service_exe = _find_file(package_dir, "agent-service.exe")
    cli_exe = _find_file(package_dir, "agent-cli.exe")
    target_service = install_dir / "agent-service.exe"
    target_cli = install_dir / "agent-cli.exe"

    if not service_exe or not cli_exe:
        logger.warning("The package doesn't contain the required exe files.")
        return False

    try:
        _wait_for_process_exit(process_id)
        _backup_and_replace(target_service, service_exe)
        _backup_and_replace(target_cli, cli_exe)
        _restart_service(target_service)
        return True
    finally:
        _cleanup_temp_files(package_dir)


def main():
    """Reads the arguments and runs the update."""
    parser = argparse.ArgumentParser(description="Helper updater for the Mastiff agent.")
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--package-dir", required=True)
    parser.add_argument("--pid", required=True, type=int)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    ok = run_update(args.install_dir, args.package_dir, args.pid)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
