from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .database import Database
from .gtfs import create_snapshot


def run(settings: Settings, db: Database, service_date) -> bool | None:
    if service_date < settings.collection_start_date:
        logging.getLogger(__name__).info("GTFS snapshot skipped service_date=%s before collection_start_date=%s", service_date, settings.collection_start_date)
        return None
    created = create_snapshot(db, settings, service_date)
    logging.getLogger(__name__).info("GTFS worker finished service_date=%s created=%s", service_date, created)
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.initialize()
    run(settings, db, datetime.now(ZoneInfo(settings.timezone)).date())


if __name__ == "__main__":
    main()
