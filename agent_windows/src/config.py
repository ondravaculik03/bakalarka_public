import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.getenv("PROGRAMDATA", ".")) / "Mastiff"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load():
    """Načte config, pokud neexistuje vytvoř prázdný"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)

    # Vytvoř default
    default = {
        "server_url": "NOT_CONFIGURED",
        "interval_seconds": 60,
        "log_level": "INFO",
        "auth_token": "NOT_CONFIGURED",
    }
    save(default)
    return default


def save(config):
    """Uloží config"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
