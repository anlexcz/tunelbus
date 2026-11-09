"""Regression checks for the isolated trolleybus collector. No API calls."""
import gzip
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.trolleybus import __main__ as tb


class TrolleybusCollectorTests(unittest.TestCase):
    def test_route_scope_and_service_day(self):
        self.assertEqual(tb.routes_from("51,52,53,58,51"), ("51", "52", "53", "58"))
        with self.assertRaises(ValueError):
            tb.routes_from("51,59")
        self.assertEqual(
            tb.service_date(datetime(2026, 11, 9, 0, 54, tzinfo=timezone.utc)),
            "2026-11-08",
        )

    def test_schema_backfill_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbfile = str(Path(tmp) / "test.sqlite3")
            conn = tb.open_db(dbfile)
            self.assertEqual(conn.execute("SELECT count(*) FROM observations").fetchone()[0], 0)
            feature = {"properties": {"trip": {
                "origin_route_name": "91", "sequence_id": 79,
                "vehicle_registration_number": 8256,
                "cis": {"trip_number": None},
                "vehicle_type": {"id": 6, "description_cs": "noční tramvaj"},
            }}}
            conn.execute(
                "INSERT INTO observations (observed_at,service_date,route_short_name,raw_payload,payload_hash) VALUES (?,?,?,?,?)",
                ("2026-11-09T00:54:00+00:00", "2026-11-07", "91", json.dumps(feature), "hash1"),
            )
            conn.commit()
            # Simulate an old schema by deleting just the newly extracted values.
            conn.execute(
                "UPDATE observations SET trip_sequence_id=NULL, origin_route_name=NULL,vehicle_type_id=NULL,vehicle_type_description_cs=NULL"
            )
            conn.commit()
            conn.close()
            # Reopening an already-migrated database must not rewrite user data.
            conn = tb.open_db(dbfile)
            self.assertIsNone(conn.execute("SELECT trip_sequence_id FROM observations").fetchone()[0])
            conn.close()
            # A completed service day is exportable.
            conn = tb.open_db(dbfile)
            output = tb.export_day(conn, "2026-11-07", str(Path(tmp) / "out"))
            with gzip.open(output, "rt", encoding="utf-8") as src:
                rows = [json.loads(line) for line in src]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["raw_payload"]["properties"]["trip"]["sequence_id"], 79)
            self.assertEqual(tb.export_day(conn, "2026-11-07", str(Path(tmp) / "out")), output)
            conn.close()

    def test_backfill_when_new_columns_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.sqlite3")
            conn = sqlite3.connect(path)
            conn.execute("""CREATE TABLE observations (
                id INTEGER PRIMARY KEY, observed_at TEXT,service_date TEXT,
                route_short_name TEXT,trip_id TEXT,vehicle_id TEXT,
                vehicle_registration_number TEXT, delay_actual INTEGER,
                latitude REAL, longitude REAL, raw_payload TEXT,payload_hash TEXT UNIQUE,
                source_timestamp TEXT
            )""")
            payload = {"properties": {"trip": {
                "origin_route_name": "91", "sequence_id": 79,
                "vehicle_type": {"id": 6, "description_cs": "noční tramvaj"},
            }}}
            conn.execute(
                "INSERT INTO observations (observed_at,service_date,route_short_name,raw_payload,payload_hash) VALUES (?,?,?,?,?)",
                ("2026-11-09T00:54:00+00:00", "2026-11-08", "91", json.dumps(payload), "x"),
            )
            conn.commit()
            conn.close()
            migrated = tb.open_db(path)
            row = migrated.execute(
                "SELECT origin_route_name,trip_sequence_id,vehicle_type_id,vehicle_type_description_cs FROM observations"
            ).fetchone()
            self.assertEqual(tuple(row), ("91", 79, 6, "noční tramvaj"))
            migrated.close()


if __name__ == "__main__":
    unittest.main()
