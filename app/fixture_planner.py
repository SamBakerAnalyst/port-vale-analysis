from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
import zlib
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from typing import Any

import requests
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.paths import FIXTURE_PLANNER_DATA_DIR
from app.scouting import SCOUTING_DIR
from app.fixture_assignment_email import (
    admin_team_emails,
    app_base_url,
    parse_reject_token,
    schedule_update_emails,
    scout_email_for,
    send_assignment_email,
    send_rejection_notify_email,
    send_schedule_update_email,
    send_ticket_request_email,
    team_badge_url,
    _format_kickoff,
)

logger = logging.getLogger(__name__)

DEFAULT_SEASON = "26/27"
ALLOWED_FIXTURE_SEASONS: tuple[str, ...] = ("26/27", "25/26")
FIXTURE_CACHE_TTL_SECONDS = 1800
FIXTURE_CACHE_STALE_SECONDS = 12 * 3600
FIXTURE_CACHE_VERSION = "v18"

FIXTURE_STAFF_TEAMS: tuple[dict[str, Any], ...] = (
    {
        "id": "recruitment",
        "label": "Recruitment Team",
        "members": (
            "Lee Darnbrough",
            "Tommy Johnson",
            "Martin Foyle",
            "Sam Baker",
        ),
    },
    {
        "id": "coaching",
        "label": "Coaching Team",
        "members": (
            "Jon Brady",
            "Gary Mills",
            "Richard O'Donnell",
            "Jamie Smith",
            "Dan Watson",
        ),
    },
    {
        "id": "scouting",
        "label": "Scouting Team",
        "members": (),
    },
)

FIXTURE_STAFF: tuple[str, ...] = tuple(
    name
    for team in FIXTURE_STAFF_TEAMS
    for name in team["members"]
)

WATCH_TYPES: tuple[str, ...] = ("LIVE", "VIDEO")

_http = requests.Session()
_http.trust_env = False

_fixture_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_fixture_cache_lock = threading.Lock()
_fixture_compute_lock = threading.Lock()
_fixture_rebuild_lock = threading.Lock()
_fixture_rebuild_pending: set[str] = set()

_scout_ops_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_scout_ops_cache_lock = threading.Lock()
SCOUT_OPS_CACHE_TTL_SECONDS = 45

ASSIGNMENTS_DIR = FIXTURE_PLANNER_DATA_DIR
ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
ASSIGNMENTS_PATH = ASSIGNMENTS_DIR / "assignments.json"
SCOUTING_REPORTS_PATH = ASSIGNMENTS_DIR / "scouting-reports.json"
MANUAL_FIXTURES_PATH = ASSIGNMENTS_DIR / "manual-fixtures.json"
FIXTURE_OVERRIDES_PATH = ASSIGNMENTS_DIR / "fixture-overrides.json"
TICKET_REQUESTS_PATH = ASSIGNMENTS_DIR / "ticket-requests.json"
TEAM_SHEETS_DIR = ASSIGNMENTS_DIR / "team-sheets"
TEAM_SHEETS_DIR.mkdir(parents=True, exist_ok=True)
_assignments_lock = threading.Lock()
_scouting_reports_lock = threading.Lock()
_manual_fixtures_lock = threading.Lock()
_fixture_overrides_lock = threading.Lock()
_ticket_requests_lock = threading.Lock()
TICKET_REQUEST_DAYS_AHEAD = 13

MANUAL_LEAGUE_LABEL = "Manual"
MANUAL_FIXTURE_ID_PREFIX = "manual|"


def _normalize_league_label(value: str | None) -> str:
    """Fold common typos / aliases into canonical competition labels."""
    raw = str(value or "").strip()
    if not raw:
        return MANUAL_LEAGUE_LABEL
    compact = "".join(ch for ch in raw.casefold() if ch.isalnum())
    # "Pre Season Friednly", "Pre-Season Friendly", "Friendly", etc.
    if "friendly" in compact or "friednly" in compact:
        return "Friendly"
    # Sponsor / historic names for the EFL Trophy
    if compact in {
        "efltrophy",
        "vertutrophy",
        "papajohnstrophy",
        "bristolstreetmotorstrophy",
        "leasingcomtrophy",
        "checkatradetrophy",
        "johnstonespainttrophy",
    } or ("trophy" in compact and any(token in compact for token in ("efl", "vertu", "papa", "bristol"))):
        return "Vertu Trophy"
    if compact in {"nationalleaguecup", "nlcup"} or "nationalleaguecup" in compact:
        return "National League Cup"
    if compact in {"premierleaguecup", "plcup"}:
        return "Premier League Cup"
    if compact in {
        "professionaldevelopmentleague",
        "pdl",
        "u21professionaldevelopmentleague",
    }:
        return "Professional Development League"
    return raw
TEAM_SHEET_MAX_BYTES = 12 * 1024 * 1024
TEAM_SHEET_ALLOWED_EXT = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"})
TEAM_SHEET_ALLOWED_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/heic",
        "image/heif",
        "application/octet-stream",
    }
)


def _parse_fixture_id_parts(fixture_id: str) -> dict[str, str] | None:
    parts = str(fixture_id or "").split("|")
    if len(parts) < 4:
        return None
    return {
        "league": parts[0],
        "home": parts[1],
        "away": parts[2],
        "date": parts[3],
    }


