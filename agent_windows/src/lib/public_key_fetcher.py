import logging
import requests

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

class PublicKeyFetcher:
    def __init__(self, server_url: str):
        self.server_url = server_url
        self._public_key: RSAPublicKey | None = None

    def fetch_public_key(self) -> RSAPublicKey:
        if self._public_key is not None:
            return self._public_key
        try:
            resp = requests.get(f"{self.server_url}/api/public_key")
            resp.raise_for_status()
            pem = resp.json()["public_key_pem"].encode("utf-8")
            public_key: RSAPublicKey = serialization.load_pem_public_key(pem)  # type: ignore
            self._public_key = public_key
            return public_key
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching public key from {self.server_url}: {e}")
            raise
