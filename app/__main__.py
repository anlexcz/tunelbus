from __future__ import annotations

import logging
import argparse
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response

from .collector import Collector
from .backfill import BackfillError, backfill_shapes
from .config import Settings
from .database import Database
from .frontend import register_frontend
from .logging_setup import configure_logging
from .ops_health import operational_health
from .analytics.history import history_days, history_hours, history_summary, resolve_range
from .analytics.comparison import trip_comparison
from .analytics.segments import problem_segments
from .web import (REALTIME_COLUMNS, SCHEDULE_COLUMNS, csv_content,
                  day_analytics, json_content, live_route, live_summary, live_vehicles, operating_hours, parse_day,
                  realtime_rows, schedule_rows, summary, trip_rows, trip_detail)


def create_app(settings: Settings | None = None, start_collector: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_dir, settings.log_level)
    db = Database(settings.database_path)
    database_error: str | None = None
    try:
        db.initialize()
    except Exception as exc:
        database_error = db.startup_error or f"Database startup failed: {exc}"
        logging.getLogger(__name__).exception("%s", database_error)
    collector = Collector(settings, db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_collector and database_error is None: collector.start()
        yield
        collector.stop()

    app = FastAPI(title="Tunelbus", lifespan=lifespan)
    app.state.settings, app.state.database, app.state.collector = settings, db, collector

    def selected_day(value: str | None) -> str:
        if value is None:
            return datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        try:
            return parse_day(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Neplatný formát data; použijte YYYY-MM-DD.") from exc

    @app.get("/health")
    def health():
        database_ok = database_error is None and db.ping()
        collector_running = collector.is_running
        collector_ok = not start_collector or collector_running
        ops = operational_health(settings)
        operational_ok = ops["storage_ok"] and ops["daily_backup_ok"] and ops["intraday_backup_ok"]
        return {"status": "ok" if database_ok and collector_ok and operational_ok else "degraded", "collector_running": collector_running,
                "last_successful_poll": collector.last_successful_poll,
                "last_gtfs_snapshot": db.latest_snapshot() if database_ok else None, "database_ok": database_ok,
                "database_error": database_error, **ops}

    @app.get("/debug/status")
    def debug_status():
        return {**health(), "poll_interval_seconds": settings.poll_interval_seconds,
                "route_short_name": settings.route_short_name}

    register_frontend(app, db, settings, health=health, selected_day=selected_day)

    @app.get("/api/live/summary")
    def api_live_summary():
        return {**live_summary(db, settings), "collector": {"running": collector.is_running,
                "last_successful_poll": collector.last_successful_poll}}

    @app.get("/api/live/vehicles")
    def api_live_vehicles():
        return live_vehicles(db, settings)

    @app.get("/api/live/route")
    def api_live_route():
        return live_route(db, settings)

    @app.get("/api/day/{day}/hours")
    def day_hours(day: str):
        return operating_hours(db, settings, selected_day(day))

    @app.get("/api/day/{day}/analytics")
    def analytics(day: str, from_offset: int | None = None, to_offset: int | None = None):
        return day_analytics(db, settings, selected_day(day), from_offset, to_offset)

    @app.get("/api/day/{day}/summary")
    def day_summary(day: str):
        return summary(db, settings, selected_day(day))

    @app.get("/api/day/{day}/trips")
    def day_trips(day: str):
        normalized_day = selected_day(day)
        return {"date": normalized_day, "trips": trip_rows(db, settings, normalized_day)}

    @app.get("/api/day/{day}/trip/{trip_id}")
    def day_trip_detail(day: str, trip_id: str):
        result = trip_detail(db, settings, selected_day(day), trip_id)
        if result is None: raise HTTPException(status_code=404, detail="Spoj nebyl nalezen.")
        return result

    @app.get("/api/history/{day}/trip/{trip_id}/comparison")
    def day_trip_comparison(day: str, trip_id: str):
        result = trip_comparison(db, settings, selected_day(day), trip_id)
        if result is None: raise HTTPException(status_code=404, detail="Spoj nebyl nalezen.")
        return result

    @app.get("/api/day/{day}/segments")
    def day_segments(day: str):
        normalized_day = selected_day(day)
        return {"date": normalized_day, "segments": problem_segments(db, settings, normalized_day)}

    def history_period(from_day: str | None, to_day: str | None):
        try:
            return resolve_range(db, from_day, to_day)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/history/summary")
    def api_history_summary(from_day: str | None = Query(None, alias="from"), to_day: str | None = Query(None, alias="to")):
        start, end, days = history_period(from_day, to_day)
        return {"from": start, "to": end, **history_summary(db, settings, days)}

    @app.get("/api/history/days")
    def api_history_days(from_day: str | None = Query(None, alias="from"), to_day: str | None = Query(None, alias="to")):
        start, end, days = history_period(from_day, to_day)
        return {"from": start, "to": end, "days": history_days(db, settings, days)}

    @app.get("/api/history/hours")
    def api_history_hours(from_day: str | None = Query(None, alias="from"), to_day: str | None = Query(None, alias="to")):
        start, end, days = history_period(from_day, to_day)
        return {"from": start, "to": end, "hours": history_hours(db, settings, days)}

    def download_day(day: str) -> str:
        return selected_day(day)

    @app.get("/download/{day}/schedule.csv")
    def download_schedule(day: str):
        normalized_day = download_day(day)
        return Response(csv_content(SCHEDULE_COLUMNS, schedule_rows(db, normalized_day)), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="schedule-{normalized_day}.csv"'})

    @app.get("/download/{day}/realtime.csv")
    def download_realtime_csv(day: str):
        normalized_day = download_day(day)
        return Response(csv_content(REALTIME_COLUMNS, realtime_rows(db, normalized_day)), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="realtime-{normalized_day}.csv"'})

    @app.get("/download/{day}/realtime.json")
    def download_realtime_json(day: str):
        normalized_day = download_day(day)
        return Response(json_content(realtime_rows(db, normalized_day, include_raw=True)), media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="realtime-{normalized_day}.json"'})
    return app


def main() -> None:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog="python -m app")
    subparsers = parser.add_subparsers(dest="command")
    backfill = subparsers.add_parser("backfill-shapes", help="Safely add shape points to an existing GTFS snapshot")
    backfill.add_argument("--date", required=True, type=date.fromisoformat, help="Snapshot service date (YYYY-MM-DD)")
    backfill.add_argument("--gtfs", required=True, type=Path, help="Archived GTFS ZIP path")
    arguments = parser.parse_args()
    if arguments.command == "backfill-shapes":
        configure_logging(settings.log_dir, settings.log_level)
        db = Database(settings.database_path); db.initialize()
        try:
            result = backfill_shapes(db, settings, arguments.date, arguments.gtfs)
        except BackfillError as exc:
            print(f"Shape backfill failed: {exc}", file=sys.stderr)
            raise SystemExit(2)
        if result.already_complete:
            print(f"Shape backfill already complete for {arguments.date.isoformat()}.")
        else:
            print(f"Shape backfill complete: snapshot_id={result.snapshot_id}, snapshot_trips={result.snapshot_trips}, matching_trips={result.matching_trips}, relevant_shape_ids={result.relevant_shape_ids}, shape_points_to_insert={result.shape_points_to_insert}, inserted_shape_points={result.inserted_shape_points}, updated_trip_shapes={result.updated_trip_shapes}")
        return
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__": main()
