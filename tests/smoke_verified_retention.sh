#!/usr/bin/env bash
set -euo pipefail
# Isolated retention test, no production DB or network.
ROOT="$(mktemp -d)"
trap 'rm -rf -- "$ROOT"' EXIT
mkdir -p "$ROOT/backups/daily" "$ROOT/backups/intraday" "$ROOT/remote" "$ROOT/bin"
cat > "$ROOT/bin/rclone" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == cat ]] || exit 2
path="$2"
[[ "$path" == fake:* ]] || exit 2
cat "$FAKE_REMOTE/${path#fake:}"
SH
chmod +x "$ROOT/bin/rclone"
export FAKE_REMOTE="$ROOT/remote"
export PATH="$ROOT/bin:$PATH"
export TUNELBUS_BACKUP_ROOT="$ROOT/backups"
export TUNELBUS_REMOTE_ROOT="fake:"
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/prune-verified-backups.sh"

for day in 2026-11-19 2026-11-20 2026-11-21 2026-11-22; do
    printf "snapshot:%s\n" "$day" | zstd -q -c > "$ROOT/backups/daily/tunelbus_$day.sqlite3.zst"
    cp "$ROOT/backups/daily/tunelbus_$day.sqlite3.zst" "$ROOT/remote/tunelbus_$day.sqlite3.zst"
done
printf "intraday\n" | zstd -q -c > "$ROOT/backups/intraday/tunelbus_2026-11-22_12-00-00.sqlite3.zst"
printf "today\n" | zstd -q -c > "$ROOT/backups/intraday/tunelbus_2026-11-23_00-00-00.sqlite3.zst"
printf "legacy\n" > "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3"
printf "legacy intraday\n" > "$ROOT/backups/intraday/tunelbus_2026-11-22_06-00-00.sqlite3"

# Dry run preserves every file.
bash "$SCRIPT" 2026-11-22 > "$ROOT/dryrun.txt"
grep -q WOULD_PRUNE "$ROOT/dryrun.txt"
test -f "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3.zst"

# Corrupt remote older daily to prove fail-closed behavior before any deletion.
printf bad > "$ROOT/remote/tunelbus_2026-11-19.sqlite3.zst"
if TUNELBUS_RETENTION_APPLY=1 bash "$SCRIPT" 2026-11-22 > "$ROOT/failure.txt" 2>&1; then
    echo "ERROR: corrupted remote was accepted" >&2
    exit 1
fi
test -f "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3.zst"
test -f "$ROOT/backups/intraday/tunelbus_2026-11-22_12-00-00.sqlite3.zst"

# Restore remote, then apply.
cp "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3.zst" "$ROOT/remote/tunelbus_2026-11-19.sqlite3.zst"
TUNELBUS_RETENTION_APPLY=1 bash "$SCRIPT" 2026-11-22 > "$ROOT/applied.txt"
test ! -e "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3.zst"
test ! -e "$ROOT/backups/intraday/tunelbus_2026-11-22_12-00-00.sqlite3.zst"
for day in 2026-11-20 2026-11-21 2026-11-22; do
    test -s "$ROOT/backups/daily/tunelbus_$day.sqlite3.zst"
done
test -s "$ROOT/backups/daily/tunelbus_2026-11-19.sqlite3"
test -s "$ROOT/backups/intraday/tunelbus_2026-11-22_06-00-00.sqlite3"
test -s "$ROOT/backups/intraday/tunelbus_2026-11-23_00-00-00.sqlite3.zst"
echo "OK: dry-run, fail-closed remote mismatch, 3-day daily retention, prior-day intraday, legacy preservation"
