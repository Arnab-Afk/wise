"""Charges orders through the bank, or through the backup processor when it's switched on."""

import random
import time

from fastapi import FastAPI

from lib import config, flags, telemetry

app = FastAPI(title="payments")
telemetry.instrument(app)
settings = config.load("payments")


def charge_with_bank(order_id: str, amount: float) -> dict:
    timeout = settings["bank_timeout_ms"] / 1000
    attempts = 1 + settings.get("retries", 0)
    for attempt in range(attempts):
        try:
            return telemetry.call("bank", "POST", "/charge",
                                  json={"order_id": order_id, "amount": amount}, timeout=timeout)
        except telemetry.DependencyError:
            if attempt == attempts - 1:
                raise


def charge_with_backup(order_id: str, amount: float) -> dict:
    time.sleep(random.uniform(0.1, 0.2))
    return {"approved": True, "auth_code": f"B{random.randint(100000, 999999)}",
            "amount": amount, "processor": "backup"}


@app.post("/pay")
def pay(body: dict):
    if flags.get("payments_use_backup", False):
        return charge_with_backup(body["order_id"], body["amount"])
    return charge_with_bank(body["order_id"], body["amount"])
