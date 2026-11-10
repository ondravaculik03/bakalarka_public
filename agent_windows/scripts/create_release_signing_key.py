"""Creates the Ed25519 key that signs agent releases (run once)."""

import argparse
import base64
import getpass
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Soukromý klíč zůstává jen na PC, kde se release podepisuje, a je zašifrovaný heslem.
# Agenti mají v src/updater.py jen veřejný klíč, takže podpis umí ověřit, ale ne vyrobit.
DEFAULT_KEY_FILE = Path.home() / ".mastiff" / "release_signing_key.pem"


def create_key(key_file, passphrase):
    """Writes a new passphrase-protected private key to key_file and returns the public key line for updater.py."""
    key_file = Path(key_file)
    if key_file.exists():
        sys.exit(f"{key_file} already exists, not overwriting it.")

    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(pem)

    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return f'RELEASE_PUBLIC_KEY = "{base64.b64encode(public_bytes).decode("ascii")}"'


def main():
    """Asks for the passphrase twice, creates the key and prints the line for updater.py."""
    parser = argparse.ArgumentParser(description="Creates the key that signs agent releases.")
    parser.add_argument("--key-file", default=str(DEFAULT_KEY_FILE))
    args = parser.parse_args()

    passphrase = getpass.getpass("Passphrase for the key: ")
    if not passphrase:
        sys.exit("The passphrase can't be empty.")
    if passphrase != getpass.getpass("Passphrase again: "):
        sys.exit("The passphrases don't match.")

    line = create_key(args.key_file, passphrase)
    print(f"Key written to: {args.key_file}")
    print("Paste this line into src/updater.py:")
    print(line)
    print("Back up the key file and the passphrase (password manager, USB). Without them no agent accepts a new release.")


if __name__ == "__main__":
    main()
