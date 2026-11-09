from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from app.collector import VEHICLE_POSITIONS_URL, observations
from app.database import canonical_json

LOG = logging.getLogger("trolleybus")
DEFAULT_ROUTES = "51,52,53,58"
SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY,
 observed_at TEXT NOT NULL,
 service_date TEXT NOT NULL,
 source_timestamp TEXT,
 route_short_name TEXT NOT NULL,
 trip_id TEXT,
 trip_sequence_id INTEGER,
 origin_route_name TEXT,
 cis_trip_number TEXT,
 vehicle_type_id INTEGER,
 vehicle_type_description_cs TEXT,
 vehicle_id TEXT,
 vehicle_registration_number TEXT,
 delay_actual INTEGER,
 latitude REAL,
 longitude REAL,
 raw_payload TEXT NOT NULL,
 payload_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_tb_service_date ON observations(service_date, id);
CREATE INDEX IF NOT EXISTS idx_tb_route_trip ON observations(route_short_name, trip_id);
CREATE TABLE IF NOT EXISTS poll_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL,
 route_short_name TEXT NOT NULL, status TEXT NOT NULL,
 received INTEGER NOT NULL DEFAULT 0, inserted INTEGER NOT NULL DEFAULT 0,
 detail TEXT
);
CREATE TABLE IF NOT EXISTS exports (
 service_date TEXT PRIMARY KEY, filename TEXT NOT NULL,
 sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
 created_at TEXT NOT NULL
);
"""


def options():
    parser = argparse.ArgumentParser(description="Headless trolleybus raw-data archive")
    parser.add_argument("command", choices=["collect", "export", "check"])
    parser.add_argument("--date", help="Service date YYYY-MM-DD; default previous completed date")
    parser.add_argument("--db", default=os.getenv("TROLLEYBUS_DB", "/srv/anlex/tunelbus/data/trolleybus.sqlite3"))
    parser.add_argument("--output", default=os.getenv("TROLLEYBUS_EXPORT_DIR", "/srv/anlex/tunelbus/trolleybus_exports"))
    parser.add_argument("--routes", default=os.getenv("TROLLEYBUS_ROUTES", DEFAULT_ROUTES))
    parser.add_argument("--interval", type=int, default=int(os.getenv("TROLLEYBUS_POLL_SECONDS", "30")))
    return parser.parse_args()


def open_db(path: str):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(observations)")}
    additions = {
        "trip_sequence_id": "INTEGER",
        "origin_route_name": "TEXT",
        "cis_trip_number": "TEXT",
        "vehicle_type_id": "INTEGER",
        "vehicle_type_description_cs": "TEXT",
    }
    added = []
    with conn:
        for name, sql_type in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE observations ADD COLUMN {name} {sql_type}")
                added.append(name)
        # Backfill only when schema changes; null CIS trip numbers are normal.
        if added:
            for item in conn.execute("SELECT id, raw_payload FROM observations").fetchall():
                try:
                    feature = json.loads(item["raw_payload"])
                    trip = (feature.get("properties") or feature).get("trip") or {}
                    vehicle_type = trip.get("vehicle_type") or {}
                    cis = trip.get("cis") or {}
                    conn.execute(
                        """UPDATE observations SET
                           trip_sequence_id=?, origin_route_name=?, cis_trip_number=?,
                           vehicle_type_id=?, vehicle_type_description_cs=?
                           WHERE id=?""",
                        (trip.get("sequence_id"), trip.get("origin_route_name"),
                         cis.get("trip_number"), vehicle_type.get("id"),
                         vehicle_type.get("description_cs"), item["id"]),
                    )
                except (TypeError, ValueError, AttributeError):
                    LOG.warning("Cannot backfill raw observation id=%s", item["id"])
    return conn


def service_date(timestamp: datetime) -> str:
    local = timestamp.astimezone(ZoneInfo("Europe/Prague"))
    return (local.date() - timedelta(days=local.hour < 3)).isoformat()


def routes_from(value: str) -> tuple[str, ...]:
    routes = tuple(dict.fromkeys(v.strip() for v in value.split(",") if v.strip()))
    if not routes or "59" in routes or not all(v.isdecimal() for v in routes):
        raise ValueError("Configure valid route numbers; route 59 is excluded.")
    return routes


def record_run(conn, route: str, status: str, received: int, inserted: int, detail: str = ""):
    with conn:
        conn.execute(
            "INSERT INTO poll_runs(started_at,route_short_name,status,received,inserted,detail) VALUES (?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), route, status, received, inserted, detail[:500]),
        )


def collect_once(conn, http: requests.Session, route: str, api_key: str):
    try:
        response = http.get(
            VEHICLE_POSITIONS_URL,
            params={"routeShortName": route},
            headers={"X-Access-Token": api_key},
            timeout=15,
        )
        response.raise_for_status()
        now = datetime.now(timezone.utc)
        parsed = observations(response.json(), now.isoformat(), route)
        inserted = 0
        with conn:
            for row in parsed:
                # Keep the original source feature, not derived metrics or web statistics.
                trip = json.loads(row["raw_payload"]).get("properties", {}).get("trip") or {}
                cis = trip.get("cis") or {}
                conn.execute(
                    """INSERT OR IGNORE INTO observations
                    (observed_at,service_date,source_timestamp,route_short_name,trip_id,
                     trip_sequence_id,origin_route_name,cis_trip_number,vehicle_type_id,vehicle_type_description_cs,vehicle_id,vehicle_registration_number,delay_actual,latitude,
                     longitude,raw_payload,payload_hash)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["observed_at"], service_date(now), row["source_timestamp"],
                     route, row["trip_id"], trip.get("sequence_id"), trip.get("origin_route_name"), cis.get("trip_number"),
                     vehicle_type.get("id"), vehicle_type.get("description_cs"), row["vehicle_id"],
                     row["vehicle_registration_number"], row["delay_actual"],
                     row["latitude"], row["longitude"], row["raw_payload"],
                     row["payload_hash"]),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
        record_run(conn, route, "ok", len(parsed), inserted)
        LOG.info("route=%s received=%s inserted=%s", route, len(parsed), inserted)
    except (requests.RequestException, ValueError, sqlite3.Error) as exc:
        LOG.exception("Polling failed for route %s", route)
        record_run(conn, route, "error", 0, 0, f"{type(exc).__name__}: {exc}")


