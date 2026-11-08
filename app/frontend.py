from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings
from .database import Database
from .web import (available_days, czech_date, czech_day_label, day_analytics,
                  day_navigation, live_summary, operating_hours, summary)


def register_frontend(
    app: FastAPI,
    database: Database,
    settings: Settings,
    *,
    health: Callable[[], dict],
    selected_day: Callable[[str | None], str],
) -> None:
    """Attach the server-rendered frontend and its static assets to an app."""
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, date: str | None = None):
        live = live_summary(database, settings)
        day = selected_day(date) if date is not None else live["service_date"]
        navigation = day_navigation(database, day)
        return templates.TemplateResponse(request=request, name="index.html", context={"selected_day": day,
                                          "days": available_days(database), "summary": summary(database, settings, day),
                                          "live": live, "health": health(), "day_label": czech_day_label(day, live["service_date"]),
                                          "live_date": czech_date(live["service_date"]), "selected_date": czech_date(day), "navigation": navigation, "hours": operating_hours(database, settings, day), "analytics": day_analytics(database, settings, day)})

    @app.get("/about", response_class=HTMLResponse)
    def about(request: Request):
        return templates.TemplateResponse(request=request, name="about.html", context={"active_page": "about"})

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request):
        return templates.TemplateResponse(request=request, name="history.html", context={"active_page": "history"})

    @app.get("/history/{day}", response_class=HTMLResponse)
    def history_day(request: Request, day: str):
        try:
            normalized_day = selected_day(day)
        except Exception:
            return HTMLResponse("Neplatné datum. Použijte formát YYYY-MM-DD.", status_code=422)
        return templates.TemplateResponse(request=request, name="history_day.html", context={"active_page": "history", "day": normalized_day, "day_label": czech_date(normalized_day)})

    @app.get("/history/{day}/trip/{trip_id}", response_class=HTMLResponse)
    def history_trip(request: Request, day: str, trip_id: str):
        try: normalized_day = selected_day(day)
        except Exception: return HTMLResponse("Neplatné datum. Použijte formát YYYY-MM-DD.", status_code=422)
        from .web import trip_detail
        detail = trip_detail(database, settings, normalized_day, trip_id)
        if detail is None: return HTMLResponse("Spoj v tomto provozním dni nebyl nalezen.", status_code=404)
        return templates.TemplateResponse(request=request, name="history_trip.html", context={"active_page":"history", "day":normalized_day, "day_label":czech_date(normalized_day), "detail":detail})
