#!/usr/bin/env bash
set -euo pipefail

# Upload an existing verified daily SQLite/Zstandard snapshot.
# Upload and verify a daily snapshot; optional local retention runs only after success.
BACKUP_ROOT="${TUNELBUS_BACKUP_ROOT:-/srv/anlex/tunelbus/backups}"
REMOTE_ROOT="${TUNELBUS_REMOTE_ROOT:-gdrive:Tunelbus/Zálohy}"
BACKUP_DATE="${1:-$(date -d yesterday +%F)}"

if [[ ! "$BACKUP_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || [[ "$(date -d "$BACKUP_DATE" +%F 2>/dev/null)" != "$BACKUP_DATE" ]]; then
    echo "ERROR: expected a valid date YYYY-MM-DD" >&2
    exit 2
fi
for cmd in rclone sha256sum zstd stat; do
    command -v "$cmd" >/dev/null || { echo "ERROR: $cmd is missing" >&2; exit 1; }
done
BACKUP="$BACKUP_ROOT/daily/tunelbus_$BACKUP_DATE.sqlite3.zst"
[[ -s "$BACKUP" && -r "$BACKUP" ]] || { echo "ERROR: missing or unreadable backup: $BACKUP" >&2; exit 1; }
DESTINATION="$REMOTE_ROOT/tunelbus_$BACKUP_DATE.sqlite3.zst"

echo "Validating local compressed backup: $BACKUP"
zstd -q -t "$BACKUP"
LOCAL_BYTES="$(stat -c %s -- "$BACKUP")"
LOCAL_HASH="$(sha256sum -- "$BACKUP" | awk '{print $1}')"

# --immutable refuses to change remote data if the target exists with
# different content. Do not use sync, move, or any remote deletion here.
echo "Uploading immutable daily snapshot: $BACKUP_DATE"
rclone copyto --immutable --retries 3 -- "$BACKUP" "$DESTINATION"

# Read the uploaded bytes back; do not rely solely on the remote metadata.
REMOTE_HASH="$(rclone cat -- "$DESTINATION" | sha256sum | awk '{print $1}')"
if [[ "$LOCAL_HASH" != "$REMOTE_HASH" ]]; then
    echo "ERROR: Google Drive checksum mismatch for $BACKUP_DATE" >&2
    exit 1
fi
echo "Verified Google Drive daily snapshot: date=$BACKUP_DATE bytes=$LOCAL_BYTES sha256=$LOCAL_HASH"

# Retention is read-only by default. Enable deletion only after reviewing a
# dry run and granting the uploader permission to remove local backup files.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
/usr/bin/bash "$SCRIPT_DIR/prune-verified-backups.sh" "$BACKUP_DATE"
