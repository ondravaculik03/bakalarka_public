import argparse
import json
import logging

from src import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def status(args):  # args parameter for consistency
    cfg = config.load()
    logging.info("\nAktuální konfigurace:")
    logging.info(json.dumps(cfg, indent=2))


def set_value(args):  # args parameter for consistency
    cfg = config.load()

    key = args.key
    value = args.value

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
    elif key == "server_url":
        # Basic URL validation
        if not (value.startswith("http://") or value.startswith("https://")):
            logging.error("server_url musí začínat 'http://' nebo 'https://'")
            return
    elif key == "auth_token":
        if not value:
            logging.error("auth_token nesmí být prázdný")
            return

    cfg[key] = value
    config.save(cfg)
    logging.info("✓ Nastaveno: %s = %s", key, value)
    logging.info("\nRestartuj službu pro aktivaci změn")


def main():
    parser = argparse.ArgumentParser(
        prog="agent-cli",
        description="CLI nástroj pro správu Mastiff agenta.",
        formatter_class=argparse.RawTextHelpFormatter,  # To preserve newlines in description
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {config.load().get('version', 'unknown')}",
        help="Zobrazí verzi agenta.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Dostupné příkazy")

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Zobrazí aktuální konfiguraci agenta.",
        description="Zobrazí aktuální konfiguraci Mastiff agenta, včetně server_url, interval_seconds a log_level.",
    )
    status_parser.set_defaults(func=status)

    # Set command
    set_parser = subparsers.add_parser(
        "set",
        help="Nastaví hodnotu v konfiguraci agenta.",
        description="Nastaví hodnotu pro specifický konfigurační klíč. Podporuje validaci pro 'interval_seconds', 'server_url' a 'auth_token'.",
    )
    set_parser.add_argument(
        "key",
        choices=["server_url", "interval_seconds", "log_level", "auth_token"],
        help="Název konfiguračního klíče (server_url, interval_seconds, log_level, auth_token).",
    )
    set_parser.add_argument("value", help="Nová hodnota pro daný konfigurační klíč.")
    set_parser.set_defaults(func=set_value)

    args = parser.parse_args()

    if args.command:  # Ensure a command was passed
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
