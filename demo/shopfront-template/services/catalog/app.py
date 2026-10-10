from fastapi import FastAPI, HTTPException

from lib import telemetry

app = FastAPI(title="catalog")
telemetry.instrument(app)

PRODUCTS = {
    f"SKU-{i:03d}": {"sku": f"SKU-{i:03d}", "name": name, "price": price}
    for i, (name, price) in enumerate(
        [("Desk lamp", 39.0), ("Notebook", 6.5), ("Backpack", 79.0), ("Water bottle", 18.0),
         ("Headphones", 129.0), ("Keyboard", 99.0), ("Mouse", 35.0), ("Monitor stand", 49.0),
         ("Mug", 12.0), ("Plant pot", 22.0), ("Desk mat", 29.0), ("Cable kit", 15.0),
         ("Webcam", 69.0), ("Charger", 25.0), ("Phone stand", 19.0), ("Pen set", 9.0),
         ("Speaker", 89.0), ("Lamp bulb", 7.0), ("Chair cushion", 34.0), ("Coaster set", 11.0)],
        start=1,
    )
}


@app.get("/products")
def products():
    return list(PRODUCTS.values())


@app.get("/products/{sku}")
def product(sku: str):
    if sku not in PRODUCTS:
        raise HTTPException(404, "unknown sku")
    stock = telemetry.call("inventory", "GET", f"/stock/{sku}")
    return {**PRODUCTS[sku], "available": stock["available"]}
