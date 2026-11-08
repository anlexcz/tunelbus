"""Read-only comparison of a scheduled trip across service days.

The database trip id is deliberately only used inside one service-day snapshot.
Historical candidates are matched through the scheduled service pattern.
"""

from __future__ import annotations

from datetime import date
from statistics import median

from app.config import Settings
from app.database import Database

from .history import available_days
from .representatives import PlannedTrip, StopRepresentative, TripRepresentative, day_representatives_many, interval_trip_representatives
from .service_day import gtfs_display_time


def _route_compatible(selected: PlannedTrip, candidate: PlannedTrip) -> bool:
    """Allow only strongly compatible ordered stop patterns.

    Exact patterns always match.  A single GTFS stop added or removed is tolerated
    only when both terminal stops agree and at least 80 % of the longer pattern is
    shared in the same order.  This avoids linking unrelated variants by sequence.
    """
    left = tuple(stop.stop_id for stop in selected.stops)
    right = tuple(stop.stop_id for stop in candidate.stops)
    if not left or not right:
        return False
    if left == right:
        return True
    if left[0] != right[0] or left[-1] != right[-1]:
        return False
    common = [stop_id for stop_id in left if stop_id in set(right)]
    # A one-stop GTFS amendment is still a compatible pattern, including on
    # short routes where 80 % would otherwise reject 2 common stops out of 3.
    if len(common) / max(len(left), len(right)) < 0.8 and not (abs(len(left) - len(right)) == 1 and len(common) == min(len(left), len(right))):
        return False
    right_positions = {stop_id: index for index, stop_id in enumerate(right)}
    return all(right_positions[first] < right_positions[second] for first, second in zip(common, common[1:]))


def _quartile(values: list[int], ratio: float) -> int:
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def _matching_days(db: Database, day: str, limit: int = 7) -> list[str]:
    selected = date.fromisoformat(day)
    workday = selected.weekday() < 5
    others = [value for value in available_days(db) if value != day]
    same_type = [value for value in others if (date.fromisoformat(value).weekday() < 5) == workday]
    fallback = [value for value in others if value not in same_type]
    sort_key = lambda value: (abs((date.fromisoformat(value) - selected).days), value > day, value)
    return (sorted(same_type, key=sort_key) + sorted(fallback, key=sort_key))[:limit]


def _representatives(data, settings: Settings) -> dict[str, TripRepresentative]:
    _, values, _, _ = interval_trip_representatives(data, settings)
    return {value.trip.trip_id: value for value in values}


def _candidate(selected: PlannedTrip, candidates: tuple[PlannedTrip, ...]) -> tuple[PlannedTrip, str] | None:
    compatible = [trip for trip in candidates if trip.direction_id == selected.direction_id and _route_compatible(selected, trip)]
    exact = [trip for trip in compatible if trip.start_seconds == selected.start_seconds]
    if exact:
        return min(exact, key=lambda trip: trip.trip_id), "exact"
    similar = [trip for trip in compatible if trip.start_seconds is not None and selected.start_seconds is not None and abs(trip.start_seconds - selected.start_seconds) <= 5 * 60]
    if not similar:
        return None
    return min(similar, key=lambda trip: (abs(trip.start_seconds - selected.start_seconds), trip.trip_id)), "similar"


def _match_record(day: str, trip: PlannedTrip, match_type: str, representative: TripRepresentative | None, settings: Settings) -> dict:
    return {
        "day": day,
        "trip_id": trip.trip_id,
        "match_type": match_type,
        "scheduled_start": gtfs_display_time(trip.scheduled_start, settings.service_day_boundary),
        "headsign": trip.headsign,
        "representative_delay": round(representative.representative_delay) if representative else None,
        "representative_stops": representative.number_of_representative_stops if representative else 0,
        "planned_stops": len(trip.stops),
        "anomaly_flags": sorted(representative.flags) if representative else [],
    }


def trip_comparison(db: Database, settings: Settings, day: str, trip_id: str) -> dict | None:
    """Compare one selected scheduled trip with at most seven nearby service days."""
    candidate_days = _matching_days(db, day)
    loaded = day_representatives_many(db, settings, [day, *candidate_days])
    selected_data = loaded[day]
    selected = next((trip for trip in selected_data.planned_trips if trip.trip_id == trip_id), None)
    if selected is None:
        return None
    selected_representative = _representatives(selected_data, settings).get(trip_id)
    selected_stop_values = {value.stop_sequence: value for value in selected_representative.stops} if selected_representative else {}

    matches: list[dict] = []
    usable: list[TripRepresentative] = []
    for candidate_day in candidate_days:
        candidate_data = loaded[candidate_day]
        found = _candidate(selected, candidate_data.planned_trips)
        if found is None:
            continue
        candidate_trip, match_type = found
        representative = _representatives(candidate_data, settings).get(candidate_trip.trip_id)
        matches.append(_match_record(candidate_day, candidate_trip, match_type, representative, settings))
        if representative is not None:
            usable.append(representative)

    # Stop identity is stop_id within a route-compatible pattern, never a bare sequence.
    delays_by_stop: dict[str, list[int]] = {stop.stop_id: [] for stop in selected.stops}
    for representative in usable:
        for value in representative.stops:
            if value.stop_id in delays_by_stop:
                delays_by_stop[value.stop_id].append(value.delay)
    typical_stops = []
    for stop in selected.stops:
        values = delays_by_stop[stop.stop_id]
        typical_stops.append({
            "sequence": stop.stop_sequence,
            "stop_id": stop.stop_id,
            "stop_name": stop.stop_name,
            "sample_size": len(values),
            "median_delay": round(median(values)) if values else None,
            "q25": _quartile(values, 0.25) if len(values) >= 4 else None,
            "q75": _quartile(values, 0.75) if len(values) >= 4 else None,
        })
    sample_size = len(usable)
    confidence = "single" if sample_size == 1 else "cautious" if sample_size < 4 else "standard"
    return {
        "selected": {
            "day": day,
            "trip_id": selected.trip_id,
            "direction_id": selected.direction_id,
            "headsign": selected.headsign,
            "scheduled_start": gtfs_display_time(selected.scheduled_start, settings.service_day_boundary),
            "planned_stops": len(selected.stops),
            "stops": [{
                "sequence": stop.stop_sequence,
                "stop_id": stop.stop_id,
                "stop_name": stop.stop_name,
                "delay": selected_stop_values.get(stop.stop_sequence).delay if stop.stop_sequence in selected_stop_values else None,
            } for stop in selected.stops],
        },
        "matches": matches,
        "typical": {
            "sample_size": sample_size,
            "anomaly_trip_count": sum(bool(item.flags) for item in usable),
            "confidence": confidence,
            "stops": typical_stops,
        },
    }
