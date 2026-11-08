from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .analytics.metrics import day_metrics
from .analytics.representatives import day_representatives, interval_trip_representatives, trip_detail as analytics_trip_detail
from .analytics.service_day import service_day_bounds as analytics_service_day_bounds, service_day_for_date as analytics_service_day_for_date
from .config import Settings
from .database import Database

SCHEDULE_COLUMNS = ["service_date", "trip_id", "direction_id", "trip_headsign", "stop_sequence", "stop_id", "stop_name", "scheduled_arrival", "scheduled_departure", "stop_lat", "stop_lon"]
REALTIME_COLUMNS = ["observed_at", "source_timestamp", "trip_id", "route_short_name", "vehicle_registration_number", "latitude", "longitude", "bearing", "speed", "delay_actual", "delay_last_stop_arrival", "delay_last_stop_departure", "last_stop_id", "last_stop_sequence", "next_stop_id", "next_stop_sequence", "trip_status", "cancellation"]


def parse_day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def available_days(db: Database) -> list[str]:
    with db.connection() as c:
        rows = c.execute("""
            SELECT service_date AS day FROM gtfs_snapshots
            UNION SELECT substr(observed_at, 1, 10) AS day FROM realtime_observations
            ORDER BY day DESC
        """).fetchall()
    return [row["day"] for row in rows if row["day"]]


def _snapshot_id(conn, day: str) -> int | None:
    row = conn.execute("SELECT id FROM gtfs_snapshots WHERE service_date=?", (day,)).fetchone()
    return row["id"] if row else None


