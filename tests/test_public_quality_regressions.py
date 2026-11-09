"""Regression tests for public-facing statistics quality policy."""
from __future__ import annotations

from app.analytics.metrics import classify_delay
from app.analytics.representatives import (
    DayRepresentatives,
    PlannedTrip,
    ScheduledStop,
    StopRepresentative,
    interval_trip_representatives,
)


def make_day(delays: list[int], conflict: set[int] | None = None):
    conflict = conflict or set()
    stops = tuple(
        ScheduledStop(
            stop_sequence=i,
            stop_id=f"STOP_{i}",
            stop_name=f"Stop {i}",
            scheduled_arrival=f"06:{i:02d}:00",
            scheduled_departure=f"06:{i:02d}:00",
            scheduled_time=f"06:{i:02d}:00",
            scheduled_seconds=180 * 60 + i * 60,
        )
        for i in range(1, len(delays) + 1)
    )
    trip = PlannedTrip(
        trip_id="TRIP1",
        direction_id="0",
        headsign="Test",
        scheduled_start=stops[0].scheduled_time,
        scheduled_end=stops[-1].scheduled_time,
        start_seconds=stops[0].scheduled_seconds,
        end_seconds=stops[-1].scheduled_seconds,
        stops=stops,
    )
    values = tuple(
        StopRepresentative(
            trip_id="TRIP1",
            stop_sequence=i,
            stop_id=f"STOP_{i}",
            stop_name=f"Stop {i}",
            scheduled_time=stops[i - 1].scheduled_time,
            scheduled_seconds=stops[i - 1].scheduled_seconds,
            observation_id=i,
            observed_at=f"2026-11-07T06:{i:02d}:30+01:00",
            delay=delay,
            delay_source="departure",
            vehicle_registration_number="5571",
            flags=frozenset({"delay_vs_last_stop_conflict"} if i in conflict else set()),
        )
        for i, delay in enumerate(delays, start=1)
    )
    return DayRepresentatives(
        service_date="2026-11-07",
        planned_trips=(trip,),
        stop_values=values,
        structurally_usable_trip_ids=frozenset({"TRIP1"}) if len(values) >= 2 else frozenset(),
        raw_observation_count=len(values),
        raw_trip_ids=frozenset({"TRIP1"}),
        raw_vehicle_ids=frozenset({"5571"}),
        first_observed_at=values[0].observed_at,
        last_observed_at=values[-1].observed_at,
        observed_sequences={"TRIP1": tuple(range(1, len(values) + 1))},
    )


def representatives(day, from_offset=None, to_offset=None):
    return interval_trip_representatives(day, None, from_offset, to_offset)[1]


def test_first_stop_conflict_not_in_aggregate():
    day = make_day([-1197, 36, 58], {1})
    values = representatives(day)
    assert len(values) == 1
    assert [value.delay for value in values[0].stops] == [36, 58]
    assert values[0].representative_delay == 47
    assert len(day.stop_values) == 3  # original points preserved


def test_single_remaining_usable_stop_does_not_count_as_trip():
    assert representatives(make_day([-1197, 36], {1})) == []


def test_persistent_real_high_delay_is_retained():
    values = representatives(make_day([720, 900, 830]))
    assert len(values) == 1
    assert [point.delay for point in values[0].stops] == [720, 900, 830]


def test_isolated_numerical_spike_is_excluded_from_summary():
    values = representatives(make_day([42, 800, 41]))
    assert [point.delay for point in values[0].stops] == [42, 41]
    assert "isolated_spike_excluded" in values[0].flags


def test_hour_and_day_use_same_quality_selection():
    day = make_day([-1197, 36, 58], {1})
    whole = representatives(day)[0]
    hour = representatives(day, 3, 3)[0]
    assert [point.observation_id for point in whole.stops] == [
        point.observation_id for point in hour.stops
    ]


def test_on_time_boundary_is_consistent():
    assert classify_delay(-61) == "early"
    assert classify_delay(-60) == "on_time"
    assert classify_delay(179) == "on_time"
    assert classify_delay(180) == "mild_delay"
    assert classify_delay(601) == "high_delay"
