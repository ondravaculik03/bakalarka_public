import logging

from lib.system_info import get_system_info

logger = logging.getLogger(__name__)


class SystemInfoReporter:
    def report_system_info(self):
        """Collects the system info, logs it and returns it."""
        system_info = get_system_info()

        logger.info("--- System info ---")
        for key, value in system_info.items():
            logger.info("%s: %s", key, value)
        logger.info("---------------------------")

        return system_info
