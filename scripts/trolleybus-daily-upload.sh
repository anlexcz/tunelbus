#!/usr/bin/env bash
set -euo pipefail

# Must run after 03:00 Europe/Prague, with rclone OAuth already configured
# for the Linux user running this script.
cd /srv/anlex/tunelbus
export TZ=Europe/Prague

YESTERDAY="$(date -d yesterday +%F)"
LOCAL="/srv/anlex/tunelbus/trolleybus_exports/trolleybus_${YESTERDAY}.jsonl.gz"
REMOTE="gdrive:Tunelbus/Trolejbusy/trolleybus_${YESTERDAY}.jsonl.gz"

.venv/bin/python -m app.trolleybus export --date "$YESTERDAY"

# --immutable refuses to change an existing remote file with different content.
# No deletion of local records. Transfer failure returns nonzero for retry.
rclone copyto --immutable "$LOCAL" "$REMOTE"

# Verify the archived bytes by downloading the remote object and hashing it.
CHECK="$(mktemp)"
trap 'rm -f "$CHECK"' EXIT
rclone cat "$REMOTE" > "$CHECK"
cmp -s "$LOCAL" "$CHECK" || { echo "ERROR: archive verification failed" >&2; exit 1; }
echo "Verified Google Drive archive: $REMOTE"
