# Shopfront

A small storefront made of seven services. Tracewise watches it, and the scenarios in
`../../scripts/scenarios.py` break it on purpose.

gateway → catalog → inventory
gateway → checkout → catalog, inventory, payments → bank, orders
