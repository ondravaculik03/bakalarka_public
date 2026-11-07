import argparse
import json
import logging

from src import config, updater

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


def status(args):  # args posílá argparse, i když je funkce nepoužije
    """Prints the agent's current configuration."""
    cfg = config.load()
    logger.info("\nCurrent configuration:")
    logger.info(json.dumps(cfg, indent=2))


def set_value(args):
    """Checks and saves one configuration value."""
    cfg = config.load()

    key = args.key
    value = args.value

    # Kontrola hodnoty
    if key == "server_url":
        if not value.startswith(("http://", "https://")):
            logger.error("server_url must start with 'http://' or 'https://'")
            return
    elif key == "auth_token" and not value:
        logger.error("auth_token must not be empty")
        return

    cfg[key] = value
    config.save(cfg)
    logger.info("Set: %s = %s", key, value)
    logger.info("\nThe change applies at the agent's next run.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="agent-cli",
        description="CLI tool for managing the Mastiff agent.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {updater.AGENT_VERSION}",
        help="Shows the agent version.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    status_parser = subparsers.add_parser(
        "status",
        help="Shows the agent's current configuration.",
        description="Shows the Mastiff agent's current configuration.",
    )
    status_parser.set_defaults(func=status)

    set_parser = subparsers.add_parser(
        "set",
        help="Sets a value in the agent's configuration.",
        description="Sets the value of one configuration key. Checks 'server_url' and 'auth_token'.",
    )
    set_parser.add_argument(
        "key",
        choices=["server_url", "auth_token"],
        help="Name of the configuration key (server_url, auth_token).",
    )
    set_parser.add_argument("value", help="The new value for the key.")
    set_parser.set_defaults(func=set_value)

    check_update_parser = subparsers.add_parser(
        "check-update",
        help="Checks whether a new agent version is available.",
        description="Checks whether a new version of the Mastiff agent is available.",
    )
    check_update_parser.add_argument(
        "--auto",
        action="store_true",
        help="Updates without asking when a new version is available.",
    )
    check_update_parser.set_defaults(func=updater.check_for_update)

    update_parser = subparsers.add_parser(
        "update",
        help="Updates the agent to the latest version.",
        description="Updates the Mastiff agent to the latest version on GitHub.",
    )
    update_parser.set_defaults(func=updater.update_agent)

    args = parser.parse_args()

    if args.command:
        args.func(args)
    else:
        parser.print_help()
