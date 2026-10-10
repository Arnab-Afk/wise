import time
import uuid

from fastapi import FastAPI, HTTPException

from lib import telemetry

app = FastAPI(title="orders")
telemetry.instrument(app)

ORDERS: dict[str, dict] = {}


@app.post("/orders")
def create(body: dict):
    order_id = body.get("order_id") or f"O-{uuid.uuid4().hex[:8]}"
    ORDERS[order_id] = {**body, "order_id": order_id, "created_at": time.time()}
    if len(ORDERS) > 5000:
        ORDERS.pop(next(iter(ORDERS)))
    return ORDERS[order_id]


@app.get("/orders/{order_id}")
def get(order_id: str):
    if order_id not in ORDERS:
        raise HTTPException(404, "unknown order")
    return ORDERS[order_id]
