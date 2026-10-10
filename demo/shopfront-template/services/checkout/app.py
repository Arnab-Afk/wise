"""Turns a cart into an order: price it, reserve stock, charge, record."""

import uuid

from fastapi import FastAPI

from lib import config, telemetry
from services.checkout import pricing

app = FastAPI(title="checkout")
telemetry.instrument(app)
settings = config.load("checkout")


@app.post("/checkout")
def checkout(body: dict):
    items = body["items"]
    prices = {
        item["sku"]: telemetry.call("catalog", "GET", f"/products/{item['sku']}")["price"]
        for item in items
    }
    totals = pricing.compute_total(items, prices, body.get("coupon"), settings["tax_rate"])
    order_id = f"O-{uuid.uuid4().hex[:8]}"
    telemetry.call("inventory", "POST", "/reserve", json={"items": items})
    payment = telemetry.call("payments", "POST", "/pay",
                             json={"order_id": order_id, "amount": totals["total"]}, timeout=5.0)
    order = telemetry.call("orders", "POST", "/orders", json={
        "order_id": order_id, "customer": body.get("customer"), "items": items,
        "totals": totals, "auth_code": payment["auth_code"],
    })
    return {"order_id": order["order_id"], **totals}
