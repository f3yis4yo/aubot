#!/bin/sh
# Start command for Render (render.yaml -> dockerCommand). Render runs dockerCommand
# without a shell, so the chained steps live here instead.
set -e
python manage.py migrate --noinput
python manage.py seed_demo
exec uvicorn config.asgi:application --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips='*'
