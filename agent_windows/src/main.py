import getpass
import json
import logging
import os
import sys
from pathlib import Path

import requests
from lib.message_encryptor import MessageEncryptor
from lib.message_sender import MessageSender
from lib.public_key_fetcher import PublicKeyFetcher
from lib.system_info_reporter import SystemInfoReporter  # Import SystemInfoReporter

from src import config, updater

__version__ = "1.0.0"

# Nastavení základního logování do C:\ProgramData\Mastiff\agent.log
log_dir = Path(os.getenv("PROGRAMDATA", "C:\\ProgramData")) / "Mastiff"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "agent_info.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename=str(log_file),
    filemode="a",
)


# PROMĚNNÁ PRO BEZPEČNOST
class Agent:
    def __init__(self):
        cfg = config.load()
        self.agent_id = os.getenv("AGENT_ID", "unknown_agent")
        self.server_url = cfg.get("server_url", "http://localhost:8000")
        self.auth_token = cfg.get("auth_token", "")
        if not self.auth_token or self.auth_token == "NOT_CONFIGURED":
            logging.error(
                "Chyba: 'auth_token' není nastaven. Spusť 'agent-cli set auth_token <token>'"
            )
            sys.exit(1)
        self._public_key_fetcher = PublicKeyFetcher(self.server_url)
        self._message_encryptor = MessageEncryptor()
        self._message_sender = MessageSender(self.server_url, self.agent_id)
        self._system_info_reporter = (
            SystemInfoReporter()
        )  # Instantiate SystemInfoReporter
        self.message_count = 0  # Initialize message_count as an instance variable

    def _fetch_public_key(self):
        return self._public_key_fetcher.fetch_public_key()

    def send_message(
        self, content, hostname, client_ip, client_os, client_state, client_points
    ):
        """Pošle šifrovanou zprávu na server (AES-GCM + RSA-OAEP)."""
        try:
            public_key = self._fetch_public_key()

            encrypted_key_b64, nonce_b64, ciphertext_b64 = (
                self._message_encryptor.encrypt_message(
                    json.loads(content), self.auth_token, public_key
                )
            )

            # Use the MessageSender to send the message
            return self._message_sender.send_message(
                encrypted_key_b64,
                nonce_b64,
                ciphertext_b64,
                client_ip,
                self.message_count,
                client_os,
                client_state,
                client_points,
            )

        except requests.exceptions.RequestException as e:
            logging.error(
                "%s: Chyba při odesílání nebo získávání klíče - %s", self.agent_id, e
            )
            return False

    def start_agent(self):
        """Spustí agenta - periodicky posílá zprávy"""
        logging.info("Agent %s startuje...", self.agent_id)
        logging.info("Cílová URL: %s", self.server_url)

        self.message_count += 1  # Increment instance message_count
        system_info = self._system_info_reporter.report_system_info()

        # Extract values for message sending
        hostname = system_info.get("hostname", "unknown-host")
        client_ip = system_info.get("client_ip", "N/A")
        client_os = system_info.get("os", "unknown-os")
        client_state = system_info.get("state", "unknown-state")
        client_points = system_info.get("points", 0)

        content = json.dumps(system_info, ensure_ascii=False)

        self.send_message(
            content,
            hostname,
            client_ip,
            client_os,
            client_state,
            client_points,
        )


if __name__ == "__main__":
    updater.check_for_update(__version__)
    agent = Agent()
    agent.start_agent()
