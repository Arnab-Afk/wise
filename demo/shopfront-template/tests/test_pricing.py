from services.checkout import pricing

PRICES = {"SKU-001": 39.0, "SKU-002": 6.5}


def test_total_without_coupon():
    totals = pricing.compute_total([{"sku": "SKU-001", "qty": 2}], PRICES, None, 0.08)
    assert totals["subtotal"] == 78.0
    assert totals["total"] == 84.24


def test_coupon_applies_discount():
    totals = pricing.compute_total([{"sku": "SKU-002", "qty": 4}], PRICES, "welcome10", 0.08)
    assert totals["discounted"] == 23.4
