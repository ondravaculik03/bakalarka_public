import json
import logging

import requests


class MessageSender:
    def __init__(self, server_url: str, agent_id: str):
        self.server_url = server_url
        self.agent_id = agent_id

    def send_message(
        self,
        encrypted_key_b64: str,
        nonce_b64: str,
        ciphertext_b64: str,
        client_ip: str,
        message_count: int,
        client_os: str,
        client_state: str,
        client_points: int,
    ):
        headers = {"Content-Type": "application/json"}
        payload = {
            "agent_id": self.agent_id,
            "client_ip": client_ip,
            "client_os": client_os,
            "client_state": client_state,
            "client_points": client_points,
            "encrypted_key": encrypted_key_b64,
            "nonce": nonce_b64,
            "ciphertext": ciphertext_b64,
        }

        try:
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
