import json
import logging

import requests

logger = logging.getLogger(__name__)


class MessageSender:
    def __init__(self, server_url: str, agent_id: str):
        self.server_url = server_url
        self.agent_id = agent_id

    def send_message(
        self,
        encrypted_key_b64: str,
        nonce_b64: str,
        ciphertext_b64: str,
        message_count: int,
    ):
        headers = {"Content-Type": "application/json"}
        payload = {
            "agent_id": self.agent_id,
            "encrypted_key": encrypted_key_b64,
            "nonce": nonce_b64,
            "ciphertext": ciphertext_b64,
        }

        try:
            response = requests.post(
                f"{self.server_url}/api/message", headers=headers, json=payload
            )

            if response.status_code == 200:
                logger.info(
                    "%s: Zpráva doručena - Celkem odesláno: %d",
                    self.agent_id,
                    message_count,
                )
                return True
            else:
                logger.error(
                    "%s: Chyba při odesílání - %s - %s",
                    self.agent_id,
                    response.status_code,
                    response.text,
                )
                return False

        except requests.exceptions.ConnectionError:
            logger.error(
                "%s: Nelze se připojit k serveru %s", self.agent_id, self.server_url
            )
            return False
