#!/usr/bin/env bash
set -euo pipefail

# Prune only local, immutable compressed backups following a verified daily
# Google Drive upload. Never touch the live database, legacy raw .sqlite3 files,
# or any remote file. Default is a read-only dry run.
ROOT="${TUNELBUS_BACKUP_ROOT:-/srv/anlex/tunelbus/backups}"
REMOTE="${TUNELBUS_REMOTE_ROOT:-gdrive:Tunelbus/Zálohy}"
DAY="${1:-$(date -d yesterday +%F)}"
APPLY="${TUNELBUS_RETENTION_APPLY:-0}"

[[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] &&
    [[ "$(date -d "$DAY" +%F 2>/dev/null)" == "$DAY" ]] || {
    echo "ERROR: invalid verified day" >&2; exit 2;
}
[[ "$APPLY" == 0 || "$APPLY" == 1 ]] || {
    echo "ERROR: TUNELBUS_RETENTION_APPLY must be 0 or 1" >&2; exit 2;
}
for cmd in rclone sha256sum zstd find stat; do
    command -v "$cmd" >/dev/null || { echo "ERROR: missing $cmd" >&2; exit 1; }
done

# The verified upload must correspond to an existing, valid local daily file.
DAILY="$ROOT/daily/tunelbus_${DAY}.sqlite3.zst"
[[ -s "$DAILY" && -r "$DAILY" ]] || { echo "ERROR: missing verified daily snapshot" >&2; exit 1; }
zstd -q -t "$DAILY"
local_hash="$(sha256sum "$DAILY" | awk '{print $1}')"
remote_hash="$(rclone cat "$REMOTE/tunelbus_${DAY}.sqlite3.zst" | sha256sum | awk '{print $1}')"
[[ "$local_hash" == "$remote_hash" ]] || {
    echo "ERROR: current daily backup is not identical to Google Drive" >&2; exit 1;
}

# Three completed days, including DAY, are kept locally.
CUTOFF="$(date -d "$DAY -2 days" +%F)"
declare -a CANDIDATES=()
declare -a DAILY_CANDIDATES=()
while IFS= read -r -d '' file; do
    name="${file##*/}"
    if [[ "$name" =~ ^tunelbus_([0-9]{4}-[0-9]{2}-[0-9]{2})\.sqlite3\.zst$ ]] &&
       [[ "${BASH_REMATCH[1]}" < "$CUTOFF" ]]; then
        DAILY_CANDIDATES+=("$file")
    fi
done < <(find "$ROOT/daily" -maxdepth 1 -type f -name 'tunelbus_*.sqlite3.zst' -print0)

# Only yesterday's intraday backups, after yesterday's daily image is verified.
# Today's intraday backups are never selected.
while IFS= read -r -d '' file; do
    name="${file##*/}"
    if [[ "$name" =~ ^tunelbus_${DAY}_[0-9]{2}-[0-9]{2}-[0-9]{2}\.sqlite3\.zst$ ]]; then
        CANDIDATES+=("$file")
    fi
done < <(find "$ROOT/intraday" -maxdepth 1 -type f -name "tunelbus_${DAY}_*.sqlite3.zst" -print0)

# Verify every eligible older daily file against its *own* matching remote.
# A missing or changed remote backup aborts the entire prune before any delete.
for file in "${DAILY_CANDIDATES[@]}"; do
    name="${file##*/}"
    zstd -q -t "$file"
    local_hash="$(sha256sum "$file" | awk '{print $1}')"
    remote_hash="$(rclone cat "$REMOTE/$name" | sha256sum | awk '{print $1}')"
    if [[ "$local_hash" != "$remote_hash" ]]; then
        echo "ERROR: remote verification failed: $name" >&2
        exit 1
    fi
    CANDIDATES+=("$file")
done

echo "Retention: verified_day=$DAY keep_daily_since=$CUTOFF apply=$APPLY candidates=${#CANDIDATES[@]}"
for file in "${CANDIDATES[@]}"; do
    if [[ "$APPLY" == 1 ]]; then
        # Refuse symlinks/non-files and files changing after candidate selection.
        [[ -f "$file" && ! -L "$file" ]] || { echo "ERROR: file changed: $file" >&2; exit 1; }
        rm -- "$file"
        echo "PRUNED: $file"
    else
        echo "WOULD_PRUNE: $file"
    fi
done
echo "Retention complete. Legacy .sqlite3 files and all Google Drive files untouched."
