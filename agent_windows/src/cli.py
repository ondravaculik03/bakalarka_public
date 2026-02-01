import json
import logging
import sys

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def show_usage():
    logging.info(
        """
Použití: agent-cli <příkaz> [parametry]

Příkazy:
    status              Zobrazí aktuální konfiguraci
    set <klíč> <hodnota>  Nastaví hodnotu v konfiguraci
  
Příklady:
    agent-cli status
    agent-cli set server_url https://api.example.com
    agent-cli set interval_seconds 120
"""
    )


def status():
    cfg = config.load()
    logging.info("\nAktuální konfigurace:")
    logging.info(json.dumps(cfg, indent=2))


def set_value(key, value):
    cfg = config.load()

    # Převod na správný typ a validace
    if key == "interval_seconds":
        try:
            value_int = int(value)
            if value_int <= 0:
                logging.error("interval_seconds musí být celé číslo větší než 0")
                return
            value = value_int
        except ValueError:
            logging.error("interval_seconds musí být celé číslo")
            return

    cfg[key] = value
    config.save(cfg)
    logging.info("✓ Nastaveno: %s = %s", key, value)
    logging.info("\nRestartuj službu pro aktivaci změn")


def main():
    if len(sys.argv) < 2:
        show_usage()
        return

    command = sys.argv[1]

    if command == "status":
        status()
    elif command == "set":
        if len(sys.argv) < 4:
            logging.error("Chyba: Použij: agent-cli set <klíč> <hodnota>")
            return
        key = sys.argv[2]
        value = sys.argv[3]
        set_value(key, value)
    else:
        logging.error("Neznámý příkaz: %s", command)
        show_usage()


if __name__ == "__main__":
    main()
