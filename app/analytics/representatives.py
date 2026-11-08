from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median
from typing import Any

from app.config import Settings
from app.database import Database

from .anomalies import observation_flags, trip_flags
from .service_day import gtfs_datetime, gtfs_display_time, gtfs_seconds, observed_at_local, service_date_for_observation, service_day_for_date


@dataclass(frozen=True)
class ScheduledStop:
    stop_sequence: int
    stop_id: str
    stop_name: str | None
    scheduled_arrival: str | None
    scheduled_departure: str | None
    scheduled_time: str | None
    scheduled_seconds: int | None


@dataclass(frozen=True)
class PlannedTrip:
    trip_id: str
    direction_id: str | None
    headsign: str | None
    scheduled_start: str | None
    scheduled_end: str | None
    start_seconds: int | None
    end_seconds: int | None
    stops: tuple[ScheduledStop, ...]


@dataclass(frozen=True)
class StopRepresentative:
    trip_id: str
    stop_sequence: int
    stop_id: str
    stop_name: str | None
    scheduled_time: str | None
    scheduled_seconds: int | None
    observation_id: int
    observed_at: str
    delay: int
    delay_source: str
    vehicle_registration_number: str | None
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TripRepresentative:
    trip: PlannedTrip
    stops: tuple[StopRepresentative, ...]
    representative_delay: float
    terminal_or_last_delay: int
    max_delay: int
    min_delay: int
    number_of_representative_stops: int
    vehicle_registration_number: str | None
    flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DayRepresentatives:
    service_date: str
    planned_trips: tuple[PlannedTrip, ...]
    stop_values: tuple[StopRepresentative, ...]
    structurally_usable_trip_ids: frozenset[str]
    raw_observation_count: int
    raw_trip_ids: frozenset[str]
    raw_vehicle_ids: frozenset[str]
    first_observed_at: str | None
    last_observed_at: str | None
    observed_sequences: dict[str, tuple[int, ...]] = field(default_factory=dict)


def _delay(row: dict[str, Any]) -> tuple[int | None, str | None]:
    if row["delay_last_stop_departure"] is not None:
        return row["delay_last_stop_departure"], "departure"
    if row["delay_last_stop_arrival"] is not None:
        return row["delay_last_stop_arrival"], "arrival"
    if row["delay_actual"] is not None:
        return row["delay_actual"], "actual"
    return None, None


def _newer(left: dict[str, Any], right: dict[str, Any], settings: Settings) -> bool:
    """Whether left wins over right by parsed timestamp and then greater database id."""
    left_at = observed_at_local(left["observed_at"], settings.timezone)
    right_at = observed_at_local(right["observed_at"], settings.timezone)
    if left_at is not None and right_at is not None and left_at != right_at:
        return left_at > right_at
    if left_at is not None and right_at is None:
        return True
    return left["id"] > right["id"]


