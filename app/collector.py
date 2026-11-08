from __future__ import annotations

import hashlib
import logging
import threading
import time
import requests

from .config import Settings
from .database import Database, canonical_json, utcnow

log = logging.getLogger(__name__)
VEHICLE_POSITIONS_URL = "https://api.golemio.cz/v2/vehiclepositions"


def _get(value: dict, *names: str):
    for name in names:
        if name in value and value[name] is not None: return value[name]
    return None


def _first(*values):
    return next((value for value in values if value is not None), None)


def observations(payload: object, observed_at: str, route_short_name: str) -> list[dict]:
    features = payload.get("features") if isinstance(payload, dict) else payload if isinstance(payload, list) else None
    if not isinstance(features, list): raise ValueError("Golemio response has no feature list")
    rows = []
    for feature in features:
        if not isinstance(feature, dict): continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else feature
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates", [])
        trip = props.get("trip", {}) if isinstance(props.get("trip"), dict) else {}
        gtfs_trip = trip.get("gtfs", {}) if isinstance(trip.get("gtfs"), dict) else {}
        vehicle = props.get("vehicle", {}) if isinstance(props.get("vehicle"), dict) else {}
        position = props.get("position", {}) if isinstance(props.get("position"), dict) else {}
        last_position = props.get("last_position", {}) if isinstance(props.get("last_position"), dict) else {}
        source_timestamp = _first(_get(last_position, "origin_timestamp", "timestamp", "last_position"), _get(props, "timestamp", "source_timestamp"),
                                  props.get("last_position") if isinstance(props.get("last_position"), (str, int, float)) else None)
        raw = canonical_json(feature)
        fingerprint = hashlib.sha256((raw + "|" + str(source_timestamp)).encode()).hexdigest()
        rows.append({
            "observed_at": observed_at, "source_timestamp": source_timestamp,
            "trip_id": _first(_get(gtfs_trip, "trip_id"), _get(trip, "id", "trip_id", "gtfs_trip_id"), _get(props, "trip_id", "gtfs_trip_id")),
            "route_short_name": _first(_get(gtfs_trip, "route_short_name"), route_short_name),
            "vehicle_id": _first(_get(vehicle, "id", "vehicle_id"), _get(props, "vehicle_id")),
            "vehicle_registration_number": _first(_get(trip, "vehicle_registration_number"), _get(vehicle, "registration_number", "label", "vehicle_registration_number")),
            "latitude": _first(_get(position, "latitude", "lat"), coords[1] if len(coords) > 1 else None), "longitude": _first(_get(position, "longitude", "lon"), coords[0] if len(coords) > 1 else None),
            "bearing": _first(_get(last_position, "bearing"), _get(position, "bearing"), _get(props, "bearing")), "speed": _first(_get(last_position, "speed"), _get(position, "speed"), _get(props, "speed")),
            "delay_actual": _first(_get(last_position.get("delay", {}) if isinstance(last_position.get("delay"), dict) else {}, "actual"), _get(props, "delay", "delay_actual")),
            "delay_last_stop_arrival": _first(_get(last_position.get("delay", {}) if isinstance(last_position.get("delay"), dict) else {}, "last_stop_arrival"), _get(props, "delay_last_stop_arrival")),
            "delay_last_stop_departure": _first(_get(last_position.get("delay", {}) if isinstance(last_position.get("delay"), dict) else {}, "last_stop_departure"), _get(props, "delay_last_stop_departure")),
            "last_stop_id": _first(_get(last_position.get("last_stop", {}) if isinstance(last_position.get("last_stop"), dict) else {}, "id"), _get(props, "last_stop_id")),
            "last_stop_sequence": _first(_get(last_position.get("last_stop", {}) if isinstance(last_position.get("last_stop"), dict) else {}, "sequence"), _get(props, "last_stop_sequence")),
            "next_stop_id": _first(_get(last_position.get("next_stop", {}) if isinstance(last_position.get("next_stop"), dict) else {}, "id"), _get(props, "next_stop_id")),
            "next_stop_sequence": _first(_get(last_position.get("next_stop", {}) if isinstance(last_position.get("next_stop"), dict) else {}, "sequence"), _get(props, "next_stop_sequence")),
            "trip_status": _first(_get(trip, "status", "trip_status"), _get(last_position, "trip_status"), _get(props, "trip_status")),
            "cancellation": int(bool(_get(last_position, "is_canceled") if _get(last_position, "is_canceled") is not None else _get(props, "cancellation", "cancelled", "is_cancelled"))), "raw_payload": raw, "payload_hash": fingerprint,
        })
    return rows


class Collector:
    def __init__(self, settings: Settings, db: Database, session=requests):
        self.settings, self.db, self.session = settings, db, session
        self.last_successful_poll: str | None = None
        self._stop = threading.Event(); self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> int:
        run_id = self.db.start_run()
        try:
            for attempt in range(self.settings.http_retries + 1):
                try:
                    response = self.session.get(VEHICLE_POSITIONS_URL, params={"routeShortName": self.settings.route_short_name}, headers={"X-Access-Token": self.settings.api_key}, timeout=self.settings.http_timeout_seconds)
                    log.debug("Golemio status=%s attempt=%d", response.status_code, attempt + 1)
                    response.raise_for_status(); payload = response.json(); break
                except (requests.RequestException, ValueError):
                    if attempt == self.settings.http_retries: raise
                    time.sleep(min(2 ** attempt, 5))
            rows = observations(payload, utcnow(), self.settings.route_short_name)
            saved = sum(self.db.save_observation(row) for row in rows)
            self.last_successful_poll = utcnow()
            self.db.finish_run(run_id, "success", saved, f"vehicles={len(rows)}")
            log.info("Golemio poll vehicles=%d records_written=%d", len(rows), saved)
            log.debug("Golemio trip_ids=%s", [r["trip_id"] for r in rows])
            return saved
        except Exception as exc:
            self.db.record_error("golemio_poll", exc); self.db.finish_run(run_id, "error", 0, str(exc))
            log.exception("Golemio poll failed")
            return 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.settings.poll_interval_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear(); self._thread = threading.Thread(target=self._loop, name="tunelbus-collector", daemon=True); self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread: self._thread.join(timeout=self.settings.http_timeout_seconds + 2)
