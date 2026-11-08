from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings


def service_day_bounds(settings: Settings, now: datetime | None = None) -> tuple[date, datetime, datetime]:
    """Return the local service date and its half-open [start, end) interval."""
    zone = ZoneInfo(settings.timezone)
    local_now = (now or datetime.now(zone)).astimezone(zone)
    boundary = settings.service_day_boundary
    service_date = local_now.date() - timedelta(days=1 if local_now.time() < boundary else 0)
    start = datetime.combine(service_date, boundary, tzinfo=zone)
    return service_date, start, start + timedelta(days=1)


def service_day_for_date(settings: Settings, value: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.timezone)
    start = datetime.combine(value, settings.service_day_boundary, tzinfo=zone)
    return start, start + timedelta(days=1)


def observed_at_local(value: str, timezone: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    zone = ZoneInfo(timezone)
    return parsed.astimezone(zone) if parsed.tzinfo else parsed.replace(tzinfo=zone)


def service_date_for_observation(settings: Settings, value: str) -> str | None:
    observed = observed_at_local(value, settings.timezone)
    if observed is None:
        return None
    return (observed.date() - timedelta(days=1 if observed.time() < settings.service_day_boundary else 0)).isoformat()


def boundary_seconds(boundary: time) -> int:
    return boundary.hour * 3600 + boundary.minute * 60 + boundary.second


def gtfs_seconds(value: str | None, boundary: time) -> int | None:
    """Convert a GTFS time, including 24:xx, to seconds from service-day start."""
    if not value:
        return None
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return None
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
        return None
    total = hours * 3600 + minutes * 60 + seconds
    return total + (86400 if total < boundary_seconds(boundary) else 0) - boundary_seconds(boundary)


def gtfs_display_time(value: str | None, boundary: time) -> str | None:
    if gtfs_seconds(value, boundary) is None:
        return None
    hours, minutes, _ = (int(part) for part in value.split(":"))
    return f"{hours % 24:02d}:{minutes:02d}"


def gtfs_datetime(service_date: date, value: str | None, settings: Settings) -> datetime | None:
    seconds = gtfs_seconds(value, settings.service_day_boundary)
    if seconds is None:
        return None
    start, _ = service_day_for_date(settings, service_date)
    return start + timedelta(seconds=seconds)