def day_representatives(db: Database, settings: Settings, day: str) -> DayRepresentatives:
    """Build immutable, read-only stop representatives for one service-day snapshot."""
    service_date = date.fromisoformat(day)
    start, end = service_day_for_date(settings, service_date)
    with db.connection() as conn:
        snapshot = conn.execute("SELECT id FROM gtfs_snapshots WHERE service_date=?", (day,)).fetchone()
        if snapshot is None:
            return DayRepresentatives(day, (), (), frozenset(), 0, frozenset(), frozenset(), None, None)
        snapshot_id = snapshot["id"]
        trip_rows = conn.execute("""
            SELECT t.trip_id,t.direction_id,t.trip_headsign,
                   min(coalesce(st.scheduled_departure,st.scheduled_arrival)) AS scheduled_start,
                   max(coalesce(st.scheduled_arrival,st.scheduled_departure)) AS scheduled_end
            FROM trips t JOIN scheduled_stop_times st ON st.snapshot_id=t.snapshot_id AND st.trip_id=t.trip_id
            WHERE t.snapshot_id=? GROUP BY t.id,t.trip_id,t.direction_id,t.trip_headsign
        """, (snapshot_id,)).fetchall()
        stop_rows = conn.execute("""
            SELECT st.trip_id,st.stop_sequence,st.stop_id,s.stop_name,st.scheduled_arrival,st.scheduled_departure
            FROM scheduled_stop_times st LEFT JOIN stops s ON s.snapshot_id=st.snapshot_id AND s.stop_id=st.stop_id
            WHERE st.snapshot_id=? ORDER BY st.trip_id,st.stop_sequence
        """, (snapshot_id,)).fetchall()
        raw_rows = conn.execute("""
            SELECT id,observed_at,trip_id,vehicle_registration_number,delay_actual,
                   delay_last_stop_arrival,delay_last_stop_departure,last_stop_id,last_stop_sequence
            FROM realtime_observations WHERE observed_at>=? AND observed_at<? ORDER BY observed_at,id
        """, (start.isoformat(), end.isoformat())).fetchall()

    stops_by_trip: dict[str, list[ScheduledStop]] = defaultdict(list)
    expected_stops: dict[tuple[str, int], ScheduledStop] = {}
    for row in stop_rows:
        scheduled_time = row["scheduled_departure"] or row["scheduled_arrival"]
        stop = ScheduledStop(row["stop_sequence"], row["stop_id"], row["stop_name"], row["scheduled_arrival"], row["scheduled_departure"], scheduled_time, gtfs_seconds(scheduled_time, settings.service_day_boundary))
        stops_by_trip[row["trip_id"]].append(stop)
        expected_stops[(row["trip_id"], row["stop_sequence"])] = stop
    planned = tuple(PlannedTrip(
        row["trip_id"], row["direction_id"], row["trip_headsign"], row["scheduled_start"], row["scheduled_end"],
        gtfs_seconds(row["scheduled_start"], settings.service_day_boundary), gtfs_seconds(row["scheduled_end"], settings.service_day_boundary),
        tuple(stops_by_trip[row["trip_id"]]),
    ) for row in trip_rows)
    planned_ids = {trip.trip_id for trip in planned}

    raw = [dict(row) for row in raw_rows if observed_at_local(row["observed_at"], settings.timezone) is not None]
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    sequence_history: dict[str, list[int]] = defaultdict(list)
    for row in raw:
        trip_id, sequence = row["trip_id"], row["last_stop_sequence"]
        expected = expected_stops.get((trip_id, sequence)) if trip_id and sequence is not None else None
        if expected is None or row["last_stop_id"] != expected.stop_id:
            continue
        sequence_history[trip_id].append(sequence)
        delay, _ = _delay(row)
        if delay is None:
            continue
        key = (trip_id, sequence)
        if key not in latest or _newer(row, latest[key], settings):
            latest[key] = row

    stop_values: list[StopRepresentative] = []
    for (trip_id, sequence), row in latest.items():
        expected = expected_stops[(trip_id, sequence)]
        delay, source = _delay(row)
        assert delay is not None and source is not None
        stop_values.append(StopRepresentative(
            trip_id, sequence, expected.stop_id, expected.stop_name, expected.scheduled_time, expected.scheduled_seconds,
            row["id"], row["observed_at"], delay, source, row["vehicle_registration_number"], frozenset(observation_flags(row)),
        ))
    stop_values.sort(key=lambda value: (value.trip_id, value.stop_sequence))
    by_trip: dict[str, list[StopRepresentative]] = defaultdict(list)
    for value in stop_values:
        by_trip[value.trip_id].append(value)
    usable = frozenset(trip_id for trip_id, values in by_trip.items() if trip_id in planned_ids and len({value.stop_sequence for value in values}) >= 2)
    raw_trip_ids = frozenset(row["trip_id"] for row in raw if row["trip_id"])
    raw_vehicle_ids = frozenset(row["vehicle_registration_number"] for row in raw if row["vehicle_registration_number"])
    return DayRepresentatives(
        day, planned, tuple(stop_values), usable, len(raw), raw_trip_ids, raw_vehicle_ids,
        min((row["observed_at"] for row in raw), default=None), max((row["observed_at"] for row in raw), default=None),
        {trip_id: tuple(sequences) for trip_id, sequences in sequence_history.items()},
    )


