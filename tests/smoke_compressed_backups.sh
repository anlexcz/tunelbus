#!/usr/bin/env bash
set -euo pipefail

# Isolated smoke test: no production paths, no production database, no cleanup of real backups.
ROOT="$(mktemp -d)"
trap 'rm -rf -- "$ROOT"' EXIT
export TUNELBUS_DB="$ROOT/data/test.sqlite3"
export TUNELBUS_BACKUP_ROOT="$ROOT/backups"
mkdir -p "$ROOT/data" "$ROOT/backups/daily"

sqlite3 "$TUNELBUS_DB" "CREATE TABLE samples (id INTEGER PRIMARY KEY, value TEXT); INSERT INTO samples (value) VALUES ('historic'), ('current');"
# Legacy snapshot sentinel must survive all new cleanup paths.
echo 'must stay' > "$ROOT/backups/daily/tunelbus_2026-01-01.sqlite3"

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backup.sh"
bash "$SCRIPT" intraday
bash "$SCRIPT" daily
bash "$SCRIPT" daily

DAILY="$(find "$ROOT/backups/daily" -maxdepth 1 -name '*.sqlite3.zst' -print -quit)"
INTRADAY="$(find "$ROOT/backups/intraday" -maxdepth 1 -name '*.sqlite3.zst' -print -quit)"
[[ -n "$DAILY" && -n "$INTRADAY" ]]
[[ "$(cat "$ROOT/backups/daily/tunelbus_2026-01-01.sqlite3")" == 'must stay' ]]
zstd -tq "$DAILY"
zstd -tq "$INTRADAY"

zstd -dc "$DAILY" > "$ROOT/restore.sqlite3"
[[ "$(sqlite3 "file:$ROOT/restore.sqlite3?immutable=1" 'PRAGMA integrity_check;')" == "ok" ]]
[[ "$(sqlite3 "file:$ROOT/restore.sqlite3?immutable=1" 'SELECT COUNT(*) FROM samples;')" == "2" ]]

echo "OK: isolated daily+intraday compressed backups restore correctly; legacy snapshots untouched"
