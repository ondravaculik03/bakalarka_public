import json
import logging
import os
import sys
from pathlib import Path

import requests
from lib.message_sender import MessageSender
from lib.system_info_reporter import SystemInfoReporter

from src import config, updater

# Nastavení základního logování do C:\ProgramData\Mastiff\agent_info.log
log_dir = Path(os.getenv("PROGRAMDATA", "C:\\ProgramData")) / "Mastiff"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "agent_info.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename=str(log_file),
    filemode="a",
)

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self):
        cfg = config.load()
        self.agent_id = cfg.get("agent_id")
        self.server_url = cfg.get("server_url")
        # bez zápisu (ID, klíč, certifikát) nemá agent čím se serveru prokázat
        if (
            not self.agent_id
            or not config.KEY_FILE.exists()
            or not config.CERTIFICATE_FILE.exists()
        ):
            logger.error("Not enrolled yet, run agent-cli enroll")
            sys.exit(1)
        self._message_sender = MessageSender(self.server_url, self.agent_id)
        self._system_info_reporter = SystemInfoReporter()
        self.message_count = 0

    def send_message(self, content):
        """Sends the check-in to the server over mutual TLS."""
        try:
            return self._message_sender.send_message(
                json.loads(content), self.message_count
            )

        except requests.exceptions.RequestException as e:
            logger.error("%s: Sending the check-in failed - %s", self.agent_id, e)
            return False

    def start_agent(self):
        """Collects the system info and sends one check-in."""
        logger.info("Agent %s starting...", self.agent_id)
        logger.info("Server URL: %s", self.server_url)

        self.message_count += 1
        system_info = self._system_info_reporter.report_system_info()

        content = json.dumps(system_info, ensure_ascii=False)

        self.send_message(content)


if __name__ == "__main__":
    if updater.is_newer_version(updater.get_latest_github_version()):
        updater.update_agent()
    agent = Agent()
    agent.start_agent()
