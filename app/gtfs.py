from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date

import requests

from .config import Settings
from .database import Database, utcnow

GTFS_URL = "https://data.pid.cz/PID_GTFS.zip"
log = logging.getLogger(__name__)


def active_service_ids(calendar: list[dict], exceptions: list[dict], service_date: date) -> set[str]:
    active: set[str] = set()
    weekday = service_date.strftime("%A").lower()
    for row in calendar:
        if row["start_date"] <= service_date.strftime("%Y%m%d") <= row["end_date"] and row.get(weekday) == "1":
            active.add(row["service_id"])
    for row in exceptions:
        if row["date"] == service_date.strftime("%Y%m%d"):
            if row["exception_type"] == "1": active.add(row["service_id"])
            elif row["exception_type"] == "2": active.discard(row["service_id"])
    return active


def _rows(archive: zipfile.ZipFile, name: str) -> list[dict]:
    with archive.open(name) as source:
        return list(csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig", newline="")))


def _iter_rows(archive: zipfile.ZipFile, name: str):
    """Yield rows while the ZIP member remains open instead of loading it into RAM."""
    with archive.open(name) as source:
        yield from csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig", newline=""))


def create_snapshot(db: Database, settings: Settings, service_date: date, session=requests) -> bool:
    """Download and persist exactly one immutable GTFS snapshot for a service date."""
    if db.has_snapshot(service_date.isoformat()):
        log.info("GTFS snapshot already exists service_date=%s", service_date)
        return False
    log.info("Downloading GTFS service_date=%s", service_date)
    response = session.get(GTFS_URL, timeout=settings.http_timeout_seconds)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        # Small files are retained; large CSVs are filtered while streamed.
        routes = _rows(archive, "routes.txt")
        trips = _rows(archive, "trips.txt")
        calendar = _rows(archive, "calendar.txt")
        exceptions = _rows(archive, "calendar_dates.txt")
        feed = _rows(archive, "feed_info.txt")
        active = active_service_ids(calendar, exceptions, service_date)
        target_routes = {r["route_id"] for r in routes if r.get("route_short_name") == settings.route_short_name or r.get("route_id") == settings.route_id}
        selected_trips = [t for t in trips if t.get("route_id") in target_routes and t.get("service_id") in active]
        trip_ids = {t["trip_id"] for t in selected_trips}
        shape_ids = {t.get("shape_id") for t in selected_trips if t.get("shape_id")}
        selected_stop_times: list[dict] = []
        stop_ids: set[str] = set()
        for row in _iter_rows(archive, "stop_times.txt"):
            if row.get("trip_id") not in trip_ids: continue
            selected_stop_times.append(row)
            if row.get("stop_id"): stop_ids.add(row["stop_id"])
        selected_stops = [row for row in _iter_rows(archive, "stops.txt") if row.get("stop_id") in stop_ids]
        try:
            selected_shape_points = [row for row in _iter_rows(archive, "shapes.txt") if row.get("shape_id") in shape_ids]
        except KeyError:
            # GTFS permits feeds without shapes; preserve the snapshot without a route geometry.
            selected_shape_points = []
    feed_version = feed[0].get("feed_version") if feed else None
    with db.connection() as c:
        snapshot_id = c.execute("INSERT INTO gtfs_snapshots(service_date,downloaded_at,feed_version,source_url) VALUES(?,?,?,?)", (service_date.isoformat(), utcnow(), feed_version, GTFS_URL)).lastrowid
        c.executemany("INSERT INTO trips(snapshot_id,trip_id,route_id,service_id,direction_id,trip_headsign,shape_id) VALUES(?,?,?,?,?,?,?)", [(snapshot_id,t["trip_id"],t["route_id"],t["service_id"],t.get("direction_id"),t.get("trip_headsign"),t.get("shape_id")) for t in selected_trips])
        c.executemany("INSERT INTO stops(snapshot_id,stop_id,stop_name,stop_lat,stop_lon) VALUES(?,?,?,?,?)", [(snapshot_id,s["stop_id"],s.get("stop_name", ""),s.get("stop_lat"),s.get("stop_lon")) for s in selected_stops])
        c.executemany("INSERT INTO scheduled_stop_times(snapshot_id,trip_id,stop_sequence,stop_id,scheduled_arrival,scheduled_departure) VALUES(?,?,?,?,?,?)", [(snapshot_id,s["trip_id"],int(s["stop_sequence"]),s["stop_id"],s.get("arrival_time"),s.get("departure_time")) for s in selected_stop_times])
        c.executemany("INSERT INTO shape_points(snapshot_id,shape_id,shape_pt_sequence,shape_pt_lat,shape_pt_lon,shape_dist_traveled) VALUES(?,?,?,?,?,?)", [(snapshot_id,s["shape_id"],int(s["shape_pt_sequence"]),float(s["shape_pt_lat"]),float(s["shape_pt_lon"]),s.get("shape_dist_traveled") or None) for s in selected_shape_points])
    log.info("GTFS snapshot saved service_date=%s active_trips=%d stop_times=%d shape_points=%d", service_date, len(selected_trips), len(selected_stop_times), len(selected_shape_points))
    return True
