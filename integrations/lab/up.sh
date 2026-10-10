#!/bin/sh
# Fills the ingest key into the tool configs and starts the lab.
set -e
cd "$(dirname "$0")"
KEY=$(grep '^TW_INGEST_KEY=' ../../.env | cut -d= -f2)
mkdir -p .gen
for f in config/*; do sed "s/__KEY__/$KEY/g" "$f" > ".gen/$(basename "$f")"; done
docker compose up -d --build "$@"
