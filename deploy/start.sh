#!/bin/bash
# Start the app on 127.0.0.1:5061; lab.trida.id forwards to it (see deploy/htaccess-docroot).
APP=/home/acehjurn/lab.trida.id/app
cd "$APP" || exit 1
set -a; . "$APP/.env.production"; set +a
export MALLOC_ARENA_MAX=2  # fewer glibc heaps = less fragmentation in this threaded app
exec "$APP/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 5061 --workers 1 \
     --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log
