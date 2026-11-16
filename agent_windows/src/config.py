import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.getenv("PROGRAMDATA", ".")) / "Mastiff"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEY_FILE = CONFIG_DIR / "agent.key"
CERTIFICATE_FILE = CONFIG_DIR / "agent.pem"
CA_FILE = CONFIG_DIR / "ca.pem"


def load():
    """Loads the config, an empty one if it doesn't exist yet."""
    # agent_id tady nevzniká, dělá ho jen enroll, jinak by každý naklonovaný image měl stejné ID
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}


def save(config):
    """Saves the config."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
