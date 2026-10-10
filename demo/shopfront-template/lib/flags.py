"""Runtime feature flags, polled from the deployer."""

import os
import threading
import time

import httpx

DEPLOYER_URL = os.environ.get("DEPLOYER_URL", "")
_flags: dict = {}


def _poll() -> None:
    global _flags
    while True:
        try:
            _flags = httpx.get(f"{DEPLOYER_URL}/flags", timeout=2.0).json()
        except Exception:
            pass
        time.sleep(2.0)


if DEPLOYER_URL:
    threading.Thread(target=_poll, daemon=True).start()


def get(name: str, default=None):
    return _flags.get(name, default)
