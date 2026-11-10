"""Signs a built release: writes dist/release-manifest.json and its signature (run after build.py)."""

import argparse
import base64
import getpass
import hashlib
import json
import platform
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

# Cesty
project_root = Path(__file__).parent.parent
dist_dir = project_root / "dist"

sys.path.insert(0, str(project_root))
from src import __version__  # noqa: E402
from src.updater import RELEASE_PUBLIC_KEY  # noqa: E402

DEFAULT_KEY_FILE = Path.home() / ".mastiff" / "release_signing_key.pem"


def write_signed_manifest(dist_dir, version, arch, key_file, passphrase):
    """Writes the manifest with the version and each exe's SHA-256, and its signature, to dist_dir."""
    dist_dir = Path(dist_dir)
    # klíče jsou pevné názvy, pod kterými si je update_agent ukládá
    files = {}
    for name in ("agent-service", "agent-cli", "agent-updater"):
        exe_path = dist_dir / f"{name}-{version}-{arch}.exe"
        if not exe_path.exists():
            sys.exit(f"{exe_path} doesn't exist, run build.py first.")
        files[f"{name}.exe"] = hashlib.sha256(exe_path.read_bytes()).hexdigest()

    try:
        private_key = serialization.load_pem_private_key(
            Path(key_file).read_bytes(), password=passphrase.encode("utf-8")
        )
    except ValueError:
        sys.exit("Can't load the key: wrong passphrase or not a key file.")

    # Release s placeholderem nebo cizím klíčem by agenti 2.0.26 ještě nainstalovali,
    # ale pak by odmítli každou další aktualizaci, proto se v tom případě nepodepisuje nic.
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    if base64.b64encode(public_bytes).decode("ascii") != RELEASE_PUBLIC_KEY:
        sys.exit(
            "The key doesn't match RELEASE_PUBLIC_KEY in src/updater.py (still the placeholder, "
            "or another key file). Nothing was signed. Fix the line and run build.py again, "
            "the built exes contain the wrong line."
        )

    # podepisují se přesně ty bajty, které se nahrají do releasu
    manifest_bytes = json.dumps({"version": version, "files": files}, indent=2).encode("utf-8")
    (dist_dir / "release-manifest.json").write_bytes(manifest_bytes)
    (dist_dir / "release-manifest.json.sig").write_bytes(private_key.sign(manifest_bytes))


def main():
    """Asks for the passphrase and signs the release in dist/."""
    parser = argparse.ArgumentParser(description="Signs the built agent release.")
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
    args = parser.parse_args()

    passphrase = getpass.getpass("Passphrase for the key: ")
    write_signed_manifest(dist_dir, __version__, platform.machine().lower(), args.key_file, passphrase)
    print(f"Signed release {__version__}.")
    print(f"Upload release-manifest.json and release-manifest.json.sig from {dist_dir} with the three exes.")


if __name__ == "__main__":
    main()
