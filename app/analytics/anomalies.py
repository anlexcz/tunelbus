from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def observation_flags(row: dict) -> set[str]:
    """Return conservative diagnostics only; callers never filter on these flags."""
    flags: set[str] = set()
    actual = row.get("delay_actual")
    last_values = [value for value in (row.get("delay_last_stop_departure"), row.get("delay_last_stop_arrival")) if value is not None]
    if actual is not None and last_values and any(abs(actual - value) > 600 for value in last_values):
        flags.add("delay_vs_last_stop_conflict")
    return flags


def trip_flags(stop_values: Iterable[object], observed_sequences: list[int]) -> set[str]:
    """Derive simple, explainable trip diagnostics without removing any value."""
    flags: set[str] = set()
    if any(after < before for before, after in zip(observed_sequences, observed_sequences[1:])):
        flags.add("sequence_regression")
    values = sorted(stop_values, key=lambda item: item.stop_sequence)
    delays = [item.delay for item in values]
    if sum(delay > 600 for delay in delays) >= 3:
        flags.add("sustained_high_delay")
    for before, current, after in zip(values, values[1:], values[2:]):
        if current.delay > 600 and before.delay <= 180 and after.delay <= 180:
            flags.add("single_stop_spike")
            break
    return flags
