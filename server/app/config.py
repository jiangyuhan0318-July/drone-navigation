"""Configuration loading for the Drone Navigation API.

Reads the gitignored ``server/config.json`` (copy ``config.example.json`` and
fill in real values). All secrets — database URL, JWT secret, SMTP password,
OAuth client secrets — live only in that file.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json "
            "and fill in real values."
        )
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


CONFIG = load_config()
