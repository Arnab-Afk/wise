"""Public entry point for the storefront."""

from fastapi import FastAPI

from lib import telemetry

app = FastAPI(title="gateway")
telemetry.instrument(app)


@app.get("/browse")
def browse():
    return telemetry.call("catalog", "GET", "/products")


@app.get("/browse/{sku}")
def browse_one(sku: str):
    return telemetry.call("catalog", "GET", f"/products/{sku}")


@app.post("/checkout")
def checkout(body: dict):
    return telemetry.call("checkout", "POST", "/checkout", json=body, timeout=8.0)