def day_representatives_many(db: Database, settings: Settings, days: list[str]) -> dict[str, DayRepresentatives]:
    """Build several service days from three bounded SQL reads.

    This is intentionally request-local: it is not a cache and preserves the
    same latest-per-trip-stop representative selection as ``day_representatives``.
    """
    wanted = list(dict.fromkeys(days))
    empty = lambda day: DayRepresentatives(day, (), (), frozenset(), 0, frozenset(), frozenset(), None, None)
    if not wanted:
        return {}
    intervals = [service_day_for_date(settings, date.fromisoformat(day)) for day in wanted]
    with db.connection() as conn:
        snapshots = conn.execute(f"SELECT id,service_date FROM gtfs_snapshots WHERE service_date IN ({','.join('?' for _ in wanted)})", wanted).fetchall()
        snapshot_days = {row["id"]: row["service_date"] for row in snapshots}
        if not snapshot_days:
            return {day: empty(day) for day in wanted}
        ids = list(snapshot_days)
        marks = ','.join('?' for _ in ids)
        trips = conn.execute(f"""SELECT t.snapshot_id,t.trip_id,t.direction_id,t.trip_headsign,
                   min(coalesce(st.scheduled_departure,st.scheduled_arrival)) AS scheduled_start,
                   max(coalesce(st.scheduled_arrival,st.scheduled_departure)) AS scheduled_end
            FROM trips t JOIN scheduled_stop_times st ON st.snapshot_id=t.snapshot_id AND st.trip_id=t.trip_id
            WHERE t.snapshot_id IN ({marks}) GROUP BY t.id,t.snapshot_id,t.trip_id,t.direction_id,t.trip_headsign""", ids).fetchall()
        stops = conn.execute(f"""SELECT st.snapshot_id,st.trip_id,st.stop_sequence,st.stop_id,s.stop_name,st.scheduled_arrival,st.scheduled_departure
            FROM scheduled_stop_times st LEFT JOIN stops s ON s.snapshot_id=st.snapshot_id AND s.stop_id=st.stop_id
            WHERE st.snapshot_id IN ({marks}) ORDER BY st.snapshot_id,st.trip_id,st.stop_sequence""", ids).fetchall()
        where = " OR ".join("(observed_at>=? AND observed_at<?)" for _ in intervals)
        parameters = [value for interval in intervals for value in (interval[0].isoformat(), interval[1].isoformat())]
        raw = conn.execute(f"""SELECT id,observed_at,trip_id,vehicle_registration_number,delay_actual,
                   delay_last_stop_arrival,delay_last_stop_departure,last_stop_id,last_stop_sequence
            FROM realtime_observations WHERE {where} ORDER BY observed_at,id""", parameters).fetchall()
    trip_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stop_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trips: trip_by_day[snapshot_days[row["snapshot_id"]]].append(dict(row))
    for row in stops: stop_by_day[snapshot_days[row["snapshot_id"]]].append(dict(row))
    for row in raw:
        value = dict(row); observed_day = service_date_for_observation(settings, value["observed_at"])
        if observed_day in wanted: raw_by_day[observed_day].append(value)

    result: dict[str, DayRepresentatives] = {}
    for day in wanted:
        if day not in trip_by_day:
            result[day] = empty(day); continue
        stops_by_trip: dict[str, list[ScheduledStop]] = defaultdict(list); expected: dict[tuple[str, int], ScheduledStop] = {}
        for row in stop_by_day[day]:
            scheduled = row["scheduled_departure"] or row["scheduled_arrival"]
            stop = ScheduledStop(row["stop_sequence"], row["stop_id"], row["stop_name"], row["scheduled_arrival"], row["scheduled_departure"], scheduled, gtfs_seconds(scheduled, settings.service_day_boundary))
            stops_by_trip[row["trip_id"]].append(stop); expected[(row["trip_id"], row["stop_sequence"])] = stop
        planned = tuple(PlannedTrip(row["trip_id"], row["direction_id"], row["trip_headsign"], row["scheduled_start"], row["scheduled_end"], gtfs_seconds(row["scheduled_start"], settings.service_day_boundary), gtfs_seconds(row["scheduled_end"], settings.service_day_boundary), tuple(stops_by_trip[row["trip_id"]])) for row in trip_by_day[day])
        raw_rows = [row for row in raw_by_day[day] if observed_at_local(row["observed_at"], settings.timezone) is not None]
        latest: dict[tuple[str, int], dict[str, Any]] = {}; sequences: dict[str, list[int]] = defaultdict(list)
        for row in raw_rows:
            trip_id, sequence = row["trip_id"], row["last_stop_sequence"]; stop = expected.get((trip_id, sequence)) if trip_id and sequence is not None else None
            if stop is None or row["last_stop_id"] != stop.stop_id: continue
            sequences[trip_id].append(sequence)
            delay, _ = _delay(row)
            if delay is None: continue
            key = (trip_id, sequence)
            if key not in latest or _newer(row, latest[key], settings): latest[key] = row
        values = []
        for (trip_id, sequence), row in latest.items():
            stop = expected[(trip_id, sequence)]; delay, source = _delay(row); assert delay is not None and source is not None
            values.append(StopRepresentative(trip_id, sequence, stop.stop_id, stop.stop_name, stop.scheduled_time, stop.scheduled_seconds, row["id"], row["observed_at"], delay, source, row["vehicle_registration_number"], frozenset(observation_flags(row))))
        values.sort(key=lambda value: (value.trip_id, value.stop_sequence)); counts: dict[str, set[int]] = defaultdict(set)
        for value in values: counts[value.trip_id].add(value.stop_sequence)
        planned_ids = {trip.trip_id for trip in planned}; usable = frozenset(trip_id for trip_id, sequences_ in counts.items() if trip_id in planned_ids and len(sequences_) >= 2)
        result[day] = DayRepresentatives(day, planned, tuple(values), usable, len(raw_rows), frozenset(row["trip_id"] for row in raw_rows if row["trip_id"]), frozenset(row["vehicle_registration_number"] for row in raw_rows if row["vehicle_registration_number"]), min((row["observed_at"] for row in raw_rows), default=None), max((row["observed_at"] for row in raw_rows), default=None), {trip_id: tuple(history) for trip_id, history in sequences.items()})
    return result


