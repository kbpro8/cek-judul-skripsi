#!/bin/sh
# Start the web app. Usage: ADMIN_PASSWORD=... ./run.sh [port]
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${1:-8000}"
