import json
import os
import uuid
from pathlib import Path

CONFIG_DIR = Path(os.getenv("PROGRAMDATA", ".")) / "Mastiff"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load():
    """Načte config, pokud neexistuje vytvoř prázdný"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            cfg = json.load(f)
        if "agent_id" not in cfg:
            cfg["agent_id"] = str(uuid.uuid4())
            save(cfg)
        return cfg

    # Vytvoř default
    default = {
        "server_url": "NOT_CONFIGURED",
        "interval_seconds": 60,
        "log_level": "INFO",
        "auth_token": "NOT_CONFIGURED",
        "agent_id": str(uuid.uuid4()),
    }
    save(default)
    return default


def save(config):
    """Uloží config"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
