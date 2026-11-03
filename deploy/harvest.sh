#!/bin/bash
# Repository harvest for the hosted app (e.g. weekly from cron): harvest + rebuild the index
# in this process, then restart the web app so it loads the new records.
APP=/home/acehjurn/lab.trida.id/app
cd "$APP" || exit 1
set -a; . "$APP/.env.production"; set +a
"$APP/.venv/bin/python" -m app.harvest >> "$APP/data/harvest.log" 2>&1
pkill -f "[u]vicorn app.main:app --host 127.0.0.1 --port 5061"
sleep 2
"$APP/deploy/keepalive.sh"
