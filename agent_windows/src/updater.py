import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

from src import __version__ as AGENT_VERSION

logger = logging.getLogger(__name__)

GITHUB_REPO = "ondravaculik03/bakalarka_public"


def get_latest_release_data():
    """Returns the latest release's metadata from the GitHub API, or None."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("GitHub API returned %s", resp.status_code)
    except Exception as e:
        logger.warning("Failed to check GitHub release: %s", e)
    return None


def _find_versioned_exe_asset(release_data, exe_prefix):
    """Returns the asset that starts with exe_prefix and ends with .exe, any version in the name."""
    for asset in release_data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.startswith(exe_prefix.lower()) and name.endswith(".exe"):
            return asset
    return None


def _download_asset(url, output_path):
    """Downloads a file in chunks to output_path."""
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)


def _launch_updater(updater_path, unpack_dir):
    """Starts the updater as a separate process."""
    install_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    )
    subprocess.Popen(
        [
            str(updater_path),
            "--install-dir",
            str(install_dir),
            "--package-dir",
            str(unpack_dir),
            "--pid",
            str(os.getpid()),
        ],
        cwd=str(unpack_dir),
    )


def _terminate_current_process():
    """Ends the current process after handing over to the updater."""
    os._exit(0)


def get_latest_github_version():
    """Returns the tag of the latest GitHub release, or None."""
    data = get_latest_release_data()
    if data:
        return data.get("tag_name", None)
    return None


def is_newer_version(latest):
    """Returns True if latest is newer than the current version."""

    def parse(v):
        """Turns a version string into a list of numbers."""
        return [int(x) for x in v.strip("v").split(".") if x.isdigit()]

    if AGENT_VERSION and latest:
        return parse(latest) > parse(AGENT_VERSION)
    return False


def update_agent(args=None):
    """Downloads the latest release's .exe files to a temp folder and starts the updater."""
    try:
        # 1) Načti data o posledním releasu.
        release_data = get_latest_release_data()
        if not release_data:
            return False

        # 2) Ověř, že release obsahuje novější verzi.
        latest = release_data.get("tag_name")
        if not latest or not is_newer_version(latest):
            logger.info("The agent is up to date.")
            return False

        # 3) Najdi všechny potřebné exe assety v releasu podle prefixu.
        exe_map = {
            "agent-service": "agent-service.exe",
            "agent-cli": "agent-cli.exe",
            "agent-updater": "agent-updater.exe",
        }
        assets = {}
        for prefix, target_name in exe_map.items():
            asset = _find_versioned_exe_asset(release_data, prefix)
            if not asset:
                logger.warning("The release has no asset for %s.", prefix)
                return False
            assets[target_name] = asset

        # 4) Stáhni všechny exe soubory do dočasné složky pod pevnými názvy.
        tmp_dir = Path(tempfile.mkdtemp(prefix="agent-update-"))
        for target_name, asset in assets.items():
            exe_path = tmp_dir / target_name
            _download_asset(asset["browser_download_url"], exe_path)

        # 5) Najdi agent-updater.exe v dočasné složce
        updater_path = tmp_dir / "agent-updater.exe"
        if not updater_path.exists():
            logger.warning("agent-updater.exe wasn't downloaded")
            return False

        # 6) Spusť updater jako samostatný proces, který se postará o aktualizaci
        _launch_updater(updater_path, tmp_dir)

        # u zabalené verze ukončíme proces, aby updater mohl přepsat exe
        if getattr(sys, "frozen", False):
            _terminate_current_process()

        logger.info("New exe files downloaded to: %s", tmp_dir)
        return True
    except Exception as e:
        logger.warning("Update failed: %s", e)
        return False


def check_for_update(args=None, auto_update=False):
    """Checks for a new version and optionally starts the update."""
    if args is not None and hasattr(args, "auto"):
        auto_update = bool(args.auto)

    latest = get_latest_github_version()

    if latest and is_newer_version(latest):
        logger.info("New version available: %s. Current: %s", latest, AGENT_VERSION)
        if auto_update:
            update_agent()
        else:
            response = (
                input("Update the agent to the new version? [y/N]: ")
                .strip()
                .lower()
            )
            if response == "y":
                update_agent()
            else:
                logger.info("Update cancelled.")
    else:
        logger.info("The agent is up to date.")
