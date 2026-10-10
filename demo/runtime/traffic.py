"""Steady storefront traffic: browsing plus checkouts with a mix of carts."""

import os
import random
import threading
import time

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://127.0.0.1:7101")
BROWSE_RPS = float(os.environ.get("BROWSE_RPS", "8"))
CHECKOUT_RPS = float(os.environ.get("CHECKOUT_RPS", "3"))
SKUS = [f"SKU-{i:03d}" for i in range(1, 21)]
CUSTOMERS = ["ana", "ben", "chen", "dara", "eli", "farah", "gus", "hana"]


def cart() -> dict:
    body = {"customer": random.choice(CUSTOMERS),
            "items": [{"sku": random.choice(SKUS), "qty": random.randint(1, 3)}
                      for _ in range(random.randint(1, 3))]}
    if random.random() < 0.3:
        body["coupon"] = random.choice(["WELCOME10", "FALL20"])
    if random.random() < 0.25:
        body["gift_wrap"] = {"style": random.choice(["classic", "kraft"]),
                             "message": "Enjoy!"}
    return body


def loop(rps: float, fn) -> None:
    client = httpx.Client(timeout=10)
    while True:
        started = time.time()
        threading.Thread(target=fn, args=(client,), daemon=True).start()
        time.sleep(max(0.0, random.expovariate(rps) - (time.time() - started)))


def browse(client: httpx.Client) -> None:
    try:
        if random.random() < 0.5:
            client.get(f"{GATEWAY}/browse")
        else:
            client.get(f"{GATEWAY}/browse/{random.choice(SKUS)}")
    except httpx.HTTPError:
        pass


def checkout(client: httpx.Client) -> None:
    try:
        client.post(f"{GATEWAY}/checkout", json=cart())
    except httpx.HTTPError:
        pass


if __name__ == "__main__":
    time.sleep(float(os.environ.get("TRAFFIC_DELAY", "10")))
    threading.Thread(target=loop, args=(BROWSE_RPS, browse), daemon=True).start()
    loop(CHECKOUT_RPS, checkout)
