import argparse
import json
import logging
import sys

from src import config, enroll, updater

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


def enroll_machine(args):
    """Enrolls this machine, asks for the address and code when they weren't given."""
    server_url = args.server_url
    if not server_url:
        server_url = input("Server address (e.g. https://10.0.0.5:8443): ").strip()
    code = args.code
    if not code:
        code = input("Enrollment code: ").strip()
    enroll.enroll(server_url, code, args.cert_hash)


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

    enroll_parser = subparsers.add_parser(
        "enroll",
        help="Enrolls this machine on the Mastiff server.",
        description="Enrolls this machine with a code from the dashboard's Add machines. "
        "Asks for the address and the code when they're missing.",
    )
    enroll_parser.add_argument(
        "server_url", nargs="?", help="The server's agent address, e.g. https://10.0.0.5:8443."
    )
    enroll_parser.add_argument("--code", help="The enrollment code from the dashboard.")
    enroll_parser.add_argument(
        "--cert-hash", help="The server certificate's fingerprint from the dashboard (sha256:...)."
    )
    enroll_parser.set_defaults(func=enroll_machine)

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
        # Soubory v ProgramData\Mastiff jsou jen pro adminy, bez nich místo tracebacku jen hláška
        try:
            args.func(args)
        except PermissionError:
            logger.error(
                "Run agent-cli as administrator, its files in C:\\ProgramData\\Mastiff "
                "are for administrators only."
            )
            sys.exit(1)
    else:
        parser.print_help()