def summary(db: Database, settings: Settings, day: str) -> dict[str, Any]:
    """Day-summary adapter backed by equal-weight trip representatives."""
    metrics = day_metrics(db, settings, day)
    data = day_representatives(db, settings, day)
    with db.connection() as conn:
        snapshot_id = _snapshot_id(conn, day)
        planned_stop_times = conn.execute("SELECT count(*) FROM scheduled_stop_times WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0] if snapshot_id else 0
    return {
        "date": day,
        "available": bool(data.planned_trips or data.raw_observation_count),
        "realtime_observations": metrics["realtime_observations"],
        "unique_trip_ids": len(data.raw_trip_ids),
        "unique_vehicles": len(data.raw_vehicle_ids),
        "planned_trips": len(data.planned_trips),
        "planned_stop_times": planned_stop_times,
        "average_delay": metrics["average_delay"],
        "median_delay": metrics["median_delay"],
        "maximum_delay": metrics["maximum_delay"],
        "minimum_delay": metrics["minimum_delay"],
        "coverage_percentage": metrics["coverage_percentage"],
        "coverage_status": metrics["coverage_status"],
    }


def trip_rows(db: Database, settings: Settings, day: str) -> list[dict[str, Any]]:
    """Compatibility response for trip rows, with analytical fields from trip representatives."""
    data = day_representatives(db, settings, day)
    _, representatives, _, _ = interval_trip_representatives(data, settings)
    by_trip = {value.trip.trip_id: value for value in representatives}
    start, end = service_day_for_date(settings, date.fromisoformat(day))
    with db.connection() as conn:
        counts = {row["trip_id"]: row["count"] for row in conn.execute("""
            SELECT trip_id,count(*) AS count FROM realtime_observations
            WHERE observed_at>=? AND observed_at<? AND trip_id IS NOT NULL GROUP BY trip_id
        """, (start.isoformat(), end.isoformat())).fetchall()}
    rows = []
    for trip in sorted(data.planned_trips, key=lambda value: (value.start_seconds if value.start_seconds is not None else float("inf"), value.trip_id)):
        value = by_trip.get(trip.trip_id)
        rows.append({
            "trip_id": trip.trip_id, "direction_id": trip.direction_id, "trip_headsign": trip.headsign,
            "scheduled_start": trip.scheduled_start,
            "vehicle_registration_number": value.vehicle_registration_number if value else None,
            "realtime_observations": counts.get(trip.trip_id, 0),
            "average_delay": round(value.representative_delay) if value else None,
            "maximum_delay": value.max_delay if value else None,
            "last_delay": value.terminal_or_last_delay if value else None,
            "number_of_representative_stops": value.number_of_representative_stops if value else 0,
            "flags": sorted(value.flags) if value else [],
        })
    return rows


def trip_detail(db: Database, settings: Settings, day: str, trip_id: str) -> dict[str, Any] | None:
    return analytics_trip_detail(db, settings, day, trip_id)


def schedule_rows(db: Database, day: str) -> list[dict[str, Any]]:
    with db.connection() as c:
        snapshot_id = _snapshot_id(c, day)
        if snapshot_id is None: return []
        rows = c.execute("""
            SELECT ? AS service_date, t.trip_id, t.direction_id, t.trip_headsign, st.stop_sequence,
                   st.stop_id, s.stop_name, st.scheduled_arrival, st.scheduled_departure, s.stop_lat, s.stop_lon
            FROM scheduled_stop_times st JOIN trips t ON t.snapshot_id=st.snapshot_id AND t.trip_id=st.trip_id
            LEFT JOIN stops s ON s.snapshot_id=st.snapshot_id AND s.stop_id=st.stop_id
            WHERE st.snapshot_id=? ORDER BY t.trip_id, st.stop_sequence
        """, (day, snapshot_id)).fetchall()
    return [dict(row) for row in rows]


def realtime_rows(db: Database, day: str, include_raw: bool = False) -> list[dict[str, Any]]:
    columns = REALTIME_COLUMNS + (["raw_payload"] if include_raw else [])
    with db.connection() as c:
        rows = c.execute(f"SELECT {','.join(columns)} FROM realtime_observations WHERE substr(observed_at,1,10)=? ORDER BY observed_at,id", (day,)).fetchall()
    return [dict(row) for row in rows]


def csv_content(columns: list[str], rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue()


def json_content(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"), default=str)


def service_day_bounds(settings: Settings, now: datetime | None = None) -> tuple[date, datetime, datetime]:
    return analytics_service_day_bounds(settings, now)


def _gtfs_seconds(value: str | None, boundary_seconds: int) -> int | None:
    if not value: return None
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (TypeError, ValueError): return None
    total = hours * 3600 + minutes * 60 + seconds
    return total + (86400 if total < boundary_seconds else 0) - boundary_seconds


def _gtfs_display_time(value: str | None, boundary_seconds: int) -> str | None:
    """Return a safe HH:mm display value, including GTFS times beyond 24:00."""
    if _gtfs_seconds(value, boundary_seconds) is None: return None
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (TypeError, ValueError): return None
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60: return None
    return f"{hours % 24:02d}:{minutes:02d}"


def _local_timestamp(value: str, zone: ZoneInfo) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(zone) if parsed.tzinfo else parsed.replace(tzinfo=zone)
    except (TypeError, ValueError): return None


def _median(values: list[int | float]) -> float | None:
    if not values: return None
    ordered = sorted(values); middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def trend_classification(delta: int) -> str:
    if delta > 45: return "worsening"
    if delta > 20: return "slightly_worsening"
    if delta < -45: return "improving"
    if delta < -20: return "slightly_improving"
    return "stable"


def _trend(db: Database, settings: Settings, now: datetime) -> tuple[str, int | None]:
    """Compare medians of per-minute latest trip values in two ten-minute windows."""
    zone = ZoneInfo(settings.timezone)
    lower = now - timedelta(minutes=30)
    with db.connection() as c:
        rows = c.execute("SELECT observed_at,trip_id,delay_actual FROM realtime_observations WHERE observed_at>=? AND observed_at<=? AND trip_id IS NOT NULL AND delay_actual IS NOT NULL ORDER BY observed_at", (lower.isoformat(), now.isoformat())).fetchall()
    minute_trip: dict[tuple[datetime, str], int] = {}
    for row in rows:
        observed = _local_timestamp(row["observed_at"], zone)
        if observed:
            minute_trip[(observed.replace(second=0, microsecond=0), row["trip_id"])] = row["delay_actual"]
    minute_medians: dict[datetime, list[int]] = {}
    for (minute, _), delay in minute_trip.items(): minute_medians.setdefault(minute, []).append(delay)
    old = [_median(values) for minute, values in minute_medians.items() if now - timedelta(minutes=30) <= minute < now - timedelta(minutes=20)]
    new = [_median(values) for minute, values in minute_medians.items() if now - timedelta(minutes=10) <= minute <= now]
    if len(old) < 3 or len(new) < 3: return "unknown", None
    delta = round(_median(new) - _median(old))
    return trend_classification(delta), delta


def live_vehicles(db: Database, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    service_date, start, end = service_day_bounds(settings, now)
    zone = ZoneInfo(settings.timezone); local_now = (now or datetime.now(zone)).astimezone(zone)
    elapsed = (local_now - start).total_seconds()
    with db.connection() as c:
        snapshot_id = _snapshot_id(c, service_date.isoformat())
        if snapshot_id is None:
            return {"service_date": service_date.isoformat(), "generated_at": local_now.isoformat(), "vehicles": []}
        schedules = c.execute("""
            SELECT t.trip_id, t.trip_headsign, t.shape_id, min(st.stop_sequence) AS first_sequence,
                   max(st.stop_sequence) AS last_sequence,
                   min(coalesce(st.scheduled_departure, st.scheduled_arrival)) AS scheduled_start,
                   max(coalesce(st.scheduled_arrival, st.scheduled_departure)) AS scheduled_end
            FROM trips t JOIN scheduled_stop_times st ON st.snapshot_id=t.snapshot_id AND st.trip_id=t.trip_id
            WHERE t.snapshot_id=? GROUP BY t.id, t.trip_id, t.trip_headsign, t.shape_id
        """, (snapshot_id,)).fetchall()
        latest = c.execute("""
            SELECT r.* FROM realtime_observations r
            JOIN (SELECT trip_id, max(observed_at) AS observed_at FROM realtime_observations
                  WHERE observed_at>=? AND observed_at<? AND trip_id IS NOT NULL GROUP BY trip_id) newest
              ON newest.trip_id=r.trip_id AND newest.observed_at=r.observed_at
        """, (start.isoformat(), (end + timedelta(minutes=3)).isoformat())).fetchall()
        stop_names = {row["stop_id"]: row["stop_name"] for row in c.execute("SELECT stop_id,stop_name FROM stops WHERE snapshot_id=?", (snapshot_id,)).fetchall()}
    latest_by_trip = {row["trip_id"]: dict(row) for row in latest}
    vehicles: list[dict[str, Any]] = []
    for schedule in schedules:
        row = latest_by_trip.get(schedule["trip_id"])
        if row is None or row["latitude"] is None or row["longitude"] is None: continue
        boundary_seconds = settings.service_day_boundary.hour * 3600 + settings.service_day_boundary.minute * 60
        scheduled_start = _gtfs_seconds(schedule["scheduled_start"], boundary_seconds)
        scheduled_end = _gtfs_seconds(schedule["scheduled_end"], boundary_seconds)
        if scheduled_start is None or scheduled_end is None: continue
        observed_at = _local_timestamp(row["observed_at"], zone)
        if observed_at is None: continue
        age_seconds = max(0, int((local_now - observed_at).total_seconds()))
        reached_terminal = row["last_stop_sequence"] is not None and row["last_stop_sequence"] >= schedule["last_sequence"]
        completed = bool(reached_terminal and age_seconds <= 180 and elapsed >= scheduled_end - 300)
        scheduled_active = scheduled_start <= elapsed <= scheduled_end + 180
        if not (scheduled_active or completed) or age_seconds > 900: continue
        freshness = "completed" if completed else "stale" if age_seconds > 300 else "fresh"
        vehicles.append({"trip_id": row["trip_id"], "vehicle_registration_number": row["vehicle_registration_number"],
                         "headsign": schedule["trip_headsign"], "latitude": row["latitude"], "longitude": row["longitude"],
                         "delay_actual": row["delay_actual"], "observed_at": row["observed_at"], "age_seconds": age_seconds,
                         "freshness": freshness, "completed": completed, "last_stop_sequence": row["last_stop_sequence"],
                         "last_stop_name": stop_names.get(row["last_stop_id"]), "terminal_stop_sequence": schedule["last_sequence"]})
    return {"service_date": service_date.isoformat(), "generated_at": local_now.isoformat(), "vehicles": vehicles}


def live_summary(db: Database, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    data = live_vehicles(db, settings, now)
    delays = [vehicle["delay_actual"] for vehicle in data["vehicles"] if vehicle["delay_actual"] is not None]
    active = len(data["vehicles"])
    on_time = sum(delay < 180 for delay in delays)
    maximum = max(data["vehicles"], key=lambda vehicle: vehicle["delay_actual"] if vehicle["delay_actual"] is not None else float("-inf"), default=None)
    generated = _local_timestamp(data["generated_at"], ZoneInfo(settings.timezone)) or datetime.now(ZoneInfo(settings.timezone))
    trend_status, trend_delta = _trend(db, settings, generated)
    return {"generated_at": data["generated_at"], "service_date": data["service_date"], "active_trips": active,
            "maximum_delay": round(max(delays)) if delays else None,
            "average_delay": round(sum(delays) / len(delays)) if delays else None,
            "current_delay_median": round(_median(delays)) if delays else None,
            "current_delay_average": round(sum(delays) / len(delays)) if delays else None,
            "maximum_delay_headsign": maximum["headsign"] if maximum and maximum["delay_actual"] is not None else None,
            "maximum_delay_last_stop_name": maximum["last_stop_name"] if maximum and maximum["delay_actual"] is not None else None,
            "on_time_percentage": round(on_time * 100 / len(delays)) if delays else None,
            "trend_status": trend_status, "trend_delta": trend_delta,
            "data_available": bool(data["vehicles"])}


def live_route(db: Database, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    service_date, _, _ = service_day_bounds(settings, now)
    with db.connection() as c:
        snapshot_id = _snapshot_id(c, service_date.isoformat())
        if snapshot_id is None:
            return {"service_date": service_date.isoformat(), "available": False, "shapes": []}
        rows = c.execute("SELECT shape_id,shape_pt_lat,shape_pt_lon FROM shape_points WHERE snapshot_id=? ORDER BY shape_id,shape_pt_sequence", (snapshot_id,)).fetchall()
    grouped: dict[str, list[list[float]]] = {}
    for row in rows: grouped.setdefault(row["shape_id"], []).append([row["shape_pt_lat"], row["shape_pt_lon"]])
    seen: set[tuple[tuple[float, float], ...]] = set(); shapes = []
    for shape_id, points in grouped.items():
        key = tuple((point[0], point[1]) for point in points)
        if key not in seen:
            seen.add(key); shapes.append({"shape_id": shape_id, "points": points})
    return {"service_date": service_date.isoformat(), "available": bool(shapes), "shapes": shapes}


def service_day_for_date(settings: Settings, value: date) -> tuple[datetime, datetime]:
    return analytics_service_day_for_date(settings, value)


def czech_day_label(value: str, today: str) -> str:
    if value == today: return "DNES"
    parsed = date.fromisoformat(value); names = ("PONDĚLÍ", "ÚTERÝ", "STŘEDA", "ČTVRTEK", "PÁTEK", "SOBOTA", "NEDĚLE")
    return f"{names[parsed.weekday()]} {parsed.day}. {parsed.month}."


def czech_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day}. {parsed.month}. {parsed.year}"


def day_navigation(db: Database, day: str) -> dict[str, Any]:
    days = available_days(db)
    try: index = days.index(day)
    except ValueError: index = -1
    return {"previous": days[index + 1] if index >= 0 and index + 1 < len(days) else None,
            "next": days[index - 1] if index > 0 else None, "available": day in days}


def operating_hours(db: Database, settings: Settings, day: str, now: datetime | None = None) -> dict[str, Any]:
    with db.connection() as c:
        snapshot_id = _snapshot_id(c, day)
        if snapshot_id is None: return {"date": day, "hours": []}
        row = c.execute("SELECT min(coalesce(scheduled_departure,scheduled_arrival)),max(coalesce(scheduled_arrival,scheduled_departure)) FROM scheduled_stop_times WHERE snapshot_id=?", (snapshot_id,)).fetchone()
    boundary_seconds = settings.service_day_boundary.hour * 3600 + settings.service_day_boundary.minute * 60
    start_seconds, end_seconds = _gtfs_seconds(row[0], boundary_seconds), _gtfs_seconds(row[1], boundary_seconds)
    if start_seconds is None or end_seconds is None: return {"date": day, "hours": []}
    _, current_start, _ = service_day_bounds(settings, now); selected_start, _ = service_day_for_date(settings, date.fromisoformat(day))
    current_elapsed = (datetime.now(ZoneInfo(settings.timezone)) - current_start).total_seconds() if now is None else ((now.astimezone(ZoneInfo(settings.timezone)) - current_start).total_seconds())
    historical = selected_start.date() != current_start.date()
    first, last = int(start_seconds // 3600), int(end_seconds // 3600)
    return {"date": day, "hours": [{"offset": offset, "label": str((settings.service_day_boundary.hour + offset) % 24), "future": not historical and offset * 3600 > current_elapsed} for offset in range(first, last + 1)]}


def day_analytics(db: Database, settings: Settings, day: str, from_offset: int | None = None, to_offset: int | None = None) -> dict[str, Any]:
    return day_metrics(db, settings, day, from_offset, to_offset)
