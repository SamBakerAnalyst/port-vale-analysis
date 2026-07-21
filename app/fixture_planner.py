from __future__ import annotations

import json
import re
import threading
import time
from calendar import monthrange
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from typing import Any

import requests
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.paths import FIXTURE_PLANNER_DATA_DIR
from app.scouting import SCOUTING_DIR
from app.fixture_assignment_email import send_assignment_email, team_badge_url

DEFAULT_SEASON = "26/27"
ALLOWED_FIXTURE_SEASONS: tuple[str, ...] = ("26/27", "25/26")
FIXTURE_CACHE_TTL_SECONDS = 1800
FIXTURE_CACHE_VERSION = "v5"

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

_scout_ops_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_scout_ops_cache_lock = threading.Lock()
SCOUT_OPS_CACHE_TTL_SECONDS = 45

ASSIGNMENTS_DIR = FIXTURE_PLANNER_DATA_DIR
ASSIGNMENTS_DIR.mkdir(parents=True, exist_ok=True)
ASSIGNMENTS_PATH = ASSIGNMENTS_DIR / "assignments.json"
SCOUTING_REPORTS_PATH = ASSIGNMENTS_DIR / "scouting-reports.json"
_assignments_lock = threading.Lock()
_scouting_reports_lock = threading.Lock()


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
            for fixture in cached[1].get("fixtures") or []:
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


class FixtureAssignmentUpdate(BaseModel):
    fixture_id: str
    staff: str = ""
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
)

FIXTURE_LEAGUE_BY_UI = {row["ui"]: row for row in FIXTURE_LEAGUES}
FIXTURE_LEAGUE_UIS = [row["ui"] for row in FIXTURE_LEAGUES]

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
}

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


def _prefer_display_name(current: str, incoming: str) -> str:
    current_name = str(current or "").strip()
    incoming_name = str(incoming or "").strip()
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
                "score": None,
                "sources": ["fotmob"],
                "source_ids": {"fotmob": str(match.get("id") or "")},
                "fotmob_page_url": str(match.get("pageUrl") or "").strip() or None,
            }
        )
    return fixtures


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
            for event in secondary.get("events") or []:
                events.append(event)
    return events


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

        pair_key = _teams_pair_key(home_name, away_name)
        for key in order:
            existing = merged[key]
            existing_home = str((existing.get("home") or {}).get("name") or "")
            existing_away = str((existing.get("away") or {}).get("name") or "")
            if _teams_pair_key(existing_home, existing_away) != pair_key:
                continue
            existing_day = _fixture_day(existing.get("date") or existing.get("scheduled_date"))
            if _days_between(row_day, existing_day) <= FIXTURE_DATE_MATCH_TOLERANCE_DAYS:
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
        if incoming_priority >= existing_priority:
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
        impect_fixtures = _fetch_impect_fixtures(
            iteration_id,
            league_ui=league_ui,
            competition=competition,
            season=season,
        )

    fotmob_fixtures = _fetch_fotmob_fixtures(
        int(config["fotmob_id"]),
        league_ui=league_ui,
        season=season,
        calendar_year=calendar_year,
    )
    bbc_fixtures = _fetch_bbc_fixtures(
        str(config.get("bbc_path") or ""),
        league_ui=league_ui,
        season=season,
        calendar_year=calendar_year,
    )
    primary = impect_fixtures or fotmob_fixtures or bbc_fixtures
    merged = _merge_fixture_sources(
        primary,
        fotmob_fixtures,
        bbc_fixtures,
    )
    filtered = _filter_fixtures_to_season(
        merged,
        season,
        calendar_year=calendar_year,
    )

    return {
        "league": league_ui,
        "competition": competition,
        "season": season,
        "iteration_id": iteration_id,
        "counts": {
            "impect": len(impect_fixtures),
            "fotmob": len(fotmob_fixtures),
            "bbc": len(bbc_fixtures),
            "merged": len(filtered),
            "verified": sum(1 for row in filtered if row.get("verified")),
            "dropped_out_of_season": max(0, len(merged) - len(filtered)),
        },
        "coverage": _league_coverage(filtered),
        "fixtures": filtered,
    }


