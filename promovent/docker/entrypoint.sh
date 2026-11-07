#!/bin/sh
# api: run migrations (idempotent), then exec uvicorn so it receives SIGTERM directly (graceful shutdown).
# worker: exec the worker. migrate: run migrations only.
set -eu
case "${1:-api}" in
  api)
    alembic upgrade head
    exec uvicorn promovent.api:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' \
         --timeout-graceful-shutdown 10 --no-server-header
    ;;
  worker)
    exec python -m promovent.worker
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
