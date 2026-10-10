import random

from fastapi import FastAPI, HTTPException

from lib import telemetry

app = FastAPI(title="inventory")
telemetry.instrument(app)

STOCK = {f"SKU-{i:03d}": 10_000 for i in range(1, 21)}


@app.get("/stock/{sku}")
def stock(sku: str):
    if sku not in STOCK:
        raise HTTPException(404, "unknown sku")
    return {"sku": sku, "available": STOCK[sku]}


@app.post("/reserve")
def reserve(body: dict):
    for item in body["items"]:
        if STOCK.get(item["sku"], 0) < item["qty"]:
            raise HTTPException(409, f"out of stock: {item['sku']}")
    for item in body["items"]:
        STOCK[item["sku"]] -= item["qty"]
        if STOCK[item["sku"]] < 100:
            STOCK[item["sku"]] = 10_000  # restock so the demo runs forever
    return {"reservation_id": f"R{random.randint(10**6, 10**7)}"}