def collect(conn, routes: tuple[str, ...], interval: int):
    if interval < 20:
        raise ValueError("Polling interval must be at least 20 seconds")
    api_key = os.getenv("GOLEMIO_API_KEY")
    if not api_key:
        raise ValueError("GOLEMIO_API_KEY environment variable is required")
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with requests.Session() as session:
        while not stopping:
            start = time.monotonic()
            for route in routes:
                if stopping:
                    break
                collect_once(conn, session, route, api_key)
            while not stopping and time.monotonic() - start < interval:
                time.sleep(min(1, max(0, interval - (time.monotonic() - start))))


def export_day(conn, day: str, output_dir: str) -> Path:
    # Freeze an already completed service day, ending at 03:00 local time.
    today = service_date(datetime.now(timezone.utc))
    if day >= today:
        raise ValueError("Only completed service days may be exported")
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / f"trolleybus_{day}.jsonl.gz"
    temporary = destination.with_suffix(".jsonl.gz.tmp")
    count = 0
    try:
        with gzip.open(temporary, "wt", encoding="utf-8", newline="\n") as sink:
            for row in conn.execute(
                "SELECT * FROM observations WHERE service_date=? ORDER BY id", (day,)
            ):
                record = dict(row)
                record["raw_payload"] = json.loads(record["raw_payload"])
                sink.write(canonical_json(record) + "\n")
                count += 1
        # Never silently overwrite an archive: idempotent re-runs verify equal bytes.
        sha = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if destination.exists():
            # gzip metadata can change between exports, so compare parsed record content.
            with gzip.open(destination, "rt", encoding="utf-8") as existing, gzip.open(temporary, "rt", encoding="utf-8") as updated:
                if existing.read() != updated.read():
                    raise RuntimeError(f"Export already exists with different data: {destination}")
            temporary.unlink()
            sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        else:
            temporary.replace(destination)
        with conn:
            conn.execute(
                """INSERT INTO exports(service_date,filename,sha256,row_count,created_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(service_date) DO UPDATE SET
                   filename=excluded.filename,sha256=excluded.sha256,
                   row_count=excluded.row_count,created_at=excluded.created_at""",
                (day, str(destination), sha, count, datetime.now(timezone.utc).isoformat()),
            )
        print(f"export={destination} rows={count} sha256={sha}")
        return destination
    finally:
        if temporary.exists():
            temporary.unlink()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = options()
    routes = routes_from(args.routes)
    conn = open_db(args.db)
    try:
        if args.command == "collect":
            collect(conn, routes, args.interval)
        elif args.command == "export":
            day = args.date or (datetime.fromisoformat(service_date(datetime.now(timezone.utc))).date() - timedelta(days=1)).isoformat()
            export_day(conn, day, args.output)
        else:
            last = conn.execute("SELECT started_at,status FROM poll_runs ORDER BY id DESC LIMIT 1").fetchone()
            total = conn.execute("SELECT count(*) FROM observations").fetchone()[0]
            by_route = [dict(row) for row in conn.execute(
                "SELECT route_short_name AS route,COUNT(*) AS rows,"
                "MAX(observed_at) AS last_observed_at,"
                "COUNT(DISTINCT origin_route_name || '/' || trip_sequence_id) AS orders,"
                "SUM(CASE WHEN trip_sequence_id IS NULL OR origin_route_name IS NULL THEN 1 ELSE 0 END) AS missing_order,"
                "SUM(CASE WHEN vehicle_registration_number IS NULL THEN 1 ELSE 0 END) AS missing_vehicle,"
                "SUM(CASE WHEN vehicle_type_id IS NULL THEN 1 ELSE 0 END) AS missing_vehicle_type "
                "FROM observations GROUP BY route_short_name ORDER BY route_short_name"
            )]
            print(json.dumps({"configured_routes":routes,"rows":total,
                              "last_poll":dict(last) if last else None,
                              "by_route":by_route}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
