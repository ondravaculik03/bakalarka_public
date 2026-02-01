import base64
import json
import logging
import os
import random
import time

import config
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from lib.system_info import get_system_info
from updater import check_for_update

states = ["Safe", "Vulnerable", "Dangerous"]
os_list = ["windows", "linux"]

message_count = 0
__version__ = "1.0.0"

# Nastavení základního logování
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# PROMĚNNÁ PRO BEZPEČNOST
class TestAgent:
    def __init__(self):
        cfg = config.load()
        self.agent_id = os.getenv("AGENT_ID", "unknown_agent")
        self.server_url = cfg.get("server_url", "http://localhost:8000")
        self.auth_token = cfg.get("auth_token", "dev_shared_token")
        self._public_key: RSAPublicKey | None = None  # cached server public key

    def _fetch_public_key(self) -> RSAPublicKey:
        if self._public_key is not None:
            return self._public_key
        resp = requests.get(f"{self.server_url}/api/public_key")
        resp.raise_for_status()
        pem = resp.json()["public_key_pem"].encode("utf-8")
        public_key: RSAPublicKey = serialization.load_pem_public_key(pem)  # type: ignore
        self._public_key = public_key
        return public_key

    def send_message(self, content, hostname, client_ip):
        """Pošle šifrovanou zprávu na server (AES-GCM + RSA-OAEP)."""
        try:
            # 1) Získej veřejný klíč serveru
            public_key = self._fetch_public_key()

            # 2) Vygeneruj náhodný AES klíč a nonce
            aes_key = os.urandom(32)  # 256-bit
            nonce = os.urandom(12)  # 96-bit pro GCM

            # 3) Připrav plaintext s časem a obsahem, pak zašifruj přes AES-GCM
            plaintext_obj = {
                "content": content,
                "client_timestamp": int(time.time()),
                "auth_token": self.auth_token,
            }
            plaintext_bytes = json.dumps(plaintext_obj, ensure_ascii=False).encode(
                "utf-8"
            )
            aesgcm = AESGCM(aes_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)

            # 4) Zašifruj AES klíč veřejným RSA klíčem serveru
            enc_key = public_key.encrypt(
                aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )

            headers = {"Content-Type": "application/json"}
            payload = {
                "agent_id": hostname,
                "client_ip": client_ip,
                "client_os": random.choice(os_list),  # pouze pro testování
                "client_state": random.choice(
                    states
                ),  # pouze pro testování (náhodný stav)
                "client_points": random.randint(
                    0, 100
                ),  # pouze pro testování (náhodné body)
                "encrypted_key": base64.b64encode(enc_key).decode("utf-8"),
                "nonce": base64.b64encode(nonce).decode("utf-8"),
                "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
            }

            response = requests.post(
                f"{self.server_url}/api/message", headers=headers, json=payload
            )

            if response.status_code == 200:
                logging.info(
                    "%s: Zpráva doručena - Celkem odesláno: %d",
                    self.agent_id,
                    message_count,
                )
                return True
            else:
                logging.error(
                    "%s: Chyba při odesílání - %s", self.agent_id, response.status_code
                )
                return False

        except requests.exceptions.ConnectionError:
            logging.error(
                "%s: Nelze se připojit k serveru %s", self.agent_id, self.server_url
            )
            return False

    def start_agent(self):
        """Spustí agenta - periodicky posílá zprávy"""
        logging.info("Agent %s startuje...", self.agent_id)
        logging.info("Cílová URL: %s", self.server_url)

        global message_count
        message_count += 1
        system_info = get_system_info()

        hostname = system_info.get("hostname")
        client_ip = "N/A"
        content = json.dumps(system_info, ensure_ascii=False)

        logging.debug(content)

        # Pošle zprávu
        self.send_message(content, hostname, client_ip)


if __name__ == "__main__":
    check_for_update(__version__)
    agent = TestAgent()
    agent.start_agent()