def _team_names_match(left: str, right: str) -> bool:
    left_norm = _normalize_team_name(left)
    right_norm = _normalize_team_name(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    return left_norm in right_norm or right_norm in left_norm


def _team_names_same_club(left: str, right: str) -> bool:
    """Stricter than substring match — used when merging fixtures across sources.

    Allows Celtic Glasgow ≈ Celtic, but not Dundee ≈ Dundee United.
    """
    left_norm = _normalize_team_name(left)
    right_norm = _normalize_team_name(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True

    shorter, longer = (
        (left_norm, right_norm)
        if len(left_norm) <= len(right_norm)
        else (right_norm, left_norm)
    )
    short_tokens = shorter.split()
    long_tokens = longer.split()
    if not short_tokens or len(long_tokens) <= len(short_tokens):
        return False

    def _remainder_is_noise(tokens: list[str]) -> bool:
        if not tokens:
            return True
        if any(token in _CLUB_DISTINGUISHER_TOKENS for token in tokens):
            return False
        return all(token in _CLUB_NOISE_TOKENS for token in tokens)

    # Celtic Glasgow ≈ Celtic (suffix place name)
    if long_tokens[: len(short_tokens)] == short_tokens:
        return _remainder_is_noise(long_tokens[len(short_tokens) :])

    # Glasgow Rangers ≈ Rangers (prefix place name)
    if long_tokens[-len(short_tokens) :] == short_tokens:
        return _remainder_is_noise(long_tokens[: -len(short_tokens)])

    return False


def _fixture_sides_match(
    left_home: str,
    left_away: str,
    right_home: str,
    right_away: str,
) -> bool:
    same = _team_names_same_club(left_home, right_home) and _team_names_same_club(
        left_away, right_away
    )
    if same:
        return True
    return _team_names_same_club(left_home, right_away) and _team_names_same_club(
        left_away, right_home
    )


def _fixture_is_played(fixture: dict[str, Any]) -> bool:
    if str(fixture.get("status") or "").strip() == "completed" or fixture.get("score"):
        return True
    date_key = _fixture_day(fixture.get("date") or fixture.get("scheduled_date"))
    if not date_key:
        return False
    today = datetime.now(UTC).date().isoformat()
    return date_key < today


def _fixture_pair_matches(
    fixture: dict[str, Any],
    *,
    league: str,
    home: str,
    away: str,
    date_key: str,
) -> bool:
    if str(fixture.get("league") or "").strip() != league:
        return False
    fixture_day = _fixture_day(fixture.get("date") or fixture.get("scheduled_date"))
    if not fixture_day or not date_key:
        return False
    if abs(_days_between(fixture_day, date_key)) > FIXTURE_DATE_MATCH_TOLERANCE_DAYS:
        return False
    home_name = str((fixture.get("home") or {}).get("name") or "")
    away_name = str((fixture.get("away") or {}).get("name") or "")
    return (
        _team_names_match(home_name, home) and _team_names_match(away_name, away)
    ) or (
        _team_names_match(home_name, away) and _team_names_match(away_name, home)
    )


def _resolve_fixture_record(
    fixture_id: str,
    fixtures: list[dict[str, Any]],
    *,
    assignment: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    by_id = {
        str(row.get("fixture_id") or ""): row
        for row in fixtures
        if row.get("fixture_id")
    }

    assignment = assignment or {}
    parsed = _parse_fixture_id_parts(fixture_id) or {}
    league = str(assignment.get("league") or parsed.get("league") or "").strip()
    home = str(assignment.get("home") or parsed.get("home") or "").strip()
    away = str(assignment.get("away") or parsed.get("away") or "").strip()
    date_key = _parse_iso_date(assignment.get("date") or parsed.get("date")) or ""

    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add_candidate(row: dict[str, Any] | None) -> None:
        if not row:
            return
        row_id = str(row.get("fixture_id") or "")
        if not row_id or row_id in seen_ids:
            return
        seen_ids.add(row_id)
        candidates.append(row)

    _add_candidate(by_id.get(fixture_id))

    if league and home and away and date_key:
        for row in fixtures:
            if _fixture_pair_matches(row, league=league, home=home, away=away, date_key=date_key):
                _add_candidate(row)

    if not candidates:
        return None

    def _rank(row: dict[str, Any]) -> tuple[int, int, int]:
        has_match_id = 0 if row.get("match_id") else 1
        has_score = 0 if row.get("score") else 1
        source_count = -int(row.get("source_count") or len(row.get("sources") or []))
        return (has_match_id, has_score, source_count)

    candidates.sort(key=_rank)
    return candidates[0]


def _cached_fixtures_list(seasons: list[str], *, warm: bool = False) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    now = time.time()
    for season in seasons:
        cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
        with _fixture_cache_lock:
            cached = _fixture_cache.get(cache_key)
        if cached and now - cached[0] < FIXTURE_CACHE_TTL_SECONDS:
            merged = _finalize_fixture_payload(cached[1], season=season)
            for fixture in merged.get("fixtures") or []:
                fixtures.append({**fixture, "season": season})
        else:
            disk = _load_disk_fixture_cache(season)
            if disk:
                ts, payload = disk
                _store_memory_fixture_cache(season, ts, payload)
                merged = _finalize_fixture_payload(payload, season=season)
                for fixture in merged.get("fixtures") or []:
                    fixtures.append({**fixture, "season": season})
            elif warm:
                try:
                    payload = build_fixture_planner_payload(season=season)
                    for fixture in payload.get("fixtures") or []:
                        fixtures.append({**fixture, "season": season})
                except HTTPException:
                    continue
    return fixtures


def _cached_fixtures_by_id(seasons: list[str]) -> dict[str, dict[str, Any]]:
    """Return fixture lookup from warm cache only — never triggers external fetches."""
    fixtures_by_id: dict[str, dict[str, Any]] = {}
    now = time.time()
    for season in seasons:
        cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
        with _fixture_cache_lock:
            cached = _fixture_cache.get(cache_key)
        if not cached or now - cached[0] >= FIXTURE_CACHE_TTL_SECONDS:
            continue
        for fixture in cached[1].get("fixtures") or []:
            fixture_id = str(fixture.get("fixture_id") or "")
            if fixture_id:
                fixtures_by_id[fixture_id] = {**fixture, "season": season}
    return fixtures_by_id


def _scout_ops_cache_get(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _scout_ops_cache_lock:
        cached = _scout_ops_cache.get(key)
        if cached and now - cached[0] < SCOUT_OPS_CACHE_TTL_SECONDS:
            return cached[1]
    return None


def _scout_ops_cache_set(key: str, payload: dict[str, Any]) -> None:
    with _scout_ops_cache_lock:
        _scout_ops_cache[key] = (time.time(), payload)


def _scout_ops_cache_clear() -> None:
    with _scout_ops_cache_lock:
        _scout_ops_cache.clear()


def _normalize_staff_names(value: Any, *, validate: bool = False) -> list[str]:
    """Accept legacy string or list; return unique staff names in order."""
    if value is None:
        raw: list[str] = []
    elif isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(item) for item in value]
    else:
        raw = [str(value)]

    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item or "").strip()
        if not name:
            continue
        if validate and name not in FIXTURE_STAFF:
            raise HTTPException(status_code=400, detail=f"Unknown staff member: {name}")
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _staff_label(value: Any) -> str:
    return ", ".join(_normalize_staff_names(value))


def _staff_name_set(value: Any) -> set[str]:
    return {name.casefold() for name in _normalize_staff_names(value)}


class FixtureAssignmentUpdate(BaseModel):
    fixture_id: str
    staff: list[str] | str = ""
    watch_type: str = ""
    season: str = ""
    league: str = ""
    home: str = ""
    away: str = ""
    date: str = ""
    kickoff_utc: str | None = None
    watched_players: list[dict[str, Any]] = Field(default_factory=list)


class FixtureAssignmentsBulkUpdate(BaseModel):
    assignments: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TicketRequestFixtureDetail(BaseModel):
    fixture_id: str
    tickets: int = 1
    parking: str = "No"
    notes: str = ""


class TicketRequestBody(BaseModel):
    fixtures: list[TicketRequestFixtureDetail] = Field(default_factory=list)
    additional_requests: str = ""


class FixtureStatusUpdate(BaseModel):
    fixture_id: str
    status: str = "postponed"


class ScoutingReportToggle(BaseModel):
    fixture_id: str
    player_id: int
    player_name: str = ""
    side: str = ""
    team: str = ""
    season: str = ""
    staff: str = ""
    fixture_date: str = ""
    position: str = ""
    reported: bool = True


class ManualFixturePlayerInput(BaseModel):
    player_name: str = ""
    name: str = ""
    team: str = ""
    side: str = ""
    position: str = ""
    player_id: int | None = None


class ManualFixtureCreate(BaseModel):
    season: str = DEFAULT_SEASON
    league: str = MANUAL_LEAGUE_LABEL
    competition: str = ""
    home: str
    away: str
    date: str
    kickoff: str = ""
    score: str = ""
    venue: str = ""
    notes: str = ""
    staff: list[str] | str = ""
    watch_type: str = "LIVE"
    players: list[ManualFixturePlayerInput] = Field(default_factory=list)
    mark_reports: bool = True
    # "scheduled" = upcoming (Fixture Planner), "completed" = played / attended
    status: str = "completed"


class ManualFixtureUpdate(BaseModel):
    league: str | None = None
    competition: str | None = None
    home: str | None = None
    away: str | None = None
    date: str | None = None
    kickoff: str | None = None
    score: str | None = None
    venue: str | None = None
    notes: str | None = None
    staff: list[str] | str | None = None
    watch_type: str | None = None
    players: list[ManualFixturePlayerInput] | None = None
    mark_reports: bool = True


# Impect / lineup position codes → report pitch buckets (1–11 style).
POSITION_REPORT_BUCKETS: tuple[dict[str, Any], ...] = (
    {
        "id": "1",
        "label": "GK",
        "codes": frozenset({"GOALKEEPER", "GK", "1"}),
    },
    {
        "id": "2",
        "label": "RB",
        "codes": frozenset({"RIGHT_WINGBACK_DEFENDER", "RIGHT_BACK", "RB", "RWB", "2"}),
    },
    {
        "id": "3",
        "label": "LB",
        "codes": frozenset({"LEFT_WINGBACK_DEFENDER", "LEFT_BACK", "LB", "LWB", "3"}),
    },
    {
        "id": "4/5",
        "label": "CB",
        "codes": frozenset({"CENTRAL_DEFENDER", "CENTRE_BACK", "CENTER_BACK", "CB", "4", "5", "4/5"}),
    },
    {
        "id": "6",
        "label": "DM",
        "codes": frozenset({"DEFENSE_MIDFIELD", "DEFENSIVE_MIDFIELD", "DM", "CDM", "6"}),
    },
    {
        "id": "8",
        "label": "CM",
        "codes": frozenset({"CENTRAL_MIDFIELD", "CM", "8"}),
    },
    {
        "id": "10",
        "label": "AM",
        "codes": frozenset({"ATTACKING_MIDFIELD", "AM", "CAM", "10"}),
    },
    {
        "id": "7",
        "label": "RW",
        "codes": frozenset({"RIGHT_WINGER", "RIGHT_MIDFIELD", "RW", "RM", "7"}),
    },
    {
        "id": "11",
        "label": "LW",
        "codes": frozenset({"LEFT_WINGER", "LEFT_MIDFIELD", "LW", "LM", "11"}),
    },
    {
        "id": "9",
        "label": "ST",
        "codes": frozenset({"CENTER_FORWARD", "CENTRE_FORWARD", "STRIKER", "ST", "CF", "9"}),
    },
)


def normalize_report_position(raw: str | None) -> dict[str, str]:
    token = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not token:
        return {"bucket_id": "unknown", "label": "Unknown", "raw": ""}
    for bucket in POSITION_REPORT_BUCKETS:
        if token in bucket["codes"] or token == str(bucket["label"]).upper():
            return {
                "bucket_id": str(bucket["id"]),
                "label": str(bucket["label"]),
                "raw": str(raw or "").strip(),
            }
    return {"bucket_id": "unknown", "label": "Unknown", "raw": str(raw or "").strip()}


FIXTURE_LEAGUES: tuple[dict[str, Any], ...] = (
    {
        "ui": "League One",
        "competition": "League One",
        "fotmob_id": 108,
        "bbc_path": "league-one",
        "transfermarkt_id": "GB3",
        "transfermarkt_slug": "league-one",
        "color": "#3d8bfd",
    },
    {
        "ui": "League Two",
        "competition": "League Two",
        "fotmob_id": 109,
        "bbc_path": "league-two",
        "transfermarkt_id": "GB4",
        "transfermarkt_slug": "league-two",
        "color": "#34d399",
    },
    {
        "ui": "National League",
        "competition": "National League",
        "fotmob_id": 117,
        "bbc_path": "national-league",
        "transfermarkt_id": "NLN6",
        "transfermarkt_slug": "national-league",
        "color": "#fbbf24",
    },
    {
        "ui": "Scottish Prem",
        "competition": "Scottish Premiership",
        "fotmob_id": 64,
        "bbc_path": "scottish-premiership",
        "transfermarkt_id": "SC1",
        "transfermarkt_slug": "scottish-premiership",
        "color": "#a78bfa",
    },
    {
        "ui": "PL2",
        "competition": "Premier League 2",
        "fotmob_id": 9084,
        "bbc_path": "premier-league-2",
        "transfermarkt_id": "GB21",
        "transfermarkt_slug": "premier-league-2",
        "color": "#f97316",
    },
    {
        "ui": "Irish Prem",
        "competition": "Irish Premier Division",
        "fotmob_id": 126,
        "bbc_path": "league-of-ireland-premier-division",
        "transfermarkt_id": "IR1",
        "transfermarkt_slug": "league-of-ireland-premier-division",
        "color": "#22d3ee",
        "calendar_year": True,
    },
    {
        # League competition (not a cup) — Pulse source; incomplete/missing on FotMob.
        "ui": "Professional Development League",
        "competition": "Professional Development League",
        "pulse_competition_id": 6,
        "color": "#14b8a6",
    },
)

# German leagues — shown under a dedicated Germany tab (not mixed with UK leagues).
FIXTURE_GERMANY_LEAGUES: tuple[dict[str, Any], ...] = (
    {
        "ui": "Bundesliga",
        "competition": "Bundesliga",
        "fotmob_id": 54,
        "color": "#e11d48",
    },
    {
        "ui": "2. Bundesliga",
        "competition": "2. Bundesliga",
        "fotmob_id": 146,
        "color": "#94a3b8",
    },
)

# Domestic cups — shown under a dedicated Cups toggle with stacked layout.
# Prefer FotMob when fotmob_id is set; use Premier League Pulse when pulse_competition_id is set
# (Premier League Cup / Vertu Trophy are incomplete or missing on FotMob).
FIXTURE_CUPS: tuple[dict[str, Any], ...] = (
    {
        "ui": "FA Cup",
        "competition": "FA Cup",
        "fotmob_id": 132,
        "bbc_path": "fa-cup",
        "color": "#ef4444",
        "cup": True,
    },
    {
        "ui": "EFL Cup",
        "competition": "EFL Cup",
        "fotmob_id": 133,
        "bbc_path": "efl-cup",
        "color": "#fb923c",
        "cup": True,
    },
    {
        "ui": "Vertu Trophy",
        "competition": "EFL Trophy",
        "fotmob_id": 142,
        "pulse_competition_id": 13,
        "bbc_path": "efl-trophy",
        "color": "#eab308",
        "cup": True,
    },
    {
        "ui": "National League Cup",
        "competition": "National League Cup",
        "fotmob_id": 10705,
        "color": "#84cc16",
        "cup": True,
    },
    {
        "ui": "Premier League Cup",
        "competition": "Premier League Cup",
        "pulse_competition_id": 9,
        "color": "#a855f7",
        "cup": True,
    },
    {
        "ui": "Scottish Cup",
        "competition": "Scottish Cup",
        "fotmob_id": 137,
        "bbc_path": "scottish-cup",
        "color": "#38bdf8",
        "cup": True,
    },
)

# FotMob competitions used for manual-fixture club autocomplete.
# UK/Ireland plus German top two (Fixture Planner leagues).
FOTMOB_TEAM_CATALOG_LEAGUES: tuple[dict[str, Any], ...] = (
    # England
    {"id": 47, "label": "Premier League", "country": "ENG"},
    {"id": 48, "label": "Championship", "country": "ENG"},
    {"id": 108, "label": "League One", "country": "ENG"},
    {"id": 109, "label": "League Two", "country": "ENG"},
    {"id": 117, "label": "National League", "country": "ENG"},
    {"id": 8944, "label": "National North & South", "country": "ENG"},
    {"id": 9084, "label": "Premier League 2", "country": "ENG"},
    {"id": 132, "label": "FA Cup", "country": "ENG"},
    {"id": 133, "label": "EFL Cup", "country": "ENG"},
    {"id": 142, "label": "Vertu Trophy", "country": "ENG"},
    {"id": 10705, "label": "National League Cup", "country": "ENG"},
    {"id": 9253, "label": "FA Trophy", "country": "ENG"},
    # Scotland
    {"id": 64, "label": "Scottish Premiership", "country": "SCO"},
    {"id": 123, "label": "Scottish Championship", "country": "SCO"},
    {"id": 124, "label": "Scottish League One", "country": "SCO"},
    {"id": 125, "label": "Scottish League Two", "country": "SCO"},
    {"id": 137, "label": "Scottish Cup", "country": "SCO"},
    {"id": 180, "label": "Scottish League Cup", "country": "SCO"},
    {"id": 179, "label": "Scottish Challenge Cup", "country": "SCO"},
    # Wales
    {"id": 116, "label": "Cymru Premier", "country": "WAL"},
    {"id": 9166, "label": "Welsh Cup", "country": "WAL"},
    # Republic of Ireland
    {"id": 126, "label": "Irish Premier Division", "country": "IRL", "calendar_year": True},
    {"id": 218, "label": "Irish First Division", "country": "IRL", "calendar_year": True},
    {"id": 219, "label": "FAI Cup", "country": "IRL", "calendar_year": True},
    # Northern Ireland
    {"id": 129, "label": "NIFL Premiership", "country": "NIR"},
    # Germany (Fixture Planner leagues)
    {"id": 54, "label": "Bundesliga", "country": "GER"},
    {"id": 146, "label": "2. Bundesliga", "country": "GER"},
)

TEAM_CATALOG_COUNTRIES = frozenset({"ENG", "SCO", "WAL", "IRL", "NIR", "GER"})
TEAM_CATALOG_TTL_SECONDS = 6 * 3600
_team_catalog_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_team_catalog_cache_lock = threading.Lock()

COUNTRY_LABELS: dict[str, str] = {
    "ENG": "England",
    "SCO": "Scotland",
    "WAL": "Wales",
    "IRL": "Ireland",
    "NIR": "N. Ireland",
    "GER": "Germany",
}

FIXTURE_COMPETITIONS: tuple[dict[str, Any], ...] = (
    tuple(FIXTURE_LEAGUES) + tuple(FIXTURE_GERMANY_LEAGUES) + tuple(FIXTURE_CUPS)
)
FIXTURE_LEAGUE_BY_UI = {row["ui"]: row for row in FIXTURE_COMPETITIONS}
FIXTURE_LEAGUE_UIS = [row["ui"] for row in FIXTURE_LEAGUES]
FIXTURE_GERMANY_UIS = [row["ui"] for row in FIXTURE_GERMANY_LEAGUES]
FIXTURE_CUP_UIS = [row["ui"] for row in FIXTURE_CUPS]

BBC_SEASON_MONTHS: dict[str, tuple[str, ...]] = {
    "26/27": (
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
        "2027-03",
        "2027-04",
        "2027-05",
        "2027-06",
    ),
    "25/26": (
        "2025-07",
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
    ),
}

TEAM_ALIASES: dict[str, str] = {
    "notts co": "notts county",
    "mk dons": "milton keynes dons",
    "brighton and hove u21": "brighton and hove albion u21",
    "man utd u21": "manchester united u21",
    "man city u21": "manchester city u21",
    "nottm forest u21": "nottingham forest u21",
    "sheff utd u21": "sheffield united u21",
    "sheff wed u21": "sheffield wednesday u21",
    "west brom u21": "west bromwich albion u21",
    "brighton u21": "brighton and hove albion u21",
    "qpr u21": "queens park rangers u21",
    "sheff utd": "sheffield united",
    "sheff wed": "sheffield wednesday",
    "man utd": "manchester united",
    "man city": "manchester city",
    "oxford utd": "oxford united",
    "cambridge utd": "cambridge united",
    # Impect vs FotMob/BBC naming for Scottish clubs
    "celtic glasgow": "celtic",
    "glasgow celtic": "celtic",
    "rangers glasgow": "rangers",
    "glasgow rangers": "rangers",
    "hibernian edinburgh": "hibernian",
    "edinburgh hibernian": "hibernian",
    "heart of midlothian": "hearts",
    "hearts of midlothian": "hearts",
    "dundee fc": "dundee",
    "st mirren": "st mirren",
    "saint mirren": "st mirren",
}

# Tokens that mean a different club when appended (Dundee ≠ Dundee United).
_CLUB_DISTINGUISHER_TOKENS = frozenset(
    {
        "united",
        "city",
        "wednesday",
        "athletic",
        "athletico",
        "wanderers",
        "rovers",
        "albion",
        "town",
        "county",
        "forest",
        "hotspur",
        "argyle",
        "villa",
        "palace",
        "orient",
    }
)

# Harmless place / filler suffixes (Celtic Glasgow ≈ Celtic).
_CLUB_NOISE_TOKENS = frozenset(
    {
        "glasgow",
        "edinburgh",
        "london",
        "manchester",
        "birmingham",
        "nottingham",
        "newcastle",
        "upon",
        "tyne",
        "and",
        "the",
        "of",
        "midlothian",
    }
)

SOURCE_PRIORITY: dict[str, int] = {
    "impect": 3,
    "bbc": 2,
    "fotmob": 1,
    "transfermarkt": 0,
}

FIXTURE_DATE_MATCH_TOLERANCE_DAYS = 2


def _impect():
    from app import main as impect_main

    return impect_main


def _calendar_year_for_season(season: str) -> str:
    """Map English football seasons (26/27) to calendar-year competitions (2026)."""
    token = str(season or DEFAULT_SEASON).strip()
    start = token.split("/")[0].strip()
    if start.isdigit():
        year = int(start)
        return str(year + 2000 if year < 100 else year)
    if token.isdigit():
        year = int(token)
        return str(year + 2000 if year < 100 else year)
    return "2026"


def _season_to_fotmob(season: str, *, calendar_year: bool = False) -> str:
    if calendar_year:
        return _calendar_year_for_season(season)
    token = str(season or DEFAULT_SEASON).strip()
    if "/" in token:
        parts = token.split("/")
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            start = int(parts[0])
            end = int(parts[1])
            if start < 100:
                start += 2000
            if end < 100:
                end += 2000
            return f"{start}/{end}"
    if token.isdigit() and len(token) == 4:
        return token
    return "2026/2027"


def _season_year_pair(season: str) -> tuple[int, int] | None:
    token = str(season or DEFAULT_SEASON).strip()
    if "/" not in token:
        return None
    left, right = [part.strip() for part in token.split("/", 1)]
    if not (left.isdigit() and right.isdigit()):
        return None
    start = int(left)
    end = int(right)
    if start < 100:
        start += 2000
    if end < 100:
        end += 2000
    return start, end


_PULSE_API = "https://footballapi.pulselive.com/football"
_PULSE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.premierleague.com",
    "Referer": "https://www.premierleague.com/",
}


def _resolve_pulse_comp_season_id(competition_id: int, season: str) -> int | None:
    """Map hub season (26/27) to a Premier League Pulse compSeason id."""
    years = _season_year_pair(season)
    if years is None:
        return None
    start, end = years
    needles = {
        f"{start}/{end}",
        f"{start}/{str(end)[-2:]}",
        f"{start}-{end}",
        f"{str(start)[-2:]}/{str(end)[-2:]}",
        f"season {start}",
    }
    try:
        response = _http.get(
            f"{_PULSE_API}/competitions/{int(competition_id)}/compseasons",
            headers=_PULSE_HEADERS,
            timeout=25,
        )
        if not response.ok:
            return None
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        logger.exception("Pulse comp-season lookup failed for competition %s", competition_id)
        return None

    rows = payload.get("content") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").casefold()
        if not label:
            continue
        if any(needle.casefold() in label for needle in needles):
            try:
                return int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
    return None


def _pulse_kickoff_iso(kickoff: Any) -> str | None:
    if not isinstance(kickoff, dict):
        return None
    millis = kickoff.get("millis")
    try:
        ms = float(millis)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()


def _fetch_pulse_fixtures(
    competition_id: int,
    *,
    league_ui: str,
    season: str,
) -> list[dict[str, Any]]:
    """Pull fixtures from Premier League Pulse (PDL, Premier League Cup, Vertu Trophy)."""
    comp_season_id = _resolve_pulse_comp_season_id(competition_id, season)
    if comp_season_id is None:
        logger.info(
            "No Pulse compSeason for competition=%s season=%s",
            competition_id,
            season,
        )
        return []

    fixtures: list[dict[str, Any]] = []
    page = 0
    total_pages = 1
    while page < total_pages and page < 40:
        try:
            response = _http.get(
                f"{_PULSE_API}/fixtures",
                params={
                    "comps": int(competition_id),
                    "compSeasons": int(comp_season_id),
                    "page": page,
                    "pageSize": 100,
                    "sort": "asc",
                    "statuses": "U,L,C,A",
                },
                headers=_PULSE_HEADERS,
                timeout=30,
            )
            if not response.ok:
                break
            payload = response.json()
        except (requests.RequestException, ValueError, TypeError):
            logger.exception(
                "Pulse fixtures fetch failed for competition %s season %s page %s",
                competition_id,
                season,
                page,
            )
            break

        page_info = payload.get("pageInfo") or {}
        try:
            total_pages = max(1, int(page_info.get("numPages") or 1))
        except (TypeError, ValueError):
            total_pages = 1
        rows = payload.get("content") or []
        if not isinstance(rows, list):
            break

        for match in rows:
            if not isinstance(match, dict):
                continue
            teams = match.get("teams") or []
            if not isinstance(teams, list) or len(teams) < 2:
                continue
            home = teams[0] if isinstance(teams[0], dict) else {}
            away = teams[1] if isinstance(teams[1], dict) else {}
            home_team = home.get("team") if isinstance(home.get("team"), dict) else {}
            away_team = away.get("team") if isinstance(away.get("team"), dict) else {}
            home_name = str(home_team.get("name") or "").strip()
            away_name = str(away_team.get("name") or "").strip()
            if not home_name or not away_name:
                continue
            kickoff = _pulse_kickoff_iso(match.get("kickoff") or match.get("provisionalKickoff"))
            status_code = str(match.get("status") or "").strip().upper()
            finished = status_code in {"C", "A"}
            home_score = home.get("score")
            away_score = away.get("score")
            try:
                home_score_i = int(home_score) if home_score is not None else None
            except (TypeError, ValueError):
                home_score_i = None
            try:
                away_score_i = int(away_score) if away_score is not None else None
            except (TypeError, ValueError):
                away_score_i = None
            score = None
            if home_score_i is not None and away_score_i is not None:
                score = f"{home_score_i} - {away_score_i}"
            group = match.get("group")
            gameweek = match.get("gameweek") if isinstance(match.get("gameweek"), dict) else {}
            round_label = None
            if group not in (None, ""):
                round_label = str(group)
            else:
                gw = _safe_int(gameweek.get("gameweek"))
                if gw is not None:
                    round_label = str(gw)

            fixtures.append(
                {
                    "league": league_ui,
                    "season": season,
                    "match_day": _safe_int(gameweek.get("gameweek")),
                    "round": round_label,
                    "round_name": round_label,
                    "scheduled_date": kickoff,
                    "date": _parse_iso_date(kickoff),
                    "kickoff_utc": kickoff,
                    "home": {
                        "name": home_name,
                        "fotmob_id": None,
                    },
                    "away": {
                        "name": away_name,
                        "fotmob_id": None,
                    },
                    "status": "completed" if finished else "scheduled",
                    "score": score,
                    "home_score": home_score_i,
                    "away_score": away_score_i,
                    "sources": ["pulse"],
                    "source_ids": {"pulse": str(match.get("id") or "")},
                }
            )
        page += 1
        if not rows:
            break

    return fixtures


def _season_to_transfermarkt(season: str, *, calendar_year: bool = False) -> int:
    if calendar_year:
        return int(_calendar_year_for_season(season))
    token = str(season or DEFAULT_SEASON).split("/")[0].strip()
    if token.isdigit():
        year = int(token)
        return year + 2000 if year < 100 else year
    return 2026


def _season_bounds(season: str, *, calendar_year: bool = False) -> tuple[str, str]:
    if calendar_year:
        year = _calendar_year_for_season(season)
        return (f"{year}-01-01", f"{year}-12-31")
    token = str(season or DEFAULT_SEASON).strip()
    parts = token.split("/")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        start_year = int(parts[0])
        end_year = int(parts[1])
        if start_year < 100:
            start_year += 2000
        if end_year < 100:
            end_year += 2000
        return (f"{start_year}-06-15", f"{end_year}-07-15")
    if token.isdigit() and len(token) == 4:
        return (f"{token}-01-01", f"{token}-12-31")
    return ("2026-06-15", "2027-07-15")


def _bbc_months_for_season(season: str, *, calendar_year: bool = False) -> tuple[str, ...]:
    if calendar_year:
        year = _calendar_year_for_season(season)
        return tuple(f"{year}-{month:02d}" for month in range(1, 13))
    return BBC_SEASON_MONTHS.get(season, BBC_SEASON_MONTHS[DEFAULT_SEASON])


def _fixture_in_season(
    row: dict[str, Any],
    season: str,
    *,
    calendar_year: bool = False,
) -> bool:
    day = _parse_iso_date(row.get("date") or row.get("scheduled_date"))
    if not day:
        return False
    start, end = _season_bounds(season, calendar_year=calendar_year)
    return start <= day <= end


def _filter_fixtures_to_season(
    fixtures: list[dict[str, Any]],
    season: str,
    *,
    calendar_year: bool = False,
) -> list[dict[str, Any]]:
    return [
        row
        for row in fixtures
        if _fixture_in_season(row, season, calendar_year=calendar_year)
    ]


def _league_coverage(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted(
        day
        for row in fixtures
        if (day := _parse_iso_date(row.get("date") or row.get("scheduled_date")))
    )
    if not dates:
        return {"first_date": None, "last_date": None, "fixture_count": 0}
    return {
        "first_date": dates[0],
        "last_date": dates[-1],
        "fixture_count": len(fixtures),
    }


def _safe_int(value: Any, default: int = 0) -> int:
    token = str(value or "").strip()
    if not token:
        return default
    match = re.search(r"\d+", token)
    return int(match.group(0)) if match else default


def _normalize_team_name(name: str) -> str:
    value = str(name or "").strip().casefold()
    value = value.replace("&", "and")
    value = re.sub(r"\bfc\b", "", value)
    value = re.sub(r"\bafc\b", "", value)
    value = re.sub(r"\bcf\b", "", value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return TEAM_ALIASES.get(value, value)


def _fixture_day(value: str | None) -> str:
    return _parse_iso_date(value) or ""


def _days_between(left: str | None, right: str | None) -> int:
    left_day = _fixture_day(left)
    right_day = _fixture_day(right)
    if not left_day or not right_day:
        return 999
    left_date = datetime.strptime(left_day, "%Y-%m-%d").date()
    right_date = datetime.strptime(right_day, "%Y-%m-%d").date()
    return abs((left_date - right_date).days)


def _teams_pair_key(home: str, away: str) -> str:
    return f"{_normalize_team_name(home)}|{_normalize_team_name(away)}"


def _row_source_priority(row: dict[str, Any]) -> int:
    sources = row.get("sources") or []
    if not sources:
        return 0
    return max(SOURCE_PRIORITY.get(str(source), 0) for source in sources)


def _parse_kickoff_utc(value: Any) -> datetime | None:
    token = str(value or "").strip()
    if not token or "T" not in token:
        return None
    try:
        stamp = datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.astimezone(UTC)


def _is_placeholder_kickoff(value: Any, *, cup: bool | None = None) -> bool:
    """True when a source stamped a date with a fake kick-off time.

    FotMob often uses 12:00–14:00Z on midweek *cup* ties before real KOs are
    published — that shows as 13:00–15:00 UK and looks like a confirmed 3pm.
    Saturday/Sunday 14:00Z (traditional 3pm) is left alone, as is Monday
    (Bank Holiday 15:00 UK is a real league kick-off).
    League competitions are never treated as midday placeholders.
    """
    stamp = _parse_kickoff_utc(value)
    if stamp is None:
        token = str(value or "").strip()
        return not token or "T" not in token
    minute = stamp.minute
    hour = stamp.hour
    # Midnight-ish UTC dumps.
    if minute == 0 and hour in (0, 22, 23):
        return True
    if cup is False:
        return False
    # Tue–Fri midday UTC placeholders (classic 14:00Z → 15:00 UK on cup rounds).
    if stamp.weekday() in (1, 2, 3, 4) and minute == 0 and hour in (12, 13, 14):
        return True
    return False


def _kickoff_time_quality(value: Any) -> int:
    """Rank how likely an ISO kickoff is a real time vs a date-only placeholder.

    Impect often stores unknown kickoffs as 22:00Z / 23:00Z (shows as 23:00/00:00 UK).
    FotMob/BBC carry the actual 15:00 etc — prefer those when merging.
    """
    token = str(value or "").strip()
    if not token:
        return 0
    if "T" not in token:
        return 1
    if _is_placeholder_kickoff(token):
        return 2
    try:
        time_part = token.split("T", 1)[1]
        hour = int(time_part[0:2])
        minute = int(time_part[3:5]) if len(time_part) >= 5 and time_part[2] == ":" else 0
    except (TypeError, ValueError):
        return 0
    if minute in (15, 45):
        return 8
    if minute in (0, 30):
        return 6
    return 5


def _prefer_kickoff_value(
    current: Any,
    incoming: Any,
    *,
    current_priority: int,
    incoming_priority: int,
) -> Any:
    current_q = _kickoff_time_quality(current)
    incoming_q = _kickoff_time_quality(incoming)
    if incoming_q > current_q:
        return incoming or current
    if incoming_q < current_q:
        return current or incoming
    if incoming_priority >= current_priority and incoming:
        return incoming
    return current or incoming


def _prefer_display_name(current: str, incoming: str) -> str:
    """Prefer the shorter same-club label (Celtic over Celtic Glasgow)."""
    current_name = str(current or "").strip()
    incoming_name = str(incoming or "").strip()
    if not current_name:
        return incoming_name
    if not incoming_name:
        return current_name
    if _team_names_same_club(current_name, incoming_name):
        return current_name if len(current_name) <= len(incoming_name) else incoming_name
    if len(incoming_name) > len(current_name):
        return incoming_name
    return current_name


def _fixture_key(home: str, away: str, scheduled_date: str | None) -> str:
    day = _fixture_day(scheduled_date)
    return f"{_normalize_team_name(home)}|{_normalize_team_name(away)}|{day}"


def _fixture_id(league_ui: str, home: str, away: str, scheduled_date: str | None) -> str:
    return f"{league_ui}|{_fixture_key(home, away, scheduled_date)}"


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    token = str(value).strip()
    if len(token) >= 10:
        return token[:10]
    return None


def _match_is_complete(match: dict[str, Any]) -> bool:
    goals = match.get("goals") or {}
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    return home_ft is not None and away_ft is not None


def _match_day_index(match: dict[str, Any]) -> int:
    match_day = match.get("matchDay") or {}
    if isinstance(match_day, dict):
        return int(match_day.get("index") or 0)
    return int(match_day or 0)


def _score_label(match: dict[str, Any]) -> str | None:
    goals = match.get("goals") or {}
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    if home_ft is None or away_ft is None:
        return None
    return f"{home_ft}-{away_ft}"


def _unwrap_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "matches"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            if isinstance(nested, dict):
                return [item for item in nested.values() if isinstance(item, dict)]
    return []


def _squads_map(iteration_id: int) -> dict[int, dict[str, Any]]:
    impect = _impect()
    squads = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
    return {int(row["id"]): row for row in squads if row.get("id") is not None}


_iteration_squad_players_cache: dict[int, tuple[float, dict[int, list[dict[str, Any]]]]] = {}
_iteration_squad_players_lock = threading.Lock()
ITERATION_SQUAD_PLAYERS_CACHE_TTL_SECONDS = 30 * 60


def _players_by_squad_for_iteration(iteration_id: int) -> dict[int, list[dict[str, Any]]]:
    """Map squad_id -> [{player_id, player_name}] for one Impect iteration."""
    iid = int(iteration_id or 0)
    if not iid:
        return {}
    now = time.time()
    with _iteration_squad_players_lock:
        cached = _iteration_squad_players_cache.get(iid)
        if cached and now - cached[0] < ITERATION_SQUAD_PLAYERS_CACHE_TTL_SECONDS:
            return cached[1]

    impect = _impect()
    by_squad: dict[int, list[dict[str, Any]]] = {}
    try:
        players = impect._fetch_players_for_iteration(iid)
    except Exception:
        players = []
    for player in players:
        squad_id = impect._extract_squad_id_from_player(player)
        player_id = player.get("id")
        name = impect._extract_player_name(player)
        if squad_id is None or player_id is None or not name:
            continue
        by_squad.setdefault(int(squad_id), []).append(
            {
                "player_id": int(player_id),
                "player_name": name,
            }
        )
    for rows in by_squad.values():
        rows.sort(key=lambda row: str(row.get("player_name") or "").casefold())

    with _iteration_squad_players_lock:
        _iteration_squad_players_cache[iid] = (now, by_squad)
    return by_squad


def _resolve_squad_player_lists(
    squad_ids: list[int],
    *,
    preferred_iteration_id: int | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Load Impect squad lists, falling back across recent seasons when the
    preferred iteration has not been populated yet (common early in a season).

    Prefers the richest squad list found for each club (e.g. Port Vale from
    last season's League One rather than a thin League Two snapshot).
    """
    wanted = [int(sid) for sid in squad_ids if int(sid or 0)]
    result: dict[int, list[dict[str, Any]]] = {sid: [] for sid in wanted}
    if not wanted:
        return result

    def _consider(by_squad: dict[int, list[dict[str, Any]]]) -> None:
        for sid in wanted:
            rows = by_squad.get(sid) or []
            if len(rows) > len(result.get(sid) or []):
                result[sid] = rows

    if preferred_iteration_id:
        _consider(_players_by_squad_for_iteration(int(preferred_iteration_id)))

    # Already have a decent list for every squad from the preferred iteration.
    if preferred_iteration_id and all(len(result.get(sid) or []) >= 12 for sid in wanted):
        return result

    impect = _impect()
    candidates: list[dict[str, Any]] = []
    for item in impect._fetch_iterations():
        season = str(item.get("season") or "").strip()
        if season not in ALLOWED_FIXTURE_SEASONS:
            continue
        iid = int(item.get("id") or 0)
        if not iid or iid == int(preferred_iteration_id or 0):
            continue
        candidates.append(item)
    season_rank = {season: idx for idx, season in enumerate(ALLOWED_FIXTURE_SEASONS)}
    candidates.sort(
        key=lambda row: (
            season_rank.get(str(row.get("season") or ""), 99),
            -int(row.get("id") or 0),
        )
    )
    for item in candidates:
        _consider(_players_by_squad_for_iteration(int(item["id"])))
        if all(len(result.get(sid) or []) >= 12 for sid in wanted):
            break
    return result


_fotmob_squad_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_fotmob_squad_cache_lock = threading.Lock()
FOTMOB_SQUAD_CACHE_TTL_SECONDS = 6 * 60 * 60


def _fetch_fotmob_team_squad(fotmob_team_id: str | int | None) -> list[dict[str, Any]]:
    """Current FotMob club squad — preferred after transfer windows over stale Impect lists."""
    token = str(fotmob_team_id or "").strip()
    if not token.isdigit():
        return []
    now = time.time()
    with _fotmob_squad_cache_lock:
        cached = _fotmob_squad_cache.get(token)
        if cached and now - cached[0] < FOTMOB_SQUAD_CACHE_TTL_SECONDS:
            return list(cached[1])

    try:
        response = _http.get(
            "https://www.fotmob.com/api/data/teams",
            params={"id": token},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
    except requests.RequestException:
        return []
    if not response.ok:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []

    groups = ((payload.get("squad") or {}).get("squad") or [])
    players: list[dict[str, Any]] = []
    seen: set[int] = set()
    for group in groups:
        title = str(group.get("title") or "").strip().casefold()
        if title in {"coach", "staff"}:
            continue
        for member in group.get("members") or []:
            if not isinstance(member, dict):
                continue
            player_id = int(member.get("id") or 0)
            name = str(member.get("name") or "").strip()
            if not player_id or not name or player_id in seen:
                continue
            seen.add(player_id)
            role = member.get("role") if isinstance(member.get("role"), dict) else {}
            players.append(
                {
                    "player_id": player_id,
                    "player_name": name,
                    "fotmob_id": player_id,
                    "source": "fotmob",
                    "position": str(role.get("fallback") or role.get("key") or "").strip() or None,
                    "shirt_number": member.get("shirtNumber"),
                }
            )
    players.sort(key=lambda row: str(row.get("player_name") or "").casefold())
    with _fotmob_squad_cache_lock:
        _fotmob_squad_cache[token] = (now, players)
    return list(players)


def _side_fotmob_team_id(side: dict[str, Any] | None) -> str | None:
    side = side or {}
    token = str(side.get("fotmob_id") or "").strip()
    if token.isdigit():
        return token
    return None


def _iteration_for_competition(competition: str, season: str) -> dict[str, Any] | None:
    impect = _impect()
    target_season = str(season or DEFAULT_SEASON).strip()
    matches: list[dict[str, Any]] = []
    for item in impect._fetch_iterations():
        if str(item.get("competition_name", "")).strip() != competition:
            continue
        if str(item.get("season", "")).strip() == target_season:
            matches.append(item)
    if not matches:
        return None
    matches.sort(key=lambda row: int(row.get("id") or 0), reverse=True)
    return matches[0]


def _fetch_impect_fixtures(
    iteration_id: int,
    *,
    league_ui: str,
    competition: str,
    season: str,
) -> list[dict[str, Any]]:
    impect = _impect()
    try:
        squads = _squads_map(iteration_id)
        matches = _unwrap_items(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
            )["data"]
        )
    except HTTPException:
        return []
    fixtures: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        home = squads.get(home_id, {})
        away = squads.get(away_id, {})
        home_name = str(home.get("name") or f"Squad {home_id}")
        away_name = str(away.get("name") or f"Squad {away_id}")
        scheduled_date = match.get("scheduledDate")
        fixtures.append(
            {
                "match_id": int(match_id),
                "iteration_id": iteration_id,
                "league": league_ui,
                "competition": competition,
                "season": season,
                "match_day": _match_day_index(match),
                "scheduled_date": scheduled_date,
                "date": _parse_iso_date(scheduled_date),
                "kickoff_utc": scheduled_date,
                "home": {
                    "id": home_id,
                    "name": home_name,
                    "image_url": home.get("imageUrl"),
                },
                "away": {
                    "id": away_id,
                    "name": away_name,
                    "image_url": away.get("imageUrl"),
                },
                "status": "completed" if _match_is_complete(match) else "scheduled",
                "score": _score_label(match),
                "sources": ["impect"],
                "source_ids": {"impect": int(match_id)},
            }
        )
    fixtures.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            int(row.get("match_day") or 0),
            str(row.get("kickoff_utc") or ""),
        )
    )
    return fixtures


def _fetch_fotmob_fixtures(
    fotmob_id: int,
    *,
    league_ui: str,
    season: str,
    calendar_year: bool = False,
) -> list[dict[str, Any]]:
    fotmob_season = _season_to_fotmob(season, calendar_year=calendar_year)
    response = _http.get(
        "https://www.fotmob.com/api/data/leagues",
        params={"id": fotmob_id, "season": fotmob_season},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    if not response.ok:
        return []
    payload = response.json()
    matches = (payload.get("fixtures") or {}).get("allMatches") or []
    fixtures: list[dict[str, Any]] = []
    for match in matches:
        home = match.get("home") or {}
        away = match.get("away") or {}
        home_name = str(home.get("name") or "")
        away_name = str(away.get("name") or "")
        status = match.get("status") or {}
        kickoff = status.get("utcTime")
        fixtures.append(
            {
                "league": league_ui,
                "season": season,
                "match_day": _safe_int(match.get("round") or match.get("roundName")),
                "round": str(match.get("round") or "").strip() or None,
                "round_name": str(match.get("roundName") or match.get("round") or "").strip() or None,
                "scheduled_date": kickoff,
                "date": _parse_iso_date(kickoff),
                "kickoff_utc": kickoff,
                "home": {
                    "name": home_name,
                    "fotmob_id": str(home.get("id") or "").strip() or None,
                },
                "away": {
                    "name": away_name,
                    "fotmob_id": str(away.get("id") or "").strip() or None,
                },
                "status": "completed" if status.get("finished") else "scheduled",
                "score": str(status.get("scoreStr") or "").strip() or None,
                "home_score": _fotmob_side_score(home, status.get("scoreStr"), which="home"),
                "away_score": _fotmob_side_score(away, status.get("scoreStr"), which="away"),
                "sources": ["fotmob"],
                "source_ids": {"fotmob": str(match.get("id") or "")},
                "fotmob_page_url": str(match.get("pageUrl") or "").strip() or None,
            }
        )
    return fixtures


def _score_pair(score_str: Any) -> tuple[int | None, int | None]:
    text = str(score_str or "").strip()
    if not text or "-" not in text:
        return None, None
    left, right = [part.strip() for part in text.split("-", 1)]
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def _fotmob_side_score(team_row: Any, score_str: Any, *, which: str) -> int | None:
    if isinstance(team_row, dict) and team_row.get("score") is not None:
        try:
            return int(team_row["score"])
        except (TypeError, ValueError):
            pass
    home_score, away_score = _score_pair(score_str)
    return home_score if which == "home" else away_score


def _parse_bbc_initial_data(html: str) -> list[dict[str, Any]]:
    match = re.search(r'window\.__INITIAL_DATA__="(.+?)";', html, re.S)
    if not match:
        return []
    raw = match.group(1).encode("utf-8").decode("unicode_escape")
    payload = json.loads(raw)
    data_block = payload.get("data") or {}
    key = next(
        (name for name in data_block if str(name).startswith("sport-data-scores-fixtures")),
        None,
    )
    if not key:
        return []
    groups = (data_block[key].get("data") or {}).get("eventGroups") or []
    events: list[dict[str, Any]] = []
    for group in groups:
        for secondary in group.get("secondaryGroups") or []:
            group_round = str(secondary.get("displayLabel") or "").strip()
            for event in secondary.get("events") or []:
                if not isinstance(event, dict):
                    continue
                stage = event.get("stage") if isinstance(event.get("stage"), dict) else {}
                round_label = str(stage.get("name") or group_round or "").strip()
                row = dict(event)
                row["_round_label"] = round_label
                events.append(row)
    return events


def _is_fa_cup_qualifier_round(round_label: Any) -> bool:
    """True for Extra Preliminary / Preliminary / Qualifying rounds (not 1st Round Proper)."""
    text = str(round_label or "").strip().casefold()
    if not text:
        return False
    if "qualif" in text:
        return True
    if "preliminary" in text:
        return True
    return False


def _fetch_bbc_fixtures(
    bbc_path: str,
    *,
    league_ui: str,
    season: str,
    calendar_year: bool = False,
) -> list[dict[str, Any]]:
    if not bbc_path:
        return []
    fixtures: list[dict[str, Any]] = []
    months = _bbc_months_for_season(season, calendar_year=calendar_year)
    for month in months:
        url = f"https://www.bbc.co.uk/sport/football/{bbc_path}/scores-fixtures/{month}"
        try:
            response = _http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        except requests.RequestException:
            continue
        if not response.ok:
            continue
        for event in _parse_bbc_initial_data(response.text):
            round_label = str(event.get("_round_label") or "").strip()
            if league_ui == "FA Cup" and _is_fa_cup_qualifier_round(round_label):
                continue
            home = event.get("home") or {}
            away = event.get("away") or {}
            home_name = str(home.get("fullName") or home.get("shortName") or "")
            away_name = str(away.get("fullName") or away.get("shortName") or "")
            kickoff = event.get("startDateTime") or (event.get("date") or {}).get("iso")
            fixtures.append(
                {
                    "league": league_ui,
                    "season": season,
                    "match_day": 0,
                    "round": round_label or None,
                    "round_name": round_label or None,
                    "scheduled_date": kickoff,
                    "date": _parse_iso_date(kickoff),
                    "kickoff_utc": kickoff,
                    "home": {"name": home_name},
                    "away": {"name": away_name},
                    "status": "scheduled",
                    "score": None,
                    "sources": ["bbc"],
                    "source_ids": {"bbc": str(event.get("id") or "")},
                }
            )
    return fixtures


def _fetch_transfermarkt_fixtures(
    competition_id: str,
    *,
    league_ui: str,
    season: str,
    slug: str,
    calendar_year: bool = False,
) -> list[dict[str, Any]]:
    saison_id = _season_to_transfermarkt(season, calendar_year=calendar_year)
    url = (
        f"https://www.transfermarkt.co.uk/{slug}/spielplan/wettbewerb/"
        f"{competition_id}/saison_id/{saison_id}/plus/1"
    )
    try:
        response = _http.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=20,
        )
    except requests.RequestException:
        return []
    if not response.ok or "spieltagsbox" not in response.text:
        return []

    fixtures: list[dict[str, Any]] = []
    matchday_blocks = re.findall(
        r'<div class="box"><h2 class="content-box-headline">(Matchday \d+)</h2>(.*?)</table>',
        response.text,
        re.S,
    )
    for matchday_label, block in matchday_blocks:
        match_day = int(re.search(r"\d+", matchday_label).group(0)) if re.search(r"\d+", matchday_label) else 0
        rows = re.findall(
            r'<td class="zentriert hauptlink">\s*(\d{2}\.\d{2}\.)</td>.*?'
            r'<td class="hauptlink no-border-links"><a[^>]*title="([^"]+)"[^>]*>.*?</td>.*?'
            r'<td class="zentriert hauptlink"><a[^>]*title="([^"]+)"',
            block,
            re.S,
        )
        for date_token, home_name, away_name in rows:
            day, month, _ = date_token.split(".")
            year = saison_id if int(month) >= 7 else saison_id + 1
            date_iso = f"{year:04d}-{int(month):02d}-{int(day):02d}"
            fixtures.append(
                {
                    "league": league_ui,
                    "season": season,
                    "match_day": match_day,
                    "scheduled_date": f"{date_iso}T15:00:00Z",
                    "date": date_iso,
                    "kickoff_utc": f"{date_iso}T15:00:00Z",
                    "home": {"name": home_name.strip()},
                    "away": {"name": away_name.strip()},
                    "status": "scheduled",
                    "score": None,
                    "sources": ["transfermarkt"],
                    "source_ids": {"transfermarkt": f"{date_iso}:{home_name}:{away_name}"},
                }
            )
    return fixtures


def _merge_fixture_sources(
    primary: list[dict[str, Any]],
    *supplemental_lists: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _find_existing_key(row: dict[str, Any]) -> str | None:
        home_name = str((row.get("home") or {}).get("name") or "")
        away_name = str((row.get("away") or {}).get("name") or "")
        row_day = _fixture_day(row.get("date") or row.get("scheduled_date"))
        exact_key = _fixture_key(home_name, away_name, row_day)
        if exact_key in merged:
            return exact_key

        for key in order:
            existing = merged[key]
            existing_home = str((existing.get("home") or {}).get("name") or "")
            existing_away = str((existing.get("away") or {}).get("name") or "")
            existing_day = _fixture_day(existing.get("date") or existing.get("scheduled_date"))
            if _days_between(row_day, existing_day) > FIXTURE_DATE_MATCH_TOLERANCE_DAYS:
                continue
            if _fixture_sides_match(existing_home, existing_away, home_name, away_name):
                return key
        return None

    def _combine_rows(existing: dict[str, Any], row: dict[str, Any]) -> None:
        for source in row.get("sources") or []:
            if source not in existing["sources"]:
                existing["sources"].append(source)
        existing["source_ids"].update(row.get("source_ids") or {})

        existing_home = existing.setdefault("home", {})
        existing_away = existing.setdefault("away", {})
        row_home = row.get("home") or {}
        row_away = row.get("away") or {}
        existing_home["name"] = _prefer_display_name(existing_home.get("name"), row_home.get("name"))
        existing_away["name"] = _prefer_display_name(existing_away.get("name"), row_away.get("name"))

        incoming_priority = _row_source_priority(row)
        existing_priority = _row_source_priority(existing)
        preferred_kickoff = _prefer_kickoff_value(
            existing.get("kickoff_utc") or existing.get("scheduled_date"),
            row.get("kickoff_utc") or row.get("scheduled_date"),
            current_priority=existing_priority,
            incoming_priority=incoming_priority,
        )
        if preferred_kickoff:
            existing["kickoff_utc"] = preferred_kickoff
            existing["scheduled_date"] = preferred_kickoff
            existing["date"] = _parse_iso_date(str(preferred_kickoff)) or existing.get("date")
        elif incoming_priority >= existing_priority:
            for field in ("date", "scheduled_date", "kickoff_utc"):
                if row.get(field):
                    existing[field] = row[field]
        else:
            for field in ("date", "scheduled_date", "kickoff_utc"):
                if not existing.get(field) and row.get(field):
                    existing[field] = row[field]

        if not existing.get("score") and row.get("score"):
            existing["score"] = row["score"]
        if existing.get("status") != "completed" and row.get("status") == "completed":
            existing["status"] = "completed"
        for field in ("match_id", "iteration_id"):
            if row.get(field) and not existing.get(field):
                existing[field] = row[field]
        if row.get("fotmob_page_url"):
            existing["fotmob_page_url"] = row["fotmob_page_url"]
        for field in ("round", "round_name"):
            if row.get(field) and (
                not existing.get(field)
                or (
                    isinstance(row.get(field), str)
                    and len(str(row.get(field))) > len(str(existing.get(field) or ""))
                )
            ):
                existing[field] = row[field]
        for side in ("home", "away"):
            row_side = row.get(side) or {}
            existing_side = existing.setdefault(side, {})
            if row_side.get("id") and not existing_side.get("id"):
                existing_side["id"] = row_side["id"]
            if row_side.get("fotmob_id") and not existing_side.get("fotmob_id"):
                existing_side["fotmob_id"] = row_side["fotmob_id"]
            if row_side.get("image_url") and not existing_side.get("image_url"):
                existing_side["image_url"] = row_side["image_url"]
            if row_side.get("name") and not existing_side.get("name"):
                existing_side["name"] = row_side["name"]

    def ingest(row: dict[str, Any]) -> None:
        home_name = str((row.get("home") or {}).get("name") or "")
        away_name = str((row.get("away") or {}).get("name") or "")
        row_day = _fixture_day(row.get("date") or row.get("scheduled_date"))
        key = _find_existing_key(row)
        if key is None:
            key = _fixture_key(home_name, away_name, row_day)
            merged[key] = {
                **row,
                "sources": list(row.get("sources") or []),
                "source_ids": dict(row.get("source_ids") or {}),
            }
            order.append(key)
            return
        _combine_rows(merged[key], row)

    for row in primary:
        ingest(row)
    for supplemental in supplemental_lists:
        for row in supplemental:
            ingest(row)

    fixtures = [merged[key] for key in order]
    for row in fixtures:
        home_name = str((row.get("home") or {}).get("name") or "")
        away_name = str((row.get("away") or {}).get("name") or "")
        row["fixture_id"] = _fixture_id(
            str(row.get("league") or ""),
            home_name,
            away_name,
            row.get("date") or row.get("scheduled_date"),
        )
        row["source_count"] = len(row.get("sources") or [])
        row["verified"] = row["source_count"] >= 2
    fixtures.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("kickoff_utc") or ""),
            str(item.get("league") or ""),
        )
    )
    return fixtures


def _attach_impect_metadata(
    fixtures: list[dict[str, Any]],
    impect_fixtures: list[dict[str, Any]],
    *,
    iteration_id: int | None,
) -> int:
    """Keep FotMob fixture rows, but attach Impect match/squad IDs for popup enrichment."""
    if iteration_id:
        for row in fixtures:
            if not row.get("iteration_id"):
                row["iteration_id"] = iteration_id

    unused = list(impect_fixtures)
    linked = 0
    for row in fixtures:
        home_name = str((row.get("home") or {}).get("name") or "")
        away_name = str((row.get("away") or {}).get("name") or "")
        row_day = _fixture_day(row.get("date") or row.get("scheduled_date") or row.get("kickoff_utc"))
        best_idx: int | None = None
        for idx, impect_row in enumerate(unused):
            impect_home = str((impect_row.get("home") or {}).get("name") or "")
            impect_away = str((impect_row.get("away") or {}).get("name") or "")
            impect_day = _fixture_day(
                impect_row.get("date")
                or impect_row.get("scheduled_date")
                or impect_row.get("kickoff_utc")
            )
            if _days_between(row_day, impect_day) > FIXTURE_DATE_MATCH_TOLERANCE_DAYS:
                continue
            if not _fixture_sides_match(home_name, away_name, impect_home, impect_away):
                continue
            best_idx = idx
            break
        if best_idx is None:
            continue
        impect_row = unused.pop(best_idx)
        if impect_row.get("match_id"):
            row["match_id"] = impect_row["match_id"]
        row["iteration_id"] = impect_row.get("iteration_id") or iteration_id
        for side in ("home", "away"):
            impect_side = impect_row.get(side) or {}
            row_side = row.setdefault(side, {})
            if impect_side.get("id") is not None:
                row_side["id"] = impect_side["id"]
            if impect_side.get("image_url") and not row_side.get("image_url"):
                row_side["image_url"] = impect_side["image_url"]
        linked += 1
    return linked


def _build_league_bundle(league_ui: str, season: str) -> dict[str, Any]:
    config = FIXTURE_LEAGUE_BY_UI.get(league_ui)
    if config is None:
        raise HTTPException(status_code=400, detail=f"Unknown league: {league_ui}")

    competition = str(config["competition"])
    calendar_year = bool(config.get("calendar_year"))
    source_season = (
        _calendar_year_for_season(season) if calendar_year else season
    )
    iteration = _iteration_for_competition(competition, source_season)
    impect_fixtures: list[dict[str, Any]] = []
    iteration_id = None
    if iteration is not None:
        iteration_id = int(iteration["id"])
        # Impect is only used to resolve match/squad IDs for enrichment popups —
        # fixture list + kickoff times come from FotMob alone.
        impect_fixtures = _fetch_impect_fixtures(
            iteration_id,
            league_ui=league_ui,
            competition=competition,
            season=season,
        )

    fotmob_fixtures: list[dict[str, Any]] = []
    if config.get("fotmob_id") is not None:
        fotmob_fixtures = _fetch_fotmob_fixtures(
            int(config["fotmob_id"]),
            league_ui=league_ui,
            season=season,
            calendar_year=calendar_year,
        )

    pulse_fixtures: list[dict[str, Any]] = []
    if config.get("pulse_competition_id") is not None:
        pulse_fixtures = _fetch_pulse_fixtures(
            int(config["pulse_competition_id"]),
            league_ui=league_ui,
            season=season,
        )

    # Prefer Pulse when configured and non-empty (better Vertu / PDL / PL Cup coverage).
    source_fixtures = pulse_fixtures if pulse_fixtures else fotmob_fixtures
    filtered = _filter_fixtures_to_season(
        source_fixtures,
        season,
        calendar_year=calendar_year,
    )
    if league_ui == "FA Cup":
        filtered = [
            row
            for row in filtered
            if not _is_fa_cup_qualifier_round(row.get("round") or row.get("round_name"))
        ]

    linked = _attach_impect_metadata(
        filtered,
        impect_fixtures,
        iteration_id=iteration_id,
    )
    primary_source = "pulse" if source_fixtures is pulse_fixtures else "fotmob"
    for row in filtered:
        sources = [primary_source]
        if row.get("match_id"):
            sources.append("impect")
        row["sources"] = sources
        row["source_count"] = len(sources)
        row["verified"] = bool(row.get("match_id"))
        row["kickoff_tbc"] = _is_placeholder_kickoff(
            row.get("kickoff_utc") or row.get("scheduled_date"),
            cup=bool(config.get("cup")),
        )
        row["fixture_id"] = _fixture_id(
            str(row.get("league") or league_ui),
            str((row.get("home") or {}).get("name") or ""),
            str((row.get("away") or {}).get("name") or ""),
            row.get("date") or row.get("scheduled_date") or row.get("kickoff_utc"),
        )

    if config.get("cup"):
        for row in filtered:
            row["cup"] = True
            row["competition"] = competition

    return {
        "league": league_ui,
        "competition": competition,
        "season": season,
        "iteration_id": iteration_id,
        "counts": {
            "impect": len(impect_fixtures),
            "impect_linked": linked,
            "fotmob": len(fotmob_fixtures),
            "pulse": len(pulse_fixtures),
            "bbc": 0,
            "merged": len(filtered),
            "verified": sum(1 for row in filtered if row.get("verified")),
            "dropped_out_of_season": max(0, len(source_fixtures) - len(filtered)),
        },
        "coverage": _league_coverage(filtered),
        "fixtures": filtered,
    }


def fixture_planner_meta() -> dict[str, Any]:
    allowed = list(ALLOWED_FIXTURE_SEASONS)
    return {
        "season": DEFAULT_SEASON,
        "seasons": allowed,
        "staff": list(FIXTURE_STAFF),
        "staff_teams": [
            {
                "id": team["id"],
                "label": team["label"],
                "members": list(team["members"]),
            }
            for team in FIXTURE_STAFF_TEAMS
        ],
        "watch_types": list(WATCH_TYPES),
        "leagues": [
            {
                "ui": row["ui"],
                "competition": row["competition"],
                "color": row["color"],
                "seasons": allowed,
            }
            for row in FIXTURE_LEAGUES
        ],
        "germany": [
            {
                "ui": row["ui"],
                "competition": row["competition"],
                "color": row["color"],
                "seasons": allowed,
            }
            for row in FIXTURE_GERMANY_LEAGUES
        ],
        "germany_uis": list(FIXTURE_GERMANY_UIS),
        "cups": [
            {
                "ui": row["ui"],
                "competition": row["competition"],
                "color": row["color"],
                "seasons": allowed,
            }
            for row in FIXTURE_CUPS
        ],
        "cup_uis": list(FIXTURE_CUP_UIS),
        "default_leagues": FIXTURE_LEAGUE_UIS,
        "default_germany": FIXTURE_GERMANY_UIS,
        "sources": ["fotmob", "pulse", "impect"],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def clear_fixture_planner_cache(season: str | None = None) -> None:
    with _fixture_cache_lock:
        if not season:
            _fixture_cache.clear()
            return
        prefix = f"{FIXTURE_CACHE_VERSION}:{season}"
        for key in list(_fixture_cache.keys()):
            if key == prefix or key.endswith(f":{season}"):
                _fixture_cache.pop(key, None)


def _disk_fixture_cache_path(season: str) -> Path:
    safe = str(season).replace("/", "-")
    return ASSIGNMENTS_DIR / f"fixtures-cache-{FIXTURE_CACHE_VERSION}-{safe}.json"


def _store_memory_fixture_cache(season: str, saved_at: float, payload: dict[str, Any]) -> None:
    cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
    with _fixture_cache_lock:
        _fixture_cache[cache_key] = (saved_at, payload)


def _load_disk_fixture_cache(season: str) -> tuple[float, dict[str, Any]] | None:
    path = _disk_fixture_cache_path(season)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or str(data.get("version") or "") != FIXTURE_CACHE_VERSION:
        return None
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    try:
        saved_at = float(data.get("saved_at") or 0)
    except (TypeError, ValueError):
        return None
    if saved_at <= 0:
        return None
    return saved_at, payload


def _save_disk_fixture_cache(season: str, payload: dict[str, Any]) -> None:
    path = _disk_fixture_cache_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {
        "version": FIXTURE_CACHE_VERSION,
        "season": season,
        "saved_at": time.time(),
        "payload": payload,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _schedule_fixture_rebuild(season: str) -> None:
    with _fixture_rebuild_lock:
        if season in _fixture_rebuild_pending:
            return
        _fixture_rebuild_pending.add(season)

    def _run() -> None:
        try:
            build_fixture_planner_payload(season=season, force_refresh=True)
        except Exception:
            logger.exception("Background fixture rebuild failed for %s", season)
        finally:
            with _fixture_rebuild_lock:
                _fixture_rebuild_pending.discard(season)

    threading.Thread(target=_run, daemon=True, name=f"fixture-rebuild-{season}").start()


def _cached_payload_for_season(season: str) -> tuple[float, dict[str, Any]] | None:
    cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
    with _fixture_cache_lock:
        cached = _fixture_cache.get(cache_key)
    if cached:
        return cached
    disk = _load_disk_fixture_cache(season)
    if not disk:
        return None
    saved_at, payload = disk
    _store_memory_fixture_cache(season, saved_at, payload)
    return saved_at, payload


def _compute_fixture_planner_payload(season: str) -> dict[str, Any]:
    selected = list(FIXTURE_LEAGUE_UIS) + list(FIXTURE_GERMANY_UIS) + list(FIXTURE_CUP_UIS)
    bundles = [_build_league_bundle(league_ui, season) for league_ui in selected]
    fixtures = [fixture for bundle in bundles for fixture in bundle["fixtures"]]
    fixtures.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
            str(row.get("league") or ""),
        )
    )
    return {
        "season": season,
        "leagues": list(FIXTURE_LEAGUE_UIS),
        "germany": list(FIXTURE_GERMANY_UIS),
        "cups": list(FIXTURE_CUP_UIS),
        "fixtures": fixtures,
        "bundles": [
            {
                "league": bundle["league"],
                "competition": bundle["competition"],
                "iteration_id": bundle["iteration_id"],
                "counts": bundle["counts"],
                "coverage": bundle["coverage"],
            }
            for bundle in bundles
        ],
        "coverage": {bundle["league"]: bundle["coverage"] for bundle in bundles},
        "summary": {
            "total_fixtures": len(fixtures),
            "verified_fixtures": sum(1 for row in fixtures if row.get("verified")),
            "by_league": {bundle["league"]: bundle["counts"]["merged"] for bundle in bundles},
            "by_source": {
                "fotmob": sum(bundle["counts"]["fotmob"] for bundle in bundles),
                "impect_linked": sum(bundle["counts"].get("impect_linked", 0) for bundle in bundles),
                "impect": sum(bundle["counts"]["impect"] for bundle in bundles),
                "bbc": 0,
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _upcoming_only_payload(payload: dict[str, Any]) -> dict[str, Any]:
    today = datetime.now(UTC).date()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=45)).isoformat()
    merged = dict(payload)
    merged["fixtures"] = [
        row
        for row in payload.get("fixtures") or []
        if row.get("manual")
        or start <= str(row.get("date") or "")[:10] <= end
    ]
    return merged


def build_fixture_planner_payload(
    *,
    season: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if season not in ALLOWED_FIXTURE_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
        )

    now = time.time()
    cached = _cached_payload_for_season(season)
    if cached and now - cached[0] < FIXTURE_CACHE_STALE_SECONDS:
        if force_refresh or now - cached[0] >= FIXTURE_CACHE_TTL_SECONDS:
            _schedule_fixture_rebuild(season)
        return _finalize_fixture_payload(cached[1], season=season)

    with _fixture_compute_lock:
        cached = _cached_payload_for_season(season)
        if cached and now - cached[0] < FIXTURE_CACHE_STALE_SECONDS:
            return _finalize_fixture_payload(cached[1], season=season)
        payload = _compute_fixture_planner_payload(season)
        saved_at = time.time()
        _store_memory_fixture_cache(season, saved_at, payload)
        try:
            _save_disk_fixture_cache(season, payload)
        except OSError:
            logger.exception("Could not write fixture disk cache for %s", season)
        return _finalize_fixture_payload(payload, season=season)


def _load_assignments_store() -> dict[str, Any]:
    with _assignments_lock:
        if not ASSIGNMENTS_PATH.exists():
            return {"version": 1, "updated_at": None, "assignments": {}}
        try:
            payload = json.loads(ASSIGNMENTS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "updated_at": None, "assignments": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "updated_at": None, "assignments": {}}
        assignments = payload.get("assignments")
        if not isinstance(assignments, dict):
            payload["assignments"] = {}
        return payload


def _save_assignments_store(payload: dict[str, Any]) -> None:
    ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = 1
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = ASSIGNMENTS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(ASSIGNMENTS_PATH)
    _scout_ops_cache_clear()


def get_fixture_assignments() -> dict[str, Any]:
    store = _load_assignments_store()
    assignments: dict[str, Any] = {}
    for fixture_id, row in dict(store.get("assignments") or {}).items():
        if not isinstance(row, dict):
            continue
        cleaned = dict(row)
        cleaned["staff"] = _normalize_staff_names(cleaned.get("staff"))
        assignments[str(fixture_id)] = cleaned
    return {
        "assignments": assignments,
        "updated_at": store.get("updated_at"),
    }


def _load_ticket_requests_store() -> dict[str, Any]:
    with _ticket_requests_lock:
        if not TICKET_REQUESTS_PATH.exists():
            return {"version": 1, "updated_at": None, "requests": {}}
        try:
            payload = json.loads(TICKET_REQUESTS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "updated_at": None, "requests": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "updated_at": None, "requests": {}}
        requests_map = payload.get("requests")
        if not isinstance(requests_map, dict):
            payload["requests"] = {}
        return payload


def _save_ticket_requests_store(payload: dict[str, Any]) -> None:
    ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = 1
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = TICKET_REQUESTS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(TICKET_REQUESTS_PATH)


def get_ticket_requests() -> dict[str, Any]:
    store = _load_ticket_requests_store()
    requests_map = dict(store.get("requests") or {})
    today = datetime.now(UTC).date().isoformat()
    pruned: dict[str, Any] = {}
    for key, value in requests_map.items():
        if not isinstance(value, dict):
            continue
        day = str(value.get("date") or "").strip()[:10]
        if not day:
            parts = str(key or "").split("|")
            day = parts[-1][:10] if parts else ""
        if day and day < today:
            continue
        pruned[key] = value
    if len(pruned) != len(requests_map):
        store["requests"] = pruned
        _save_ticket_requests_store(store)
    return {
        "requests": pruned,
        "updated_at": store.get("updated_at"),
    }


def mark_ticket_requests_sent(rows: list[dict[str, Any]]) -> dict[str, Any]:
    store = _load_ticket_requests_store()
    requests_map = dict(store.get("requests") or {})
    now = datetime.now(UTC).isoformat()
    for row in rows:
        fixture_id = str(row.get("fixture_id") or "").strip()
        if not fixture_id:
            continue
        requests_map[fixture_id] = {
            "fixture_id": fixture_id,
            "requested_at": now,
            "home": row.get("home") or "",
            "away": row.get("away") or "",
            "league": row.get("league") or "",
            "date": str(row.get("date") or "")[:10],
            "staff": row.get("staff") or "",
            "watch_type": row.get("watch_type") or "LIVE",
            "kickoff_utc": row.get("kickoff_utc"),
            "tickets": row.get("tickets", 1),
            "parking": row.get("parking") or "No",
            "notes": row.get("notes") or "",
        }
    store["requests"] = requests_map
    _save_ticket_requests_store(store)
    return get_ticket_requests()


def _synthetic_player_id(name: str, team: str = "") -> int:
    raw = f"{str(name or '').strip().casefold()}|{str(team or '').strip().casefold()}"
    digest = zlib.crc32(raw.encode("utf-8")) & 0x7FFFFFFF
    # Negative IDs stay clear of Impect player IDs.
    return -digest if digest else -1


def _normalize_watched_players(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("player_name") or row.get("name") or "").strip()
        team = str(row.get("team") or "").strip()
        try:
            player_id = int(row.get("player_id") or 0)
        except (TypeError, ValueError):
            player_id = 0
        if not player_id and name:
            player_id = _synthetic_player_id(name, team)
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        cleaned.append(
            {
                "player_id": player_id,
                "player_name": name,
                "team": team,
                "side": str(row.get("side") or "").strip().lower(),
                "position": str(row.get("position") or "").strip(),
            }
        )
    cleaned.sort(
        key=lambda item: (
            0 if item.get("side") == "home" else 1 if item.get("side") == "away" else 2,
            str(item.get("player_name") or "").casefold(),
        )
    )
    return cleaned


def _watched_player_ids(rows: list[dict[str, Any]] | None) -> set[int]:
    ids: set[int] = set()
    for row in rows or []:
        try:
            player_id = int((row or {}).get("player_id") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if player_id:
            ids.add(player_id)
    return ids


def upsert_fixture_assignment(
    body: FixtureAssignmentUpdate,
    *,
    mirror_to_live: bool = True,
    send_email: bool = True,
) -> dict[str, Any]:
    store = _load_assignments_store()
    assignments: dict[str, Any] = store.setdefault("assignments", {})
    fixture_id = str(body.fixture_id or "").strip()
    if not fixture_id:
        raise HTTPException(status_code=400, detail="fixture_id is required")

    staff_names = _normalize_staff_names(body.staff, validate=True)
    watch_type = str(body.watch_type or "").strip().upper()
    if watch_type and watch_type not in WATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"watch_type must be one of: {', '.join(WATCH_TYPES)}")

    previous = dict(assignments.get(fixture_id) or {})
    previous_staff = _normalize_staff_names(previous.get("staff"))
    previous_staff_keys = {name.casefold() for name in previous_staff}
    previous_watch = str(previous.get("watch_type") or "").strip().upper()
    previous_players = _watched_player_ids(previous.get("watched_players") or [])
    watched_players = _normalize_watched_players(body.watched_players)

    if not staff_names and not watch_type:
        assignments.pop(fixture_id, None)
        saved_assignment: dict[str, Any] = {}
    else:
        saved_assignment = {
            "staff": staff_names,
            "watch_type": watch_type,
            "season": str(body.season or "").strip(),
            "league": str(body.league or "").strip(),
            "home": str(body.home or "").strip(),
            "away": str(body.away or "").strip(),
            "date": str(body.date or "").strip()[:10],
            "kickoff_utc": body.kickoff_utc,
            "watched_players": watched_players,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        assignments[fixture_id] = saved_assignment
    _save_assignments_store(store)

    if mirror_to_live:
        _mirror_assignment_to_live(fixture_id=fixture_id, assignment=saved_assignment)

    sheets_result: dict[str, Any] | None = None
    try:
        from app.fixture_sheets_backup import sync_assignment_to_sheet

        sheets_result = sync_assignment_to_sheet(fixture_id, saved_assignment or None)
    except Exception as exc:  # noqa: BLE001 - never fail assignment save on Sheets
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Sheets backup hook failed for %s", fixture_id)
        sheets_result = {"ok": False, "reason": str(exc)}

    email_result: dict[str, Any] | None = None
    added_staff = [name for name in staff_names if name.casefold() not in previous_staff_keys]
    coverage_changed = bool(
        staff_names
        and (
            (watch_type and watch_type != previous_watch)
            or _watched_player_ids(watched_players) != previous_players
        )
    )
    notify_targets = added_staff if added_staff else (staff_names if coverage_changed else [])
    if send_email and notify_targets:
        results = []
        for name in notify_targets:
            results.append(
                _notify_assignment_email(
                    fixture_id=fixture_id,
                    assignment=assignments.get(fixture_id) or {},
                    staff=name,
                )
            )
        sent = [row for row in results if row.get("sent")]
        if sent:
            email_result = {
                "sent": True,
                "to": ", ".join(str(row.get("to") or "") for row in sent if row.get("to")),
                "results": results,
            }
        else:
            email_result = {
                "sent": False,
                "reason": "; ".join(
                    str(row.get("reason") or "not sent") for row in results
                )
                or "No staff emails sent",
                "results": results,
            }

    payload = get_fixture_assignments()
    if email_result is not None:
        payload["email"] = email_result
    if sheets_result is not None:
        payload["sheets_backup"] = sheets_result
    return payload


def _title_from_slug(value: str) -> str:
    raw = str(value or "").replace("-", " ").replace("_", " ").strip()
    if not raw:
        return ""
    return " ".join(part.capitalize() for part in raw.split())


def _mirror_assignment_to_live(*, fixture_id: str, assignment: dict[str, Any]) -> None:
    """Keep the live hub assignment store in sync so reject links work for staff."""
    import os

    if str(os.getenv("FIXTURE_MIRROR_ASSIGNMENTS", "1") or "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return

    base = app_base_url().rstrip("/")
    if not base:
        return

    username = str(os.getenv("TEAM_USERNAME", "PortVale") or "PortVale").strip()
    password = str(os.getenv("TEAM_PASSWORD", "") or "").strip()
    if not password:
        return

    payload = {
        "fixture_id": fixture_id,
        "staff": _normalize_staff_names(assignment.get("staff")),
        "watch_type": str(assignment.get("watch_type") or ""),
        "season": str(assignment.get("season") or ""),
        "league": str(assignment.get("league") or ""),
        "home": str(assignment.get("home") or ""),
        "away": str(assignment.get("away") or ""),
        "date": str(assignment.get("date") or ""),
        "kickoff_utc": assignment.get("kickoff_utc"),
        "watched_players": list(assignment.get("watched_players") or []),
    }

    try:
        session = requests.Session()
        session.trust_env = False
        login = session.post(
            f"{base}/api/auth/login",
            json={"username": username, "password": password},
            timeout=12,
        )
        if login.status_code >= 400:
            return
        session.patch(
            f"{base}/api/fixture-planner/assignment",
            params={"mirror": "0"},
            json=payload,
            timeout=12,
        )
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Failed to mirror assignment %s to live hub", fixture_id)


def build_fixture_squads_payload(*, season: str, fixture_id: str) -> dict[str, Any]:
    if season not in ALLOWED_FIXTURE_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
        )
    fixture_token = str(fixture_id or "").strip()
    if not fixture_token:
        raise HTTPException(status_code=400, detail="fixture_id is required")

    fixture = None
    for row in _cached_fixtures_list([season], warm=True):
        if str(row.get("fixture_id") or "") == fixture_token:
            fixture = dict(row)
            break
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")

    home = dict(fixture.get("home") or {}) if isinstance(fixture.get("home"), dict) else {}
    away = dict(fixture.get("away") or {}) if isinstance(fixture.get("away"), dict) else {}
    home_id = int(home.get("id") or 0)
    away_id = int(away.get("id") or 0)
    iteration_id = int(fixture.get("iteration_id") or 0)

    # If FotMob row is missing Impect IDs (stale cache), try to attach them now.
    if not iteration_id or not (home_id and away_id):
        league_ui = str(fixture.get("league") or "").strip()
        competition = str(
            (FIXTURE_LEAGUE_BY_UI.get(league_ui) or {}).get("competition") or league_ui
        )
        iteration = _iteration_for_competition(competition, season)
        if iteration is not None:
            iteration_id = iteration_id or int(iteration["id"])
            try:
                impect_fixtures = _fetch_impect_fixtures(
                    int(iteration["id"]),
                    league_ui=league_ui or competition,
                    competition=competition,
                    season=season,
                )
            except Exception:
                impect_fixtures = []
            _attach_impect_metadata(
                [fixture],
                impect_fixtures,
                iteration_id=int(iteration["id"]),
            )
            home = dict(fixture.get("home") or {}) if isinstance(fixture.get("home"), dict) else home
            away = dict(fixture.get("away") or {}) if isinstance(fixture.get("away"), dict) else away
            home_id = int(home.get("id") or 0)
            away_id = int(away.get("id") or 0)
            iteration_id = int(fixture.get("iteration_id") or iteration_id or 0)

    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []
    squad_source = None

    # Prefer current FotMob squads (post-window accurate). Impect season lists are often empty
    # early in the year and last-season Impect lists go stale after the summer window.
    home_fm = _side_fotmob_team_id(home)
    away_fm = _side_fotmob_team_id(away)
    if home_fm:
        home_players = _fetch_fotmob_team_squad(home_fm)
    if away_fm:
        away_players = _fetch_fotmob_team_squad(away_fm)
    if home_players or away_players:
        squad_source = "fotmob"

    if not (home_players and away_players) and iteration_id and (home_id or away_id):
        by_squad = _resolve_squad_player_lists(
            [sid for sid in (home_id, away_id) if sid],
            preferred_iteration_id=iteration_id,
        )
        if not home_players:
            home_players = list(by_squad.get(home_id) or [])
        if not away_players:
            away_players = list(by_squad.get(away_id) or [])
        if (home_players or away_players) and squad_source is None:
            squad_source = "impect"

    available = bool(home_players or away_players)

    return {
        "fixture_id": fixture_token,
        "season": season,
        "league": fixture.get("league"),
        "date": fixture.get("date"),
        "kickoff_utc": fixture.get("kickoff_utc") or fixture.get("scheduled_date"),
        "iteration_id": iteration_id or None,
        "squad_source": squad_source,
        "available": available,
        "home": {
            "id": home_id or None,
            "fotmob_id": home_fm or home.get("fotmob_id"),
            "name": home.get("name") or "",
            "image_url": home.get("image_url"),
            "players": home_players,
        },
        "away": {
            "id": away_id or None,
            "fotmob_id": away_fm or away.get("fotmob_id"),
            "name": away.get("name") or "",
            "image_url": away.get("image_url"),
            "players": away_players,
        },
    }


def _resolve_fixture_for_email(fixture_id: str, assignment: dict[str, Any]) -> dict[str, Any]:
    seasons: list[str] = []
    season = str(assignment.get("season") or "").strip()
    if season in ALLOWED_FIXTURE_SEASONS:
        seasons = [season]
    else:
        seasons = list(ALLOWED_FIXTURE_SEASONS)

    for fixture in _cached_fixtures_list(seasons, warm=True):
        if str(fixture.get("fixture_id") or "") == fixture_id:
            return fixture

    return {
        "fixture_id": fixture_id,
        "league": assignment.get("league") or "",
        "home": {"name": assignment.get("home") or ""},
        "away": {"name": assignment.get("away") or ""},
        "date": assignment.get("date") or "",
        "kickoff_utc": assignment.get("kickoff_utc"),
    }


def _notify_assignment_email(
    *,
    fixture_id: str,
    assignment: dict[str, Any],
    staff: str | None = None,
) -> dict[str, Any]:
    staff_name = str(staff or "").strip() or (_normalize_staff_names(assignment.get("staff"))[:1] or [""])[0]
    if not staff_name:
        return {"sent": False, "reason": "No staff assigned"}

    try:
        fixture = _resolve_fixture_for_email(fixture_id, assignment)
        home = fixture.get("home") if isinstance(fixture.get("home"), dict) else {"name": fixture.get("home")}
        away = fixture.get("away") if isinstance(fixture.get("away"), dict) else {"name": fixture.get("away")}
        home_name = str((home or {}).get("name") or assignment.get("home") or "Home")
        away_name = str((away or {}).get("name") or assignment.get("away") or "Away")
        venue = None
        page_url = fixture.get("fotmob_page_url")
        if page_url:
            venue = _fotmob_venue_from_page(page_url)
        if not venue:
            venue = f"{home_name} (home)"

        return send_assignment_email(
            staff=staff_name,
            home=home_name,
            away=away_name,
            league=str(fixture.get("league") or assignment.get("league") or ""),
            watch_type=str(assignment.get("watch_type") or "LIVE"),
            kickoff_utc=str(fixture.get("kickoff_utc") or assignment.get("kickoff_utc") or "") or None,
            date_key=str(fixture.get("date") or assignment.get("date") or "") or None,
            venue=venue,
            home_badge_url=team_badge_url(home if isinstance(home, dict) else None),
            away_badge_url=team_badge_url(away if isinstance(away, dict) else None),
            watched_players=list(assignment.get("watched_players") or []),
            fixture_id=fixture_id,
        )
    except Exception as exc:  # noqa: BLE001 - never fail assignment save on email errors
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Failed to send assignment email for %s", fixture_id)
        return {"sent": False, "reason": str(exc)}


def replace_fixture_assignments(body: FixtureAssignmentsBulkUpdate) -> dict[str, Any]:
    """Full replace of the assignment store from the client map."""
    cleaned: dict[str, Any] = {}
    for fixture_id, row in (body.assignments or {}).items():
        if not isinstance(row, dict):
            continue
        key = str(fixture_id or "").strip()
        if not key:
            continue
        staff_names = _normalize_staff_names(row.get("staff"), validate=True)
        watch_type = str(row.get("watch_type") or "").strip().upper()
        if not staff_names and not watch_type:
            continue
        cleaned[key] = {
            "staff": staff_names,
            "watch_type": watch_type,
            "season": str(row.get("season") or "").strip(),
            "league": str(row.get("league") or "").strip(),
            "home": str(row.get("home") or "").strip(),
            "away": str(row.get("away") or "").strip(),
            "date": str(row.get("date") or "").strip()[:10],
            "kickoff_utc": row.get("kickoff_utc"),
            "watched_players": _normalize_watched_players(row.get("watched_players") or []),
            "updated_at": row.get("updated_at") or datetime.now(UTC).isoformat(),
        }
    store = _load_assignments_store()
    store["assignments"] = cleaned
    _save_assignments_store(store)
    return get_fixture_assignments()


def _load_scouting_reports_store() -> dict[str, Any]:
    with _scouting_reports_lock:
        if not SCOUTING_REPORTS_PATH.exists():
            return {"version": 1, "updated_at": None, "reports": {}}
        try:
            payload = json.loads(SCOUTING_REPORTS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "updated_at": None, "reports": {}}
        reports = payload.get("reports")
        if not isinstance(reports, dict):
            payload["reports"] = {}
        return payload


def _save_scouting_reports_store(payload: dict[str, Any]) -> None:
    ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = SCOUTING_REPORTS_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(SCOUTING_REPORTS_PATH)
    _scout_ops_cache_clear()


def get_scouting_reports(fixture_id: str | None = None) -> dict[str, Any]:
    store = _load_scouting_reports_store()
    reports = dict(store.get("reports") or {})
    if fixture_id:
        fixture_reports = reports.get(fixture_id)
        if not isinstance(fixture_reports, dict):
            fixture_reports = {}
        return {
            "fixture_id": fixture_id,
            "reports": fixture_reports,
            "updated_at": store.get("updated_at"),
        }
    return {
        "reports": reports,
        "updated_at": store.get("updated_at"),
    }


def scouting_reports_for_fixture(fixture_id: str) -> list[dict[str, Any]]:
    fixture_reports = get_scouting_reports(fixture_id).get("reports") or {}
    if not isinstance(fixture_reports, dict):
        return []
    rows: list[dict[str, Any]] = []
    for player_key, row in fixture_reports.items():
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "player_id": int(row.get("player_id") or player_key or 0),
                "player_name": str(row.get("player_name") or ""),
                "side": str(row.get("side") or ""),
                "team": str(row.get("team") or ""),
                "staff": str(row.get("staff") or ""),
                "fixture_date": str(row.get("fixture_date") or ""),
                "position": str(row.get("position") or ""),
                "marked_at": row.get("marked_at"),
            }
        )
    rows.sort(key=lambda item: str(item.get("player_name") or "").casefold())
    return rows


def _load_manual_fixtures_store() -> dict[str, Any]:
    with _manual_fixtures_lock:
        if not MANUAL_FIXTURES_PATH.exists():
            return {"version": 1, "updated_at": None, "fixtures": {}}
        try:
            payload = json.loads(MANUAL_FIXTURES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "updated_at": None, "fixtures": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "updated_at": None, "fixtures": {}}
        fixtures = payload.get("fixtures")
        if not isinstance(fixtures, dict):
            payload["fixtures"] = {}
        return payload


def _save_manual_fixtures_store(payload: dict[str, Any]) -> None:
    ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = MANUAL_FIXTURES_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(MANUAL_FIXTURES_PATH)
    _scout_ops_cache_clear()


def _manual_fixture_list_shape(row: dict[str, Any]) -> dict[str, Any]:
    home_name = str((row.get("home") or {}).get("name") if isinstance(row.get("home"), dict) else row.get("home") or "").strip()
    away_name = str((row.get("away") or {}).get("name") if isinstance(row.get("away"), dict) else row.get("away") or "").strip()
    team_sheet = row.get("team_sheet") if isinstance(row.get("team_sheet"), dict) else None
    date_key = str(row.get("date") or "")[:10]
    status = str(row.get("status") or "").strip().lower()
    if status not in {"scheduled", "completed"}:
        # Legacy rows defaulted to completed; future dates without an explicit
        # status should still surface in Fixture Planner as upcoming.
        today = datetime.now(UTC).date().isoformat()
        status = "completed" if (date_key and date_key < today) or row.get("score") else "scheduled"
        if not date_key and not row.get("score"):
            status = "completed"
    league = _normalize_league_label(row.get("league") or MANUAL_LEAGUE_LABEL)
    competition = _normalize_league_label(
        row.get("competition") or row.get("league") or MANUAL_LEAGUE_LABEL
    )
    return {
        "fixture_id": str(row.get("fixture_id") or ""),
        "manual": True,
        "season": str(row.get("season") or ""),
        "league": league,
        "competition": competition,
        "home": {"name": home_name},
        "away": {"name": away_name},
        "date": date_key,
        "scheduled_date": date_key,
        "kickoff_utc": row.get("kickoff_utc"),
        "score": str(row.get("score") or "").strip() or None,
        "venue": str(row.get("venue") or "").strip() or None,
        "status": status,
        "notes": str(row.get("notes") or ""),
        "watched_players": list(row.get("watched_players") or []),
        "team_sheet": team_sheet,
        "staff": str(row.get("staff") or ""),
        "watch_type": str(row.get("watch_type") or ""),
        "match_id": None,
        "sources": ["manual"],
        "source_count": 1,
        "verified": False,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def get_manual_fixture(fixture_id: str) -> dict[str, Any] | None:
    store = _load_manual_fixtures_store()
    row = (store.get("fixtures") or {}).get(str(fixture_id or "").strip())
    if not isinstance(row, dict):
        return None
    return _manual_fixture_list_shape(row)


def list_manual_fixtures(*, season: str | None = None) -> list[dict[str, Any]]:
    store = _load_manual_fixtures_store()
    rows: list[dict[str, Any]] = []
    for row in (store.get("fixtures") or {}).values():
        if not isinstance(row, dict):
            continue
        shaped = _manual_fixture_list_shape(row)
        if season and shaped.get("season") and shaped["season"] != season:
            continue
        rows.append(shaped)
    rows.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("home", {}).get("name") or "")))
    return rows


def _merge_manual_fixtures_into_payload(payload: dict[str, Any], *, season: str) -> dict[str, Any]:
    manuals = list_manual_fixtures(season=season)
    if not manuals:
        return payload
    merged = dict(payload)
    fixtures = list(payload.get("fixtures") or [])
    existing = {str(row.get("fixture_id") or "") for row in fixtures}
    added = 0
    for row in manuals:
        fid = str(row.get("fixture_id") or "")
        if not fid or fid in existing:
            continue
        fixtures.append(row)
        existing.add(fid)
        added += 1
    if not added:
        return payload
    fixtures.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
            str(row.get("league") or ""),
        )
    )
    leagues = list(payload.get("leagues") or list(FIXTURE_LEAGUE_UIS))
    if MANUAL_LEAGUE_LABEL not in leagues:
        leagues.append(MANUAL_LEAGUE_LABEL)
    summary = dict(payload.get("summary") or {})
    summary["total_fixtures"] = len(fixtures)
    by_league = dict(summary.get("by_league") or {})
    by_league[MANUAL_LEAGUE_LABEL] = sum(1 for row in fixtures if row.get("manual"))
    summary["by_league"] = by_league
    merged["fixtures"] = fixtures
    merged["leagues"] = leagues
    merged["summary"] = summary
    return merged


def _load_fixture_overrides_store() -> dict[str, Any]:
    with _fixture_overrides_lock:
        if not FIXTURE_OVERRIDES_PATH.exists():
            return {"version": 1, "updated_at": None, "overrides": {}}
        try:
            payload = json.loads(FIXTURE_OVERRIDES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "updated_at": None, "overrides": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "updated_at": None, "overrides": {}}
        overrides = payload.get("overrides")
        if not isinstance(overrides, dict):
            payload["overrides"] = {}
        return payload


def _save_fixture_overrides_store(payload: dict[str, Any]) -> None:
    FIXTURE_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _fixture_overrides_lock:
        FIXTURE_OVERRIDES_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    _scout_ops_cache_clear()


def get_fixture_overrides() -> dict[str, dict[str, Any]]:
    store = _load_fixture_overrides_store()
    raw = store.get("overrides") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, dict)
    }


def set_fixture_status_override(fixture_id: str, *, status: str) -> dict[str, Any]:
    fid = str(fixture_id or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="fixture_id is required")
    normalized = str(status or "").strip().lower()
    if normalized not in {"scheduled", "postponed"}:
        raise HTTPException(status_code=400, detail="status must be scheduled or postponed")

    store = _load_fixture_overrides_store()
    overrides = dict(store.get("overrides") or {})
    if normalized == "scheduled":
        overrides.pop(fid, None)
    else:
        overrides[fid] = {
            "status": normalized,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    store["overrides"] = overrides
    store["updated_at"] = datetime.now(UTC).isoformat()
    _save_fixture_overrides_store(store)
    clear_fixture_planner_cache()

    return {"ok": True, "fixture_id": fid, "status": normalized}


def _apply_fixture_overrides_to_payload(payload: dict[str, Any]) -> dict[str, Any]:
    overrides = get_fixture_overrides()
    if not overrides:
        return payload
    fixtures: list[dict[str, Any]] = []
    changed = False
    for row in payload.get("fixtures") or []:
        fid = str(row.get("fixture_id") or "")
        override = overrides.get(fid)
        if override and str(override.get("status") or "").lower() == "postponed":
            fixtures.append({**row, "status": "postponed", "postponed": True})
            changed = True
        else:
            fixtures.append(row)
    if not changed:
        return payload
    merged = dict(payload)
    merged["fixtures"] = fixtures
    return merged


def _finalize_fixture_payload(payload: dict[str, Any], *, season: str) -> dict[str, Any]:
    merged = _merge_manual_fixtures_into_payload(payload, season=season)
    return _apply_fixture_overrides_to_payload(merged)


def _fixture_is_postponed(fixture_id: str, fixture: dict[str, Any] | None = None) -> bool:
    if isinstance(fixture, dict) and str(fixture.get("status") or "").lower() == "postponed":
        return True
    override = get_fixture_overrides().get(str(fixture_id or "").strip()) or {}
    return str(override.get("status") or "").lower() == "postponed"


def _extract_fotmob_league_team_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def remember(raw: Any) -> None:
        name = str(raw or "").strip()
        if not name:
            return
        key = name.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(name)

    table = payload.get("table") or []
    if isinstance(table, list):
        for block in table:
            if not isinstance(block, dict):
                continue
            data = block.get("data") or {}
            if not isinstance(data, dict):
                continue
            inner = data.get("table") or {}
            rows: list[Any] = []
            if isinstance(inner, dict):
                for value in inner.values():
                    if isinstance(value, list):
                        rows.extend(value)
            elif isinstance(inner, list):
                rows = inner
            for row in rows:
                if isinstance(row, dict):
                    remember(row.get("name"))

    matches = (payload.get("fixtures") or {}).get("allMatches") or []
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, dict):
                continue
            for side in ("home", "away"):
                remember((match.get(side) or {}).get("name"))
    return names


def _fetch_fotmob_catalog_league_teams(
    *,
    fotmob_id: int,
    country: str,
    season: str,
    calendar_year: bool = False,
) -> list[dict[str, Any]]:
    fotmob_season = _season_to_fotmob(season, calendar_year=calendar_year)
    try:
        response = _http.get(
            "https://www.fotmob.com/api/data/leagues",
            params={"id": int(fotmob_id), "season": fotmob_season},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=25,
        )
    except Exception:
        logger.exception("FotMob team catalog fetch failed for league %s", fotmob_id)
        return []
    if not response.ok:
        return []
    try:
        payload = response.json()
    except Exception:
        return []
    details = payload.get("details") or {}
    resolved_country = str(details.get("country") or country or "").strip().upper()
    if resolved_country and resolved_country not in TEAM_CATALOG_COUNTRIES:
        return []
    country_code = resolved_country or str(country or "").strip().upper()
    rows: list[dict[str, Any]] = []
    for name in _extract_fotmob_league_team_names(payload):
        rows.append(
            {
                "name": name,
                "country": country_code,
                "country_label": COUNTRY_LABELS.get(country_code, country_code),
            }
        )
    return rows


def list_known_team_entries(*, seasons: list[str] | None = None) -> list[dict[str, Any]]:
    """Canonical clubs from FotMob ENG/SCO/WAL/IRL/NIR competitions (+ local fixtures)."""
    use_seasons = [
        season
        for season in (seasons or list(ALLOWED_FIXTURE_SEASONS))
        if season in ALLOWED_FIXTURE_SEASONS
    ] or list(ALLOWED_FIXTURE_SEASONS)
    cache_key = f"fotmob-bi|{','.join(use_seasons)}"
    now = time.time()
    with _team_catalog_cache_lock:
        cached = _team_catalog_cache.get(cache_key)
        if cached and now - cached[0] < TEAM_CATALOG_TTL_SECONDS:
            return list(cached[1])

    by_norm: dict[str, dict[str, Any]] = {}

    def remember(name: str, *, country: str = "") -> None:
        clean = str(name or "").strip()
        norm = _normalize_team_name(clean)
        if not norm:
            return
        country_code = str(country or "").strip().upper()
        existing = by_norm.get(norm)
        if not existing:
            by_norm[norm] = {
                "name": clean,
                "country": country_code,
                "country_label": COUNTRY_LABELS.get(country_code, country_code),
            }
            return
        preferred = _prefer_display_name(str(existing.get("name") or ""), clean)
        existing["name"] = preferred
        if country_code and not existing.get("country"):
            existing["country"] = country_code
            existing["country_label"] = COUNTRY_LABELS.get(country_code, country_code)

    # Local planner fixtures first (includes manuals already merged into cache).
    for fixture in _cached_fixtures_list(use_seasons, warm=True):
        for name, _side in _fixture_team_sides(fixture):
            remember(name)

    # Broad FotMob catalog for British Isles competitions only.
    catalog_season = use_seasons[0] if use_seasons else DEFAULT_SEASON
    for league in FOTMOB_TEAM_CATALOG_LEAGUES:
        rows = _fetch_fotmob_catalog_league_teams(
            fotmob_id=int(league["id"]),
            country=str(league.get("country") or ""),
            season=catalog_season,
            calendar_year=bool(league.get("calendar_year")),
        )
        for row in rows:
            remember(str(row.get("name") or ""), country=str(row.get("country") or ""))

    entries = sorted(by_norm.values(), key=lambda row: str(row.get("name") or "").casefold())
    with _team_catalog_cache_lock:
        _team_catalog_cache[cache_key] = (now, entries)
    return entries


def list_known_team_names(*, seasons: list[str] | None = None) -> list[str]:
    return [str(row.get("name") or "") for row in list_known_team_entries(seasons=seasons) if row.get("name")]


def resolve_canonical_team_name(raw: str, catalog: list[str] | None = None) -> str:
    """Map typed scout input onto the fixture catalog when the club is unambiguous."""
    typed = str(raw or "").strip()
    if not typed:
        return typed
    names = catalog if catalog is not None else list_known_team_names()
    for name in names:
        if name.casefold() == typed.casefold():
            return name
    typed_norm = _normalize_team_name(typed)
    if typed_norm:
        exact_norm = [name for name in names if _normalize_team_name(name) == typed_norm]
        if len(exact_norm) == 1:
            return exact_norm[0]
    same_club = [name for name in names if _team_names_same_club(name, typed)]
    if len(same_club) == 1:
        return same_club[0]
    return typed


def _players_from_manual_inputs(rows: list[ManualFixturePlayerInput] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, ManualFixturePlayerInput):
            raw.append(row.model_dump())
        elif isinstance(row, dict):
            raw.append(row)
    catalog = list_known_team_names()
    for row in raw:
        if isinstance(row, dict) and row.get("team"):
            row["team"] = resolve_canonical_team_name(str(row.get("team") or ""), catalog)
    cleaned = _normalize_watched_players(raw)
    return [_resolve_watched_player_against_catalog(player) for player in cleaned]


def _resolve_watched_player_against_catalog(player: dict[str, Any]) -> dict[str, Any]:
    """Prefer a real Impect player_id so LIVE/VID/REP and dossier links line up."""
    try:
        existing = int(player.get("player_id") or 0)
    except (TypeError, ValueError):
        existing = 0
    if existing > 0:
        return player

    name = str(player.get("player_name") or "").strip()
    team = str(player.get("team") or "").strip()
    resolved = _lookup_impect_player_id(name, team=team)
    if not resolved:
        return player
    return {**player, "player_id": int(resolved)}


def _lookup_impect_player_id(name: str, *, team: str = "") -> int | None:
    clean = str(name or "").strip()
    if len(clean) < 3:
        return None
    try:
        from app import main as impect

        body = impect.PlayerCatalogRequest(search=clean)
        payload = impect.list_players(body)
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Could not resolve Impect player id for %s", clean)
        return None

    players = list(payload.get("players") or [])
    if not players:
        return None

    norm = clean.casefold()
    matches = [
        row
        for row in players
        if str(row.get("name") or "").strip().casefold() == norm
    ]
    if not matches:
        matches = [
            row
            for row in players
            if norm in str(row.get("name") or "").strip().casefold()
        ]
    team_norm = str(team or "").strip().casefold()
    if team_norm and len(matches) > 1:
        club_hits = []
        for row in matches:
            club = str(
                row.get("club")
                or row.get("context_club")
                or row.get("label")
                or ""
            ).casefold()
            if team_norm in club or club in team_norm:
                club_hits.append(row)
        if club_hits:
            matches = club_hits

    best = matches[0] if matches else (players[0] if len(players) == 1 else None)
    if not best:
        return None
    try:
        player_id = int(best.get("impect_player_id") or best.get("playerId") or best.get("id") or 0)
    except (TypeError, ValueError):
        return None
    return player_id if player_id > 0 else None


def _kickoff_utc_from_date_and_time(date_key: str, kickoff: str | None) -> str | None:
    date_token = _parse_iso_date(date_key) or ""
    if not date_token:
        return None
    time_token = str(kickoff or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_token)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{date_token}T{hour:02d}:{minute:02d}:00"
    return f"{date_token}T15:00:00"


def _sync_manual_assignment(
    *,
    fixture_id: str,
    season: str,
    league: str,
    home: str,
    away: str,
    date_key: str,
    kickoff_utc: str | None,
    staff: list[str] | str,
    watch_type: str,
    watched_players: list[dict[str, Any]],
    send_email: bool = False,
) -> None:
    staff_names = _normalize_staff_names(staff, validate=True)
    watch = str(watch_type or "").strip().upper() or "LIVE"
    if not staff_names:
        # Clear assignment if staff removed.
        upsert_fixture_assignment(
            FixtureAssignmentUpdate(fixture_id=fixture_id),
            mirror_to_live=True,
            send_email=False,
        )
        return
    upsert_fixture_assignment(
        FixtureAssignmentUpdate(
            fixture_id=fixture_id,
            staff=staff_names,
            watch_type=watch if watch in WATCH_TYPES else "LIVE",
            season=season,
            league=league,
            home=home,
            away=away,
            date=date_key,
            kickoff_utc=kickoff_utc,
            watched_players=watched_players,
        ),
        mirror_to_live=True,
        send_email=send_email,
    )


def _sync_manual_scouting_reports(
    *,
    fixture_id: str,
    season: str,
    staff: str,
    date_key: str,
    players: list[dict[str, Any]],
    mark_reports: bool,
) -> None:
    if not mark_reports:
        return
    for player in players:
        player_id = int(player.get("player_id") or 0)
        if not player_id:
            continue
        toggle_scouting_report(
            ScoutingReportToggle(
                fixture_id=fixture_id,
                player_id=player_id,
                player_name=str(player.get("player_name") or ""),
                side=str(player.get("side") or ""),
                team=str(player.get("team") or ""),
                season=season,
                staff=staff,
                fixture_date=date_key,
                position=str(player.get("position") or ""),
                reported=True,
            )
        )


def create_manual_fixture(body: ManualFixtureCreate) -> dict[str, Any]:
    season = str(body.season or DEFAULT_SEASON).strip()
    if season not in ALLOWED_FIXTURE_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
        )
    home = resolve_canonical_team_name(str(body.home or "").strip())
    away = resolve_canonical_team_name(str(body.away or "").strip())
    if not home or not away:
        raise HTTPException(status_code=400, detail="home and away team names are required")
    date_key = _parse_iso_date(body.date)
    if not date_key:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    staff_names = _normalize_staff_names(body.staff, validate=True)
    watch_type = str(body.watch_type or "LIVE").strip().upper() or "LIVE"
    if watch_type not in WATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"watch_type must be one of: {', '.join(WATCH_TYPES)}")

    league = _normalize_league_label(body.league or MANUAL_LEAGUE_LABEL) or MANUAL_LEAGUE_LABEL
    competition = _normalize_league_label(body.competition or league) or league
    kickoff_utc = _kickoff_utc_from_date_and_time(date_key, body.kickoff)
    players = _players_from_manual_inputs(body.players)
    fixture_id = f"{MANUAL_FIXTURE_ID_PREFIX}{uuid.uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    today = datetime.now(UTC).date().isoformat()
    status = str(body.status or "").strip().lower()
    if status not in {"scheduled", "completed"}:
        status = "completed" if date_key <= today else "scheduled"
    # Upcoming games shouldn't auto-mark reports unless explicitly requested.
    mark_reports = bool(body.mark_reports) if status == "completed" else bool(body.mark_reports)

    record = {
        "fixture_id": fixture_id,
        "manual": True,
        "season": season,
        "league": league,
        "competition": competition,
        "home": {"name": home},
        "away": {"name": away},
        "date": date_key,
        "kickoff_utc": kickoff_utc,
        "score": str(body.score or "").strip(),
        "venue": str(body.venue or "").strip(),
        "notes": str(body.notes or "").strip(),
        "watched_players": players,
        "team_sheet": None,
        "staff": staff_names,
        "watch_type": watch_type if staff_names else "",
        "status": status,
        "created_at": now,
        "updated_at": now,
    }

    store = _load_manual_fixtures_store()
    fixtures = store.setdefault("fixtures", {})
    fixtures[fixture_id] = record
    _save_manual_fixtures_store(store)

    if staff_names:
        _sync_manual_assignment(
            fixture_id=fixture_id,
            season=season,
            league=league,
            home=home,
            away=away,
            date_key=date_key,
            kickoff_utc=kickoff_utc,
            staff=staff_names,
            watch_type=watch_type,
            watched_players=players,
            send_email=status == "scheduled",
        )
    _sync_manual_scouting_reports(
        fixture_id=fixture_id,
        season=season,
        staff=staff_names[0] if staff_names else "",
        date_key=date_key,
        players=players,
        mark_reports=mark_reports,
    )

    return {"ok": True, "fixture": _manual_fixture_list_shape(record)}


def update_manual_fixture(fixture_id: str, body: ManualFixtureUpdate) -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    store = _load_manual_fixtures_store()
    fixtures = store.setdefault("fixtures", {})
    record = fixtures.get(token)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Manual fixture not found")

    if body.home is not None:
        home = resolve_canonical_team_name(str(body.home or "").strip())
        if not home:
            raise HTTPException(status_code=400, detail="home team name is required")
        record["home"] = {"name": home}
    if body.away is not None:
        away = resolve_canonical_team_name(str(body.away or "").strip())
        if not away:
            raise HTTPException(status_code=400, detail="away team name is required")
        record["away"] = {"name": away}
    if body.date is not None:
        date_key = _parse_iso_date(body.date)
        if not date_key:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
        record["date"] = date_key
    if body.league is not None:
        record["league"] = _normalize_league_label(body.league or MANUAL_LEAGUE_LABEL) or MANUAL_LEAGUE_LABEL
        record["competition"] = record["league"]
    if body.competition is not None:
        record["competition"] = str(body.competition or "").strip()
    if body.kickoff is not None:
        record["kickoff_utc"] = _kickoff_utc_from_date_and_time(str(record.get("date") or ""), body.kickoff)
    if body.score is not None:
        record["score"] = str(body.score or "").strip()
    if body.venue is not None:
        record["venue"] = str(body.venue or "").strip()
    if body.notes is not None:
        record["notes"] = str(body.notes or "").strip()
    if body.staff is not None:
        staff_names = _normalize_staff_names(body.staff, validate=True)
        record["staff"] = staff_names
    if body.watch_type is not None:
        watch = str(body.watch_type or "").strip().upper()
        if watch and watch not in WATCH_TYPES:
            raise HTTPException(status_code=400, detail=f"watch_type must be one of: {', '.join(WATCH_TYPES)}")
        record["watch_type"] = watch
    if body.players is not None:
        record["watched_players"] = _players_from_manual_inputs(body.players)

    record["updated_at"] = datetime.now(UTC).isoformat()
    fixtures[token] = record
    _save_manual_fixtures_store(store)

    home_name = str((record.get("home") or {}).get("name") or "")
    away_name = str((record.get("away") or {}).get("name") or "")
    date_key = str(record.get("date") or "")
    staff_names = _normalize_staff_names(record.get("staff"))
    players = list(record.get("watched_players") or [])
    _sync_manual_assignment(
        fixture_id=token,
        season=str(record.get("season") or DEFAULT_SEASON),
        league=str(record.get("league") or MANUAL_LEAGUE_LABEL),
        home=home_name,
        away=away_name,
        date_key=date_key,
        kickoff_utc=record.get("kickoff_utc"),
        staff=staff_names,
        watch_type=str(record.get("watch_type") or "LIVE"),
        watched_players=players,
    )
    if staff_names:
        _sync_manual_scouting_reports(
            fixture_id=token,
            season=str(record.get("season") or DEFAULT_SEASON),
            staff=staff_names[0],
            date_key=date_key,
            players=players,
            mark_reports=bool(body.mark_reports),
        )

    return {"ok": True, "fixture": _manual_fixture_list_shape(record)}


def delete_manual_fixture(fixture_id: str) -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    store = _load_manual_fixtures_store()
    fixtures = store.setdefault("fixtures", {})
    record = fixtures.pop(token, None)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Manual fixture not found")
    _save_manual_fixtures_store(store)

    team_sheet = record.get("team_sheet") if isinstance(record.get("team_sheet"), dict) else None
    if team_sheet:
        stored = str(team_sheet.get("stored_name") or "").strip()
        if stored:
            path = TEAM_SHEETS_DIR / stored
            if path.exists() and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass

    upsert_fixture_assignment(
        FixtureAssignmentUpdate(fixture_id=token),
        mirror_to_live=True,
        send_email=False,
    )
    report_store = _load_scouting_reports_store()
    reports = report_store.setdefault("reports", {})
    if token in reports:
        reports.pop(token, None)
        _save_scouting_reports_store(report_store)

    return {"ok": True, "fixture_id": token}


def _safe_team_sheet_name(filename: str) -> str:
    base = Path(str(filename or "team-sheet")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "team-sheet"
    return cleaned[:120]


def attach_manual_team_sheet(
    *,
    fixture_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> dict[str, Any]:
    token = str(fixture_id or "").strip()
    store = _load_manual_fixtures_store()
    fixtures = store.setdefault("fixtures", {})
    record = fixtures.get(token)
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Manual fixture not found")

    original = _safe_team_sheet_name(filename or "team-sheet")
    ext = Path(original).suffix.lower()
    if ext not in TEAM_SHEET_ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Team sheet must be one of: {', '.join(sorted(TEAM_SHEET_ALLOWED_EXT))}",
        )
    media = str(content_type or "application/octet-stream").split(";")[0].strip().lower()
    if media not in TEAM_SHEET_ALLOWED_TYPES and ext not in TEAM_SHEET_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Unsupported team sheet file type")

    if not data:
        raise HTTPException(status_code=400, detail="Empty team sheet file")
    if len(data) > TEAM_SHEET_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Team sheet must be 12MB or smaller")

    TEAM_SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = TEAM_SHEETS_DIR / stored_name
    dest.write_bytes(data)

    previous = record.get("team_sheet") if isinstance(record.get("team_sheet"), dict) else None
    if previous:
        old_name = str(previous.get("stored_name") or "").strip()
        if old_name:
            old_path = TEAM_SHEETS_DIR / old_name
            if old_path.exists() and old_path.is_file():
                try:
                    old_path.unlink()
                except OSError:
                    pass

    record["team_sheet"] = {
        "filename": original,
        "stored_name": stored_name,
        "content_type": media or "application/octet-stream",
        "size_bytes": len(data),
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
    record["updated_at"] = datetime.now(UTC).isoformat()
    fixtures[token] = record
    _save_manual_fixtures_store(store)
    return {"ok": True, "fixture": _manual_fixture_list_shape(record)}


def get_manual_team_sheet_file(fixture_id: str) -> FileResponse:
    token = str(fixture_id or "").strip()
    row = get_manual_fixture(token)
    if not row:
        raise HTTPException(status_code=404, detail="Manual fixture not found")
    team_sheet = row.get("team_sheet") if isinstance(row.get("team_sheet"), dict) else None
    if not team_sheet:
        raise HTTPException(status_code=404, detail="No team sheet attached")
    stored = str(team_sheet.get("stored_name") or "").strip()
    path = TEAM_SHEETS_DIR / stored
    if not stored or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Team sheet file missing")
    filename = str(team_sheet.get("filename") or path.name)
    media = str(team_sheet.get("content_type") or "application/octet-stream")
    return FileResponse(path, media_type=media, filename=filename)


def toggle_scouting_report(body: ScoutingReportToggle) -> dict[str, Any]:
    fixture_id = str(body.fixture_id or "").strip()
    player_id = int(body.player_id or 0)
    if not fixture_id or not player_id:
        raise HTTPException(status_code=400, detail="fixture_id and player_id are required")

    store = _load_scouting_reports_store()
    reports: dict[str, Any] = store.setdefault("reports", {})
    fixture_reports: dict[str, Any] = reports.setdefault(fixture_id, {})
    player_key = str(player_id)

    if body.reported:
        fixture_reports[player_key] = {
            "player_id": player_id,
            "player_name": str(body.player_name or "").strip(),
            "side": str(body.side or "").strip().lower(),
            "team": str(body.team or "").strip(),
            "season": str(body.season or "").strip(),
            "staff": str(body.staff or "").strip(),
            "fixture_date": str(body.fixture_date or "").strip()[:10],
            "position": str(body.position or "").strip(),
            "marked_at": datetime.now(UTC).isoformat(),
        }
    else:
        fixture_reports.pop(player_key, None)
        if not fixture_reports:
            reports.pop(fixture_id, None)

    _save_scouting_reports_store(store)
    _sync_watched_player_from_report(
        fixture_id=fixture_id,
        player_id=player_id,
        player_name=str(body.player_name or "").strip(),
        side=str(body.side or "").strip().lower(),
        team=str(body.team or "").strip(),
        position=str(body.position or "").strip(),
        season=str(body.season or "").strip(),
        staff=str(body.staff or "").strip(),
        fixture_date=str(body.fixture_date or "").strip()[:10],
        reported=bool(body.reported),
    )
    return get_scouting_reports(fixture_id)


def _sync_watched_player_from_report(
    *,
    fixture_id: str,
    player_id: int,
    player_name: str,
    side: str,
    team: str,
    position: str,
    season: str,
    staff: str,
    fixture_date: str,
    reported: bool,
) -> None:
    """Add pitch/squad report marks onto assignment watched_players (LIVE/VID counts).

    Unmarking a report does not remove an existing watched_player — they may still
    have been selected for coverage at assign time.
    """
    if not reported:
        return

    assign_store = _load_assignments_store()
    assignments: dict[str, Any] = assign_store.setdefault("assignments", {})
    current = dict(assignments.get(fixture_id) or {})

    watched = list(current.get("watched_players") or [])
    already = False
    for row in watched:
        if not isinstance(row, dict):
            continue
        try:
            if int(row.get("player_id") or 0) == int(player_id):
                already = True
                break
        except (TypeError, ValueError):
            continue
    if already:
        return

    watched.append(
        {
            "player_id": int(player_id),
            "player_name": player_name,
            "team": team,
            "side": side,
            "position": position,
        }
    )
    watched = _normalize_watched_players(watched)

    watch_type = str(current.get("watch_type") or "").strip().upper()
    staff_names = _normalize_staff_names(staff) or _normalize_staff_names(current.get("staff"))
    if not watch_type or not staff_names:
        manual = get_manual_fixture(fixture_id)
        if manual:
            watch_type = watch_type or str(manual.get("watch_type") or "").strip().upper()
            if not staff_names:
                staff_names = _normalize_staff_names(manual.get("staff"))
    if not watch_type:
        watch_type = "LIVE"
    if watch_type not in WATCH_TYPES:
        watch_type = "LIVE"
    if not staff_names:
        # Need an assignee to persist watched_players on the assignment row.
        return

    saved = {
        **current,
        "staff": staff_names,
        "watch_type": str(current.get("watch_type") or watch_type).strip().upper() or watch_type,
        "season": str(current.get("season") or season or "").strip(),
        "league": str(current.get("league") or "").strip(),
        "home": str(current.get("home") or "").strip(),
        "away": str(current.get("away") or "").strip(),
        "date": str(current.get("date") or fixture_date or "").strip()[:10],
        "kickoff_utc": current.get("kickoff_utc"),
        "watched_players": watched,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if saved["watch_type"] not in WATCH_TYPES:
        saved["watch_type"] = watch_type
    assignments[fixture_id] = saved
    _save_assignments_store(assign_store)
    _mirror_assignment_to_live(fixture_id=fixture_id, assignment=saved)


def _assignment_watch_type_matches(assigned_watch: Any, filter_watch: str | None) -> bool:
    if not filter_watch:
        return True
    assigned = str(assigned_watch or "").strip().upper() or "LIVE"
    target = str(filter_watch).strip().upper()
    if target == "ALL":
        return True
    return assigned == target


def _expand_calendar_staff_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One calendar card per scout when multiple staff share an assignment."""
    expanded: list[dict[str, Any]] = []
    for row in rows:
        names = list(row.get("staff_names") or _normalize_staff_names(row.get("staff")))
        if len(names) <= 1:
            expanded.append(row)
            continue
        for name in names:
            clone = dict(row)
            clone["staff"] = name
            clone["staff_names"] = [name]
            expanded.append(clone)
    expanded.sort(
        key=lambda item: (
            str(item.get("date") or ""),
            str(item.get("kickoff_utc") or ""),
            str(item.get("staff") or ""),
            str(item.get("league") or ""),
        )
    )
    return expanded


def _assignment_rows_for_seasons(
    seasons: list[str],
    *,
    include_past: bool = False,
    staff: str | None = None,
    watch_type: str | None = None,
) -> list[dict[str, Any]]:
    assignment_store = get_fixture_assignments()["assignments"]
    fixtures_list = _cached_fixtures_list(seasons, warm=True)
    fixtures_by_id = {
        str(row.get("fixture_id") or ""): row
        for row in fixtures_list
        if row.get("fixture_id")
    }

    today = datetime.now(UTC).date().isoformat()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for fixture_id, assignment in assignment_store.items():
        if not isinstance(assignment, dict):
            continue
        staff_names = _normalize_staff_names(assignment.get("staff"))
        assigned_watch = str(assignment.get("watch_type") or "").strip().upper()
        if not staff_names:
            continue
        if staff and staff.casefold() not in {name.casefold() for name in staff_names}:
            continue
        if watch_type and not _assignment_watch_type_matches(assigned_watch, watch_type):
            continue

        assignment_season = str(assignment.get("season") or "").strip()
        if seasons and assignment_season and assignment_season not in seasons:
            continue

        fixture = _resolve_fixture_record(fixture_id, fixtures_list, assignment=assignment)
        if _fixture_is_postponed(fixture_id, fixture if isinstance(fixture, dict) else None):
            continue
        home_name = str(assignment.get("home") or "").strip()
        away_name = str(assignment.get("away") or "").strip()
        league_name = str(assignment.get("league") or "").strip()
        kickoff = assignment.get("kickoff_utc")
        assignment_date = _parse_iso_date(assignment.get("date") or assignment.get("kickoff_utc"))
        date_key = assignment_date

        if fixture is not None:
            home_name = (fixture.get("home") or {}).get("name") or home_name
            away_name = (fixture.get("away") or {}).get("name") or away_name
            league_name = str(fixture.get("league") or league_name)
            kickoff = fixture.get("kickoff_utc") or kickoff
            if not assignment_date:
                date_key = _parse_iso_date(fixture.get("date") or fixture.get("scheduled_date")) or date_key
            assignment_season = assignment_season or str(fixture.get("season") or "").strip()

        fixture_status = str((fixture or {}).get("status") or "").strip()
        fixture_score = (fixture or {}).get("score")
        fixture_match_id = (fixture or {}).get("match_id")
        fixture_iteration_id = (fixture or {}).get("iteration_id")

        if not include_past and date_key and date_key < today:
            continue

        staff_label = _staff_label(staff_names)
        canonical_fixture_id = str((fixture or {}).get("fixture_id") or fixture_id)
        dedupe_key = f"{canonical_fixture_id}|{staff_label}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        report_rows = scouting_reports_for_fixture(canonical_fixture_id)
        manual = get_manual_fixture(canonical_fixture_id) or get_manual_fixture(fixture_id)
        watched = list(assignment.get("watched_players") or [])
        if not watched and manual:
            watched = list(manual.get("watched_players") or [])

        rows.append(
            {
                "fixture_id": canonical_fixture_id,
                "staff": staff_label,
                "staff_names": staff_names,
                "watch_type": assigned_watch,
                "season": assignment_season,
                "league": league_name or (manual.get("league") if manual else "") or "",
                "home": home_name or ((manual or {}).get("home") or {}).get("name") or "",
                "away": away_name or ((manual or {}).get("away") or {}).get("name") or "",
                "date": date_key or (manual.get("date") if manual else "") or "",
                "kickoff_utc": kickoff or (manual.get("kickoff_utc") if manual else None),
                "status": fixture_status
                or ("completed" if fixture_score or manual else ""),
                "score": fixture_score or (manual.get("score") if manual else None),
                "match_id": fixture_match_id,
                "iteration_id": fixture_iteration_id,
                "manual": bool(manual) or str(canonical_fixture_id).startswith(MANUAL_FIXTURE_ID_PREFIX),
                "notes": (manual.get("notes") if manual else "") or "",
                "team_sheet": (manual.get("team_sheet") if manual else None),
                "watched_players": watched,
                "scouting_reports": report_rows,
                "scouting_report_count": len(report_rows),
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
            str(row.get("league") or ""),
        )
    )
    return rows


def build_scout_summary_payload(
    *,
    season: str | None = None,
    include_past: bool = True,
    staff: str | None = None,
) -> dict[str, Any]:
    cache_key = f"summary|{season or 'ALL'}|{include_past}|{staff or ''}"
    cached = _scout_ops_cache_get(cache_key)
    if cached is not None:
        return cached

    seasons = [season] if season in ALLOWED_FIXTURE_SEASONS else list(ALLOWED_FIXTURE_SEASONS)
    rows = _assignment_rows_for_seasons(
        seasons,
        include_past=include_past,
        staff=staff or None,
    )

    by_staff: dict[str, dict[str, Any]] = {
        name: {
            "staff": name,
            "live": 0,
            "video": 0,
            "total": 0,
            "by_league": {},
            "fixtures": [],
        }
        for name in FIXTURE_STAFF
    }

    totals = {"assigned": 0, "live": 0, "video": 0, "scouting_reports": 0}
    by_league: dict[str, int] = {}

    for row in rows:
        names = list(row.get("staff_names") or [])
        if not names:
            label = str(row.get("staff") or "").strip()
            names = [label] if label else []
        if not names:
            continue

        totals["assigned"] += 1
        if row["watch_type"] == "LIVE":
            totals["live"] += 1
        elif row["watch_type"] == "VIDEO":
            totals["video"] += 1
        league = row.get("league") or "Unknown"
        by_league[league] = by_league.get(league, 0) + 1
        totals["scouting_reports"] += int(row.get("scouting_report_count") or 0)

        for staff_name in names:
            bucket = by_staff.setdefault(
                staff_name,
                {
                    "staff": staff_name,
                    "live": 0,
                    "video": 0,
                    "total": 0,
                    "by_league": {},
                    "fixtures": [],
                },
            )
            bucket["total"] += 1
            if row["watch_type"] == "LIVE":
                bucket["live"] += 1
            elif row["watch_type"] == "VIDEO":
                bucket["video"] += 1
            bucket["by_league"][league] = bucket["by_league"].get(league, 0) + 1
            person_row = dict(row)
            person_row["staff"] = staff_name
            bucket["fixtures"].append(person_row)

    staff_rows = [by_staff[name] for name in FIXTURE_STAFF if by_staff[name]["total"]]
    for name, bucket in by_staff.items():
        if name not in FIXTURE_STAFF and bucket["total"]:
            staff_rows.append(bucket)
    staff_rows.sort(key=lambda row: (-int(row["total"]), row["staff"]))

    payload = {
        "seasons": seasons,
        "include_past": include_past,
        "staff_filter": staff or "",
        "totals": totals,
        "by_league": by_league,
        "staff": staff_rows,
        "assignments_updated_at": get_fixture_assignments().get("updated_at"),
        "scouting_reports_updated_at": get_scouting_reports().get("updated_at"),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _scout_ops_cache_set(cache_key, payload)
    return payload


SCOUT_SUMMARY_PERIODS: dict[str, str] = {
    "all": "All time",
    "this_week": "This week",
    "last_week": "Last week",
    "next_week": "Next week",
    "this_month": "This month",
    "last_month": "Last month",
    "last_3_months": "Last 3 months",
    "last_6_months": "Last 6 months",
    "this_season": "This season",
    "last_season": "Last season",
    "upcoming": "Upcoming",
}


def _football_week_start(date_key: str) -> str:
    date = datetime.fromisoformat(f"{date_key}T12:00:00").date()
    weekday = date.weekday()
    if weekday == 5:
        days_back = 0
    elif weekday == 6:
        days_back = 1
    else:
        days_back = weekday + 2
    return (date - timedelta(days=days_back)).isoformat()


def _add_days(date_key: str, days: int) -> str:
    date = datetime.fromisoformat(f"{date_key}T12:00:00").date()
    return (date + timedelta(days=days)).isoformat()


def scout_summary_period_range(period_id: str) -> dict[str, str | None] | None:
    today = datetime.now(UTC).date().isoformat()
    if period_id == "this_week":
        start = _football_week_start(today)
        return {"start": start, "end": _add_days(start, 6)}
    if period_id == "last_week":
        start = _add_days(_football_week_start(today), -7)
        return {"start": start, "end": _add_days(start, 6)}
    if period_id == "next_week":
        start = _add_days(_football_week_start(today), 7)
        return {"start": start, "end": _add_days(start, 6)}
    if period_id == "this_month":
        now = datetime.now(UTC)
        last_day = monthrange(now.year, now.month)[1]
        return {
            "start": datetime(now.year, now.month, 1).date().isoformat(),
            "end": datetime(now.year, now.month, last_day).date().isoformat(),
        }
    if period_id == "last_month":
        now = datetime.now(UTC)
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1
        last_day = monthrange(year, month)[1]
        return {
            "start": datetime(year, month, 1).date().isoformat(),
            "end": datetime(year, month, last_day).date().isoformat(),
        }
    if period_id == "upcoming":
        return {"start": today, "end": None}
    if period_id == "this_season":
        return _football_season_date_range(DEFAULT_SEASON)
    if period_id == "last_season":
        return _football_season_date_range(_previous_season_code(DEFAULT_SEASON))
    if period_id == "last_3_months":
        now = datetime.now(UTC).date()
        return {"start": (now - timedelta(days=90)).isoformat(), "end": today}
    if period_id == "last_6_months":
        now = datetime.now(UTC).date()
        return {"start": (now - timedelta(days=183)).isoformat(), "end": today}
    return None


def _previous_season_code(season_code: str) -> str:
    parts = str(season_code or DEFAULT_SEASON).split("/")
    if len(parts) != 2:
        return "25/26"
    year = int(parts[0])
    return f"{year - 1:02d}/{year:02d}"


def _football_season_date_range(season_code: str) -> dict[str, str]:
    parts = str(season_code or DEFAULT_SEASON).split("/")
    if len(parts) != 2:
        now = datetime.now(UTC)
        return {
            "start": datetime(now.year, 8, 1).date().isoformat(),
            "end": datetime(now.year + 1, 7, 31).date().isoformat(),
        }
    start_year = 2000 + int(parts[0])
    return {
        "start": datetime(start_year, 8, 1).date().isoformat(),
        "end": datetime(start_year + 1, 7, 31).date().isoformat(),
    }


def filter_scout_summary_by_date_range(
    payload: dict[str, Any],
    *,
    date_from: str | None,
    date_to: str | None,
    period_label: str,
) -> dict[str, Any]:
    if not payload:
        return {}

    if not date_from and not date_to:
        filtered = json.loads(json.dumps(payload))
        filtered["period"] = "all"
        filtered["period_label"] = period_label or SCOUT_SUMMARY_PERIODS["all"]
        filtered["period_range"] = None
        return filtered

    filtered_staff: list[dict[str, Any]] = []
    for staff_row in payload.get("staff") or []:
        fixtures = [
            fixture
            for fixture in (staff_row.get("fixtures") or [])
            if _fixture_in_date_range(fixture, date_from=date_from, date_to=date_to)
        ]
        if not fixtures:
            continue
        live = sum(1 for fixture in fixtures if fixture.get("watch_type") == "LIVE")
        video = sum(1 for fixture in fixtures if fixture.get("watch_type") == "VIDEO")
        filtered_staff.append(
            {
                **staff_row,
                "fixtures": fixtures,
                "total": len(fixtures),
                "live": live,
                "video": video,
            }
        )

    totals = {"assigned": 0, "live": 0, "video": 0, "scouting_reports": 0}
    by_league: dict[str, int] = {}
    for staff_row in filtered_staff:
        for fixture in staff_row.get("fixtures") or []:
            totals["assigned"] += 1
            if fixture.get("watch_type") == "LIVE":
                totals["live"] += 1
            if fixture.get("watch_type") == "VIDEO":
                totals["video"] += 1
            totals["scouting_reports"] += int(fixture.get("scouting_report_count") or 0)
            league = str(fixture.get("league") or "Unknown")
            by_league[league] = by_league.get(league, 0) + 1

    return {
        **payload,
        "staff": filtered_staff,
        "totals": totals,
        "by_league": by_league,
        "period": "custom",
        "period_label": period_label,
        "period_range": {"start": date_from, "end": date_to},
    }


def _fixture_in_date_range(
    fixture: dict[str, Any],
    *,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    date_key = str(fixture.get("date") or "").strip()
    if not date_key:
        return False
    if date_from and date_key < date_from:
        return False
    if date_to and date_key > date_to:
        return False
    return True


def _fixture_in_period(fixture: dict[str, Any], period_id: str) -> bool:
    if not period_id or period_id == "all":
        return True
    date_key = str(fixture.get("date") or "").strip()
    if not date_key:
        return False
    period_range = scout_summary_period_range(period_id)
    if not period_range:
        return True
    start = period_range.get("start")
    end = period_range.get("end")
    if start and date_key < start:
        return False
    if end and date_key > end:
        return False
    return True


def filter_scout_summary_by_period(payload: dict[str, Any], period_id: str) -> dict[str, Any]:
    if not payload:
        return {}
    if not period_id or period_id == "all":
        filtered = json.loads(json.dumps(payload))
        filtered["period"] = "all"
        filtered["period_label"] = SCOUT_SUMMARY_PERIODS["all"]
        return filtered

    filtered_staff: list[dict[str, Any]] = []
    for staff_row in payload.get("staff") or []:
        fixtures = [
            fixture
            for fixture in (staff_row.get("fixtures") or [])
            if _fixture_in_period(fixture, period_id)
        ]
        if not fixtures:
            continue
        live = sum(1 for fixture in fixtures if fixture.get("watch_type") == "LIVE")
        video = sum(1 for fixture in fixtures if fixture.get("watch_type") == "VIDEO")
        filtered_staff.append(
            {
                **staff_row,
                "fixtures": fixtures,
                "total": len(fixtures),
                "live": live,
                "video": video,
            }
        )

    totals = {"assigned": 0, "live": 0, "video": 0, "scouting_reports": 0}
    by_league: dict[str, int] = {}
    for staff_row in filtered_staff:
        for fixture in staff_row.get("fixtures") or []:
            totals["assigned"] += 1
            if fixture.get("watch_type") == "LIVE":
                totals["live"] += 1
            if fixture.get("watch_type") == "VIDEO":
                totals["video"] += 1
            totals["scouting_reports"] += int(fixture.get("scouting_report_count") or 0)
            league = str(fixture.get("league") or "Unknown")
            by_league[league] = by_league.get(league, 0) + 1

    return {
        **payload,
        "staff": filtered_staff,
        "totals": totals,
        "by_league": by_league,
        "period": period_id,
        "period_label": SCOUT_SUMMARY_PERIODS.get(period_id, period_id),
        "period_range": scout_summary_period_range(period_id),
    }


def _fixture_label(fixture: dict[str, Any]) -> str:
    home = str(fixture.get("home") or "").strip()
    away = str(fixture.get("away") or "").strip()
    date_key = str(fixture.get("date") or "").strip()
    teams = f"{home} vs {away}".strip(" vs")
    return f"{teams} ({date_key})" if date_key else teams


def _format_export_period_label(date_from: str | None, date_to: str | None) -> str:
    if date_from and date_to:
        return f"{date_from} to {date_to}"
    if date_from:
        return f"From {date_from}"
    if date_to:
        return f"Up to {date_to}"
    return SCOUT_SUMMARY_PERIODS["all"]


def _parse_export_date(value: str | None) -> str | None:
    clean = str(value or "").strip()[:10]
    if not clean:
        return None
    try:
        datetime.fromisoformat(f"{clean}T12:00:00")
    except ValueError as exc:
        raise ValueError(f"Invalid date: {clean}") from exc
    return clean


def _fixture_team_names(fixture: dict[str, Any]) -> list[str]:
    return [name for name, _side in _fixture_team_sides(fixture)]


def _fixture_team_sides(fixture: dict[str, Any]) -> list[tuple[str, str]]:
    sides: list[tuple[str, str]] = []
    for side in ("home", "away"):
        value = fixture.get(side)
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
        else:
            name = str(value or "").strip()
        if name:
            sides.append((name, side))
    return sides


def _build_league_team_exposure(
    payload: dict[str, Any],
    *,
    seasons: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 12,
) -> list[dict[str, Any]]:
    # Per team+fixture: watch type, home/away side, and whether the game has been played.
    team_fixture_meta: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    def remember_fixture(
        league: str,
        team: str,
        fixture_id: str,
        *,
        watch: str = "",
        side: str = "",
        played: bool = False,
    ) -> None:
        if not league or not team or not fixture_id:
            return
        key = (league, team)
        bucket = team_fixture_meta.setdefault(key, {})
        entry = bucket.setdefault(
            fixture_id,
            {"watch": "", "side": "", "played": False},
        )
        if side in {"home", "away"}:
            entry["side"] = side
        if played:
            entry["played"] = True
        watch_token = str(watch or "").strip().upper()
        if watch_token == "LIVE":
            entry["watch"] = "LIVE"
        elif watch_token == "VIDEO" and entry.get("watch") != "LIVE":
            entry["watch"] = "VIDEO"

    for fixture in _cached_fixtures_list(seasons, warm=True):
        if not _fixture_in_date_range(fixture, date_from=date_from, date_to=date_to):
            continue
        league = _normalize_league_label(fixture.get("league") or "Unknown")
        fixture_id = str(fixture.get("fixture_id") or "")
        if not fixture_id:
            continue
        played = _fixture_is_played(fixture)
        for team, side in _fixture_team_sides(fixture):
            remember_fixture(league, team, fixture_id, side=side, played=played)

    for staff_row in payload.get("staff") or []:
        for fixture in staff_row.get("fixtures") or []:
            league = _normalize_league_label(fixture.get("league") or "Unknown")
            fixture_id = str(fixture.get("fixture_id") or "")
            if not fixture_id:
                continue
            watch_type = str(fixture.get("watch_type") or "").strip().upper()
            played = _fixture_is_played(fixture)
            for team, side in _fixture_team_sides(fixture):
                remember_fixture(
                    league,
                    team,
                    fixture_id,
                    watch=watch_type,
                    side=side,
                    played=played,
                )

    leagues_map: dict[str, list[dict[str, Any]]] = {}
    for (league, team), fixture_map in team_fixture_meta.items():
        entries = list(fixture_map.values())
        played = sum(1 for entry in entries if entry.get("played"))
        live = sum(
            1
            for entry in entries
            if entry.get("played") and entry.get("watch") == "LIVE"
        )
        video = sum(
            1
            for entry in entries
            if entry.get("played") and entry.get("watch") == "VIDEO"
        )
        not_seen = sum(
            1 for entry in entries if entry.get("played") and not entry.get("watch")
        )
        watched_home = sum(
            1
            for entry in entries
            if entry.get("played")
            and entry.get("watch") in {"LIVE", "VIDEO"}
            and entry.get("side") == "home"
        )
        watched_away = sum(
            1
            for entry in entries
            if entry.get("played")
            and entry.get("watch") in {"LIVE", "VIDEO"}
            and entry.get("side") == "away"
        )
        scheduled = len(entries)
        if not played and not live and not video:
            continue
        leagues_map.setdefault(league, []).append(
            {
                "team": team,
                "live": live,
                "video": video,
                "not_seen": not_seen,
                "played": played,
                "watched_home": watched_home,
                "watched_away": watched_away,
                "scheduled": scheduled,
                # Bar scale / right-hand total = games already played.
                "total": played,
            }
        )

    charts: list[dict[str, Any]] = []
    for league in sorted(leagues_map.keys(), key=str.casefold):
        teams = sorted(
            leagues_map[league],
            key=lambda row: (
                -int(row.get("live") or 0) - int(row.get("video") or 0),
                -int(row.get("played") or 0),
                str(row.get("team") or "").casefold(),
            ),
        )[:top_n]
        if teams:
            charts.append({"league": league, "teams": teams})
    return charts


def _build_league_coverage_charts(
    payload: dict[str, Any],
    *,
    seasons: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    league_live: dict[str, int] = {}
    league_video: dict[str, int] = {}
    covered_ids: dict[str, set[str]] = {}

    for staff_row in payload.get("staff") or []:
        for fixture in staff_row.get("fixtures") or []:
            league = str(fixture.get("league") or "Unknown")
            fixture_id = str(fixture.get("fixture_id") or "")
            seen = covered_ids.setdefault(league, set())
            if fixture_id and fixture_id in seen:
                continue
            if fixture_id:
                seen.add(fixture_id)
            watch_type = str(fixture.get("watch_type") or "").strip().upper()
            if watch_type == "LIVE":
                league_live[league] = league_live.get(league, 0) + 1
            elif watch_type == "VIDEO":
                league_video[league] = league_video.get(league, 0) + 1

    league_totals: dict[str, int] = {}
    for fixture in _cached_fixtures_list(seasons, warm=True):
        if not _fixture_in_date_range(fixture, date_from=date_from, date_to=date_to):
            continue
        league = str(fixture.get("league") or "Unknown")
        league_totals[league] = league_totals.get(league, 0) + 1

    charts: list[dict[str, Any]] = []
    for league in sorted(set(league_live) | set(league_video) | set(league_totals), key=str.casefold):
        live = league_live.get(league, 0)
        video = league_video.get(league, 0)
        total = league_totals.get(league, live + video)
        not_covered = max(0, total - live - video)
        charts.append(
            {
                "league": league,
                "live": live,
                "video": video,
                "not_covered": not_covered,
                "total": total,
            }
        )
    charts.sort(key=lambda row: (-int(row.get("total") or 0), str(row.get("league") or "")))
    return charts


def build_scout_summary_export_payload(
    *,
    season: str | None = None,
    include_past: bool = True,
    staff: str | None = None,
    period: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    period_label: str | None = None,
) -> dict[str, Any]:
    raw_payload = build_scout_summary_payload(
        season=season,
        include_past=include_past,
        staff=staff,
    )

    if date_from or date_to:
        label = period_label or _format_export_period_label(date_from, date_to)
        payload = filter_scout_summary_by_date_range(
            raw_payload,
            date_from=date_from,
            date_to=date_to,
            period_label=label,
        )
    else:
        if period not in SCOUT_SUMMARY_PERIODS:
            raise ValueError(
                f"Period must be one of: {', '.join(SCOUT_SUMMARY_PERIODS)}"
            )
        payload = filter_scout_summary_by_period(raw_payload, period)

    if not staff:
        staff_by_name = {row.get("staff"): row for row in payload.get("staff") or []}
        payload["staff"] = [
            staff_by_name.get(
                name,
                {
                    "staff": name,
                    "live": 0,
                    "video": 0,
                    "total": 0,
                    "by_league": {},
                    "fixtures": [],
                },
            )
            for name in FIXTURE_STAFF
        ]

    team_counts: dict[str, int] = {}
    player_map: dict[str, dict[str, Any]] = {}
    position_counts: dict[str, dict[str, Any]] = {
        str(bucket["id"]): {
            "bucket_id": str(bucket["id"]),
            "label": str(bucket["label"]),
            "report_count": 0,
            "player_count": 0,
            "players": set(),
        }
        for bucket in POSITION_REPORT_BUCKETS
    }
    position_counts["unknown"] = {
        "bucket_id": "unknown",
        "label": "Unknown",
        "report_count": 0,
        "player_count": 0,
        "players": set(),
    }

    for staff_row in payload.get("staff") or []:
        for fixture in staff_row.get("fixtures") or []:
            for team_name in (fixture.get("home"), fixture.get("away")):
                team = str(team_name or "").strip()
                if team:
                    team_counts[team] = team_counts.get(team, 0) + 1

            for report in fixture.get("scouting_reports") or []:
                player_id = str(report.get("player_id") or report.get("player_name") or "")
                if not player_id:
                    continue
                pos_info = normalize_report_position(report.get("position"))
                entry = player_map.setdefault(
                    player_id,
                    {
                        "player_id": report.get("player_id"),
                        "player_name": str(report.get("player_name") or ""),
                        "team": str(report.get("team") or ""),
                        "position": pos_info["raw"],
                        "position_label": pos_info["label"],
                        "position_bucket": pos_info["bucket_id"],
                        "report_count": 0,
                        "fixtures": [],
                        "staff": [],
                    },
                )
                entry["report_count"] += 1
                if pos_info["raw"] and not entry.get("position"):
                    entry["position"] = pos_info["raw"]
                    entry["position_label"] = pos_info["label"]
                    entry["position_bucket"] = pos_info["bucket_id"]
                elif pos_info["bucket_id"] != "unknown" and entry.get("position_bucket") == "unknown":
                    entry["position"] = pos_info["raw"]
                    entry["position_label"] = pos_info["label"]
                    entry["position_bucket"] = pos_info["bucket_id"]
                report_staff = str(report.get("staff") or staff_row.get("staff") or "").strip()
                if report_staff and report_staff not in entry["staff"]:
                    entry["staff"].append(report_staff)
                label = _fixture_label(fixture)
                if label not in entry["fixtures"]:
                    entry["fixtures"].append(label)

                bucket = position_counts.setdefault(
                    pos_info["bucket_id"],
                    {
                        "bucket_id": pos_info["bucket_id"],
                        "label": pos_info["label"],
                        "report_count": 0,
                        "player_count": 0,
                        "players": set(),
                    },
                )
                bucket["report_count"] += 1
                bucket["players"].add(player_id)

    ranked_teams = sorted(team_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    min_count = ranked_teams[-1][1] if ranked_teams else 0
    least_seen = sorted(
        [item for item in ranked_teams if item[1] == min_count],
        key=lambda item: item[0].casefold(),
    )

    payload["player_reports"] = sorted(
        player_map.values(),
        key=lambda row: (-int(row.get("report_count") or 0), str(row.get("player_name") or "").casefold()),
    )

    position_rows: list[dict[str, Any]] = []
    for bucket in list(POSITION_REPORT_BUCKETS) + [
        {"id": "unknown", "label": "Unknown"},
    ]:
        row = position_counts.get(str(bucket["id"])) or {
            "bucket_id": str(bucket["id"]),
            "label": str(bucket["label"]),
            "report_count": 0,
            "players": set(),
        }
        players = row.get("players") or set()
        position_rows.append(
            {
                "bucket_id": str(row.get("bucket_id") or bucket["id"]),
                "label": str(row.get("label") or bucket["label"]),
                "report_count": int(row.get("report_count") or 0),
                "player_count": len(players),
            }
        )
    payload["position_reports"] = position_rows

    staff_by_name = {str(row.get("staff") or ""): row for row in (payload.get("staff") or [])}
    staff_team_rows: list[dict[str, Any]] = []
    for team in FIXTURE_STAFF_TEAMS:
        members: list[dict[str, Any]] = []
        team_live = 0
        team_video = 0
        team_total = 0
        team_by_league: dict[str, int] = {}
        for name in team["members"]:
            member = staff_by_name.get(name) or {
                "staff": name,
                "live": 0,
                "video": 0,
                "total": 0,
                "by_league": {},
            }
            members.append(
                {
                    "staff": name,
                    "live": int(member.get("live") or 0),
                    "video": int(member.get("video") or 0),
                    "total": int(member.get("total") or 0),
                    "by_league": dict(member.get("by_league") or {}),
                }
            )
            team_live += int(member.get("live") or 0)
            team_video += int(member.get("video") or 0)
            team_total += int(member.get("total") or 0)
            for league, count in (member.get("by_league") or {}).items():
                team_by_league[str(league)] = team_by_league.get(str(league), 0) + int(count or 0)
        member_count = len(team["members"])
        staff_team_rows.append(
            {
                "id": team["id"],
                "label": team["label"],
                "members": members,
                "live": team_live,
                "video": team_video,
                "total": team_total,
                "avg_per_member": round(team_total / member_count, 1) if member_count else 0.0,
                "by_league": team_by_league,
            }
        )
    payload["staff_teams"] = staff_team_rows

    recommendations = [
        {
            "player_name": row.get("player_name"),
            "team": row.get("team"),
            "position_label": row.get("position_label") or "Unknown",
            "report_count": row.get("report_count"),
            "staff": ", ".join(row.get("staff") or []),
        }
        for row in payload["player_reports"]
        if int(row.get("report_count") or 0) >= 1
    ][:8]
    payload["recommendations"] = recommendations

    payload["most_seen_teams"] = ranked_teams[:12]
    payload["least_seen_teams"] = least_seen[:12]
    payload["team_counts"] = team_counts

    period_range = payload.get("period_range") or {}
    chart_from = date_from or period_range.get("start")
    chart_to = date_to or period_range.get("end")
    if payload.get("period") == "all" and not chart_from and not chart_to:
        chart_from = None
        chart_to = None
    payload["league_coverage"] = _build_league_coverage_charts(
        payload,
        seasons=list(payload.get("seasons") or []),
        date_from=chart_from,
        date_to=chart_to,
    )
    payload["league_team_exposure"] = _build_league_team_exposure(
        payload,
        seasons=list(payload.get("seasons") or []),
        date_from=chart_from,
        date_to=chart_to,
    )
    return payload


def build_scout_summary_report_payload(
    *,
    season: str | None = None,
    include_past: bool = True,
    staff: str | None = None,
    period: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    period_label: str | None = None,
) -> dict[str, Any]:
    payload = build_scout_summary_export_payload(
        season=season,
        include_past=include_past,
        staff=staff,
        period=period,
        date_from=date_from,
        date_to=date_to,
        period_label=period_label,
    )
    staff_rows: list[dict[str, Any]] = []
    for row in payload.get("staff") or []:
        staff_rows.append(
            {
                "staff": row.get("staff"),
                "live": row.get("live"),
                "video": row.get("video"),
                "total": row.get("total"),
            }
        )
    league_entries = sorted(
        (payload.get("by_league") or {}).items(),
        key=lambda item: (-item[1], item[0]),
    )
    total_games = sum(count for _league, count in league_entries)
    league_chart = [
        {
            "league": league,
            "count": count,
            "pct": round((count / total_games) * 100, 1) if total_games else 0.0,
        }
        for league, count in league_entries
    ]
    player_reports = [
        {
            "player_name": row.get("player_name"),
            "team": row.get("team"),
            "position_label": row.get("position_label") or "Unknown",
            "report_count": row.get("report_count"),
            "staff": row.get("staff") or [],
        }
        for row in (payload.get("player_reports") or [])
    ]
    position_reports = [
        {
            "bucket_id": row.get("bucket_id"),
            "label": row.get("label"),
            "report_count": row.get("report_count"),
            "player_count": row.get("player_count"),
        }
        for row in (payload.get("position_reports") or [])
    ]
    staff_teams = [
        {
            "id": row.get("id"),
            "label": row.get("label"),
            "live": row.get("live"),
            "video": row.get("video"),
            "total": row.get("total"),
            "avg_per_member": row.get("avg_per_member"),
            "members": [
                {
                    "staff": member.get("staff"),
                    "live": member.get("live"),
                    "video": member.get("video"),
                    "total": member.get("total"),
                }
                for member in (row.get("members") or [])
            ],
        }
        for row in (payload.get("staff_teams") or [])
    ]
    return {
        "seasons": payload.get("seasons") or [],
        "staff_filter": payload.get("staff_filter") or "",
        "period": payload.get("period") or period,
        "period_label": payload.get("period_label") or period_label or "All time",
        "period_range": payload.get("period_range"),
        "generated_at": payload.get("generated_at"),
        "totals": payload.get("totals") or {},
        "staff": staff_rows,
        "staff_teams": staff_teams,
        "league_chart": league_chart,
        "league_coverage": payload.get("league_coverage") or [],
        "league_team_exposure": payload.get("league_team_exposure") or [],
        "player_reports": player_reports,
        "position_reports": position_reports,
        "recommendations": payload.get("recommendations") or [],
        "most_seen_teams": [
            {"team": team, "count": count}
            for team, count in (payload.get("most_seen_teams") or [])
        ],
        "least_seen_teams": [
            {"team": team, "count": count}
            for team, count in (payload.get("least_seen_teams") or [])
        ],
    }


def build_scouts_calendar_payload(
    *,
    season: str | None = None,
    staff: str | None = None,
    watch_type: str = "ALL",
    include_past: bool = True,
) -> dict[str, Any]:
    watch_filter = str(watch_type or "ALL").strip().upper()
    if watch_filter not in ("LIVE", "VIDEO", "ALL"):
        watch_filter = "ALL"
    cache_key = f"calendar|{season or 'ALL'}|{watch_filter}|{include_past}|{staff or ''}"
    cached = _scout_ops_cache_get(cache_key)
    if cached is not None:
        return cached

    seasons = [season] if season in ALLOWED_FIXTURE_SEASONS else list(ALLOWED_FIXTURE_SEASONS)

    rows = _expand_calendar_staff_rows(
        _assignment_rows_for_seasons(
            seasons,
            include_past=include_past,
            staff=staff or None,
            watch_type=None if watch_filter == "ALL" else watch_filter,
        )
    )

    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = row.get("date") or ""
        if not day:
            continue
        by_date.setdefault(day, []).append(row)

    payload = {
        "seasons": seasons,
        "staff": staff or "",
        "watch_type": watch_filter,
        "include_past": include_past,
        "fixtures": rows,
        "by_date": by_date,
        "assignments_updated_at": get_fixture_assignments().get("updated_at"),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _scout_ops_cache_set(cache_key, payload)
    return payload


MATCH_ENRICHMENT_CACHE_TTL_SECONDS = 3600
FORMATION_LAYOUT_VERSION = "v5"
PXT_SQUAD_SCORE_ID = 48
PLAYER_PXT_SCORE_ID = 194
MATCH_PLAYER_POSITIONS: tuple[str, ...] = (
    "GOALKEEPER",
    "CENTRAL_DEFENDER",
    "LEFT_WINGBACK_DEFENDER",
    "RIGHT_WINGBACK_DEFENDER",
    "DEFENSE_MIDFIELD",
    "CENTRAL_MIDFIELD",
    "ATTACKING_MIDFIELD",
    "LEFT_WINGER",
    "RIGHT_WINGER",
    "CENTER_FORWARD",
    "SECOND_STRIKER",
)
_enrichment_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_enrichment_cache_lock = threading.Lock()
_squad_score_catalog_cache: tuple[float, dict[int, str]] | None = None
_player_names_cache: dict[int, tuple[float, dict[int, str]]] = {}
_fotmob_venue_cache: dict[str, tuple[float, str | None]] = {}


def _squad_score_names() -> dict[int, str]:
    global _squad_score_catalog_cache
    now = time.time()
    if _squad_score_catalog_cache and now - _squad_score_catalog_cache[0] < MATCH_ENRICHMENT_CACHE_TTL_SECONDS:
        return _squad_score_catalog_cache[1]

    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/squad-scores")["data"]
    catalog = raw.get("data") if isinstance(raw, dict) else raw
    mapping = {
        int(row["id"]): str(row.get("name") or "")
        for row in catalog or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    _squad_score_catalog_cache = (now, mapping)
    return mapping


def _player_names_for_iteration(iteration_id: int) -> dict[int, str]:
    now = time.time()
    cached = _player_names_cache.get(iteration_id)
    if cached and now - cached[0] < MATCH_ENRICHMENT_CACHE_TTL_SECONDS:
        return cached[1]

    from app.pre_match import _player_names_map

    impect = _impect()
    players = _unwrap_items(
        impect._impect_get(impect._players_path(iteration_id))["data"]
    )
    mapping = _player_names_map(players)
    _player_names_cache[iteration_id] = (now, mapping)
    return mapping


def _fetch_match_squad_scores(match_id: int) -> dict[str, Any]:
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{match_id}/squad-scores")["data"]
    payload = raw.get("data") if isinstance(raw, dict) else raw
    return payload if isinstance(payload, dict) else {}


def _pxt_from_squad_scores(scores_payload: dict[str, Any]) -> dict[str, float | None]:
    result = {"home": None, "away": None}
    for side_key, target in (("squadHome", "home"), ("squadAway", "away")):
        squad = scores_payload.get(side_key) or {}
        for row in squad.get("squadScores") or []:
            if not isinstance(row, dict):
                continue
            if int(row.get("squadScoreId") or -1) == PXT_SQUAD_SCORE_ID:
                try:
                    result[target] = round(float(row.get("value") or 0), 2)
                except (TypeError, ValueError):
                    result[target] = None
                break
    return result


def _fotmob_venue_from_page(page_url: str | None) -> str | None:
    token = str(page_url or "").strip().split("#", 1)[0]
    if not token:
        return None

    now = time.time()
    cached = _fotmob_venue_cache.get(token)
    if cached and now - cached[0] < MATCH_ENRICHMENT_CACHE_TTL_SECONDS:
        return cached[1]

    venue: str | None = None
    try:
        response = _http.get(
            f"https://www.fotmob.com{token}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=3,
        )
        if response.ok:
            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                response.text,
                re.S,
            )
            if match:
                payload = json.loads(match.group(1))
                info_box = (
                    ((payload.get("props") or {}).get("pageProps") or {})
                    .get("content") or {}
                ).get("matchFacts") or {}
                info_box = info_box.get("infoBox") or {}
                stadium = info_box.get("Stadium") or {}
                name = str(stadium.get("name") or "").strip()
                city = str(stadium.get("city") or "").strip()
                if name and city:
                    venue = f"{name}, {city}"
                elif name:
                    venue = name
    except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError, ValueError):
        venue = None

    _fotmob_venue_cache[token] = (now, venue)
    return venue


def _lineup_from_detail(
    detail: dict[str, Any],
    squad_id: int,
    player_names: dict[int, str],
) -> dict[str, Any] | None:
    from app.match_player_utils import _position_abbr
    from app.pre_match import _match_squad_block, _shirt_map_from_squad_block

    squad = _match_squad_block(detail, squad_id)
    if not squad:
        return None
    shirts = _shirt_map_from_squad_block(squad)
    players: list[dict[str, Any]] = []
    for row in squad.get("startingPositions") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        position_code = str(row.get("position") or "")
        players.append(
            {
                "player_id": player_id,
                "name": player_names.get(player_id, f"Player {player_id}"),
                "shirt_number": shirts.get(player_id),
                "position": _position_abbr(position_code),
                "position_code": position_code,
            }
        )
    if not players:
        return None
    return {
        "formation": str(squad.get("startingFormation") or "").strip() or None,
        "players": players,
    }


def _player_pxt_lookup(match_id: int) -> dict[int, float]:
    from app.scouting_monthly import _fetch_match_position_scores

    lookup: dict[int, float] = {}
    for position in MATCH_PLAYER_POSITIONS:
        try:
            for row in _fetch_match_position_scores(match_id, position):
                player_id = int(row.get("playerId") or 0)
                if not player_id:
                    continue
                for score in row.get("playerScores") or []:
                    if not isinstance(score, dict):
                        continue
                    if int(score.get("playerScoreId") or -1) != PLAYER_PXT_SCORE_ID:
                        continue
                    try:
                        lookup[player_id] = round(float(score.get("value") or 0), 2)
                    except (TypeError, ValueError):
                        pass
                    break
        except HTTPException:
            continue
    return lookup


def _attach_player_pxt_to_lineups(
    lineups: dict[str, Any],
    pxt_lookup: dict[int, float],
) -> None:
    for side in ("home", "away"):
        lineup = lineups.get(side)
        if not isinstance(lineup, dict):
            continue
        for player in lineup.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = int(player.get("player_id") or 0)
            if player_id and player_id in pxt_lookup:
                player["pxt"] = pxt_lookup[player_id]


def _player_photo_api_url(name: str) -> str | None:
    from app.squad_photos import player_photo_available

    clean = str(name or "").strip()
    if not clean or not player_photo_available(clean):
        return None
    return f"/api/player-photo?name={quote(clean)}"


def _finalize_lineup_layout(lineup: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(lineup, dict):
        return None
    from app.pre_match import assign_lineup_formation_slots, _normalize_formation_key
    from app.match_player_utils import _position_abbr

    pool: list[dict[str, Any]] = []
    for player in lineup.get("players") or []:
        if not isinstance(player, dict):
            continue
        position_code = str(player.get("position_code") or player.get("position") or "")
        pool.append(
            {
                **player,
                "position": position_code,
            }
        )
    if not pool:
        return lineup

    formation_key = _normalize_formation_key(lineup.get("formation"))
    positioned = assign_lineup_formation_slots(pool, formation_key)
    for player in positioned:
        position_code = str(player.get("position") or player.get("position_code") or "")
        player["position_code"] = position_code
        player["position"] = _position_abbr(position_code)
        photo_url = _player_photo_api_url(str(player.get("name") or ""))
        if photo_url:
            player["photo_url"] = photo_url

    return {
        **lineup,
        "players": positioned,
    }


def _enrich_completed_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture_key = f"{FORMATION_LAYOUT_VERSION}:{fixture.get('fixture_id') or ''}"
    now = time.time()
    with _enrichment_cache_lock:
        cached = _enrichment_cache.get(fixture_key)
        if cached and now - cached[0] < MATCH_ENRICHMENT_CACHE_TTL_SECONDS:
            return cached[1]

    enrichment: dict[str, Any] = {
        "fixture_id": fixture_key,
        "venue": None,
        "pxt": {"home": None, "away": None},
        "lineups": {"home": None, "away": None},
        "home_team": fixture.get("home"),
        "away_team": fixture.get("away"),
        "score": fixture.get("score"),
        "source": None,
    }

    match_id = fixture.get("match_id")
    iteration_id = fixture.get("iteration_id")
    home_id = int((fixture.get("home") or {}).get("id") or 0)
    away_id = int((fixture.get("away") or {}).get("id") or 0)

    if match_id and iteration_id and home_id and away_id:
        from app.pre_match import _fetch_match_detail

        try:
            detail = _fetch_match_detail(int(match_id))
            player_names = _player_names_for_iteration(int(iteration_id))
            enrichment["lineups"]["home"] = _lineup_from_detail(detail, home_id, player_names)
            enrichment["lineups"]["away"] = _lineup_from_detail(detail, away_id, player_names)
            _attach_player_pxt_to_lineups(enrichment["lineups"], _player_pxt_lookup(int(match_id)))
            enrichment["lineups"]["home"] = _finalize_lineup_layout(enrichment["lineups"]["home"])
            enrichment["lineups"]["away"] = _finalize_lineup_layout(enrichment["lineups"]["away"])
            scores_payload = _fetch_match_squad_scores(int(match_id))
            enrichment["pxt"] = _pxt_from_squad_scores(scores_payload)
            enrichment["source"] = "impect"
        except HTTPException:
            pass

    venue = _fotmob_venue_from_page(fixture.get("fotmob_page_url"))
    if venue:
        enrichment["venue"] = venue
    elif (fixture.get("home") or {}).get("name"):
        enrichment["venue"] = f"{(fixture.get('home') or {}).get('name')} (home)"

    with _enrichment_cache_lock:
        _enrichment_cache[fixture_key] = (now, enrichment)
    return enrichment


def _fixtures_from_season_cache(season: str) -> list[dict[str, Any]]:
    cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
    with _fixture_cache_lock:
        cached = _fixture_cache.get(cache_key)
    if not cached:
        return []
    return list(cached[1].get("fixtures") or [])


def build_match_enrichment_payload(
    *,
    season: str,
    fixture_ids: list[str],
    hints: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fixtures = _fixtures_from_season_cache(season)
    if not fixtures:
        payload = build_fixture_planner_payload(season=season)
        fixtures = payload.get("fixtures") or []

    hints = hints or {}
    enrichments: dict[str, dict[str, Any]] = {}
    for fixture_id in fixture_ids[:30]:
        fixture = _resolve_fixture_record(
            fixture_id,
            fixtures,
            assignment=hints.get(fixture_id),
        )
        if not fixture or not _fixture_is_played(fixture):
            continue
        enrichments[fixture_id] = _enrich_completed_fixture(fixture)

    return {
        "season": season,
        "enrichments": enrichments,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _scout_summary_export_response(
    *,
    season: str | None,
    include_past: bool,
    staff: str | None,
    period: str,
    date_from: str | None,
    date_to: str | None,
    period_label: str | None,
    report_format: str,
) -> Response:
    from app.scout_summary_pdf import (
        build_scout_summary_one_pager_pdf,
        build_scout_summary_pdf,
        build_scout_summary_player_position_pdf,
        build_scout_summary_two_pager_pdf,
        scout_summary_export_filename,
    )

    report_format = str(report_format or "full").strip().lower()
    if report_format not in {"full", "one_pager", "two_pager", "player_position"}:
        raise HTTPException(
            status_code=400,
            detail="report_format must be 'full', 'two_pager', 'player_position', or 'one_pager'",
        )

    if season is not None and season not in ALLOWED_FIXTURE_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
        )
    if staff and staff not in FIXTURE_STAFF:
        raise HTTPException(status_code=400, detail=f"Unknown staff member: {staff}")

    parsed_from = _parse_export_date(date_from) if date_from else None
    parsed_to = _parse_export_date(date_to) if date_to else None
    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to")

    if not (parsed_from or parsed_to):
        if period not in SCOUT_SUMMARY_PERIODS:
            raise HTTPException(
                status_code=400,
                detail=f"Period must be one of: {', '.join(SCOUT_SUMMARY_PERIODS)}",
            )

    try:
        payload = build_scout_summary_export_payload(
            season=season,
            include_past=include_past,
            staff=staff,
            period=period,
            date_from=parsed_from,
            date_to=parsed_to,
            period_label=period_label,
        )
        if report_format == "one_pager":
            pdf_bytes = build_scout_summary_one_pager_pdf(payload)
        elif report_format == "two_pager":
            pdf_bytes = build_scout_summary_two_pager_pdf(payload)
        elif report_format == "player_position":
            pdf_bytes = build_scout_summary_player_position_pdf(payload)
        else:
            pdf_bytes = build_scout_summary_pdf(payload)
        filename = scout_summary_export_filename(payload, report_format=report_format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _email_fixture_rows(
    *,
    watch_types: set[str] | None = None,
    days_ahead: int | None = None,
    fetch_venues: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Build upcoming assigned fixture rows for bulk emails."""
    from app.fixture_assignment_email import _format_kickoff

    today = datetime.now(UTC).date()
    end_day = today + timedelta(days=int(days_ahead)) if days_ahead is not None else None
    rows = _assignment_rows_for_seasons(
        list(ALLOWED_FIXTURE_SEASONS),
        include_past=False,
    )
    fixtures: list[dict[str, Any]] = []
    for row in rows:
        watch = str(row.get("watch_type") or "").strip().upper()
        if watch_types and watch not in watch_types:
            continue
        date_key = str(row.get("date") or "").strip()[:10]
        if not date_key:
            continue
        try:
            day = datetime.fromisoformat(date_key).date()
        except ValueError:
            continue
        if day < today:
            continue
        if end_day is not None and day > end_day:
            continue

        venue = ""
        fixture_id = str(row.get("fixture_id") or "")
        if _fixture_is_postponed(fixture_id):
            continue
        try:
            resolved = _resolve_fixture_for_email(fixture_id, row) if fixture_id else None
        except Exception:
            resolved = None
        if isinstance(resolved, dict):
            page_url = resolved.get("fotmob_page_url")
            if fetch_venues and page_url:
                venue = _fotmob_venue_from_page(page_url) or ""
            if not venue:
                home = resolved.get("home") if isinstance(resolved.get("home"), dict) else {}
                venue = f"{(home or {}).get('name') or row.get('home') or 'Home'} (home)"

        fixtures.append(
            {
                "fixture_id": fixture_id,
                "home": row.get("home") or "Home",
                "away": row.get("away") or "Away",
                "league": row.get("league") or "",
                "staff": row.get("staff") or "",
                "watch_type": watch,
                "date": date_key,
                "kickoff_utc": row.get("kickoff_utc"),
                "kickoff_label": _format_kickoff(
                    str(row.get("kickoff_utc") or "") or None,
                    date_key,
                ),
                "venue": venue,
            }
        )

    if days_ahead is not None:
        period_label = (
            f"{today.strftime('%d %b %Y')} – {end_day.strftime('%d %b %Y')}"
            if end_day
            else today.strftime("%d %b %Y")
        )
    else:
        period_label = f"Upcoming from {today.strftime('%d %b %Y')}"
    return fixtures, period_label


def preview_admin_ticket_request() -> dict[str, Any]:
    fixtures, period_label = _email_fixture_rows(
        watch_types={"LIVE"},
        days_ahead=TICKET_REQUEST_DAYS_AHEAD,
    )
    requested = get_ticket_requests().get("requests") or {}
    new_fixtures: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for row in fixtures:
        fixture_id = str(row.get("fixture_id") or "")
        prior = requested.get(fixture_id) if fixture_id else None
        if isinstance(prior, dict):
            already.append(
                {
                    **row,
                    "tickets": prior.get("tickets", 1),
                    "parking": prior.get("parking") or "No",
                    "notes": prior.get("notes") or "",
                    "requested_at": prior.get("requested_at"),
                    "already_requested": True,
                }
            )
        else:
            new_fixtures.append({**row, "already_requested": False})

    return {
        "period_label": period_label,
        "days_ahead": TICKET_REQUEST_DAYS_AHEAD,
        "recipients": admin_team_emails(),
        "fixtures": new_fixtures,
        "already_requested": already,
        "fixture_count": len(new_fixtures),
        "already_requested_count": len(already),
        "total_live_in_window": len(fixtures),
    }


def send_admin_ticket_request(body: TicketRequestBody | None = None) -> dict[str, Any]:
    fixtures, period_label = _email_fixture_rows(
        watch_types={"LIVE"},
        days_ahead=TICKET_REQUEST_DAYS_AHEAD,
        fetch_venues=True,
    )
    requested = get_ticket_requests().get("requests") or {}
    detail_by_id = {
        str(item.fixture_id): item
        for item in ((body.fixtures if body else None) or [])
        if str(item.fixture_id or "").strip()
    }

    # Only fixtures in the fortnight window that have not already been emailed.
    candidates = [
        row
        for row in fixtures
        if str(row.get("fixture_id") or "")
        and str(row.get("fixture_id") or "") not in requested
    ]
    if detail_by_id:
        candidates = [
            row
            for row in candidates
            if str(row.get("fixture_id") or "") in detail_by_id
        ]

    enriched: list[dict[str, Any]] = []
    for row in candidates:
        fixture_id = str(row.get("fixture_id") or "")
        detail = detail_by_id.get(fixture_id)
        tickets = 1
        parking = "No"
        notes = ""
        if detail is not None:
            try:
                tickets = max(0, int(detail.tickets))
            except (TypeError, ValueError):
                tickets = 1
            parking = str(detail.parking or "No").strip() or "No"
            notes = str(detail.notes or "").strip()
        enriched.append(
            {
                **row,
                "tickets": tickets,
                "parking": parking,
                "notes": notes,
            }
        )

    if not enriched:
        return {
            "sent": False,
            "reason": "No new LIVE fixtures in the next two weeks to request (already sent or none assigned)",
            "period_label": period_label,
            "fixture_count": 0,
            "already_requested_count": len(
                [row for row in fixtures if str(row.get("fixture_id") or "") in requested]
            ),
            "recipients": admin_team_emails(),
            "fixtures": [],
        }

    additional = str((body.additional_requests if body else "") or "").strip()
    result = send_ticket_request_email(
        fixtures=enriched,
        period_label=f"{period_label} · new requests only",
        additional_requests=additional,
    )
    if result.get("sent"):
        mark_rows = [
            {
                "fixture_id": row.get("fixture_id"),
                "home": row.get("home"),
                "away": row.get("away"),
                "league": row.get("league"),
                "date": row.get("date"),
                "staff": row.get("staff"),
                "watch_type": row.get("watch_type"),
                "kickoff_utc": row.get("kickoff_utc"),
                "tickets": row.get("tickets"),
                "parking": row.get("parking"),
                "notes": row.get("notes"),
            }
            for row in enriched
        ]
        mark_ticket_requests_sent(mark_rows)

    result["period_label"] = period_label
    result["fixtures"] = [
        {
            "fixture_id": row.get("fixture_id"),
            "home": row.get("home"),
            "away": row.get("away"),
            "date": row.get("date"),
            "staff": row.get("staff"),
            "watch_type": row.get("watch_type"),
            "tickets": row.get("tickets"),
            "parking": row.get("parking"),
            "notes": row.get("notes"),
        }
        for row in enriched
    ]
    result["recipients"] = admin_team_emails()
    result["already_requested_count"] = len(
        [row for row in fixtures if str(row.get("fixture_id") or "") in requested]
    )
    return result


def send_fortnight_schedule_update() -> dict[str, Any]:
    fixtures, period_label = _email_fixture_rows(watch_types={"LIVE", "VIDEO"}, days_ahead=13)
    result = send_schedule_update_email(fixtures=fixtures, period_label=period_label)
    result["period_label"] = period_label
    result["fixtures"] = [
        {
            "home": row.get("home"),
            "away": row.get("away"),
            "date": row.get("date"),
            "staff": row.get("staff"),
            "watch_type": row.get("watch_type"),
        }
        for row in fixtures
    ]
    result["recipients"] = schedule_update_emails()
    return result


def _escape_html(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _reject_assignment_shell(*, title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape_html(title)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background: radial-gradient(1200px 600px at 20% -10%, #1e293b, #0b1220 55%);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #e2e8f0;
    }}
    .card {{
      width: min(520px, 100%);
      background: #111827;
      border: 1px solid #1f2937;
      border-radius: 16px;
      padding: 28px 26px;
      box-shadow: 0 24px 60px rgba(0,0,0,.35);
    }}
    h1 {{ margin: 0 0 8px; font-size: 1.45rem; color: #f8fafc; }}
    p {{ margin: 0 0 14px; line-height: 1.5; color: #94a3b8; font-size: .95rem; }}
    .meta {{
      margin: 0 0 18px;
      padding: 12px 14px;
      border-radius: 10px;
      background: #0f172a;
      border: 1px solid #1f2937;
      font-size: .9rem;
      color: #cbd5e1;
      line-height: 1.55;
    }}
    label {{ display:block; font-size:.82rem; color:#94a3b8; margin-bottom:6px; }}
    textarea {{
      width: 100%;
      min-height: 110px;
      box-sizing: border-box;
      border-radius: 10px;
      border: 1px solid #334155;
      background: #0b1220;
      color: #f8fafc;
      padding: 12px;
      font: inherit;
      resize: vertical;
    }}
    button {{
      margin-top: 14px;
      width: 100%;
      border: 0;
      border-radius: 10px;
      padding: 12px 16px;
      background: #7f1d1d;
      color: #fecaca;
      font-weight: 700;
      font-size: .95rem;
      cursor: pointer;
    }}
    button:hover {{ background: #991b1b; }}
    .ok {{ color: #86efac; }}
    .warn {{ color: #fbbf24; }}
  </style>
</head>
<body>
  <div class="card">
    {body_html}
  </div>
</body>
</html>
"""


def _reject_assignment_context(token: str) -> dict[str, Any]:
    parsed = parse_reject_token(token)
    if not parsed:
        return {"ok": False, "error": "This reject link is invalid or has expired."}

    fixture_id = str(parsed.get("fixture_id") or "").strip()
    staff = str(parsed.get("staff") or "").strip()
    store = _load_assignments_store()
    assignments: dict[str, Any] = store.get("assignments") or {}
    assignment = dict(assignments.get(fixture_id) or {})
    current_staff_names = _normalize_staff_names(assignment.get("staff"))
    current_staff = _staff_label(current_staff_names)
    parsed_id = _parse_fixture_id_parts(fixture_id) or {}

    fixture = _resolve_fixture_for_email(fixture_id, assignment) if assignment else {
        "fixture_id": fixture_id,
        "home": {"name": assignment.get("home") or _title_from_slug(parsed_id.get("home") or "")},
        "away": {"name": assignment.get("away") or _title_from_slug(parsed_id.get("away") or "")},
        "league": assignment.get("league") or parsed_id.get("league") or "",
        "date": assignment.get("date") or parsed_id.get("date") or "",
        "kickoff_utc": assignment.get("kickoff_utc"),
    }
    home = fixture.get("home") if isinstance(fixture.get("home"), dict) else {"name": fixture.get("home")}
    away = fixture.get("away") if isinstance(fixture.get("away"), dict) else {"name": fixture.get("away")}
    home_name = str(
        (home or {}).get("name")
        or assignment.get("home")
        or _title_from_slug(parsed_id.get("home") or "")
        or "Home"
    )
    away_name = str(
        (away or {}).get("name")
        or assignment.get("away")
        or _title_from_slug(parsed_id.get("away") or "")
        or "Away"
    )
    league = str(fixture.get("league") or assignment.get("league") or parsed_id.get("league") or "")
    watch_type = str(assignment.get("watch_type") or "LIVE")
    kickoff_label = _format_kickoff(
        str(fixture.get("kickoff_utc") or assignment.get("kickoff_utc") or "") or None,
        str(fixture.get("date") or assignment.get("date") or parsed_id.get("date") or "") or None,
    )

    status = "active"
    if not assignment or not current_staff_names:
        status = "already_cleared"
    elif staff.casefold() not in {name.casefold() for name in current_staff_names}:
        status = "reassigned"

    return {
        "ok": True,
        "token": token,
        "fixture_id": fixture_id,
        "staff": staff,
        "current_staff": current_staff,
        "status": status,
        "home": home_name,
        "away": away_name,
        "league": league,
        "watch_type": watch_type,
        "kickoff_label": kickoff_label,
        "assignment": assignment,
    }


def reject_assignment_page_html(*, token: str = "", message: str = "", error: str = "") -> str:
    if error:
        return _reject_assignment_shell(
            title="Reject fixture",
            body_html=f"<h1>Can't reject fixture</h1><p class='warn'>{_escape_html(error)}</p>",
        )
    if message:
        return _reject_assignment_shell(
            title="Fixture rejected",
            body_html=f"<h1 class='ok'>You're off this game</h1><p>{_escape_html(message)}</p>",
        )

    ctx = _reject_assignment_context(token)
    if not ctx.get("ok"):
        return reject_assignment_page_html(error=str(ctx.get("error") or "Invalid link"))

    staff = str(ctx["staff"])
    meta = (
        f"<strong>{_escape_html(ctx['home'])} vs {_escape_html(ctx['away'])}</strong><br>"
        f"{_escape_html(ctx['league'] or 'Fixture')} · {_escape_html(str(ctx['watch_type']).upper())}<br>"
        f"{_escape_html(ctx['kickoff_label'])}"
    )

    if ctx["status"] == "reassigned":
        return _reject_assignment_shell(
            title="Reassigned",
            body_html=(
                f"<h1>Assignment changed</h1>"
                f"<p>This fixture is now assigned to "
                f"<strong>{_escape_html(str(ctx['current_staff']))}</strong>, so your reject link no longer applies.</p>"
                f"<div class='meta'>{meta}</div>"
            ),
        )

    note = (
        "Hi {_name}, confirm below to remove yourself from this fixture. "
        "Please add a reason so Sam knows what's going on."
    ).format(_name=_escape_html(staff.split(" ")[0]))
    if ctx["status"] == "already_cleared":
        note = (
            f"Hi {_escape_html(staff.split(' ')[0])}, this fixture is already clear on the hub, "
            "but you can still send Sam a reason so he knows you can't cover."
        )

    body = f"""
    <h1>Reject this game?</h1>
    <p>{note}</p>
    <div class="meta">{meta}</div>
    <form method="post" action="/fixture-planner/reject-assignment">
      <input type="hidden" name="token" value="{_escape_html(token)}" />
      <label for="reason">Reason (required)</label>
      <textarea id="reason" name="reason" maxlength="800" required placeholder="e.g. clash with another game / travel issue"></textarea>
      <button type="submit">Confirm — remove me from this game</button>
    </form>
    """
    return _reject_assignment_shell(title="Reject fixture", body_html=body)


def process_reject_assignment(*, token: str, reason: str = "") -> dict[str, Any]:
    ctx = _reject_assignment_context(token)
    if not ctx.get("ok"):
        return {"ok": False, "error": str(ctx.get("error") or "Invalid link")}
    if ctx["status"] == "reassigned":
        return {
            "ok": False,
            "error": "This fixture has been reassigned to someone else.",
            "status": ctx["status"],
        }

    reason_clean = str(reason or "").strip()
    if not reason_clean:
        return {"ok": False, "error": "Please provide a reason before rejecting this game."}

    fixture_id = str(ctx["fixture_id"])
    staff = str(ctx["staff"])
    removed = False
    if ctx["status"] == "active":
        store = _load_assignments_store()
        assignments: dict[str, Any] = store.setdefault("assignments", {})
        current = dict(assignments.get(fixture_id) or {})
        current_names = _normalize_staff_names(current.get("staff"))
        if staff.casefold() not in {name.casefold() for name in current_names}:
            return {
                "ok": False,
                "error": "This fixture has been reassigned to someone else.",
                "status": "reassigned",
            }
        remaining = [name for name in current_names if name.casefold() != staff.casefold()]
        if remaining:
            current["staff"] = remaining
            current["updated_at"] = datetime.now(UTC).isoformat()
            assignments[fixture_id] = current
            _save_assignments_store(store)
            _mirror_assignment_to_live(fixture_id=fixture_id, assignment=current)
            try:
                from app.fixture_sheets_backup import sync_assignment_to_sheet

                sync_assignment_to_sheet(fixture_id, current)
            except Exception:  # noqa: BLE001
                logger = __import__("logging").getLogger(__name__)
                logger.exception("Sheets backup after reject failed for %s", fixture_id)
        else:
            assignments.pop(fixture_id, None)
            store["updated_at"] = datetime.now(UTC).isoformat()
            _save_assignments_store(store)
            _mirror_assignment_to_live(fixture_id=fixture_id, assignment={})
            try:
                from app.fixture_sheets_backup import remove_assignment_from_sheet

                remove_assignment_from_sheet(fixture_id)
            except Exception:  # noqa: BLE001
                logger = __import__("logging").getLogger(__name__)
                logger.exception("Sheets backup remove after reject failed for %s", fixture_id)
        removed = True

    notify: dict[str, Any]
    try:
        notify = send_rejection_notify_email(
            staff=staff,
            home=str(ctx["home"]),
            away=str(ctx["away"]),
            league=str(ctx["league"]),
            watch_type=str(ctx["watch_type"]),
            kickoff_label=str(ctx["kickoff_label"]),
            reason=reason_clean,
            scout_email=scout_email_for(staff),
        )
    except Exception as exc:  # noqa: BLE001
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Failed to send rejection notify for %s", fixture_id)
        notify = {"sent": False, "reason": str(exc)}

    if removed:
        message = (
            f"Thanks — you've been removed from {ctx['home']} vs {ctx['away']}. "
            "Sam has been emailed."
        )
    else:
        message = (
            f"Thanks — Sam has been emailed that you can't cover "
            f"{ctx['home']} vs {ctx['away']}."
        )

    return {
        "ok": True,
        "fixture_id": fixture_id,
        "staff": staff,
        "notify": notify,
        "removed": removed,
        "message": message,
    }


def register_fixture_planner_routes(app: FastAPI) -> None:
    @app.get("/fixture-planner", response_class=HTMLResponse)
    def fixture_planner_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "fixture-planner.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Fixture planner UI not found.")
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/played-fixtures", response_class=HTMLResponse)
    def played_fixtures_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "played-fixtures.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Played fixtures UI not found.")
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/fixture-planner/reject-assignment", response_class=HTMLResponse)
    def fixture_planner_reject_assignment_get(
        token: str = Query(""),
    ) -> HTMLResponse:
        return HTMLResponse(reject_assignment_page_html(token=token))

    @app.post("/fixture-planner/reject-assignment", response_class=HTMLResponse)
    def fixture_planner_reject_assignment_post(
        token: str = Form(""),
        reason: str = Form(""),
    ) -> HTMLResponse:
        result = process_reject_assignment(token=token, reason=reason)
        if not result.get("ok"):
            return HTMLResponse(
                reject_assignment_page_html(error=str(result.get("error") or "Could not reject assignment")),
                status_code=400,
            )
        return HTMLResponse(
            reject_assignment_page_html(message=str(result.get("message") or "Assignment rejected."))
        )

    @app.get("/api/fixture-planner/meta")
    def fixture_planner_meta_route() -> dict[str, Any]:
        return fixture_planner_meta()

    @app.get("/api/fixture-planner/fixtures")
    def fixture_planner_fixtures_route(
        season: str = Query(DEFAULT_SEASON),
        refresh: int = Query(0),
        upcoming: int = Query(0),
    ) -> JSONResponse:
        payload = build_fixture_planner_payload(
            season=season,
            force_refresh=bool(refresh),
        )
        if upcoming:
            payload = _upcoming_only_payload(payload)
        return JSONResponse(
            content=payload,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/api/fixture-planner/match-enrichment")
    def fixture_planner_match_enrichment_route(
        season: str = Query(DEFAULT_SEASON),
        fixture_ids: str = Query(""),
    ) -> dict[str, Any]:
        if season not in ALLOWED_FIXTURE_SEASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
            )
        ids = [token.strip() for token in fixture_ids.split(",") if token.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="fixture_ids is required")
        return build_match_enrichment_payload(season=season, fixture_ids=ids)

    @app.get("/api/fixture-planner/fixture-squads")
    def fixture_planner_fixture_squads_route(
        fixture_id: str = Query(...),
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return build_fixture_squads_payload(season=season, fixture_id=fixture_id)

    @app.get("/api/fixture-planner/assignments")
    def fixture_planner_assignments_route() -> dict[str, Any]:
        return get_fixture_assignments()

    @app.get("/api/fixture-planner/sheets-backup/status")
    def fixture_planner_sheets_backup_status_route() -> dict[str, Any]:
        from app.fixture_sheets_backup import get_sheets_backup_status

        return get_sheets_backup_status()

    @app.post("/api/fixture-planner/sheets-backup/rebuild")
    def fixture_planner_sheets_backup_rebuild_route() -> dict[str, Any]:
        from app.fixture_sheets_backup import rebuild_sheet_from_assignments, sheets_backup_enabled

        if not sheets_backup_enabled():
            raise HTTPException(
                status_code=400,
                detail="Sheets backup is disabled. Set FIXTURE_SHEETS_ENABLED=1 and configure credentials.",
            )
        result = rebuild_sheet_from_assignments()
        if not result.get("ok"):
            raise HTTPException(
                status_code=502,
                detail=result.get("last_error") or result.get("reason") or "Sheets rebuild failed",
            )
        return result

    @app.put("/api/fixture-planner/assignments")
    def fixture_planner_assignments_bulk_route(
        body: FixtureAssignmentsBulkUpdate,
    ) -> dict[str, Any]:
        return replace_fixture_assignments(body)

    @app.patch("/api/fixture-planner/assignment")
    def fixture_planner_assignment_route(
        body: FixtureAssignmentUpdate,
        mirror: str = Query("1"),
    ) -> dict[str, Any]:
        allow_mirror = str(mirror or "1").strip().lower() not in {"0", "false", "no", "off"}
        return upsert_fixture_assignment(
            body,
            mirror_to_live=allow_mirror,
            send_email=allow_mirror,
        )

    @app.patch("/api/fixture-planner/fixture-status")
    def fixture_planner_fixture_status_route(body: FixtureStatusUpdate) -> dict[str, Any]:
        return set_fixture_status_override(body.fixture_id, status=body.status)

    @app.get("/api/fixture-planner/email/ticket-request")
    def fixture_planner_ticket_request_preview_route() -> dict[str, Any]:
        return preview_admin_ticket_request()

    @app.post("/api/fixture-planner/email/ticket-request")
    def fixture_planner_ticket_request_route(
        body: TicketRequestBody = Body(default_factory=TicketRequestBody),
    ) -> dict[str, Any]:
        return send_admin_ticket_request(body)

    @app.post("/api/fixture-planner/email/schedule-update")
    def fixture_planner_schedule_update_route() -> dict[str, Any]:
        return send_fortnight_schedule_update()

    @app.get("/api/fixture-planner/scouting-reports")
    def fixture_planner_scouting_reports_route(
        fixture_id: str | None = Query(None),
    ) -> dict[str, Any]:
        return get_scouting_reports(fixture_id=fixture_id)

    @app.patch("/api/fixture-planner/scouting-report")
    def fixture_planner_scouting_report_route(
        body: ScoutingReportToggle,
    ) -> dict[str, Any]:
        return toggle_scouting_report(body)

    @app.get("/api/fixture-planner/team-names")
    def fixture_planner_team_names_route(
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        seasons = [season] if season in ALLOWED_FIXTURE_SEASONS else None
        entries = list_known_team_entries(seasons=seasons)
        return {
            "teams": entries,
            "names": [str(row.get("name") or "") for row in entries if row.get("name")],
            "count": len(entries),
            "countries": sorted(TEAM_CATALOG_COUNTRIES),
            "source": "fotmob",
        }

    @app.get("/api/fixture-planner/manual-fixtures")
    def fixture_planner_manual_fixtures_list_route(
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        if season is not None and season not in ALLOWED_FIXTURE_SEASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
            )
        rows = list_manual_fixtures(season=season)
        return {"fixtures": rows, "updated_at": _load_manual_fixtures_store().get("updated_at")}

    @app.post("/api/fixture-planner/manual-fixtures")
    def fixture_planner_manual_fixtures_create_route(
        body: ManualFixtureCreate,
    ) -> dict[str, Any]:
        return create_manual_fixture(body)

    @app.patch("/api/fixture-planner/manual-fixtures/{fixture_id:path}")
    def fixture_planner_manual_fixtures_update_route(
        fixture_id: str,
        body: ManualFixtureUpdate,
    ) -> dict[str, Any]:
        return update_manual_fixture(fixture_id, body)

    @app.delete("/api/fixture-planner/manual-fixtures/{fixture_id:path}")
    def fixture_planner_manual_fixtures_delete_route(
        fixture_id: str,
    ) -> dict[str, Any]:
        return delete_manual_fixture(fixture_id)

    @app.post("/api/fixture-planner/manual-fixtures/{fixture_id:path}/team-sheet")
    async def fixture_planner_manual_team_sheet_upload_route(
        fixture_id: str,
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        data = await file.read()
        return attach_manual_team_sheet(
            fixture_id=fixture_id,
            filename=file.filename or "team-sheet",
            content_type=file.content_type or "application/octet-stream",
            data=data,
        )

    @app.get("/api/fixture-planner/manual-fixtures/{fixture_id:path}/team-sheet")
    def fixture_planner_manual_team_sheet_download_route(
        fixture_id: str,
    ) -> FileResponse:
        return get_manual_team_sheet_file(fixture_id)

    @app.get("/api/fixture-planner/scout-summary")
    def fixture_planner_scout_summary_route(
        season: str | None = Query(None),
        include_past: bool = Query(True),
        staff: str | None = Query(None),
    ) -> dict[str, Any]:
        if season is not None and season not in ALLOWED_FIXTURE_SEASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
            )
        if staff and staff not in FIXTURE_STAFF:
            raise HTTPException(status_code=400, detail=f"Unknown staff member: {staff}")
        return build_scout_summary_payload(season=season, include_past=include_past, staff=staff)

    @app.get("/api/fixture-planner/scout-summary/report")
    def fixture_planner_scout_summary_report_route(
        season: str | None = Query(None),
        include_past: bool = Query(True),
        staff: str | None = Query(None),
        period: str = Query("all"),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        period_label: str | None = Query(None),
    ) -> dict[str, Any]:
        if season is not None and season not in ALLOWED_FIXTURE_SEASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
            )
        if staff and staff not in FIXTURE_STAFF:
            raise HTTPException(status_code=400, detail=f"Unknown staff member: {staff}")

        parsed_from = _parse_export_date(date_from) if date_from else None
        parsed_to = _parse_export_date(date_to) if date_to else None
        if parsed_from and parsed_to and parsed_from > parsed_to:
            raise HTTPException(status_code=400, detail="date_from must be on or before date_to")

        if not (parsed_from or parsed_to):
            if period not in SCOUT_SUMMARY_PERIODS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Period must be one of: {', '.join(SCOUT_SUMMARY_PERIODS)}",
                )

        try:
            return build_scout_summary_report_payload(
                season=season,
                include_past=include_past,
                staff=staff,
                period=period,
                date_from=parsed_from,
                date_to=parsed_to,
                period_label=period_label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/fixture-planner/scout-summary/export")
    def fixture_planner_scout_summary_export_route(
        season: str | None = Query(None),
        include_past: bool = Query(True),
        staff: str | None = Query(None),
        period: str = Query("all"),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        period_label: str | None = Query(None),
        report_format: str = Query("full"),
    ) -> Response:
        return _scout_summary_export_response(
            season=season,
            include_past=include_past,
            staff=staff,
            period=period,
            date_from=date_from,
            date_to=date_to,
            period_label=period_label,
            report_format=report_format,
        )

    @app.get("/api/fixture-planner/scout-summary/export-one-pager")
    def fixture_planner_scout_summary_export_one_pager_route(
        season: str | None = Query(None),
        include_past: bool = Query(True),
        staff: str | None = Query(None),
        period: str = Query("all"),
        date_from: str | None = Query(None),
        date_to: str | None = Query(None),
        period_label: str | None = Query(None),
    ) -> Response:
        return _scout_summary_export_response(
            season=season,
            include_past=include_past,
            staff=staff,
            period=period,
            date_from=date_from,
            date_to=date_to,
            period_label=period_label,
            report_format="one_pager",
        )

    @app.get("/api/fixture-planner/scouts-calendar")
    def fixture_planner_scouts_calendar_route(
        season: str | None = Query(None),
        staff: str | None = Query(None),
        watch_type: str = Query("ALL"),
        include_past: bool = Query(True),
    ) -> dict[str, Any]:
        if season is not None and season not in ALLOWED_FIXTURE_SEASONS:
            raise HTTPException(
                status_code=400,
                detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
            )
        if staff and staff not in FIXTURE_STAFF:
            raise HTTPException(status_code=400, detail=f"Unknown staff member: {staff}")
        return build_scouts_calendar_payload(
            season=season,
            staff=staff,
            watch_type=watch_type,
            include_past=include_past,
        )

    @app.get("/scout-summary-report", response_class=HTMLResponse)
    def scout_summary_report_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "scout-summary-report.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scout summary report UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/scout-summary", response_class=HTMLResponse)
    def scout_summary_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "scout-summary.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scout summary UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/scouts-calendar", response_class=HTMLResponse)
    def scouts_calendar_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "scouts-calendar.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scouts calendar UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/scouts-calander")
    def scouts_calander_redirect() -> RedirectResponse:
        return RedirectResponse(url="/scouts-calendar", status_code=307)

    @app.get("/scout-calander")
    def scout_calander_redirect() -> RedirectResponse:
        return RedirectResponse(url="/scouts-calendar", status_code=307)

    @app.get("/scouts-summary")
    def scouts_summary_redirect() -> RedirectResponse:
        return RedirectResponse(url="/scout-summary", status_code=307)
