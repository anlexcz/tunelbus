from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings


GIB = 1024 ** 3


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _latest_backup(directory: Path) -> tuple[str | None, float | None]:
    if not directory.exists():
        return None, None
    files = list(directory.glob("tunelbus_*.sqlite3"))
    if not files:
        return None, None
    try:
        latest = max(files, key=lambda item: item.stat().st_mtime)
        modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None, None
    age_hours = (datetime.now(timezone.utc) - modified).total_seconds() / 3600
    return modified.isoformat(), round(age_hours, 2)


def operational_health(settings: Settings) -> dict:
    disk = shutil.disk_usage(settings.data_dir)
    free_percent = disk.free / disk.total * 100 if disk.total else 0.0
    daily_time, daily_age = _latest_backup(settings.backup_dir / "daily")
    intraday_time, intraday_age = _latest_backup(settings.backup_dir / "intraday")
    return {
        "storage_ok": disk.free >= 2 * GIB and free_percent >= 10.0,
        "disk_free_bytes": disk.free,
        "disk_free_percent": round(free_percent, 1),
        "database_size_bytes": settings.database_path.stat().st_size if settings.database_path.exists() else 0,
        "backups_size_bytes": _directory_size(settings.backup_dir),
        "log_size_bytes": (settings.log_dir / "tunelbus.log").stat().st_size if (settings.log_dir / "tunelbus.log").exists() else 0,
        "latest_daily_backup": daily_time,
        "daily_backup_age_hours": daily_age,
        "daily_backup_ok": daily_age is not None and daily_age <= 30,
        "latest_intraday_backup": intraday_time,
        "intraday_backup_age_hours": intraday_age,
        "intraday_backup_ok": intraday_age is not None and intraday_age <= 8,
    }
