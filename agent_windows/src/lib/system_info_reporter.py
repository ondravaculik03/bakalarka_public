import json
import logging

from lib.system_info import get_system_info


class SystemInfoReporter:
    def report_system_info(self):
        system_info = get_system_info()

        content = json.dumps(system_info, ensure_ascii=False)
        logging.debug(content)

        logging.info("--- Informace o systému ---")
        for key, value in system_info.items():
            logging.info(f"{key}: {value}")
        logging.info("---------------------------")

        return system_info  # Return for potential use in message sending
