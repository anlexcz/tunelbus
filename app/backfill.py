from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import Settings
from .database import Database


class BackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackfillResult:
    snapshot_id: int
    snapshot_trips: int
    matching_trips: int
    relevant_shape_ids: int
    shape_points_to_insert: int
    inserted_shape_points: int
    updated_trip_shapes: int
    already_complete: bool


def _rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as source:
        return list(csv.DictReader(io.TextIOWrapper(source, encoding="utf-8-sig", newline="")))


def backfill_shapes(db: Database, settings: Settings, service_date: date, gtfs_path: Path) -> BackfillResult:
    if not gtfs_path.is_file():
        raise BackfillError(f"GTFS ZIP was not found: {gtfs_path}")
    with db.connection() as conn:
        snapshot = conn.execute("SELECT id FROM gtfs_snapshots WHERE service_date=?", (service_date.isoformat(),)).fetchone()
        if snapshot is None: raise BackfillError(f"No GTFS snapshot exists for {service_date.isoformat()}.")
        snapshot_id = snapshot["id"]
        stored_trips = conn.execute("SELECT trip_id,shape_id FROM trips WHERE snapshot_id=?", (snapshot_id,)).fetchall()
        existing_points = conn.execute("SELECT shape_id,shape_pt_sequence FROM shape_points WHERE snapshot_id=?", (snapshot_id,)).fetchall()
    if not stored_trips: raise BackfillError(f"Snapshot {snapshot_id} contains no trips.")
    try:
        with zipfile.ZipFile(gtfs_path) as archive:
            names = set(archive.namelist())
            required = {"routes.txt", "trips.txt", "shapes.txt"}
            missing = required - names
            if missing: raise BackfillError(f"GTFS ZIP is missing required file(s): {', '.join(sorted(missing))}.")
            routes, source_trips, source_shapes = _rows(archive, "routes.txt"), _rows(archive, "trips.txt"), _rows(archive, "shapes.txt")
    except zipfile.BadZipFile as exc:
        raise BackfillError("GTFS file is not a valid ZIP archive.") from exc
    route_ids = {row["route_id"] for row in routes if row.get("route_short_name") == settings.route_short_name or row.get("route_id") == settings.route_id}
    if not route_ids: raise BackfillError(f"Route {settings.route_short_name} was not found in GTFS ZIP.")
    source_by_trip = {row["trip_id"]: row.get("shape_id") for row in source_trips if row.get("route_id") in route_ids and row.get("trip_id")}
    stored_by_trip = {row["trip_id"]: row["shape_id"] for row in stored_trips}
    matching_ids = set(stored_by_trip) & set(source_by_trip)
    minimum_matches = max(1, math.ceil(len(stored_by_trip) * 0.75))
    if len(matching_ids) < minimum_matches:
        raise BackfillError(f"GTFS trip mismatch: snapshot has {len(stored_by_trip)} trips, ZIP matches {len(matching_ids)}; at least {minimum_matches} are required. No data were written.")
    conflicts = [trip_id for trip_id in matching_ids if stored_by_trip[trip_id] and source_by_trip[trip_id] and stored_by_trip[trip_id] != source_by_trip[trip_id]]
    if conflicts:
        raise BackfillError(f"GTFS shape_id conflict for {len(conflicts)} stored trip(s). No data were written.")
    shape_ids = {source_by_trip[trip_id] for trip_id in matching_ids if source_by_trip[trip_id]}
    if not shape_ids: raise BackfillError("No relevant shape_id values were found for matching trips.")
    points = []
    try:
        for row in source_shapes:
            if row.get("shape_id") in shape_ids:
                points.append((row["shape_id"], int(row["shape_pt_sequence"]), float(row["shape_pt_lat"]), float(row["shape_pt_lon"]), row.get("shape_dist_traveled") or None))
    except (KeyError, TypeError, ValueError) as exc:
        raise BackfillError(f"Invalid shapes.txt content: {exc}") from exc
    point_shape_ids = {point[0] for point in points}
    if shape_ids - point_shape_ids:
        raise BackfillError(f"shapes.txt has no points for {len(shape_ids - point_shape_ids)} relevant shape_id value(s). No data were written.")
    existing_keys = {(row["shape_id"], row["shape_pt_sequence"]) for row in existing_points}
    missing_points = [point for point in points if (point[0], point[1]) not in existing_keys]
    missing_trip_shapes = [(source_by_trip[trip_id], snapshot_id, trip_id) for trip_id in matching_ids if not stored_by_trip[trip_id] and source_by_trip[trip_id]]
    if not missing_points and not missing_trip_shapes:
        return BackfillResult(snapshot_id, len(stored_by_trip), len(matching_ids), len(shape_ids), 0, 0, 0, True)
    with db.connection() as conn:
        updated = 0
        for shape_id, target_snapshot_id, trip_id in missing_trip_shapes:
            updated += conn.execute("UPDATE trips SET shape_id=? WHERE snapshot_id=? AND trip_id=? AND (shape_id IS NULL OR shape_id='')", (shape_id, target_snapshot_id, trip_id)).rowcount
        inserted = 0
        for shape_id, sequence, lat, lon, distance in missing_points:
            inserted += conn.execute("INSERT OR IGNORE INTO shape_points(snapshot_id,shape_id,shape_pt_sequence,shape_pt_lat,shape_pt_lon,shape_dist_traveled) VALUES(?,?,?,?,?,?)", (snapshot_id, shape_id, sequence, lat, lon, distance)).rowcount
    return BackfillResult(snapshot_id, len(stored_by_trip), len(matching_ids), len(shape_ids), len(missing_points), inserted, updated, False)
