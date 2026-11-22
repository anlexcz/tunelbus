# Tunelbus: off-site daily SQLite backups to Google Drive

**Status: staged, NOT enabled automatically by git pull.** The daily local backup service continues to run as `tunelbus`, and the remote uploader runs under `anlex` with supplementary `tunelbus` group *only in that service*. The latter group grants read access to backups and potentially other group-readable data: review this access before activation. No global chmod/chgrp and no sudoers changes are needed.

## Prerequisites
- Local daily snapshot `backups/daily/tunelbus_YYYY-MM-DD.sqlite3.zst` created by existing `backup.sh daily`.
- `rclone` configured as `anlex` with access to `gdrive:Tunelbus/Zálohy`.
- Fix rclone shared Google Drive OAuth client retirement with a user-managed client ID and confirm it remains usable. Do not put tokens or client secrets in Git.
- `zstd`, `sha256sum`, `rclone` installed; enough free disk space to run the normal daily snapshot.
- Confirm service account/group names and path on the VPS.

## Behavior
- Uploads **yesterday's daily compressed snapshot** at 04:00 Europe/Prague (assuming host local timezone is Europe/Prague); daily SQLite backup remains at 02:30.
- Existing filenames are immutable; same snapshot can be retried, changed remote content is refused.
- Checks Zstandard stream locally; reads remote file back via `rclone cat` and checks SHA-256 exact byte identity.
- Exits nonzero on missing snapshot, insufficient permissions, transfer errors or checksum mismatch.
- **Never removes or prunes any local or remote files.** The existing local backup script has a separate ~14-day retention for new compressed daily archives; shortening this to 3 days is NOT implemented because remote archiving has not yet been observed over time.
- A successful transfer means the uploaded compressed bytes match a locally verified archive; a remote restore test is still required for long-term assurance.

## Manual test before activation
1. Ensure client ID migration is complete and rclone connectivity works.
2. Verify `id anlex`, `getent group tunelbus`, and the directory ownership/access.
3. Read-only local test with group privileges: `sudo -u anlex -g anlex -G tunelbus zstd -t /srv/anlex/tunelbus/backups/daily/tunelbus_YYYY-MM-DD.sqlite3.zst`.
4. Upload one existing daily snapshot by running the script under service context, ideally using `sudo systemctl start tunelbus-gdrive-upload.service` **after** installing the unit. Inspect `journalctl -u tunelbus-gdrive-upload.service -n 100 --no-pager`.
5. Validate restore by downloading a remote snapshot to a temporary file, decompressing, and running SQLite `PRAGMA integrity_check`. Keep enough free space or stream into a test destination with sufficient capacity.

## Installation (only after explicit approval)
```bash
cd /srv/anlex/tunelbus
git pull --ff-only origin main
sudo install -m 0644 deploy/systemd/tunelbus-gdrive-upload.service /etc/systemd/system/
sudo install -m 0644 deploy/systemd/tunelbus-gdrive-upload.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start tunelbus-gdrive-upload.service
sudo systemctl status tunelbus-gdrive-upload.service --no-pager
# Enable only after verifying success:
sudo systemctl enable --now tunelbus-gdrive-upload.timer
```

## Next stage (not part of this change)
1. Archive/verify historical daily snapshots one at a time.
2. Agree 3-day local retention policy and ensure a remote verification marker/manifest supports safe pruning.
3. Fix any incorrect `app/backup.py` offline file-copy backup usage.
4. Add failure alerts and regular remote restore drills.
