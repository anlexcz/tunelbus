from __future__ import annotations

from collections import defaultdict
from statistics import median

from app.config import Settings
from app.database import Database

from .metrics import percentile_90
from .representatives import day_representatives, interval_trip_representatives


def problem_segments(db: Database, settings: Settings, day: str, limit: int = 5) -> list[dict]:
    """Aggregate adjacent represented stops by median delay increase, never raw polls."""
    data = day_representatives(db, settings, day)
    _, trips, _, _ = interval_trip_representatives(data, settings)
    deltas: dict[tuple[str, str, str | None, str | None], list[int]] = defaultdict(list)
    for trip in trips:
        for before, after in zip(trip.stops, trip.stops[1:]):
            if after.stop_sequence != before.stop_sequence + 1:
                continue
            key = (before.stop_id, after.stop_id, before.stop_name, after.stop_name)
            deltas[key].append(after.delay - before.delay)
    result = []
    for (_, _, from_name, to_name), values in deltas.items():
        typical = round(median(values))
        if typical <= 0:
            continue
        result.append({
            "from_stop_name": from_name, "to_stop_name": to_name,
            "median_delay_delta": typical, "passages": len(values),
            "p90_delay_delta": round(percentile_90(values)), "maximum_delay_delta": max(values),
        })
    return sorted(result, key=lambda item: (item["median_delay_delta"], item["p90_delay_delta"], item["passages"]), reverse=True)[:limit]
