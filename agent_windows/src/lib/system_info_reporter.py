import json
import logging

from lib.system_info import get_system_info

logger = logging.getLogger(__name__)


class SystemInfoReporter:
    def report_system_info(self):
        system_info = get_system_info()

        content = json.dumps(system_info, ensure_ascii=False)
        logger.debug(content)

        logger.info("--- Informace o systému ---")
        for key, value in system_info.items():
            logger.info(f"{key}: {value}")
        logger.info("---------------------------")

        return system_info  # Return for potential use in message sending