def fixture_planner_meta() -> dict[str, Any]:
    impect = _impect()
    seasons_by_league: dict[str, list[str]] = {}
    for row in FIXTURE_LEAGUES:
        competition = str(row["competition"])
        seasons: list[str] = []
        for item in impect._fetch_iterations():
            if str(item.get("competition_name", "")).strip() != competition:
                continue
            season = str(item.get("season", "")).strip()
            if season and season not in seasons:
                seasons.append(season)
        seasons.sort(key=impect._season_sort_key, reverse=True)
        allowed = [item for item in seasons if item in ALLOWED_FIXTURE_SEASONS]
        seasons_by_league[row["ui"]] = allowed or list(ALLOWED_FIXTURE_SEASONS)

    return {
        "season": DEFAULT_SEASON,
        "seasons": list(ALLOWED_FIXTURE_SEASONS),
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
                "seasons": seasons_by_league.get(row["ui"], []),
            }
            for row in FIXTURE_LEAGUES
        ],
        "default_leagues": FIXTURE_LEAGUE_UIS,
        "sources": ["impect", "fotmob", "bbc"],
        "generated_at": datetime.now(UTC).isoformat(),
    }


def build_fixture_planner_payload(
    *,
    season: str,
) -> dict[str, Any]:
    if season not in ALLOWED_FIXTURE_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_FIXTURE_SEASONS)}",
        )

    selected = FIXTURE_LEAGUE_UIS
    cache_key = f"{FIXTURE_CACHE_VERSION}:{season}"
    now = time.time()
    with _fixture_cache_lock:
        cached = _fixture_cache.get(cache_key)
        if cached and now - cached[0] < FIXTURE_CACHE_TTL_SECONDS:
            return cached[1]

    bundles = [_build_league_bundle(league_ui, season) for league_ui in selected]
    fixtures = [fixture for bundle in bundles for fixture in bundle["fixtures"]]
    fixtures.sort(
        key=lambda row: (
            str(row.get("date") or ""),
            str(row.get("kickoff_utc") or ""),
            str(row.get("league") or ""),
        )
    )

    payload = {
        "season": season,
        "leagues": list(FIXTURE_LEAGUE_UIS),
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
        "coverage": {
            bundle["league"]: bundle["coverage"]
            for bundle in bundles
        },
        "summary": {
            "total_fixtures": len(fixtures),
            "verified_fixtures": sum(1 for row in fixtures if row.get("verified")),
            "by_league": {bundle["league"]: bundle["counts"]["merged"] for bundle in bundles},
            "by_source": {
                "impect": sum(bundle["counts"]["impect"] for bundle in bundles),
                "fotmob": sum(bundle["counts"]["fotmob"] for bundle in bundles),
                "bbc": sum(bundle["counts"]["bbc"] for bundle in bundles),
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }

    with _fixture_cache_lock:
        _fixture_cache[cache_key] = (now, payload)
    return payload


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
    return {
        "assignments": dict(store.get("assignments") or {}),
        "updated_at": store.get("updated_at"),
    }


def _normalize_watched_players(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            player_id = int(row.get("player_id") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        cleaned.append(
            {
                "player_id": player_id,
                "player_name": str(row.get("player_name") or "").strip(),
                "team": str(row.get("team") or "").strip(),
                "side": str(row.get("side") or "").strip().lower(),
            }
        )
    cleaned.sort(
        key=lambda item: (
            0 if item.get("side") == "home" else 1,
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


def upsert_fixture_assignment(body: FixtureAssignmentUpdate) -> dict[str, Any]:
    store = _load_assignments_store()
    assignments: dict[str, Any] = store.setdefault("assignments", {})
    fixture_id = str(body.fixture_id or "").strip()
    if not fixture_id:
        raise HTTPException(status_code=400, detail="fixture_id is required")

    staff = str(body.staff or "").strip()
    watch_type = str(body.watch_type or "").strip().upper()
    if watch_type and watch_type not in WATCH_TYPES:
        raise HTTPException(status_code=400, detail=f"watch_type must be one of: {', '.join(WATCH_TYPES)}")
    if staff and staff not in FIXTURE_STAFF:
        raise HTTPException(status_code=400, detail=f"Unknown staff member: {staff}")

    previous = dict(assignments.get(fixture_id) or {})
    previous_staff = str(previous.get("staff") or "").strip()
    previous_watch = str(previous.get("watch_type") or "").strip().upper()
    previous_players = _watched_player_ids(previous.get("watched_players") or [])
    watched_players = _normalize_watched_players(body.watched_players)

    if not staff and not watch_type:
        assignments.pop(fixture_id, None)
    else:
        assignments[fixture_id] = {
            "staff": staff,
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
    _save_assignments_store(store)

    email_result: dict[str, Any] | None = None
    should_notify = bool(
        staff
        and (
            staff != previous_staff
            or (watch_type and watch_type != previous_watch)
            or _watched_player_ids(watched_players) != previous_players
        )
    )
    if should_notify:
        email_result = _notify_assignment_email(
            fixture_id=fixture_id,
            assignment=assignments.get(fixture_id) or {},
        )

    payload = get_fixture_assignments()
    if email_result is not None:
        payload["email"] = email_result
    return payload


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
            fixture = row
            break
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")

    home = fixture.get("home") if isinstance(fixture.get("home"), dict) else {}
    away = fixture.get("away") if isinstance(fixture.get("away"), dict) else {}
    home_id = int(home.get("id") or 0)
    away_id = int(away.get("id") or 0)
    iteration_id = int(fixture.get("iteration_id") or 0)

    home_players: list[dict[str, Any]] = []
    away_players: list[dict[str, Any]] = []
    available = bool(iteration_id and (home_id or away_id))

    if available:
        impect = _impect()
        try:
            players = impect._fetch_players_for_iteration(iteration_id)
        except Exception:
            players = []
        for player in players:
            squad_id = impect._extract_squad_id_from_player(player)
            player_id = player.get("id")
            name = impect._extract_player_name(player)
            if player_id is None or not name:
                continue
            entry = {
                "player_id": int(player_id),
                "player_name": name,
            }
            if home_id and squad_id == home_id:
                home_players.append(entry)
            elif away_id and squad_id == away_id:
                away_players.append(entry)
        home_players.sort(key=lambda row: str(row.get("player_name") or "").casefold())
        away_players.sort(key=lambda row: str(row.get("player_name") or "").casefold())

    return {
        "fixture_id": fixture_token,
        "season": season,
        "league": fixture.get("league"),
        "date": fixture.get("date"),
        "kickoff_utc": fixture.get("kickoff_utc") or fixture.get("scheduled_date"),
        "iteration_id": iteration_id or None,
        "available": available and bool(home_players or away_players),
        "home": {
            "id": home_id or None,
            "name": home.get("name") or "",
            "image_url": home.get("image_url"),
            "players": home_players,
        },
        "away": {
            "id": away_id or None,
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


def _notify_assignment_email(*, fixture_id: str, assignment: dict[str, Any]) -> dict[str, Any]:
    staff = str(assignment.get("staff") or "").strip()
    if not staff:
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
            staff=staff,
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
        )
    except Exception as exc:  # noqa: BLE001 - never fail assignment save on email errors
        logger = __import__("logging").getLogger(__name__)
        logger.exception("Failed to send assignment email for %s", fixture_id)
        return {"sent": False, "reason": str(exc)}


def replace_fixture_assignments(body: FixtureAssignmentsBulkUpdate) -> dict[str, Any]:
    store = _load_assignments_store()
    merged = dict(store.get("assignments") or {})
    for fixture_id, row in (body.assignments or {}).items():
        if not isinstance(row, dict):
            continue
        staff = str(row.get("staff") or "").strip()
        watch_type = str(row.get("watch_type") or "").strip().upper()
        if not staff and not watch_type:
            merged.pop(fixture_id, None)
            continue
        merged[fixture_id] = {
            "staff": staff,
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
    store["assignments"] = merged
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
    return get_scouting_reports(fixture_id)


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
        assigned_staff = str(assignment.get("staff") or "").strip()
        assigned_watch = str(assignment.get("watch_type") or "").strip().upper()
        if not assigned_staff:
            continue
        if staff and assigned_staff != staff:
            continue
        if watch_type and assigned_watch != watch_type.upper():
            continue

        assignment_season = str(assignment.get("season") or "").strip()
        if seasons and assignment_season and assignment_season not in seasons:
            continue

        fixture = _resolve_fixture_record(fixture_id, fixtures_list, assignment=assignment)
        home_name = str(assignment.get("home") or "").strip()
        away_name = str(assignment.get("away") or "").strip()
        league_name = str(assignment.get("league") or "").strip()
        kickoff = assignment.get("kickoff_utc")
        date_key = _parse_iso_date(assignment.get("date") or assignment.get("kickoff_utc"))

        if fixture is not None:
            home_name = (fixture.get("home") or {}).get("name") or home_name
            away_name = (fixture.get("away") or {}).get("name") or away_name
            league_name = str(fixture.get("league") or league_name)
            kickoff = fixture.get("kickoff_utc") or kickoff
            date_key = _parse_iso_date(fixture.get("date") or fixture.get("scheduled_date")) or date_key
            assignment_season = assignment_season or str(fixture.get("season") or "").strip()

        fixture_status = str((fixture or {}).get("status") or "").strip()
        fixture_score = (fixture or {}).get("score")
        fixture_match_id = (fixture or {}).get("match_id")
        fixture_iteration_id = (fixture or {}).get("iteration_id")

        if not include_past and date_key and date_key < today:
            continue

        dedupe_key = fixture_id or f"{assigned_staff}|{date_key}|{league_name}|{home_name}|{away_name}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        canonical_fixture_id = str((fixture or {}).get("fixture_id") or fixture_id)
        report_rows = scouting_reports_for_fixture(canonical_fixture_id)

        rows.append(
            {
                "fixture_id": canonical_fixture_id,
                "staff": assigned_staff,
                "watch_type": assigned_watch,
                "season": assignment_season,
                "league": league_name,
                "home": home_name,
                "away": away_name,
                "date": date_key or "",
                "kickoff_utc": kickoff,
                "status": fixture_status or ("completed" if fixture_score else ""),
                "score": fixture_score,
                "match_id": fixture_match_id,
                "iteration_id": fixture_iteration_id,
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
        staff_name = row["staff"]
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
        totals["assigned"] += 1
        if row["watch_type"] == "LIVE":
            bucket["live"] += 1
            totals["live"] += 1
        elif row["watch_type"] == "VIDEO":
            bucket["video"] += 1
            totals["video"] += 1

        league = row.get("league") or "Unknown"
        bucket["by_league"][league] = bucket["by_league"].get(league, 0) + 1
        by_league[league] = by_league.get(league, 0) + 1
        totals["scouting_reports"] += int(row.get("scouting_report_count") or 0)
        bucket["fixtures"].append(row)

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
    names: list[str] = []
    for side in ("home", "away"):
        value = fixture.get(side)
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
        else:
            name = str(value or "").strip()
        if name:
            names.append(name)
    return names


def _build_league_team_exposure(
    payload: dict[str, Any],
    *,
    seasons: list[str],
    date_from: str | None = None,
    date_to: str | None = None,
    top_n: int = 12,
) -> list[dict[str, Any]]:
    team_fixture_watch: dict[tuple[str, str], dict[str, str]] = {}

    def remember_fixture(league: str, team: str, fixture_id: str, watch: str = "") -> None:
        if not league or not team or not fixture_id:
            return
        key = (league, team)
        bucket = team_fixture_watch.setdefault(key, {})
        existing = bucket.get(fixture_id, "")
        if watch == "LIVE":
            bucket[fixture_id] = "LIVE"
        elif watch == "VIDEO":
            bucket[fixture_id] = "VIDEO"
        elif fixture_id not in bucket:
            bucket[fixture_id] = existing

    for fixture in _cached_fixtures_list(seasons, warm=True):
        if not _fixture_in_date_range(fixture, date_from=date_from, date_to=date_to):
            continue
        league = str(fixture.get("league") or "Unknown")
        fixture_id = str(fixture.get("fixture_id") or "")
        if not fixture_id:
            continue
        for team in _fixture_team_names(fixture):
            remember_fixture(league, team, fixture_id)

    for staff_row in payload.get("staff") or []:
        for fixture in staff_row.get("fixtures") or []:
            league = str(fixture.get("league") or "Unknown")
            fixture_id = str(fixture.get("fixture_id") or "")
            if not fixture_id:
                continue
            watch_type = str(fixture.get("watch_type") or "").strip().upper()
            for team in _fixture_team_names(fixture):
                remember_fixture(league, team, fixture_id, watch_type)

    leagues_map: dict[str, list[dict[str, Any]]] = {}
    for (league, team), fixture_map in team_fixture_watch.items():
        live = sum(1 for watch in fixture_map.values() if watch == "LIVE")
        video = sum(1 for watch in fixture_map.values() if watch == "VIDEO")
        not_seen = sum(1 for watch in fixture_map.values() if not watch)
        total = len(fixture_map)
        covered = live + video
        if not total and not covered:
            continue
        leagues_map.setdefault(league, []).append(
            {
                "team": team,
                "live": live,
                "video": video,
                "not_seen": not_seen,
                "total": total,
            }
        )

    charts: list[dict[str, Any]] = []
    for league in sorted(leagues_map.keys(), key=str.casefold):
        teams = sorted(
            leagues_map[league],
            key=lambda row: (
                -int(row.get("live") or 0) - int(row.get("video") or 0),
                -int(row.get("total") or 0),
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
    watch_type: str = "LIVE",
    include_past: bool = False,
) -> dict[str, Any]:
    watch_filter = str(watch_type or "LIVE").strip().upper()
    if watch_filter not in ("LIVE", "VIDEO", "ALL"):
        watch_filter = "LIVE"
    cache_key = f"calendar|{season or 'ALL'}|{watch_filter}|{include_past}|{staff or ''}"
    cached = _scout_ops_cache_get(cache_key)
    if cached is not None:
        return cached

    seasons = [season] if season in ALLOWED_FIXTURE_SEASONS else list(ALLOWED_FIXTURE_SEASONS)

    rows = _assignment_rows_for_seasons(
        seasons,
        include_past=include_past,
        staff=staff or None,
        watch_type=None if watch_filter == "ALL" else watch_filter,
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
            timeout=20,
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
    from app.pre_match import _match_squad_block
    from app.pre_match_handout import _position_abbr, _shirt_map

    squad = _match_squad_block(detail, squad_id)
    if not squad:
        return None
    shirts = _shirt_map(squad)
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
    from app.pre_match_handout import _position_abbr

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


def register_fixture_planner_routes(app: FastAPI) -> None:
    @app.get("/fixture-planner", response_class=HTMLResponse)
    def fixture_planner_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "fixture-planner.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Fixture planner UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/fixture-planner/meta")
    def fixture_planner_meta_route() -> dict[str, Any]:
        return fixture_planner_meta()

    @app.get("/api/fixture-planner/fixtures")
    def fixture_planner_fixtures_route(
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return build_fixture_planner_payload(season=season)

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

    @app.put("/api/fixture-planner/assignments")
    def fixture_planner_assignments_bulk_route(
        body: FixtureAssignmentsBulkUpdate,
    ) -> dict[str, Any]:
        return replace_fixture_assignments(body)

    @app.patch("/api/fixture-planner/assignment")
    def fixture_planner_assignment_route(
        body: FixtureAssignmentUpdate,
    ) -> dict[str, Any]:
        return upsert_fixture_assignment(body)

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
        watch_type: str = Query("LIVE"),
        include_past: bool = Query(False),
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
