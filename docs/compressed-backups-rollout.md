# Tunelbus — compressed SQLite backups (rollout)

## Scope
- Keeps the live `data/tunelbus.sqlite3` and all historical records unchanged.
- Keeps existing `tunelbus-backup-daily.timer` and `tunelbus-backup-intraday.timer` schedules.
- Creates full, consistent SQLite Backup API snapshots compressed as `.sqlite3.zst` with `zstd -1 -T1`.
- Checks SQLite integrity **before** compression and validates Zstandard archive **after** compression.
- Uses same-directory temporary files, a shared `flock`, and final rename.
- Keeps the existing approximate 14-day retention on **new compressed daily snapshots**; removes only previous-day **compressed** intraday snapshots after a successful daily backup.
- **Does not delete, compress in place, or migrate any existing `.sqlite3` archives.**
- Does not configure Google Drive uploads. Off-server backups are a separate step requiring account/permissions verification.

## Rollout (do not run before reviewing)
1. Merge the PR, then update the server copy of `backup.sh` only, ensuring no local modifications are lost.
2. First, run the isolated smoke test without changing the production working tree:\n\n   ```bash\n   cd /srv/anlex/tunelbus\n   git fetch origin feat/compressed-sqlite-backups\n   TEST_DIR="$(mktemp -d)"\n   git archive FETCH_HEAD backup.sh tests/smoke_compressed_backups.sh | tar -x -C "$TEST_DIR"\n   bash "$TEST_DIR/tests/smoke_compressed_backups.sh"\n   # Remove TEST_DIR after confirming it contains only the extracted test files.\n   ```\n\n3. Before enabling: `bash -n /srv/anlex/tunelbus/backup.sh`; ensure `zstd`, `sqlite3`, and `flock` are installed.
3. Check available disk. The snapshot process needs room for an additional uncompressed SQLite copy **plus** its compressed output simultaneously, currently approximately 1.3 GB, with safety margin.
4. For first trial, use an isolated test environment or deliberately run one service while monitoring available disk: `sudo systemctl start tunelbus-backup-intraday.service`. Note: this writes a **new** backup but deletes no legacy backup.
5. Check `systemctl status tunelbus-backup-intraday.service`, journal logs and generated `.sqlite3.zst`. `zstd -t /path/to/new.sqlite3.zst` should succeed.
6. Full **restore test** (requires another ~1.1 GB temporary disk): decompress a new archive into a separate temporary location using `zstd -dc archive.sqlite3.zst > /separate/test/location/restore.sqlite3`, then `sqlite3 'file:/separate/test/location/restore.sqlite3?immutable=1' 'PRAGMA integrity_check;'`. Remove the restored **test** copy only after validation.
7. Observe next automatic daily/intraday runs and `/health`. Verify collection and web history remain available.
8. Separately configure and verify authenticated offsite backup to Google Drive, including readback/restore, before any legacy backup deletion.
9. Legacy archive migration/cleanup requires a separate explicit approval and verified replacement archives. With only ~6.4 GB free, use one-at-a-time conversion and validation; do not bulk-copy all 20 GB.

## Cautions
- SQLite snapshot consistency is obtained with `sqlite3 .backup`; never copy active DB or `-wal`/`-shm` with a plain file copy as an alternative.
- `zstd -t` checks compressed-stream integrity; it is not a substitute for a decompressed SQLite restore test.
- `rclone listremotes` verifies only that a remote is configured, not that offsite backups exist.
- During rollout, old `.sqlite3` and new `.sqlite3.zst` coexist, so disk usage can temporarily increase.
- The `app/backup.py` utility still uses `shutil.copy2`; audit its callers before relying on it for live backups.
