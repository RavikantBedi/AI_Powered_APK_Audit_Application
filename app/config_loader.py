"""Per-client business config loader.

Each client has a JSON file at configs/client_<id>.json holding the facts the
agent is allowed to answer from: FAQs, services, pricing, hours. Kept as flat
JSON for now so onboarding is a copy-paste job; can move to a DB table later
without touching callers (they only see the returned dict).
"""
import json
import os
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "configs"


def _config_dir() -> Path:
    # CONFIG_DIR env override keeps tests away from real client configs.
    return Path(os.getenv("CONFIG_DIR", str(_DEFAULT_DIR)))


class ClientConfigNotFound(Exception):
    pass


def load_client_config(client_id: int) -> dict:
    path = _config_dir() / f"client_{client_id}.json"
    if not path.exists():
        raise ClientConfigNotFound(f"No config file for client {client_id} at {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_client_config(client_id: int, config: dict) -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / f"client_{client_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
