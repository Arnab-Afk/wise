"""Order totals: line items, coupons and tax."""

COUPONS = {"WELCOME10": 0.10, "FALL20": 0.20}


def line_total(item: dict, price: float) -> float:
    return round(price * item["qty"], 2)


def apply_coupon(subtotal: float, coupon: str | None) -> float:
    if not coupon:
        return subtotal
    return round(subtotal * (1 - COUPONS.get(coupon.upper(), 0.0)), 2)


def compute_total(items: list[dict], prices: dict[str, float], coupon: str | None,
                  tax_rate: float) -> dict:
    subtotal = sum(line_total(item, prices[item["sku"]]) for item in items)
    discounted = apply_coupon(subtotal, coupon)
    tax = round(discounted * tax_rate, 2)
    return {"subtotal": subtotal, "discounted": discounted, "tax": tax,
            "total": round(discounted + tax, 2)}
