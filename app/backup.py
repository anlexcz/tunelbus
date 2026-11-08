from __future__ import annotations

import shutil
from datetime import datetime

from .config import Settings


def create_backup(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    destination = settings.backup_dir / f"tunelbus-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    shutil.copy2(settings.database_path, destination)
    return destination