def interval_trip_representatives(day_data: DayRepresentatives, settings: Settings, from_offset: int | None = None, to_offset: int | None = None) -> tuple[list[PlannedTrip], list[TripRepresentative], int, int]:
    """Return planned and usable trip values for a whole day or half-open hour range."""
    if from_offset is None:
        start_seconds, end_seconds = 0, 24 * 3600
    else:
        to_offset = from_offset if to_offset is None else to_offset
        if from_offset > to_offset:
            from_offset, to_offset = to_offset, from_offset
        start_seconds, end_seconds = from_offset * 3600, min((to_offset + 1) * 3600, 24 * 3600)
    planned = [trip for trip in day_data.planned_trips if trip.start_seconds is not None and trip.end_seconds is not None and trip.start_seconds < end_seconds and trip.end_seconds >= start_seconds]
    stop_by_trip: dict[str, list[StopRepresentative]] = defaultdict(list)
    for stop in day_data.stop_values:
        if stop.scheduled_seconds is not None and start_seconds <= stop.scheduled_seconds < end_seconds:
            stop_by_trip[stop.trip_id].append(stop)
    representatives: list[TripRepresentative] = []
    for trip in planned:
        # Preserve every raw/stop observation. A proven conflict is unsuitable for
        # public aggregates, but remains available for diagnostics and exports.
        selected = sorted(
            (value for value in stop_by_trip.get(trip.trip_id, ())
             if "delay_vs_last_stop_conflict" not in value.flags),
            key=lambda value: value.stop_sequence,
        )
        # A single implausible spike bracketed by normal adjacent stops is
        # diagnostically retained but does not distort public aggregates.
        isolated_spikes = {
            current.observation_id
            for before, current, after in zip(selected, selected[1:], selected[2:])
            if before.stop_sequence + 1 == current.stop_sequence
            and current.stop_sequence + 1 == after.stop_sequence
            and current.delay > 600 and before.delay <= 180 and after.delay <= 180
        }
        if isolated_spikes:
            selected = [v for v in selected if v.observation_id not in isolated_spikes]
        if trip.trip_id not in day_data.structurally_usable_trip_ids or not selected:
            continue
        last = selected[-1]
        registration = next((value.vehicle_registration_number for value in reversed(selected) if value.vehicle_registration_number), None)
        flags = set().union(*(value.flags for value in selected))
        flags.update(trip_flags(selected, list(day_data.observed_sequences.get(trip.trip_id, ()))))
        delays = [value.delay for value in selected]
        representatives.append(TripRepresentative(trip, tuple(selected), median(delays), last.delay, max(delays), min(delays), len(selected), registration, frozenset(flags)))
    return planned, representatives, start_seconds, end_seconds


