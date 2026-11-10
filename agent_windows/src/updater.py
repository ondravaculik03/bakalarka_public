import base64
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src import __version__ as AGENT_VERSION

logger = logging.getLogger(__name__)

GITHUB_REPO = "ondravaculik03/bakalarka_public"

# Veřejný klíč releasů (Ed25519, base64), vypíše ho scripts/create_release_signing_key.py.
# HTTPS jen dokazuje že soubor je z GitHubu, podpis že ho vydal majitel soukromého klíče.
# Dokud je tu placeholder, podpis nikdy neprojde = žádná aktualizace (bezpečná výchozí hodnota).
RELEASE_PUBLIC_KEY = "lqPM4SwNSrTj+V6Z1QHFebytSyIvZFli8mnU73eB4x0="


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


def _find_asset_by_name(release_data, name):
    """Returns the asset with exactly this name, or None."""
    for asset in release_data.get("assets", []):
        if asset.get("name") == name:
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


def _get_install_dir():
    """Returns the folder the agent runs from (the exe's folder, or the current folder when not built)."""
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    )


def _signature_is_valid(manifest_bytes, signature):
    """Returns True if the manifest was signed with the release key."""
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(RELEASE_PUBLIC_KEY)
        )
        public_key.verify(signature, manifest_bytes)
        return True
    except (InvalidSignature, ValueError):
        # ValueError = klíč není platný (třeba ještě placeholder)
        return False


def _download_and_check_release(latest, assets, update_dir):
    """Downloads the manifest, signature and exes to update_dir; returns True only if all of them check out."""
    manifest_path = update_dir / "release-manifest.json"
    signature_path = update_dir / "release-manifest.json.sig"
    _download_asset(
        assets["release-manifest.json"]["browser_download_url"], manifest_path
    )
    _download_asset(
        assets["release-manifest.json.sig"]["browser_download_url"], signature_path
    )

    # nejdřív podpis, až pak se manifestu dá věřit
    manifest_bytes = manifest_path.read_bytes()
    if not _signature_is_valid(manifest_bytes, signature_path.read_bytes()):
        logger.warning("Update refused: the release signature is not valid.")
        return False

    # verze je v podepsaném manifestu, takže starý podepsaný build pod vyšším tagem neprojde
    manifest = json.loads(manifest_bytes)
    version = manifest.get("version")
    if version != latest.lstrip("v") or not is_newer_version(version):
        logger.warning(
            "Update refused: the signed version %s doesn't match the release %s or isn't newer than %s.",
            version,
            latest,
            AGENT_VERSION,
        )
        return False

    for target_name in ("agent-service.exe", "agent-cli.exe", "agent-updater.exe"):
        exe_path = update_dir / target_name
        _download_asset(assets[target_name]["browser_download_url"], exe_path)
        if hashlib.sha256(exe_path.read_bytes()).hexdigest() != manifest["files"].get(
            target_name
        ):
            logger.warning(
                "Update refused: %s doesn't match the signed manifest.", target_name
            )
            return False

    return True


def _launch_updater(updater_path, unpack_dir):
    """Starts the updater as a separate process."""
    install_dir = _get_install_dir()
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
    """Downloads the latest release to <install dir>\\update, checks its signature and hashes and starts the updater."""
    update_dir = None
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

        # 4) Podepsaný manifest a jeho podpis, jména přesně.
        for name in ("release-manifest.json", "release-manifest.json.sig"):
            asset = _find_asset_by_name(release_data, name)
            if not asset:
                logger.warning("The release has no %s.", name)
                return False
            assets[name] = asset

        # 5) Stáhni a zkontroluj všechno do <install dir>\update. Do Program Files\Mastiff smí
        # zapisovat jen admin a SYSTEM, takže nikdo nevymění zkontrolovaný soubor před spuštěním
        update_dir = _get_install_dir() / "update"
        shutil.rmtree(update_dir, ignore_errors=True)
        update_dir.mkdir()
        if not _download_and_check_release(latest, assets, update_dir):
            shutil.rmtree(update_dir, ignore_errors=True)
            return False

        # 6) Spusť updater jako samostatný proces, který se postará o aktualizaci
        _launch_updater(update_dir / "agent-updater.exe", update_dir)

        # u zabalené verze ukončíme proces, aby updater mohl přepsat exe
        if getattr(sys, "frozen", False):
            _terminate_current_process()

        logger.info("New exe files downloaded to: %s", update_dir)
        return True
    except Exception as e:
        logger.warning("Update failed: %s", e)
        if update_dir is not None:
            shutil.rmtree(update_dir, ignore_errors=True)
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
                input("Update the agent to the new version? [y/N]: ").strip().lower()
            )
            if response == "y":
                update_agent()
            else:
                logger.info("Update cancelled.")
    else:
        logger.info("The agent is up to date.")
