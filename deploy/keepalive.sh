#!/bin/bash
# Start the app if it is not answering on port 5061. Run from cron every 5 minutes.
APP="$(cd "$(dirname "$0")/.." && pwd)"  # the app folder, one level above deploy/
cd "$APP" || exit 1
if ! curl -s -m 15 -o /dev/null http://127.0.0.1:5061/; then
    pkill -f "[u]vicorn app.main:app --host 127.0.0.1 --port 5061"
    sleep 2
    echo "$(date) starting" >> "$APP/data/keepalive.log"
    nohup setsid "$APP/deploy/start.sh" >> "$APP/data/app.log" 2>&1 < /dev/null &
fi
