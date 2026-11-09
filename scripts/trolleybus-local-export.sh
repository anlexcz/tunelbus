#!/usr/bin/env bash
set -euo pipefail

# Creates a local archive for the last completed Prague service day.
# This does not require cloud credentials or modify the active collector.
export TZ=Europe/Prague
SERVICE_DAY="$(date -d yesterday +%F)"
DB="/srv/anlex/tunelbus-trolleybus/data/trolleybus.sqlite3"
OUTPUT_DIR="/srv/anlex/tunelbus-trolleybus/exports"
PYTHON="/srv/anlex/tunelbus/.venv/bin/python"

if [[ ! -f "$DB" ]]; then
  echo "ERROR: collector database not found: $DB" >&2
  exit 1
fi

"$PYTHON" -m app.trolleybus export \
  --db "$DB" \
  --date "$SERVICE_DAY" \
  --output "$OUTPUT_DIR"
