import logging
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

AGENT_VERSION = "2.0.8"
GITHUB_REPO = "ondravaculik03/bakalarka_public"


def get_latest_release_data():
    """Načte metadata posledního releasu z GitHub API."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        logging.warning(f"GitHub API returned {resp.status_code}")
    except Exception as e:
        logging.warning(f"Failed to check GitHub release: {e}")
    return None


def _pick_zip_asset(release_data):
    """Vybere první asset, který je ZIP balíček."""
    for asset in release_data.get("assets", []):
        if asset.get("name", "").lower().endswith(".zip"):
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


def _extract_zip(zip_path, target_dir):
    """Rozbalí ZIP do cílové složky."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target_dir)


def _find_file(root_dir, file_name):
    """Najde soubor podle názvu v rozbaleném obsahu."""
    matches = list(Path(root_dir).rglob(file_name))
    return matches[0] if matches else None


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
    """Provede kontrolu releasu a stazeni ZIP balicku do docasne slozky."""
    try:
        # 1) Načti data o posledním releasu.
        release_data = get_latest_release_data()
        if not release_data:
            return False

        # 2) Ověř, že release obsahuje novější verzi.
        latest = release_data.get("tag_name")
        if not latest or not is_newer_version(latest):
            logging.info("Aplikace je aktuální.")
            return False

        # 3) Najdi ZIP asset v releasu.
        asset = _pick_zip_asset(release_data)
        if not asset:
            logging.warning("Release neobsahuje ZIP asset.")
            return False

        # 4) Stáhni ZIP do dočasné složky.
        tmp_dir = Path(tempfile.mkdtemp(prefix="agent-update-"))
        zip_path = tmp_dir / asset["name"]
        unpack_dir = tmp_dir / "unpacked"
        unpack_dir.mkdir(parents=True, exist_ok=True)

        # rozbalíme ZIP
        _download_asset(asset["browser_download_url"], zip_path)
        _extract_zip(zip_path, unpack_dir)

        # hledáme updater.exe v rozbaleném obsahu
        updater_path = _find_file(unpack_dir, "updater.exe")
        if not updater_path:
            logging.warning("ZIP neobsahuje updater.exe")
            return False

        # spustíme updater jako samostatný proces, který se postará o aktualizaci
        _launch_updater(updater_path, unpack_dir)

        # u zabalené verze ukončíme proces, aby updater mohl přepsat exe
        if getattr(sys, "frozen", False):
            _terminate_current_process()

        logging.info(f"ZIP balicek stazen do: {zip_path}")
        return True
    except Exception as e:
        logging.warning(f"Aktualizace selhala: {e}")
        return False


def check_for_update(
    args=None, auto_update=False
):  # autoupdate není takový jaký si myslíte - používá se aby se ušetřilo pár interakcí s uživatelem
    """Zkontroluje dostupnost nove verze a volitelne spusti update."""
    if args is not None and hasattr(args, "auto"):
        auto_update = bool(args.auto)

    latest = get_latest_github_version()

    if latest and is_newer_version(latest):
        logging.info(f"Nová verze dostupná: {latest}. Aktuální: {AGENT_VERSION}")
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
                logging.info("Aktualizace byla zrušena uživatelem.")
    else:
        logging.info("Aplikace je aktuální.")
