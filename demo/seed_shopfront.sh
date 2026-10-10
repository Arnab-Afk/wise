#!/bin/sh
# Builds demo/shopfront: a git repo of the Shopfront services with a short, multi-author history.
# Safe to re-run: it refuses to overwrite an existing repo unless --force is given.
set -e
cd "$(dirname "$0")"
TEMPLATE=shopfront-template
REPO=shopfront
if [ -d "$REPO/.git" ]; then
  if [ "$1" != "--force" ]; then echo "$REPO already exists (use --force to rebuild)"; exit 0; fi
  rm -rf "$REPO"
fi
mkdir -p "$REPO"
git -C "$REPO" init -q -b main
commit() { # author email message paths...
  name="$1"; email="$2"; msg="$3"; shift 3
  for p in "$@"; do mkdir -p "$REPO/$(dirname "$p")"; cp -r "$TEMPLATE/$p" "$REPO/$p"; done
  git -C "$REPO" add -A
  git -C "$REPO" -c user.name="$name" -c user.email="$email" commit -q -m "$msg"
}
commit "Rahul Iyer" rahul@shopfront.dev "Service skeleton: gateway, catalog, inventory, bank stub" \
  lib services/__init__.py services/gateway services/catalog services/inventory services/bank \
  services.yaml requirements.txt
commit "Priya Shah" priya@shopfront.dev "Checkout flow with coupons and order records" \
  services/checkout services/orders config/checkout.yaml tests
commit "Meera Nair" meera@shopfront.dev "Payments service with bank timeout and retry" \
  services/payments config/payments.yaml
commit "Rahul Iyer" rahul@shopfront.dev "Add README with the service map" README.md
git -C "$REPO" log --oneline
# Track coding-agent sessions (Claude and Cursor) with Entire, and give agents the Entire Graph guide.
if command -v entire >/dev/null 2>&1; then
  (cd "$REPO" && entire enable --agent claude-code >/dev/null && entire agent add cursor >/dev/null \
    && entire graph init-agents --repo . >/dev/null)
  git -C "$REPO" add -A
  git -C "$REPO" -c user.name="Rahul Iyer" -c user.email=rahul@shopfront.dev commit -q \
    -m "Track coding-agent sessions with Entire"
fi
git -C "$REPO" tag -f baseline HEAD >/dev/null
