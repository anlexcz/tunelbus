# Trolleybus Collector (development branch)

Headless raw-data collection only. No UI, public API, or analytics.

## Scope
- Routes configured via TROLLEYBUS_ROUTES (default 51,52,53,58); route 59 explicitly forbidden.
- Replacement buses are included because filtering is by line rather than vehicle type.
- Observations retain source JSON, source timestamp, fetched timestamp, delay, vehicle identity and trip.
- Run alongside Tunelbus 145, using **a separate SQLite database**. The service template uses a separate Git worktree `/srv/anlex/tunelbus-trolleybus` and the existing venv and protected `.env` file. Do not start a service against code not deployed at that path.
- No automatic deletion until daily cloud uploads and independent backups have been verified.
- The route roster must be checked against the actual PID timetable before production.

## Local smoke tests
Run from repository root with the existing Python virtual environment:

```bash
python -m app.trolleybus check --db /tmp/trolleybus-test.sqlite3
python -m app.trolleybus export --date 2026-11-07 --db /tmp/trolleybus-test.sqlite3 --output /tmp/trolleybus-out
```

Collection needs GOLEMIO_API_KEY in the process environment. This tool does not automatically load .env; production systemd should obtain its EnvironmentFile from the existing protected location.

```bash
TROLLEYBUS_ROUTES=51,52,53,58 GOLEMIO_API_KEY=... python -m app.trolleybus collect
```

Never put an actual API key in shell history. Prefer an EnvironmentFile or protected runtime environment.

## Daily archive
Service day: Europe/Prague 03:00–02:59:59. Export is named for its starting date.
At **03:15** local time a scheduler should run the exporter for the previous completed service date and upload via **rclone copyto** to the private Drive folder, avoiding overwrite unless verified. Maintain a stable remote folder ID or explicit rclone folder target after interactive OAuth configuration.

Google Drive folder ID for this project: `18nrR4SBh3reuc3tpzSrOXaBIMOvMg6lf`.
Do **not** put OAuth credentials or rclone configuration into Git.

Suggested example after configuring remote name `gdrive` and verifying folder placement:

```bash
python -m app.trolleybus export --date YYYY-MM-DD
rclone copyto /srv/anlex/tunelbus/trolleybus_exports/trolleybus_YYYY-MM-DD.jsonl.gz gdrive:Tunelbus/Trolejbusy/trolleybus_YYYY-MM-DD.jsonl.gz
```

Do not automate this example as-is until folder targeting, timer, service accounts, timezone and rclone permissions are tested.

**Data fields:** The archive preserves the original Golemio feature. Indexed SQLite columns include `origin_route_name` + `trip_sequence_id` (operational route/order), vehicle registration, vehicle type ID and Czech description (`trip.vehicle_type`), GTFS trip ID, timestamps and actual delay. The vehicle type is a **Golemio-reported type**, not independently verified physical vehicle type. This allows observing replacement buses when returned on a monitored line.\n\n**Important limitation:** This implementation does not yet archive matching historical GTFS schedules. The exact `source_timestamp` freshness and API coverage need longer live observation before production is considered validated.

## Integrity / safety
- Existing production tables for line 145 are not modified.
- Archive files are immutable by default; a re-export with different records fails.
- Check poll errors, count/coverage and archive integrity before considering any retention policy.
- Keep source times: sampling time is not source observation time.