def trip_detail(db: Database, settings: Settings, day: str, trip_id: str) -> dict[str, Any] | None:
    day_data = day_representatives(db, settings, day)
    planned = next((trip for trip in day_data.planned_trips if trip.trip_id == trip_id), None)
    if planned is None:
        return None
    _, representatives, _, _ = interval_trip_representatives(day_data, settings)
    representative = next((value for value in representatives if value.trip.trip_id == trip_id), None)
    values = {value.stop_sequence: value for value in day_data.stop_values if value.trip_id == trip_id}
    stops = []
    previous_delay = None
    for stop in planned.stops:
        value = values.get(stop.stop_sequence)
        delay = value.delay if value else None
        actual = None
        if delay is not None:
            scheduled = gtfs_datetime(date.fromisoformat(day), stop.scheduled_arrival or stop.scheduled_departure, settings)
            actual = (scheduled + __import__("datetime").timedelta(seconds=delay)).strftime("%H:%M") if scheduled else None
        stops.append({"sequence": stop.stop_sequence, "stop_id": stop.stop_id, "stop_name": stop.stop_name, "scheduled_time": gtfs_display_time(stop.scheduled_time, settings.service_day_boundary), "delay": delay, "delay_source": value.delay_source if value else None, "actual_time": actual, "delta_from_previous": delay - previous_delay if delay is not None and previous_delay is not None else None, "anomaly_flags": sorted(value.flags) if value else []})
        if delay is not None:
            previous_delay = delay
    selected = [value for value in day_data.stop_values if value.trip_id == trip_id]
    registrations = {value.vehicle_registration_number for value in selected if value.vehicle_registration_number}
    registration = registrations.pop() if len(registrations) == 1 else None
    flags = set().union(*(value.flags for value in selected))
    if representative: flags.update(representative.flags)
    return {"day": day, "trip_id": trip_id, "direction_id": planned.direction_id, "headsign": planned.headsign, "scheduled_start": gtfs_display_time(planned.scheduled_start, settings.service_day_boundary), "scheduled_end": gtfs_display_time(planned.scheduled_end, settings.service_day_boundary), "vehicle_registration_number": registration, "summary": {"representative_delay": round(representative.representative_delay) if representative else None, "last_delay": representative.terminal_or_last_delay if representative else None, "max_delay": representative.max_delay if representative else None, "min_delay": representative.min_delay if representative else None, "representative_stops": representative.number_of_representative_stops if representative else 0, "planned_stops": len(planned.stops)}, "stops": stops, "anomaly_flags": sorted(flags)}
