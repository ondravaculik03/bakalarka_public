import logging
import time

import requests

from src import config

logger = logging.getLogger(__name__)


class MessageSender:
    def __init__(self, server_url: str, agent_id: str):
        self.server_url = server_url
        self.agent_id = agent_id

    def send_message(self, content: dict, message_count: int):
        """Sends the check-in with the machine certificate, returns True on success."""
        payload = {"client_timestamp": int(time.time()), "content": content}

        try:
            # stroj se serveru prokáže svým certifikátem, agent_id v těle není
            response = requests.post(
                f"{self.server_url}/api/message",
                json=payload,
                cert=(str(config.CERTIFICATE_FILE), str(config.KEY_FILE)),
                verify=str(config.CA_FILE),
                timeout=30,
            )

            if response.status_code == 200:
                logger.info(
                    "%s: Check-in delivered - sent in total: %d",
                    self.agent_id,
                    message_count,
                )
                return True
            elif response.status_code == 401:
                logger.error(
                    "%s: This machine was removed from the server, enroll it again with a new code",
                    self.agent_id,
                )
                return False
            else:
                logger.error(
                    "%s: Sending failed - %s - %s",
                    self.agent_id,
                    response.status_code,
                    response.text,
                )
                return False

        except requests.exceptions.ConnectionError:
            logger.error(
                "%s: Can't connect to the server %s", self.agent_id, self.server_url
            )
            return False
