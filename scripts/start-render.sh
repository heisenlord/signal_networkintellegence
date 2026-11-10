#!/usr/bin/env bash
set -euo pipefail
# Render terminates HTTPS and supplies trusted forwarding headers. Keep one
# process because SQLite, rate limits and investigation admission are local.
exec python -m uvicorn backend.main:app \
  --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips '*' --no-server-header \
  --limit-concurrency 64 --timeout-keep-alive 5
