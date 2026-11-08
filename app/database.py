from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS gtfs_snapshots (
 id INTEGER PRIMARY KEY, service_date TEXT NOT NULL UNIQUE, downloaded_at TEXT NOT NULL,
 feed_version TEXT, source_url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES gtfs_snapshots(id), trip_id TEXT NOT NULL,
 route_id TEXT NOT NULL, service_id TEXT NOT NULL, direction_id TEXT, trip_headsign TEXT, shape_id TEXT,
 UNIQUE(snapshot_id, trip_id)
);
CREATE TABLE IF NOT EXISTS stops (
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES gtfs_snapshots(id), stop_id TEXT NOT NULL,
 stop_name TEXT NOT NULL, stop_lat REAL, stop_lon REAL, UNIQUE(snapshot_id, stop_id)
);
CREATE TABLE IF NOT EXISTS scheduled_stop_times (
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES gtfs_snapshots(id), trip_id TEXT NOT NULL,
 stop_sequence INTEGER NOT NULL, stop_id TEXT NOT NULL, scheduled_arrival TEXT, scheduled_departure TEXT,
 UNIQUE(snapshot_id, trip_id, stop_sequence)
);
CREATE TABLE IF NOT EXISTS shape_points (
 id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES gtfs_snapshots(id), shape_id TEXT NOT NULL,
 shape_pt_sequence INTEGER NOT NULL, shape_pt_lat REAL NOT NULL, shape_pt_lon REAL NOT NULL,
 shape_dist_traveled REAL, UNIQUE(snapshot_id, shape_id, shape_pt_sequence)
);
CREATE TABLE IF NOT EXISTS realtime_observations (
 id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, source_timestamp TEXT, trip_id TEXT,
 route_short_name TEXT, vehicle_id TEXT, vehicle_registration_number TEXT, latitude REAL, longitude REAL,
 bearing REAL, speed REAL, delay_actual INTEGER, delay_last_stop_arrival INTEGER,
 delay_last_stop_departure INTEGER, last_stop_id TEXT, last_stop_sequence INTEGER, next_stop_id TEXT,
 next_stop_sequence INTEGER, trip_status TEXT, cancellation INTEGER, raw_payload TEXT NOT NULL,
 payload_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS collector_runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
 records_written INTEGER NOT NULL DEFAULT 0, details TEXT
);
CREATE TABLE IF NOT EXISTS collector_errors (
 id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, component TEXT NOT NULL, error_type TEXT NOT NULL,
 message TEXT NOT NULL, details TEXT
);
CREATE INDEX IF NOT EXISTS idx_rt_observed ON realtime_observations(observed_at);
CREATE INDEX IF NOT EXISTS idx_rt_trip ON realtime_observations(trip_id);
CREATE INDEX IF NOT EXISTS idx_rt_observed_trip ON realtime_observations(observed_at, trip_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_service_date ON gtfs_snapshots(service_date);
CREATE INDEX IF NOT EXISTS idx_stop_times_snapshot_trip ON scheduled_stop_times(snapshot_id, trip_id);
CREATE INDEX IF NOT EXISTS idx_shape_points_snapshot_shape ON shape_points(snapshot_id, shape_id, shape_pt_sequence);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.startup_error: str | None = None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        # SQLite enables foreign-key constraints per connection, not per database.
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()

    def initialize(self) -> None:
        """Create the schema and prove that the service can write database and WAL files."""
        try:
            with self.connection() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.executescript(SCHEMA)
                # BEGIN IMMEDIATE obtains a write lock, detecting read-only DB/data directories at startup.
                conn.execute("BEGIN IMMEDIATE")
            self.startup_error = None
        except (OSError, sqlite3.Error) as exc:
            self.startup_error = f"SQLite startup write check failed for {self.path}: {exc}"
            raise

    def has_snapshot(self, service_date: str) -> bool:
        with self.connection() as c: return c.execute("SELECT 1 FROM gtfs_snapshots WHERE service_date=?", (service_date,)).fetchone() is not None

    def latest_snapshot(self) -> str | None:
        with self.connection() as c:
            row = c.execute("SELECT service_date FROM gtfs_snapshots ORDER BY service_date DESC LIMIT 1").fetchone()
            return row[0] if row else None

    def record_error(self, component: str, exc: Exception) -> None:
        with self.connection() as c: c.execute("INSERT INTO collector_errors(occurred_at,component,error_type,message) VALUES(?,?,?,?)", (utcnow(), component, type(exc).__name__, str(exc)))

    def save_observation(self, row: dict) -> bool:
        columns = list(row)
        with self.connection() as c:
            cursor = c.execute(f"INSERT OR IGNORE INTO realtime_observations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", tuple(row.values()))
            return cursor.rowcount == 1

    def start_run(self) -> int:
        with self.connection() as c:
            return c.execute("INSERT INTO collector_runs(started_at,status) VALUES(?,?)", (utcnow(), "running")).lastrowid

    def finish_run(self, run_id: int, status: str, count: int, details: str | None = None) -> None:
        with self.connection() as c: c.execute("UPDATE collector_runs SET finished_at=?,status=?,records_written=?,details=? WHERE id=?", (utcnow(), status, count, details, run_id))

    def ping(self) -> bool:
        try:
            with self.connection() as c: c.execute("SELECT 1")
            return True
        except (sqlite3.Error, OSError): return False


def utcnow() -> str: return datetime.now().astimezone().isoformat()
def canonical_json(value: object) -> str: return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
