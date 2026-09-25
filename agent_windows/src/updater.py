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
    """Načte metadata posledního releasu z GitHub API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"GitHub API returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"Failed to check GitHub release: {e}")
    return None


def _find_versioned_exe_asset(release_data, exe_prefix):
    """Najde asset, který začíná na exe_prefix a končí na .exe (ignoruje verzi v názvu)."""
    for asset in release_data.get("assets", []):
        name = asset.get("name", "").lower()
        if name.startswith(exe_prefix.lower()) and name.endswith(".exe"):
            return asset
    return None


def _download_asset(url, output_path):
    """Stáhne soubor po částech do cílové cesty."""
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)


def _launch_updater(updater_path, unpack_dir):
    """Spustí updater jako samostatný proces."""
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
    """Ukončí aktuální proces po předání řízení updateru."""
    os._exit(0)


def get_latest_github_version():
    """Vrati tag posledni verze z GitHub releasu nebo None."""
    data = get_latest_release_data()
    if data:
        return data.get("tag_name", None)
    return None


def is_newer_version(latest):
    """Vrati True, pokud je latest novejsi nez current."""

    def parse(v):
        return [int(x) for x in v.strip("v").split(".") if x.isdigit()]

    if AGENT_VERSION and latest:
        return parse(latest) > parse(AGENT_VERSION)
    return False


def update_agent(args=None):
    """Provede kontrolu releasu a stazeni všech .exe souborů do docasne slozky (podporuje verzované názvy)."""
    try:
        # 1) Načti data o posledním releasu.
        release_data = get_latest_release_data()
        if not release_data:
            return False

        # 2) Ověř, že release obsahuje novější verzi.
        latest = release_data.get("tag_name")
        if not latest or not is_newer_version(latest):
            logger.info("Aplikace je aktuální.")
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
                logger.warning(f"Release neobsahuje asset pro {prefix}.")
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
            logger.warning("Nebyl stažen agent-updater.exe")
            return False

        # 6) Spusť updater jako samostatný proces, který se postará o aktualizaci
        _launch_updater(updater_path, tmp_dir)

        # u zabalené verze ukončíme proces, aby updater mohl přepsat exe
        if getattr(sys, "frozen", False):
            _terminate_current_process()

        logger.info(f"Staženy nové exe soubory do: {tmp_dir}")
        return True
    except Exception as e:
        logger.warning(f"Aktualizace selhala: {e}")
        return False


def check_for_update(
    args=None, auto_update=False
):  # autoupdate není takový jaký si myslíte - používá se aby se ušetřilo pár interakcí s uživatelem
    """Zkontroluje dostupnost nove verze a volitelne spusti update."""
    if args is not None and hasattr(args, "auto"):
        auto_update = bool(args.auto)

    latest = get_latest_github_version()

    if latest and is_newer_version(latest):
        logger.info(f"Nová verze dostupná: {latest}. Aktuální: {AGENT_VERSION}")
        if auto_update:
            update_agent()
        else:
            response = (
                input("Chcete aktualizovat agenta na novou verzi? [y/N]: ")
                .strip()
                .lower()
            )
            if response == "y":
                update_agent()
            else:
                logger.info("Aktualizace byla zrušena uživatelem.")
    else:
        logger.info("Aplikace je aktuální.")
