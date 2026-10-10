#!/bin/sh
set -e
git config --global --add safe.directory '*'
python /app/traffic.py &
exec python -m uvicorn deployer:app --app-dir /app --host 0.0.0.0 --port 7000 --log-level warning
