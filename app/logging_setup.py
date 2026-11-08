import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def configure_logging(directory: Path, level: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        directory / "tunelbus.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
        force=True,
    )
