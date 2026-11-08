from __future__ import annotations

from datetime import date
from statistics import median

from app.config import Settings
from app.database import Database

from .metrics import DELAY_CLASSES, classify_delay, coverage_status, percentile_90
from .representatives import day_representatives, interval_trip_representatives


def available_days(db: Database) -> list[str]:
    with db.connection() as conn:
        return [row["service_date"] for row in conn.execute("SELECT service_date FROM gtfs_snapshots ORDER BY service_date")]


def resolve_range(db: Database, from_day: str | None, to_day: str | None) -> tuple[str, str, list[str]]:
    days = available_days(db)
    if not days:
        raise ValueError("Nejsou dostupné žádné service days.")
    if from_day is not None:
        date.fromisoformat(from_day)
    if to_day is not None:
        date.fromisoformat(to_day)
    start = from_day or days[max(0, len(days) - 7)]
    end = to_day or days[-1]
    if start > end:
        raise ValueError("Parametr from nesmí být později než to.")
    selected = [day for day in days if start <= day <= end]
    if not selected:
        raise LookupError("Žádané období neobsahuje dostupné service days.")
    return start, end, selected


def _aggregate(planned, representatives) -> dict:
    delays = [item.representative_delay for item in representatives]
    count = len(delays)
    distribution = {key: sum(classify_delay(delay) == key for delay in delays) for key in DELAY_CLASSES}
    coverage = round(count * 100 / len(planned), 1) if planned else None
    return {
        "average_delay": round(sum(delays) / count) if count else None,
        "median_delay": round(median(delays)) if count else None,
        "p90_delay": round(percentile_90(delays)) if count else None,
        "min_delay": round(min(delays)) if count else None,
        "max_delay": round(max(delays)) if count else None,
        "distribution": distribution,
        "planned_trips": len(planned), "usable_trips": count,
        "coverage": coverage, "coverage_status": coverage_status(coverage),
    }


def _loaded_days(db: Database, settings: Settings, days: list[str]):
    return [(day, day_representatives(db, settings, day)) for day in days]


def history_days(db: Database, settings: Settings, days: list[str]) -> list[dict]:
    result = []
    for day, data in _loaded_days(db, settings, days):
        planned, representatives, _, _ = interval_trip_representatives(data, settings)
        result.append({"date": day, **_aggregate(planned, representatives)})
    return result


def history_summary(db: Database, settings: Settings, days: list[str]) -> dict:
    planned_all, representatives_all, day_records = [], [], []
    for day, data in _loaded_days(db, settings, days):
        planned, representatives, _, _ = interval_trip_representatives(data, settings)
        planned_all.extend(planned); representatives_all.extend(representatives)
        day_records.append(_aggregate(planned, representatives))
    result = _aggregate(planned_all, representatives_all)
    result.update({
        "days_total": len(days),
        "days_good": sum(item["coverage_status"] == "good" for item in day_records),
        "days_partial": sum(item["coverage_status"] == "partial" for item in day_records),
        "days_insufficient": sum(item["coverage_status"] == "insufficient" for item in day_records),
    })
    return result


def history_hours(db: Database, settings: Settings, days: list[str]) -> list[dict]:
    loaded = _loaded_days(db, settings, days)
    result = []
    for offset in range(24):
        planned_all, representatives_all = [], []
        for _, data in loaded:
            planned, representatives, _, _ = interval_trip_representatives(data, settings, offset, offset)
            planned_all.extend(planned); representatives_all.extend(representatives)
        if planned_all:
            result.append({"hour": (settings.service_day_boundary.hour + offset) % 24, "offset": offset, **_aggregate(planned_all, representatives_all)})
    return result
