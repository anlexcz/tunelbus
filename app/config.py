from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

from dotenv import load_dotenv


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    timezone: str
    route_short_name: str
    route_id: str
    collection_start_date: date
    data_dir: Path
    backup_dir: Path
    log_dir: Path
    host: str
    port: int
    poll_interval_seconds: int
    http_timeout_seconds: int
    http_retries: int
    log_level: str
    debug: bool
    service_day_boundary: time = time(3, 0)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "tunelbus.sqlite3"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        root = Path.cwd()
        path = lambda key, default: Path(os.getenv(key, default)).expanduser().resolve()
        return cls(
            api_key=os.getenv("GOLEMIO_API_KEY", ""),
            timezone=os.getenv("TZ", "Europe/Prague"),
            route_short_name=os.getenv("ROUTE_SHORT_NAME", "145"),
            route_id=os.getenv("ROUTE_ID", "L145"),
            collection_start_date=date.fromisoformat(os.getenv("COLLECTION_START_DATE", "2026-08-16")),
            data_dir=path("DATA_DIR", str(root / "data")),
            backup_dir=path("BACKUP_DIR", str(root / "backups")),
            log_dir=path("LOG_DIR", str(root / "logs")),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8010")),
            poll_interval_seconds=max(1, int(os.getenv("POLL_INTERVAL_SECONDS", "20"))),
            http_timeout_seconds=max(1, int(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))),
            http_retries=max(0, int(os.getenv("HTTP_RETRIES", "2"))),
            log_level=os.getenv("LOG_LEVEL", "DEBUG" if _bool(os.getenv("DEBUG", "false")) else "INFO").upper(),
            debug=_bool(os.getenv("DEBUG", "false")),
            service_day_boundary=time.fromisoformat(os.getenv("SERVICE_DAY_BOUNDARY", "03:00")),
        )
