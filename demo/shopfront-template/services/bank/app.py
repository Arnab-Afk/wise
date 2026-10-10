"""Stand-in for the card network. Its health is controlled by the `bank_mode` flag."""

import random
import time

from fastapi import FastAPI, HTTPException

from lib import flags, telemetry

app = FastAPI(title="bank")
telemetry.instrument(app)


@app.post("/charge")
def charge(body: dict):
    mode = flags.get("bank_mode", "ok")
    if mode == "down":
        raise HTTPException(503, "bank unavailable")
    time.sleep(random.uniform(1.5, 3.0) if mode == "slow" else random.uniform(0.06, 0.16))
    return {"approved": True, "auth_code": f"A{random.randint(100000, 999999)}",
            "amount": body.get("amount")}
