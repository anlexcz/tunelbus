from __future__ import annotations

from statistics import median
from typing import Any

from app.config import Settings
from app.database import Database

from .representatives import day_representatives, interval_trip_representatives


DELAY_CLASSES = ("early", "on_time", "mild_delay", "larger_delay", "high_delay")


def classify_delay(delay: int | float) -> str:
    if delay < -60:
        return "early"
    if delay < 180:
        return "on_time"
    if delay <= 360:
        return "mild_delay"
    if delay <= 600:
        return "larger_delay"
    return "high_delay"


def percentile_90(values: list[int | float]) -> int | float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * 90 + 99) // 100 - 1)]


def coverage_status(percentage: float | None) -> str:
    if percentage is None or percentage < 50:
        return "insufficient"
    if percentage < 80:
        return "partial"
    return "good"


def _round(value: int | float | None) -> int | None:
    return round(value) if value is not None else None


def _outliers(representatives, settings: Settings) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    worst_trip_value = max(representatives, key=lambda value: value.max_delay, default=None)
    worst_trip = None
    if worst_trip_value:
        maximum_stop = max(worst_trip_value.stops, key=lambda value: value.delay)
        worst_trip = {
            "trip_id": worst_trip_value.trip.trip_id,
            "scheduled_start": worst_trip_value.trip.scheduled_start[:5] if worst_trip_value.trip.scheduled_start else None,
            "headsign": worst_trip_value.trip.headsign,
            "maximum_delay": maximum_stop.delay,
            "maximum_delay_stop_name": maximum_stop.stop_name,
            "maximum_delay_scheduled_time": maximum_stop.scheduled_time[:5] if maximum_stop.scheduled_time else None,
        }
    worst_segment = None
    for trip in representatives:
        for before, after in zip(trip.stops, trip.stops[1:]):
            if after.stop_sequence != before.stop_sequence + 1:
                continue
            increase = after.delay - before.delay
            if increase > 0 and (worst_segment is None or increase > worst_segment["delay_increase"]):
                worst_segment = {
                    "from_stop_name": before.stop_name, "to_stop_name": after.stop_name, "delay_increase": increase,
                    "to_scheduled_time": after.scheduled_time[:5] if after.scheduled_time else None,
                }
    early_candidates = [stop for trip in representatives for stop in trip.stops if stop.delay < -60]
    earliest = min(early_candidates, key=lambda value: value.delay, default=None)
    largest_early = None
    if earliest:
        trip = next(value for value in representatives if value.trip.trip_id == earliest.trip_id)
        largest_early = {
            "trip_id": earliest.trip_id, "scheduled_start": trip.trip.scheduled_start[:5] if trip.trip.scheduled_start else None,
            "headsign": trip.trip.headsign, "delay": earliest.delay, "stop_name": earliest.stop_name,
            "scheduled_time": earliest.scheduled_time[:5] if earliest.scheduled_time else None,
        }
    return worst_trip, worst_segment, largest_early


def day_metrics(db: Database, settings: Settings, day: str, from_offset: int | None = None, to_offset: int | None = None) -> dict[str, Any]:
    """Return all daily/hourly metrics from equal-weight trip representatives."""
    data = day_representatives(db, settings, day)
    planned, representatives, start_seconds, end_seconds = interval_trip_representatives(data, settings, from_offset, to_offset)
    delays = [trip.representative_delay for trip in representatives]
    count = len(delays)
    coverage = round(count * 100 / len(planned), 1) if planned else None
    distribution = []
    for key in DELAY_CLASSES:
        bucket_count = sum(classify_delay(delay) == key for delay in delays)
        distribution.append({"key": key, "count": bucket_count, "percentage": round(bucket_count * 100 / count) if count else 0})
    worst_trip, worst_segment, largest_early = _outliers(representatives, settings)
    interval_start = start_seconds
    interval_end = end_seconds
    raw_in_interval = []
    # Metadata remains raw by definition; core delay metrics above never use it.
    with db.connection() as conn:
        from .service_day import service_day_for_date
        from datetime import date, timedelta
        start, _ = service_day_for_date(settings, date.fromisoformat(day))
        raw_start = start + timedelta(seconds=interval_start)
        raw_end = start + timedelta(seconds=interval_end)
        raw_in_interval = conn.execute("""
            SELECT observed_at,trip_id,vehicle_registration_number FROM realtime_observations
            WHERE observed_at>=? AND observed_at<? ORDER BY observed_at,id
        """, (raw_start.isoformat(), raw_end.isoformat())).fetchall()
    return {
        "date": day, "from_offset": from_offset, "to_offset": to_offset,
        "planned_trips": len(planned), "captured_trips": count, "usable_trips": count,
        "vehicles": len({row["vehicle_registration_number"] for row in raw_in_interval if row["vehicle_registration_number"]}),
        "realtime_observations": len(raw_in_interval),
        "average_delay": _round(sum(delays) / count) if count else None,
        "median_delay": _round(median(delays)) if delays else None,
        "maximum_delay": _round(max(delays)) if delays else None,
        "minimum_delay": _round(min(delays)) if delays else None,
        "within_1_minute": round(sum(-60 <= delay < 60 for delay in delays) * 100 / count) if count else None,
        "within_3_minutes": round(sum(classify_delay(delay) == "on_time" for delay in delays) * 100 / count) if count else None,
        "within_5_minutes": round(sum(-60 <= delay <= 300 for delay in delays) * 100 / count) if count else None,
        "over_10_minutes": round(sum(delay > 600 for delay in delays) * 100 / count) if count else None,
        "percentile_90": _round(percentile_90(delays)), "delay_distribution": distribution,
        "coverage_percentage": coverage, "coverage_status": coverage_status(coverage),
        "largest_early": largest_early, "worst_trip": worst_trip, "worst_delay_segment": worst_segment,
        "first_observed_at": min((row["observed_at"] for row in raw_in_interval), default=None),
        "last_observed_at": max((row["observed_at"] for row in raw_in_interval), default=None),
        "trip_flags": {trip.trip.trip_id: sorted(trip.flags) for trip in representatives if trip.flags},
    }
