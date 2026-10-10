import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load(service: str) -> dict:
    path = ROOT / "config" / f"{service}.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def service_name() -> str:
    return os.environ.get("TW_SERVICE", "unknown")
