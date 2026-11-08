#!/usr/bin/env bash
set -euo pipefail

DB="/srv/anlex/tunelbus/data/tunelbus.sqlite3"
BACKUP_ROOT="/srv/anlex/tunelbus/backups"
INTRADAY_DIR="$BACKUP_ROOT/intraday"
DAILY_DIR="$BACKUP_ROOT/daily"

MODE="${1:-}"

mkdir -p "$INTRADAY_DIR" "$DAILY_DIR"

create_backup() {
    local destination="$1"

    sqlite3 "$DB" ".backup '$destination'"

    local check
    check="$(sqlite3 "$destination" 'PRAGMA integrity_check;')"

    if [ "$check" != "ok" ]; then
        echo "ERROR: integrity check failed for $destination: $check" >&2
        rm -f "$destination"
        exit 1
    fi
}

case "$MODE" in

    intraday)
        TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
        BACKUP="$INTRADAY_DIR/tunelbus_$TIMESTAMP.sqlite3"

        create_backup "$BACKUP"

        echo "Intraday backup created: $BACKUP"
        ;;

    daily)
        # Záloha spuštěná po půlnoci patří předchozímu dokončenému dni.
        BACKUP_DATE="$(date -d 'yesterday' '+%Y-%m-%d')"
        BACKUP="$DAILY_DIR/tunelbus_$BACKUP_DATE.sqlite3"

        create_backup "$BACKUP"

        # Teprve po úspěšném backupu a integrity checku
        # smažeme průběžné zálohy dokončeného dne.
        find "$INTRADAY_DIR" \
            -type f \
            -name "tunelbus_${BACKUP_DATE}_*.sqlite3" \
            -delete

        # Denní zálohy držíme 14 dní.
        find "$DAILY_DIR" \
            -type f \
            -name 'tunelbus_*.sqlite3' \
            -mtime +14 \
            -delete

        echo "Daily backup created: $BACKUP"
        ;;

    *)
        echo "Usage: $0 {intraday|daily}" >&2
        exit 2
        ;;
esac
