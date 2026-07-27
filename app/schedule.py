"""First-team + recruitment calendars — training / regen, R flag, events, FotMob fixtures."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.paths import SCHEDULE_DATA_DIR
from app.scouting import SCOUTING_DIR

DATA_DIR = SCHEDULE_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH = DATA_DIR / "schedule.json"
_store_lock = threading.Lock()

DEFAULT_REPORT_TIME = "09:00"
DAY_TYPES = frozenset({"training", "regen", "preseason"})
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

SCHEDULE_OWNERS: tuple[dict[str, str], ...] = (
    {"id": "team", "label": "Team", "full_name": "Team"},
    {"id": "sam", "label": "Sam", "full_name": "Sam Baker"},
    {"id": "tommy", "label": "Tommy", "full_name": "Tommy Johnson"},
    {"id": "lee", "label": "Lee", "full_name": "Lee Darnbrough"},
    {"id": "martin", "label": "Martin", "full_name": "Martin Foyle"},
)
OWNER_IDS = frozenset(row["id"] for row in SCHEDULE_OWNERS)
DEFAULT_OWNER = "team"


class DayUpdate(BaseModel):
    type: Literal["training", "regen", "preseason", "none"] | None = None
    report_time: str | None = None
    cycle: bool = False
    recruitment_in: bool | None = None
    toggle_recruitment: bool = False
    toggle_preseason: bool = False


class EventCreate(BaseModel):
    date: str = Field(min_length=8, max_length=10)
    title: str = Field(min_length=1, max_length=120)
    time: str | None = Field(default=None, max_length=5)
    notes: str = Field(default="", max_length=500)
    owner: str = Field(default=DEFAULT_OWNER, max_length=32)


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    time: str | None = Field(default=None, max_length=5)
    notes: str | None = Field(default=None, max_length=500)
    date: str | None = Field(default=None, min_length=8, max_length=10)


def _empty_calendar() -> dict[str, Any]:
    return {"days": {}, "events": {}}


def _empty_store() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": None,
        "calendars": {owner["id"]: _empty_calendar() for owner in SCHEDULE_OWNERS},
    }


def _migrate_store(payload: dict[str, Any]) -> dict[str, Any]:
    """Upgrade v1 flat days/events into the team calendar."""
    if int(payload.get("version") or 1) >= 2 and isinstance(payload.get("calendars"), dict):
        calendars = payload["calendars"]
        for owner in SCHEDULE_OWNERS:
            bucket = calendars.get(owner["id"])
            if not isinstance(bucket, dict):
                calendars[owner["id"]] = _empty_calendar()
                continue
            if not isinstance(bucket.get("days"), dict):
                bucket["days"] = {}
            if not isinstance(bucket.get("events"), dict):
                bucket["events"] = {}
        return payload

    migrated = _empty_store()
    team = migrated["calendars"]["team"]
    days = payload.get("days")
    events = payload.get("events")
    if isinstance(days, dict):
        for date_key, entry in days.items():
            if isinstance(entry, dict) and entry.get("type") in DAY_TYPES:
                cleaned = {"type": entry["type"], "recruitment_in": bool(entry.get("recruitment_in"))}
                if entry["type"] == "training":
                    cleaned["report_time"] = (
                        str(entry.get("report_time") or DEFAULT_REPORT_TIME).strip()
                        or DEFAULT_REPORT_TIME
                    )
                team["days"][str(date_key)] = cleaned
    if isinstance(events, dict):
        team["events"] = {
            str(event_id): event
            for event_id, event in events.items()
            if isinstance(event, dict)
        }
    migrated["updated_at"] = payload.get("updated_at")
    return migrated


def _load_store() -> dict[str, Any]:
    with _store_lock:
        if not DATA_PATH.exists():
            return _empty_store()
        try:
            payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_store()
        if not isinstance(payload, dict):
            return _empty_store()
        return _migrate_store(payload)


def _save_store(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = 2
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = DATA_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(DATA_PATH)


def _validate_owner(owner: str | None) -> str:
    token = str(owner or DEFAULT_OWNER).strip().lower()
    if token not in OWNER_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Owner must be one of: {', '.join(sorted(OWNER_IDS))}",
        )
    return token


def _calendar_bucket(store: dict[str, Any], owner: str) -> dict[str, Any]:
    calendars = store.setdefault("calendars", {})
    bucket = calendars.get(owner)
    if not isinstance(bucket, dict):
        bucket = _empty_calendar()
        calendars[owner] = bucket
    if not isinstance(bucket.get("days"), dict):
        bucket["days"] = {}
    if not isinstance(bucket.get("events"), dict):
        bucket["events"] = {}
    return bucket


def _validate_date(value: str) -> str:
    token = str(value or "").strip()
    if not DATE_RE.match(token):
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD.")
    try:
        datetime.strptime(token, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid calendar date.") from exc
    return token


def _validate_time(value: str | None, *, required: bool = False) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise HTTPException(status_code=400, detail="Time is required (HH:MM).")
        return None
    token = str(value).strip()
    if not TIME_RE.match(token):
        raise HTTPException(status_code=400, detail="Time must be HH:MM (24h).")
    hour, minute = token.split(":")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise HTTPException(status_code=400, detail="Time must be a valid clock time.")
    return token


def _event_id() -> str:
    return f"ev-{uuid.uuid4().hex[:10]}"


def _fixtures_by_date(fixtures: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in fixtures:
        day = str(row.get("date") or "").strip()
        if not day:
            continue
        by_date.setdefault(day, []).append(row)
    return by_date


def _events_by_date(events: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for event in events.values():
        if not isinstance(event, dict):
            continue
        day = str(event.get("date") or "").strip()
        if not day:
            continue
        by_date.setdefault(day, []).append(event)
    for rows in by_date.values():
        rows.sort(key=lambda row: (str(row.get("time") or "99:99"), str(row.get("title") or "")))
    return by_date


def _normalize_day_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    day_type = str(entry.get("type") or "").strip()
    # Legacy "off" days are treated as cleared.
    if day_type == "off":
        return None
    if day_type not in DAY_TYPES:
        return None
    cleaned: dict[str, Any] = {
        "type": day_type,
        "recruitment_in": bool(entry.get("recruitment_in")),
    }
    if day_type == "training":
        cleaned["report_time"] = (
            str(entry.get("report_time") or DEFAULT_REPORT_TIME).strip() or DEFAULT_REPORT_TIME
        )
    return cleaned


def build_schedule_payload(
    *,
    owner: str = DEFAULT_OWNER,
    refresh_fixtures: bool = False,
) -> dict[str, Any]:
    from app.home_dashboard import build_port_vale_fixtures

    owner_id = _validate_owner(owner)
    store = _load_store()
    bucket = _calendar_bucket(store, owner_id)
    fixtures_payload = build_port_vale_fixtures(force_refresh=refresh_fixtures)
    fixtures = list(fixtures_payload.get("fixtures") or [])
    events = bucket.get("events") or {}
    days = {
        date_key: normalized
        for date_key, entry in (bucket.get("days") or {}).items()
        if (normalized := _normalize_day_entry(entry)) is not None
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "updated_at": store.get("updated_at"),
        "default_report_time": DEFAULT_REPORT_TIME,
        "owner": owner_id,
        "owners": list(SCHEDULE_OWNERS),
        "club": fixtures_payload.get("club") or "Port Vale",
        "fotmob_team_id": fixtures_payload.get("fotmob_team_id"),
        "fixtures": fixtures,
        "fixtures_by_date": _fixtures_by_date(fixtures),
        "days": days,
        "events": list(events.values()),
        "events_by_date": _events_by_date(events),
        "fixture_counts": {
            "played": fixtures_payload.get("played_count") or 0,
            "upcoming": fixtures_payload.get("upcoming_count") or 0,
            "total": len(fixtures),
        },
    }


def set_day(date_key: str, body: DayUpdate, *, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    owner_id = _validate_owner(owner)
    day = _validate_date(date_key)
    store = _load_store()
    bucket = _calendar_bucket(store, owner_id)
    days = bucket["days"]
    current = _normalize_day_entry(days.get(day) if isinstance(days.get(day), dict) else None)

    # Recruitment "R" toggle is independent of the training/regen click cycle.
    if body.toggle_recruitment:
        if current is None:
            current = {
                "type": "training",
                "report_time": DEFAULT_REPORT_TIME,
                "recruitment_in": True,
            }
        else:
            current = {
                **current,
                "recruitment_in": not bool(current.get("recruitment_in")),
            }
        days[day] = current
        _save_store(store)
        return {"date": day, "owner": owner_id, "day": current, "days": days}

    # Alt-click: toggle pre-season game (blue).
    if body.toggle_preseason:
        if current and current.get("type") == "preseason":
            days.pop(day, None)
            _save_store(store)
            return {"date": day, "owner": owner_id, "day": None, "days": days}
        entry = {
            "type": "preseason",
            "recruitment_in": bool((current or {}).get("recruitment_in")),
        }
        days[day] = entry
        _save_store(store)
        return {"date": day, "owner": owner_id, "day": entry, "days": days}

    if body.recruitment_in is not None and body.type is None and not body.cycle:
        if current is None:
            current = {
                "type": "training",
                "report_time": DEFAULT_REPORT_TIME,
                "recruitment_in": bool(body.recruitment_in),
            }
        else:
            current = {**current, "recruitment_in": bool(body.recruitment_in)}
        days[day] = current
        _save_store(store)
        return {"date": day, "owner": owner_id, "day": current, "days": days}

    recruitment_in = bool((current or {}).get("recruitment_in"))
    if body.recruitment_in is not None:
        recruitment_in = bool(body.recruitment_in)

    if body.cycle:
        # Click: blank → IN → Regen → Pre-season (blue) → blank
        current_type = str((current or {}).get("type") or "").strip() or None
        if current_type is None:
            next_type = "training"
        elif current_type == "training":
            next_type = "regen"
        elif current_type == "regen":
            next_type = "preseason"
        else:
            next_type = None
    elif body.type == "none" or (body.type is None and body.report_time is None):
        next_type = None
    elif body.type in DAY_TYPES:
        next_type = body.type
    elif body.type is None and current:
        next_type = str(current.get("type") or "").strip() or None
        if next_type not in DAY_TYPES:
            next_type = None
    else:
        raise HTTPException(
            status_code=400,
            detail="Day type must be training, regen, preseason, or none.",
        )

    if next_type is None:
        days.pop(day, None)
        _save_store(store)
        return {"date": day, "owner": owner_id, "day": None, "days": days}

    entry: dict[str, Any] = {
        "type": next_type,
        "recruitment_in": recruitment_in,
    }
    if next_type == "training":
        if body.report_time is not None:
            entry["report_time"] = (
                _validate_time(body.report_time, required=True) or DEFAULT_REPORT_TIME
            )
        elif current and current.get("type") == "training" and current.get("report_time"):
            entry["report_time"] = str(current.get("report_time"))
        else:
            entry["report_time"] = DEFAULT_REPORT_TIME

    days[day] = entry
    _save_store(store)
    return {"date": day, "owner": owner_id, "day": entry, "days": days}


def create_event(body: EventCreate) -> dict[str, Any]:
    owner_id = _validate_owner(body.owner)
    day = _validate_date(body.date)
    title = str(body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Event title is required.")
    event_time = _validate_time(body.time)
    event_id = _event_id()
    store = _load_store()
    bucket = _calendar_bucket(store, owner_id)
    events = bucket["events"]
    entry = {
        "id": event_id,
        "date": day,
        "title": title,
        "time": event_time,
        "notes": str(body.notes or "").strip(),
        "owner": owner_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    events[event_id] = entry
    _save_store(store)
    return {"event": entry, "owner": owner_id, "events": list(events.values())}


def update_event(event_id: str, body: EventUpdate, *, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    owner_id = _validate_owner(owner)
    store = _load_store()
    bucket = _calendar_bucket(store, owner_id)
    events = bucket["events"]
    entry = events.get(event_id)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail="Event not found.")

    if body.title is not None:
        title = str(body.title).strip()
        if not title:
            raise HTTPException(status_code=400, detail="Event title is required.")
        entry["title"] = title
    if body.notes is not None:
        entry["notes"] = str(body.notes).strip()
    if body.time is not None:
        entry["time"] = _validate_time(body.time)
    if body.date is not None:
        entry["date"] = _validate_date(body.date)
    entry["updated_at"] = datetime.now(UTC).isoformat()
    events[event_id] = entry
    _save_store(store)
    return {"event": entry, "owner": owner_id, "events": list(events.values())}


def delete_event(event_id: str, *, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    owner_id = _validate_owner(owner)
    store = _load_store()
    bucket = _calendar_bucket(store, owner_id)
    events = bucket["events"]
    if event_id not in events:
        raise HTTPException(status_code=404, detail="Event not found.")
    events.pop(event_id, None)
    _save_store(store)
    return {"ok": True, "owner": owner_id, "events": list(events.values())}


def register_schedule_routes(app: FastAPI) -> None:
    @app.get("/schedule", response_class=HTMLResponse)
    def schedule_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "schedule.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Schedule UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/schedule")
    def schedule_get_route(
        refresh: bool = Query(False),
        owner: str = Query(DEFAULT_OWNER),
    ) -> dict[str, Any]:
        return build_schedule_payload(owner=owner, refresh_fixtures=refresh)

    @app.put("/api/schedule/day/{date_key}")
    def schedule_day_route(
        date_key: str,
        body: DayUpdate,
        owner: str = Query(DEFAULT_OWNER),
    ) -> dict[str, Any]:
        return set_day(date_key, body, owner=owner)

    @app.post("/api/schedule/events")
    def schedule_event_create_route(body: EventCreate) -> dict[str, Any]:
        return create_event(body)

    @app.patch("/api/schedule/events/{event_id}")
    def schedule_event_update_route(
        event_id: str,
        body: EventUpdate,
        owner: str = Query(DEFAULT_OWNER),
    ) -> dict[str, Any]:
        return update_event(event_id, body, owner=owner)

    @app.delete("/api/schedule/events/{event_id}")
    def schedule_event_delete_route(
        event_id: str,
        owner: str = Query(DEFAULT_OWNER),
    ) -> dict[str, Any]:
        return delete_event(event_id, owner=owner)
