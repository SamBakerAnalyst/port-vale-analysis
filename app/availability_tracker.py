from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.paths import AVAILABILITY_DATA_DIR
from app.scouting import SCOUTING_DIR
from app.squad_photos import (
    fetch_club_squad_roster,
    fetch_photo_bytes,
    resolve_local_photo_path,
    resolve_squad_photo_url,
    save_local_player_photo,
    squad_photo_map,
)
from app.squad_review import (
    PORT_VALE_COMPETITIONS,
    _port_vale_candidate_iterations,
    _resolve_port_vale_iteration,
    _resolve_port_vale_squad_id,
)

DATA_DIR = AVAILABILITY_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH = DATA_DIR / "availability.json"
_store_lock = threading.Lock()
_match_minutes_cache: dict[tuple[int, int], tuple[float, dict[int, dict[int, dict[str, Any]]]]] = {}
CACHE_TTL_SECONDS = 3600
FIXTURES_CACHE_TTL_SECONDS = 300
FOTMOB_TEAM_ID = 9799
FOTMOB_LEAGUE_IDS = frozenset({108, 109})  # League One, League Two
_fotmob_minutes_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_fotmob_fixtures_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _season_date_bounds(season: str) -> tuple[str, str]:
    start_year = int(str(season).split("/")[0])
    if start_year < 100:
        start_year += 2000
    return f"{start_year}-07-01", f"{start_year + 1}-06-30"


def _normalize_player_key(name: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _fotmob_http_get(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.fixture_planner import _http

    response = _http.get(
        url,
        params=params or {},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"FotMob request failed ({response.status_code})")
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _fotmob_match_category(tournament: dict[str, Any] | None) -> str:
    tournament = tournament or {}
    try:
        league_id = int(tournament.get("leagueId") or 0)
    except (TypeError, ValueError):
        league_id = 0
    if league_id in FOTMOB_LEAGUE_IDS:
        return "league"
    name = str(tournament.get("name") or "").casefold()
    if "friendly" in name:
        return "friendly"
    if name:
        return "cup"
    return "friendly"


def _fotmob_fixtures_for_season(season: str) -> list[dict[str, Any]]:
    season = _validate_season(season)
    cached = _fotmob_fixtures_cache.get(season)
    now = time.time()
    if cached and now - cached[0] < FIXTURES_CACHE_TTL_SECONDS:
        return cached[1]

    payload = _fotmob_http_get(
        "https://www.fotmob.com/api/data/teams",
        params={"id": FOTMOB_TEAM_ID},
    )
    raw = (
        ((payload.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures")
        or []
    )
    start, end = _season_date_bounds(season)
    rows: list[dict[str, Any]] = []
    for match in raw:
        if not isinstance(match, dict):
            continue
        status = match.get("status") or {}
        kickoff = str(status.get("utcTime") or "")
        match_date = kickoff[:10]
        if not match_date or match_date < start or match_date > end:
            continue

        home = match.get("home") or {}
        away = match.get("away") or {}
        tournament = match.get("tournament") or {}
        try:
            home_id = int(home.get("id") or 0)
            away_id = int(away.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if FOTMOB_TEAM_ID not in (home_id, away_id):
            continue

        is_home = home_id == FOTMOB_TEAM_ID
        opponent = away if is_home else home
        finished = bool(status.get("finished"))
        home_score = home.get("score") if finished else None
        away_score = away.get("score") if finished else None
        try:
            home_goals = int(home_score) if home_score is not None else None
            away_goals = int(away_score) if away_score is not None else None
        except (TypeError, ValueError):
            home_goals = away_goals = None

        complete = finished and home_goals is not None and away_goals is not None
        pv_goals = opp_goals = points = None
        result = ""
        score = ""
        if complete:
            pv_goals = home_goals if is_home else away_goals
            opp_goals = away_goals if is_home else home_goals
            if pv_goals > opp_goals:
                result = "W"
                points = 3
            elif pv_goals < opp_goals:
                result = "L"
                points = 0
            else:
                result = "D"
                points = 1
            score = f"{home_goals}-{away_goals}"

        short_name = str(opponent.get("name") or "TBC").strip() or "TBC"
        prefix = "H" if is_home else "A"
        category = _fotmob_match_category(tournament if isinstance(tournament, dict) else {})
        competition = str(tournament.get("name") or "").strip() or (
            "League" if category == "league" else "Cup"
        )
        match_id = int(match["id"])
        rows.append(
            {
                "match_id": match_id,
                "date": match_date,
                "kickoff_utc": kickoff or None,
                "label": f"{short_name} ({prefix})",
                "match_day": None,
                "competition": competition,
                "match_category": category,
                "opponent": short_name,
                "opponent_short": short_name,
                "is_home": is_home,
                "venue": prefix,
                "result": result,
                "score": score,
                "complete": complete,
                "pv_goals": pv_goals,
                "opp_goals": opp_goals,
                "points": points,
                "source": "fotmob",
            }
        )

    rows.sort(key=lambda row: (str(row.get("date") or ""), int(row.get("match_id") or 0)))
    _fotmob_fixtures_cache[season] = (now, rows)
    return rows


def _extract_fotmob_minutes(player_stats: dict[str, Any]) -> float:
    for block in player_stats.get("stats") or []:
        if not isinstance(block, dict):
            continue
        stats = block.get("stats") or {}
        if not isinstance(stats, dict):
            continue
        for label in ("Minutes played", "Mins played", "Minutes"):
            entry = stats.get(label)
            if not isinstance(entry, dict):
                continue
            stat = entry.get("stat") or {}
            try:
                return float(stat.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
        minutes_key = stats.get("minutes_played") or stats.get("Minutes played")
        if isinstance(minutes_key, dict):
            try:
                return float((minutes_key.get("stat") or {}).get("value") or 0.0)
            except (TypeError, ValueError):
                pass
    return 0.0


def _fotmob_match_minutes_by_name(match_id: int) -> dict[str, dict[str, Any]]:
    cached = _fotmob_minutes_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    try:
        payload = _fotmob_http_get(
            "https://www.fotmob.com/api/data/matchDetails",
            params={"matchId": match_id},
        )
    except HTTPException:
        _fotmob_minutes_cache[match_id] = (now, {})
        return {}

    content = payload.get("content") or {}
    player_stats = content.get("playerStats") or {}
    lineup = content.get("lineup") or {}
    starter_ids: set[int] = set()
    for side_key in ("homeTeam", "awayTeam"):
        side = lineup.get(side_key) or {}
        if int(side.get("id") or 0) != FOTMOB_TEAM_ID:
            continue
        for player in side.get("starters") or []:
            if isinstance(player, dict) and player.get("id") is not None:
                starter_ids.add(int(player["id"]))

    by_name: dict[str, dict[str, Any]] = {}
    if isinstance(player_stats, dict):
        for pid_token, row in player_stats.items():
            if not isinstance(row, dict):
                continue
            try:
                team_id = int(row.get("teamId") or 0)
            except (TypeError, ValueError):
                continue
            if team_id != FOTMOB_TEAM_ID:
                continue
            minutes = _extract_fotmob_minutes(row)
            if minutes <= 0:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            try:
                fotmob_player_id = int(row.get("id") or pid_token)
            except (TypeError, ValueError):
                fotmob_player_id = None
            key = _normalize_player_key(name)
            by_name[key] = {
                "name": name,
                "minutes": minutes,
                "match_share": min(1.0, minutes / 90.0),
                "started": fotmob_player_id in starter_ids if fotmob_player_id else minutes >= 45,
                "fotmob_player_id": fotmob_player_id,
            }

    _fotmob_minutes_cache[match_id] = (now, by_name)
    return by_name


def _fotmob_minutes_by_match(
    matches: list[dict[str, Any]],
) -> dict[int, dict[str, dict[str, Any]]]:
    result: dict[int, dict[str, dict[str, Any]]] = {}
    for match in matches:
        if not match.get("complete"):
            continue
        match_id = int(match["match_id"])
        result[match_id] = _fotmob_match_minutes_by_name(match_id)
    return result


def _roster_minutes_for_match(
    *,
    player: dict[str, Any],
    match_id: int,
    minutes_by_match: dict[int, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    per_match = minutes_by_match.get(match_id) or {}
    if not per_match:
        return None
    key = _normalize_player_key(str(player.get("name") or ""))
    row = per_match.get(key)
    if row:
        return row
    # Fallback: last-name match when full-name keys differ slightly.
    last = key[-6:] if len(key) >= 6 else key
    for candidate_key, candidate in per_match.items():
        if candidate_key.endswith(last) or key.endswith(candidate_key[-6:]):
            return candidate
    return None

UNAVAILABLE_STATUSES = frozenset({"INJ", "UN", "LOAN", "INT"})
FIT_EXCLUDED_STATUSES = frozenset({"INJ", "UN", "LOAN", "INT"})
TRAINING_UNAVAILABLE_STATUSES = frozenset({"INT", "SICK", "INJ", "REST", "OTHER", "NAC"})
TRAINING_AVAILABLE_STATUSES = frozenset({"AVAIL", "PART"})

ALLOWED_SEASONS: tuple[str, ...] = ("26/27", "25/26")
DEFAULT_SEASON = "26/27"

POSITION_GROUPS: tuple[dict[str, str], ...] = (
    {"id": "GK", "label": "Goalkeepers"},
    {"id": "DEF", "label": "Defenders"},
    {"id": "MID", "label": "Midfielders"},
    {"id": "ATT", "label": "Attackers"},
)

# Older availability boards used CB/WB/CM — map into the four simple groups.
LEGACY_POSITION_GROUP_MAP: dict[str, str] = {
    "CB": "DEF",
    "WB": "DEF",
    "CM": "MID",
}

STATUS_CODES: dict[str, dict[str, str]] = {
    "AVAIL": {"label": "Available", "short": "✓", "color": "#22c55e"},
    "PART": {"label": "Part training", "short": "PART", "color": "#84cc16"},
    "INJ": {"label": "Injured", "short": "INJ", "color": "#ef4444"},
    "MM": {"label": "Managed minutes", "short": "MM", "color": "#14b8a6"},
    "SICK": {"label": "Sick", "short": "SICK", "color": "#f97316"},
    "REST": {"label": "Rested", "short": "REST", "color": "#a855f7"},
    "OTHER": {"label": "Other", "short": "OTH", "color": "#64748b"},
    "NAC": {"label": "Not at club", "short": "NAC", "color": "#475569"},
    "UN": {"label": "Unavailable", "short": "UN", "color": "#6b7280"},
    "N": {"label": "Not in squad", "short": "N", "color": "#374151"},
    "INT": {"label": "International break", "short": "INT", "color": "#3b82f6"},
    "LOAN": {"label": "On loan", "short": "LOAN", "color": "#1f2937"},
    "SUB": {"label": "Substitute", "short": "SUB", "color": "#f59e0b"},
}

TRAINING_STATUSES: tuple[str, ...] = (
    "AVAIL",
    "PART",
    "INT",
    "SICK",
    "INJ",
    "REST",
    "OTHER",
    "NAC",
)

MATCH_STATUSES: tuple[str, ...] = (
    "AVAIL",
    "INJ",
    "MM",
    "UN",
    "N",
    "INT",
    "LOAN",
    "SUB",
)

IMPECT_POSITION_TO_GROUP: dict[str, str] = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "DEF",
    "LEFT_WINGBACK_DEFENDER": "DEF",
    "RIGHT_WINGBACK_DEFENDER": "DEF",
    "DEFENSE_MIDFIELD": "MID",
    "CENTRAL_MIDFIELD": "MID",
    "ATTACKING_MIDFIELD": "ATT",
    "LEFT_WINGER": "ATT",
    "RIGHT_WINGER": "ATT",
    "CENTER_FORWARD": "ATT",
    "SECOND_STRIKER": "ATT",
}


class RosterPlayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position_group: str = Field(min_length=2, max_length=8)
    impect_id: int | None = None
    highlight: str | None = None


class RosterPlayerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    position_group: str | None = Field(default=None, min_length=2, max_length=8)
    sort_order: int | None = None
    impect_id: int | None = None
    highlight: str | None = None


class InjuryUpdate(BaseModel):
    status: str = Field(min_length=2, max_length=8)
    return_date: str | None = None
    notes: str = ""
    since: str | None = None
    away_from_club: bool = False


class SessionCreate(BaseModel):
    type: str = Field(pattern="^(training|match)$")
    date: str = Field(min_length=8, max_length=10)
    label: str = Field(default="", max_length=80)
    match_id: int | None = None


class SessionEntriesUpdate(BaseModel):
    entries: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TrainingLogRequest(BaseModel):
    date: str = Field(min_length=8, max_length=10)
    label: str = Field(default="Training", max_length=80)
    session_id: str | None = None
    entries: dict[str, dict[str, Any]] = Field(default_factory=dict)
    apply_injuries: bool = True


class MatchLogRequest(BaseModel):
    date: str = Field(min_length=8, max_length=10)
    label: str = Field(default="", max_length=80)
    match_category: str = Field(pattern="^(league|friendly|cup)$")
    match_id: int | None = None
    session_id: str | None = None
    opponent: str = Field(default="", max_length=80)
    venue: str = Field(default="H", pattern="^(H|A)$")
    entries: dict[str, dict[str, Any]] = Field(default_factory=dict)
    apply_injuries: bool = False


TRAINING_SESSION_PRESETS: tuple[str, ...] = (
    "Mon AM",
    "Mon PM",
    "Tue AM",
    "Tue PM",
    "Wed AM",
    "Wed PM",
    "Thu AM",
    "Thu PM",
    "Fri AM",
    "Fri PM",
    "Recovery",
    "Training",
)


class RosterReorderRequest(BaseModel):
    player_ids: list[str] = Field(default_factory=list)


def _impect():
    from app import main as impect_main

    return impect_main


def _pre_match():
    from app import pre_match as pre_match_module

    return pre_match_module


def _empty_store() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": None,
        "roster": {},
        "injuries": {},
        "sessions": {},
    }


def _legacy_availability_paths() -> list[Path]:
    home = Path.home() / ".cache" / "impect-availability" / "availability.json"
    return [home]


def _store_has_active_roster(store: dict[str, Any], season: str | None = None) -> bool:
    roster_root = store.get("roster")
    if not isinstance(roster_root, dict):
        return False
    seasons = [season] if season else list(roster_root.keys())
    for key in seasons:
        rows = roster_root.get(key)
        if not isinstance(rows, list):
            continue
        if any(isinstance(row, dict) and row.get("active", True) is not False for row in rows):
            return True
    return False


def _maybe_migrate_legacy_store(store: dict[str, Any]) -> dict[str, Any]:
    """Fill missing season data from legacy ~/.cache when the DATA_ROOT store is thin."""
    changed = False
    for legacy_path in _legacy_availability_paths():
        if not legacy_path.exists() or legacy_path.resolve() == DATA_PATH.resolve():
            continue
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(legacy, dict):
            continue

        for key in ("roster", "injuries", "sessions", "injury_history"):
            legacy_bucket = legacy.get(key)
            if not isinstance(legacy_bucket, dict):
                continue
            current_bucket = store.setdefault(key, {})
            if not isinstance(current_bucket, dict):
                current_bucket = {}
                store[key] = current_bucket
            for season, value in legacy_bucket.items():
                if season in current_bucket and current_bucket[season]:
                    if key == "roster" and _store_has_active_roster(store, season):
                        continue
                    if key != "roster":
                        continue
                current_bucket[season] = value
                changed = True

        if changed:
            store["version"] = int(legacy.get("version") or store.get("version") or 2)
            store["updated_at"] = datetime.now(UTC).isoformat()
            _save_store(store)
            return store
    return store


def _load_store() -> dict[str, Any]:
    with _store_lock:
        if not DATA_PATH.exists():
            store = _empty_store()
        else:
            try:
                payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                store = _empty_store()
            else:
                if not isinstance(payload, dict):
                    store = _empty_store()
                else:
                    store = payload
                    for key in ("roster", "injuries", "sessions", "injury_history"):
                        bucket = store.get(key)
                        if not isinstance(bucket, dict):
                            store[key] = {}
    return _maybe_migrate_legacy_store(store)


def _save_store(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload["version"] = 2
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = DATA_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(DATA_PATH)


def _season_bucket(store: dict[str, Any], key: str, season: str) -> dict[str, Any] | list[Any]:
    bucket = store.setdefault(key, {})
    if not isinstance(bucket, dict):
        bucket = {}
        store[key] = bucket
    if season not in bucket:
        if key == "sessions":
            bucket[season] = []
        else:
            bucket[season] = {} if key == "injuries" else []
    return bucket[season]


def _validate_season(season: str) -> str:
    token = str(season or "").strip()
    if token not in ALLOWED_SEASONS:
        raise HTTPException(
            status_code=400,
            detail=f"Season must be one of: {', '.join(ALLOWED_SEASONS)}",
        )
    return token


def _validate_position_group(position_group: str) -> str:
    allowed = {row["id"] for row in POSITION_GROUPS}
    token = str(position_group or "").strip().upper()
    token = LEGACY_POSITION_GROUP_MAP.get(token, token)
    if token not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Position group must be one of: {', '.join(sorted(allowed))}",
        )
    return token


def _validate_status(status: str) -> str:
    token = str(status or "").strip().upper()
    if token.isdigit():
        return token
    if token.startswith("SUB"):
        return token
    if token not in STATUS_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown status: {status}",
        )
    return token


def _player_id() -> str:
    return f"p-{uuid.uuid4().hex[:10]}"


def _session_id(prefix: str = "s") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _injury_history_id() -> str:
    return f"ih-{uuid.uuid4().hex[:10]}"


def _injury_history_for_season(store: dict[str, Any], season: str) -> dict[str, list[dict[str, Any]]]:
    root = store.setdefault("injury_history", {})
    if not isinstance(root, dict):
        root = {}
        store["injury_history"] = root
    bucket = root.get(season)
    if not isinstance(bucket, dict):
        bucket = {}
        root[season] = bucket
    return bucket


def _close_open_injury_record(records: list[dict[str, Any]], ended_at: str) -> None:
    for record in reversed(records):
        if not record.get("ended_at"):
            record["ended_at"] = ended_at[:10]
            return


def _injury_period_end(record: dict[str, Any]) -> str:
    """Actual end of the injury spell for counts (so far) — never the expected return date."""
    ended = record.get("ended_at")
    if ended:
        return str(ended)[:10]
    return datetime.now(UTC).date().isoformat()


def _days_between_dates(start: str | None, end: str | None) -> int | None:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if not start_date or not end_date:
        return None
    # Inclusive calendar days from onset through end / today.
    return max(0, (end_date - start_date).days + 1)


def _days_injured(injury: dict[str, Any] | None) -> int | None:
    if not injury:
        return None
    status = str(injury.get("status") or "").upper()
    if status not in {"INJ", "UN", "LOAN"}:
        return None
    since = _parse_date(injury.get("since"))
    if not since:
        return None
    today = datetime.now(UTC).date()
    return max(0, (today - since).days + 1)


def _missed_sessions_for_period(
    sessions: list[dict[str, Any]],
    *,
    since: str,
    until: str,
) -> dict[str, Any]:
    missed_training = 0
    missed_matches = 0
    items: list[str] = []
    since_date = _parse_date(since)
    until_date = _parse_date(until)
    if not since_date or not until_date:
        return {"training": 0, "matches": 0, "items": []}

    for session in sessions:
        session_date = _parse_date(str(session.get("date") or "")[:10])
        if not session_date or session_date < since_date or session_date > until_date:
            continue
        label = str(session.get("label") or session.get("date") or "Session")
        if session.get("type") == "training":
            missed_training += 1
            items.append(f"Training · {label} ({session.get('date')})")
        elif session.get("type") == "match":
            missed_matches += 1
            items.append(f"Match · {label} ({session.get('date')})")

    return {
        "training": missed_training,
        "matches": missed_matches,
        "items": items,
    }


def _enrich_injury_records(
    records: list[dict[str, Any]] | None,
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    enriched: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        until = _injury_period_end(record)
        missed = _missed_sessions_for_period(
            sessions,
            since=str(record.get("since") or "")[:10],
            until=until,
        )
        enriched.append(
            {
                **record,
                "days_out": _days_between_dates(record.get("since"), until),
                "missed_training": missed["training"],
                "missed_matches": missed["matches"],
                "missed_items": missed["items"],
                "active": not bool(record.get("ended_at")),
            }
        )
    enriched.sort(key=lambda row: str(row.get("since") or ""), reverse=True)
    return enriched


def _migrate_injury_history(
    store: dict[str, Any],
    *,
    season: str,
    injuries: dict[str, Any],
    history_bucket: dict[str, list[dict[str, Any]]],
) -> bool:
    changed = False
    if not isinstance(injuries, dict):
        return False
    for player_id, injury in injuries.items():
        if not isinstance(injury, dict):
            continue
        records = history_bucket.setdefault(player_id, [])
        if not isinstance(records, list):
            records = []
            history_bucket[player_id] = records
        has_open = any(isinstance(row, dict) and not row.get("ended_at") for row in records)
        if has_open:
            continue
        records.append(
            {
                "id": _injury_history_id(),
                "status": str(injury.get("status") or "INJ"),
                "since": str(injury.get("since") or datetime.now(UTC).date().isoformat())[:10],
                "return_date": injury.get("return_date"),
                "ended_at": None,
                "notes": str(injury.get("notes") or ""),
                "away_from_club": bool(injury.get("away_from_club")),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
        changed = True
    if changed:
        _save_store(store)
    return changed


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _photo_url_for_name(name: str) -> str | None:
    if resolve_local_photo_path(name) is not None:
        return f"/api/availability/photo?name={quote(name)}"
    if resolve_squad_photo_url(name):
        return f"/api/availability/photo?name={quote(name)}"
    return None


def _roster_for_season(store: dict[str, Any], season: str) -> list[dict[str, Any]]:
    roster = _season_bucket(store, "roster", season)
    if not isinstance(roster, list):
        roster = []
        store["roster"][season] = roster
    if _normalize_roster_position_groups(roster):
        store["roster"][season] = roster
        _save_store(store)
    return roster


def _active_roster(roster: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [player for player in roster if player.get("active", True) is not False]


def _find_player(roster: list[dict[str, Any]], player_id: str) -> dict[str, Any] | None:
    for player in roster:
        if str(player.get("id")) == player_id:
            return player
    return None


def _normalize_roster_position_groups(roster: list[dict[str, Any]]) -> bool:
    """Rewrite legacy CB/WB/CM groups in place. Returns True if anything changed."""
    changed = False
    for player in roster:
        if not isinstance(player, dict):
            continue
        raw = str(player.get("position_group") or "").strip().upper()
        mapped = LEGACY_POSITION_GROUP_MAP.get(raw, raw) or "MID"
        if player.get("position_group") != mapped:
            player["position_group"] = mapped
            changed = True
    return changed


def _impect_position_group(position: str | None) -> str:
    return IMPECT_POSITION_TO_GROUP.get(str(position or "").strip(), "MID")


def _impect_primary_positions(iteration_id: int) -> dict[int, str]:
    from app.scouting import _build_primary_positions, _get_primary_positions

    primary = _get_primary_positions(iteration_id)
    if primary:
        return primary
    return _build_primary_positions(iteration_id)


def _position_minutes_by_player(
    match_player_data: dict[int, dict[int, dict[str, Any]]],
) -> dict[int, dict[str, float]]:
    totals: dict[int, dict[str, float]] = {}
    for players in match_player_data.values():
        for player_id, row in players.items():
            position = str(row.get("position") or "").strip()
            minutes = float(row.get("minutes") or 0.0)
            if not position or minutes <= 0:
                continue
            bucket = totals.setdefault(int(player_id), {})
            bucket[position] = bucket.get(position, 0.0) + minutes
    return totals


def _resolve_player_position_group(
    impect_id: int | None,
    *,
    primary_positions: dict[int, str],
    position_minutes: dict[int, dict[str, float]],
    catalog_position: str | None = None,
    default: str | None = "MID",
) -> str | None:
    """Map Impect position data to a board group.

    When ``default`` is None, return None unless Impect actually has a signal —
    used by position sync so empty 26/27 Impect data cannot wipe club-site groups.
    """
    if impect_id is not None:
        primary = primary_positions.get(int(impect_id))
        if primary:
            return _impect_position_group(primary)

        by_minutes = position_minutes.get(int(impect_id)) or {}
        if by_minutes:
            best_position = max(by_minutes.items(), key=lambda item: item[1])[0]
            return _impect_position_group(best_position)

    if catalog_position:
        return _impect_position_group(catalog_position)
    return default


def _resolve_iteration(season: str) -> dict[str, Any]:
    return _resolve_port_vale_iteration(season)


def _previous_allowed_season(season: str) -> str | None:
    try:
        index = ALLOWED_SEASONS.index(season)
    except ValueError:
        return None
    if index + 1 >= len(ALLOWED_SEASONS):
        return None
    return ALLOWED_SEASONS[index + 1]


def _port_vale_players_from_impect(iteration_id: int, squad_id: int) -> list[dict[str, Any]]:
    impect = _impect()
    pre_match = _pre_match()
    players = pre_match._unwrap_items(
        impect._impect_get(f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/players")["data"]
    )
    squad_players = [
        player
        for player in players
        if impect._extract_squad_id_from_player(player) == squad_id
    ]
    if squad_players:
        return squad_players

    from app.scouting import _load_iteration_bundle

    iteration = next(
        (
            row
            for row in _port_vale_candidate_iterations(impect)
            if int(row["id"]) == iteration_id
        ),
        {"id": iteration_id},
    )
    try:
        bundle = _load_iteration_bundle(iteration, "CENTRAL_MIDFIELD", 0)
    except Exception:
        return []
    seen: set[int] = set()
    fallback: list[dict[str, Any]] = []
    for row in bundle.get("score_rows") or []:
        row_squad = row.get("_squadId") or row.get("squadId")
        player_id = row.get("playerId")
        if row_squad is None or player_id is None:
            continue
        if int(row_squad) != squad_id:
            continue
        player_id = int(player_id)
        if player_id in seen:
            continue
        seen.add(player_id)
        catalog = bundle["player_lookup"].get((iteration_id, player_id), {})
        fallback.append(
            {
                "id": player_id,
                "commonname": impect._extract_player_name(catalog),
                "positions": [row.get("position")] if row.get("position") else [],
            }
        )
    return fallback


def _impect_squad_players_for_season(season: str) -> dict[str, Any]:
    """Load Port Vale squad players from Impect, falling back to the prior season if empty."""
    season = _validate_season(season)
    iteration = _resolve_iteration(season)
    iteration_id = int(iteration["id"])
    squad_id = _resolve_squad_id(iteration_id)
    players = _port_vale_players_from_impect(iteration_id, squad_id)
    source_season = season
    warning: str | None = None

    if not players:
        prior = _previous_allowed_season(season)
        if prior:
            prior_iteration = _resolve_iteration(prior)
            prior_iteration_id = int(prior_iteration["id"])
            prior_squad_id = _resolve_squad_id(prior_iteration_id)
            prior_players = _port_vale_players_from_impect(prior_iteration_id, prior_squad_id)
            if prior_players:
                players = prior_players
                source_season = prior
                iteration_id = prior_iteration_id
                squad_id = prior_squad_id
                warning = (
                    f"Impect has no {season} Port Vale squad list yet "
                    f"(access may still be closed). Used {prior} Impect squad — "
                    "delete anyone who has left."
                )

    return {
        "players": players,
        "iteration_id": iteration_id,
        "squad_id": squad_id,
        "source_season": source_season,
        "warning": warning,
    }


def _resolve_squad_id(iteration_id: int) -> int:
    impect = _impect()
    pre_match = _pre_match()
    squads = {
        int(item["id"]): str(item.get("name") or "")
        for item in pre_match._unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
        if item.get("id") is not None
    }
    squad_id = _resolve_port_vale_squad_id(squads)
    if squad_id is None:
        raise HTTPException(status_code=404, detail="Port Vale squad not found for this season.")
    return int(squad_id)


def _match_minutes_by_match(iteration_id: int, squad_id: int) -> dict[int, dict[int, float]]:
    data = _match_player_data_by_match(iteration_id, squad_id)
    return {
        match_id: {
            player_id: float(row.get("minutes") or 0.0)
            for player_id, row in players.items()
        }
        for match_id, players in data.items()
    }


def _match_player_data_by_match(iteration_id: int, squad_id: int) -> dict[int, dict[int, dict[str, Any]]]:
    cache_key = (iteration_id, squad_id)
    cached = _match_minutes_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    pre_match = _pre_match()
    impect = _impect()
    matches = pre_match._unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    squad_match_ids = [
        int(match["id"])
        for match in matches
        if match.get("id") is not None
        and (
            int(match.get("homeSquadId") or -1) == squad_id
            or int(match.get("awaySquadId") or -1) == squad_id
        )
    ]

    result: dict[int, dict[int, dict[str, Any]]] = {}
    for match_id in squad_match_ids:
        payload = pre_match._unwrap_match_player_payload(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
            )["data"]
        )
        per_match: dict[int, dict[str, Any]] = {}
        for side in ("squadHome", "squadAway"):
            squad = payload.get(side) or {}
            if int(squad.get("id") or -1) != squad_id:
                continue
            for row in squad.get("players") or []:
                player_id = row.get("id")
                if player_id is None:
                    continue
                minutes = pre_match._match_play_minutes(row)
                match_share = float(row.get("matchShare") or 0.0)
                pid = int(player_id)
                existing = per_match.get(pid)
                if existing is None or minutes > float(existing.get("minutes") or 0.0):
                    per_match[pid] = {
                        "minutes": minutes,
                        "match_share": match_share,
                        "started": match_share >= 0.5,
                        "position": str(row.get("position") or ""),
                    }
        result[int(match_id)] = per_match

    _match_minutes_cache[cache_key] = (now, result)
    return result


def _port_vale_matches(iteration_id: int, squad_id: int) -> list[dict[str, Any]]:
    pre_match = _pre_match()
    impect = _impect()
    matches = pre_match._unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    squads = {
        int(item["id"]): item
        for item in pre_match._unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
        if item.get("id") is not None
    }

    rows: list[dict[str, Any]] = []
    for match in matches:
        match_id = match.get("id")
        if match_id is None:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        if squad_id not in (home_id, away_id):
            continue

        is_home = squad_id == home_id
        opponent_id = away_id if is_home else home_id
        opponent = squads.get(opponent_id, {})
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        complete = home_goals is not None and away_goals is not None

        if complete:
            pv_goals = int(home_goals if is_home else away_goals)
            opp_goals = int(away_goals if is_home else home_goals)
            if pv_goals > opp_goals:
                result = "W"
                points = 3
            elif pv_goals < opp_goals:
                result = "L"
                points = 0
            else:
                result = "D"
                points = 1
            score = f"{home_goals}-{away_goals}"
        else:
            result = ""
            score = ""
            pv_goals = None
            opp_goals = None
            points = None

        opponent_name = str(opponent.get("name") or f"Squad {opponent_id}")
        short_name = opponent_name.upper().replace(" FC", "").replace(" UNITED", " UTD")
        short_name = short_name[:12]
        prefix = "H" if is_home else "A"

        rows.append(
            {
                "match_id": int(match_id),
                "match_day": pre_match._match_day_index(match),
                "date": str(match.get("scheduledDate") or "")[:10],
                "competition": str(match.get("competitionName") or "L1"),
                "opponent": opponent_name,
                "opponent_short": short_name,
                "is_home": is_home,
                "venue": prefix,
                "result": result,
                "score": score,
                "complete": complete,
                "pv_goals": pv_goals,
                "opp_goals": opp_goals,
                "points": points,
                "label": f"{short_name} ({prefix})",
            }
        )

    rows.sort(key=lambda row: (str(row.get("date") or ""), int(row.get("match_day") or 0)))
    return rows


def _injury_applies(injury: dict[str, Any] | None, session_date: str) -> bool:
    """True when the session falls inside an unavailable spell (INJ / UN / LOAN)."""
    return _standing_status_applies(injury, session_date, statuses={"INJ", "UN", "LOAN"})


def _managed_minutes_applies(injury: dict[str, Any] | None, session_date: str) -> bool:
    return _standing_status_applies(injury, session_date, statuses={"MM"})


def _standing_status_applies(
    injury: dict[str, Any] | None,
    session_date: str,
    *,
    statuses: set[str],
) -> bool:
    """True when the session falls inside the actual standing-status spell (not expected return)."""
    if not injury:
        return False
    status = str(injury.get("status") or "").upper()
    if status not in statuses:
        return False
    session = _parse_date(session_date)
    if not session:
        return False
    since = _parse_date(injury.get("since"))
    if since and session < since:
        return False
    ended = _parse_date(injury.get("ended_at"))
    if ended and session > ended:
        return False
    return True


def _effective_entry(
    *,
    player_id: str,
    session: dict[str, Any],
    manual_entries: dict[str, Any],
    injuries: dict[str, Any],
    play_minutes: float | None,
    has_player_identity: bool,
) -> dict[str, Any]:
    session_type = str(session.get("type") or "")
    session_date = str(session.get("date") or "")
    injury = injuries.get(player_id) if isinstance(injuries, dict) else None
    complete = bool(session.get("complete"))
    mm_active = complete and _managed_minutes_applies(injury, session_date)

    # Completed match minutes win over manual codes so MM can annotate real play time.
    if session_type == "match" and play_minutes is not None and play_minutes > 0:
        minutes = int(round(play_minutes))
        if mm_active:
            return {
                "status": "MM",
                "display": f"{minutes} MM",
                "source": "managed",
                "minutes": minutes,
                "managed_minutes": True,
            }
        return {
            "status": str(minutes),
            "display": str(minutes),
            "source": str(session.get("source") or "fotmob"),
            "minutes": minutes,
        }

    manual = manual_entries.get(player_id)
    if isinstance(manual, dict) and manual.get("status"):
        status = str(manual["status"])
        # Standing MM is shown only after completion — ignore session-level MM on fixtures yet to play.
        if status.upper() == "MM" and not complete:
            pass
        else:
            short = STATUS_CODES.get(status.upper(), {}).get("short", status)
            display = short if not status.isdigit() else str(int(float(status)))
            if complete and mm_active and status.isdigit():
                display = f"{int(float(status))} MM"
                return {
                    "status": "MM",
                    "display": display,
                    "source": "managed",
                    "minutes": int(float(status)),
                    "managed_minutes": True,
                }
            if status.upper() != "MM" or complete:
                return {
                    "status": status,
                    "display": display,
                    "source": "manual",
                    "minutes": int(float(status)) if status.isdigit() else None,
                }

    # Never predict injury / MM onto incomplete fixtures — only once the game is done.
    if complete and _injury_applies(injury, session_date):
        status = str(injury.get("status") or "INJ").upper()
        return {
            "status": status,
            "display": STATUS_CODES.get(status, {}).get("short", status),
            "source": "injury",
            "minutes": None,
            "injury_notes": injury.get("notes") or "",
            "return_date": injury.get("return_date"),
        }

    if mm_active:
        return {
            "status": "MM",
            "display": "MM",
            "source": "managed",
            "minutes": None,
            "managed_minutes": True,
        }

    if session_type == "match" and has_player_identity and complete:
        return {
            "status": "N",
            "display": "N",
            "source": str(session.get("source") or "fotmob"),
            "minutes": 0,
        }

    return {
        "status": "AVAIL",
        "display": "",
        "source": "default",
        "minutes": None,
    }


def _minutes_bracket(total_minutes: float, sessions_played: int) -> str:
    if sessions_played <= 0:
        return "Squad"
    avg = total_minutes / max(sessions_played, 1)
    if avg >= 70:
        return "Starter"
    if avg >= 30:
        return "Rotation"
    return "Squad"


def _is_training_available_status(status: str | None) -> bool:
    token = str(status or "AVAIL").strip().upper()
    return token in TRAINING_AVAILABLE_STATUSES


def _is_available_status(status: str | None, *, session_type: str | None = None) -> bool:
    if session_type == "training":
        return _is_training_available_status(status)
    token = str(status or "AVAIL").strip().upper()
    if not token or token == "AVAIL":
        return True
    if token.isdigit() or token.startswith("SUB"):
        return True
    return token not in UNAVAILABLE_STATUSES


def _is_fit_for_match(status: str | None) -> bool:
    """Fit to be involved — excludes injury/unavailable/international, includes not-selected (N)."""
    token = str(status or "AVAIL").strip().upper()
    if not token or token == "AVAIL":
        return True
    if token.isdigit() or token.startswith("SUB"):
        return True
    return token not in FIT_EXCLUDED_STATUSES


def _cell_played(cell: dict[str, Any]) -> bool:
    minutes = cell.get("minutes")
    if minutes is not None and int(minutes) > 0:
        return True
    status = str(cell.get("status") or "")
    if status.isdigit() and int(float(status)) > 0:
        return True
    return False


def _availability_rates(
    cells: dict[str, Any],
    sessions: list[dict[str, Any]],
) -> dict[str, Any]:
    training_available = 0
    training_total = 0
    games_available = 0
    games_available_total = 0
    games_fit = 0
    games_played_when_fit = 0

    for session in sessions:
        session_id = str(session.get("id") or "")
        cell = cells.get(session_id) or {}
        status = str(cell.get("status") or "AVAIL")
        if session.get("type") == "training":
            training_total += 1
            if _is_available_status(status, session_type="training"):
                training_available += 1
            continue

        if session.get("type") != "match" or not session.get("complete"):
            continue

        games_available_total += 1
        if _is_available_status(status, session_type="match"):
            games_available += 1

        if _is_fit_for_match(status):
            games_fit += 1
            if _cell_played(cell):
                games_played_when_fit += 1

    return {
        "training_pct": round(100 * training_available / training_total, 1) if training_total else None,
        "training_available": training_available,
        "training_total": training_total,
        # % of completed games they were fit to play (not injured / loan / int).
        # "N" (not selected) still counts as available.
        "games_available_pct": round(100 * games_available / games_available_total, 1)
        if games_available_total
        else None,
        "games_available": games_available,
        "games_available_total": games_available_total,
        # % of completed games actually played when fit (not injured/unavailable/int)
        "games_played_when_fit_pct": round(100 * games_played_when_fit / games_fit, 1) if games_fit else None,
        "games_played_when_fit": games_played_when_fit,
        "games_fit_total": games_fit,
        # Back-compat alias
        "match_pct": round(100 * games_available / games_available_total, 1) if games_available_total else None,
        "match_available": games_available,
        "match_total": games_available_total,
    }


def _competition_totals(matches: list[dict[str, Any]]) -> dict[str, Any]:
    all_complete = [match for match in matches if match.get("complete")]
    league_complete = [
        match
        for match in all_complete
        if str(match.get("match_category") or "league") == "league"
    ]
    team_points = sum(
        int(match.get("points") or 0)
        for match in league_complete
        if match.get("points") is not None
    )
    team_wins = sum(1 for match in league_complete if str(match.get("result") or "").upper() == "W")
    complete_matches = len(all_complete)
    return {
        "complete_matches": complete_matches,
        "complete_league_matches": len(league_complete),
        "possible_mins": complete_matches * 90,
        "team_points": team_points,
        "team_wins": team_wins,
    }


def _on_pitch_impact(
    matches: list[dict[str, Any]],
    player_rows_by_match: dict[int, dict[str, Any]],
    *,
    competition: dict[str, Any] | None = None,
    games_available: int | None = None,
) -> dict[str, Any]:
    empty = {
        "appearances": 0,
        "starts": 0,
        "minutes": 0,
        "goals_for": 0,
        "goals_against": 0,
        "goal_diff": 0,
        "goal_plus_minus": 0.0,
        "points": 0,
        "points_plus_minus": 0.0,
        "mins_in_wins": 0,
        "mins_in_points": 0,
        "wins_played": 0,
        "pct_of_l1_mins": None,
        "mins_per_game_played": None,
        "mins_per_available": None,
        "mins_per_possible": None,
        "ppg": None,
        "pct_of_wins": None,
        "pct_of_points": None,
    }

    stats = dict(empty)
    goal_pm = 0.0
    points_pm = 0.0
    for match in matches:
        if not match.get("complete"):
            continue
        is_league = str(match.get("match_category") or "league") == "league"
        match_id = int(match["match_id"])
        row = player_rows_by_match.get(match_id)
        minutes = float((row or {}).get("minutes") or 0.0)
        if minutes <= 0:
            continue

        mins_int = int(round(minutes))
        stats["appearances"] += 1
        stats["minutes"] += mins_int
        if (row or {}).get("started"):
            stats["starts"] += 1

        # Cup/friendly minutes count as playing time; points / GD stay league-only.
        if not is_league:
            continue

        share = float((row or {}).get("match_share") or 0.0)
        if share <= 0:
            share = min(1.0, minutes / 90.0)

        result = str(match.get("result") or "").upper()
        points = match.get("points")
        if result == "W":
            stats["mins_in_wins"] += mins_int
            stats["wins_played"] += 1
        if points is not None and int(points) > 0:
            stats["mins_in_points"] += mins_int

        pv_goals = match.get("pv_goals")
        opp_goals = match.get("opp_goals")
        if pv_goals is not None and opp_goals is not None:
            match_gd = int(pv_goals) - int(opp_goals)
            stats["goals_for"] += int(pv_goals)
            stats["goals_against"] += int(opp_goals)
            stats["goal_diff"] += match_gd
            goal_pm += match_gd * share
        if points is not None:
            stats["points"] += int(points)
            points_pm += (int(points) - 1) * share

    stats["minutes"] = int(stats["minutes"])
    stats["mins_in_wins"] = int(stats["mins_in_wins"])
    stats["mins_in_points"] = int(stats["mins_in_points"])
    stats["goal_plus_minus"] = round(goal_pm, 1)
    stats["points_plus_minus"] = round(points_pm, 1)
    stats["goal_diff"] = int(stats["goal_diff"])

    apps = int(stats["appearances"])
    total_mins = int(stats["minutes"])
    totals = competition or {}
    possible_mins = int(totals.get("possible_mins") or 0)
    complete_matches = int(totals.get("complete_matches") or 0)
    team_wins = int(totals.get("team_wins") or 0)
    team_points = int(totals.get("team_points") or 0)
    available = int(games_available or 0)

    if possible_mins > 0:
        stats["pct_of_l1_mins"] = round(100 * total_mins / possible_mins, 2)
    if apps > 0:
        stats["mins_per_game_played"] = round(total_mins / apps, 2)
        stats["ppg"] = round(int(stats["points"]) / apps, 2)
    if available > 0:
        stats["mins_per_available"] = round(total_mins / available, 2)
    if complete_matches > 0:
        stats["mins_per_possible"] = round(total_mins / complete_matches, 2)
    if team_wins > 0:
        stats["pct_of_wins"] = round(100 * int(stats["wins_played"]) / team_wins, 2)
    if team_points > 0:
        stats["pct_of_points"] = round(100 * int(stats["points"]) / team_points, 2)

    return stats


def availability_meta() -> dict[str, Any]:
    # Keep this fast — the page boots on /meta. Do not call Impect here; iteration
    # IDs are resolved when the board / import paths actually need them.
    competition_by_season = {
        "26/27": "League Two",
        "25/26": "League One",
    }
    seasons = [
        {
            "season": season,
            "iteration_id": None,
            "competition": competition_by_season.get(season, ""),
        }
        for season in ALLOWED_SEASONS
    ]
    return {
        "seasons": seasons,
        "default_season": DEFAULT_SEASON,
        "position_groups": list(POSITION_GROUPS),
        "status_codes": STATUS_CODES,
        "training_statuses": list(TRAINING_STATUSES),
        "match_statuses": list(MATCH_STATUSES),
        "training_presets": list(TRAINING_SESSION_PRESETS),
        "match_categories": [
            {"id": "league", "label": "League"},
            {"id": "friendly", "label": "Friendly"},
            {"id": "cup", "label": "Cup"},
        ],
        "storage_path": str(DATA_PATH),
    }


def build_availability_payload(*, season: str, refresh: bool = False) -> dict[str, Any]:
    season = _validate_season(season)
    if refresh:
        _match_minutes_cache.clear()
        _fotmob_minutes_cache.clear()
        _fotmob_fixtures_cache.clear()
        squad_photo_map(force=True)

    store = _load_store()
    roster = _roster_for_season(store, season)
    injuries = _season_bucket(store, "injuries", season)
    history_bucket = _injury_history_for_season(store, season)
    if not isinstance(injuries, dict):
        injuries = {}
    _migrate_injury_history(store, season=season, injuries=injuries, history_bucket=history_bucket)
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        sessions = []

    iteration = None
    iteration_id = None
    try:
        iteration = _resolve_iteration(season)
        iteration_id = int(iteration["id"])
    except HTTPException:
        iteration_id = None

    try:
        matches = _fotmob_fixtures_for_season(season)
    except HTTPException:
        matches = []
        if iteration_id is not None:
            squad_id = _resolve_squad_id(iteration_id)
            matches = _port_vale_matches(iteration_id, squad_id)
            for match in matches:
                match.setdefault("match_category", "league")
                match.setdefault("source", "impect")

    minutes_by_match = _fotmob_minutes_by_match(matches)

    match_sessions_by_id = {
        int(session.get("match_id")): session
        for session in sessions
        if str(session.get("type")) == "match" and session.get("match_id") is not None
    }
    manual_match_sessions = [
        session
        for session in sessions
        if str(session.get("type")) == "match"
        and (
            session.get("match_id") is None
            or str(session.get("match_category") or "") in {"friendly", "cup"}
        )
    ]

    merged_sessions: list[dict[str, Any]] = []
    fotmob_match_ids: set[int] = set()
    for match in matches:
        match_id = int(match["match_id"])
        fotmob_match_ids.add(match_id)
        stored = match_sessions_by_id.get(match_id)
        session_id = str(stored.get("id") if stored else f"fm-{match_id}")
        manual_entries = dict((stored or {}).get("entries") or {})
        merged_sessions.append(
            {
                "id": session_id,
                "type": "match",
                "date": match["date"],
                "label": match["label"],
                "match_id": match_id,
                "match_category": match.get("match_category") or "league",
                "match_day": match.get("match_day"),
                "competition": match.get("competition"),
                "opponent": match.get("opponent"),
                "venue": match.get("venue"),
                "result": match.get("result"),
                "score": match.get("score"),
                "complete": match.get("complete"),
                "source": match.get("source") or "fotmob",
                "entries": manual_entries,
            }
        )

    for session in manual_match_sessions:
        session_match_id = session.get("match_id")
        if session_match_id is not None and int(session_match_id) in fotmob_match_ids:
            continue
        merged_sessions.append(
            {
                "id": str(session.get("id") or _session_id("m")),
                "type": "match",
                "date": session.get("date"),
                "label": session.get("label") or session.get("date"),
                "match_id": session_match_id,
                "match_category": session.get("match_category") or "friendly",
                "opponent": session.get("opponent"),
                "venue": session.get("venue"),
                "result": session.get("result") or "",
                "score": session.get("score") or "",
                "complete": bool(session.get("complete")),
                "source": "manual",
                "entries": dict(session.get("entries") or {}),
            }
        )

    # Training sessions are no longer used for logging or the matrix.
    merged_sessions.sort(key=lambda row: (str(row.get("date") or ""), 0 if row.get("type") == "match" else 1))

    competition = _competition_totals(matches)
    player_rows: list[dict[str, Any]] = []
    for player in sorted(roster, key=lambda row: (row.get("position_group") or "", row.get("sort_order") or 0, row.get("name") or "")):
        player_id = str(player["id"])
        impect_id = player.get("impect_id")
        total_minutes = 0.0
        sessions_played = 0
        cells: dict[str, Any] = {}
        player_rows_by_match: dict[int, dict[str, Any]] = {}

        for session in merged_sessions:
            play_minutes = None
            match_id = session.get("match_id")
            if session.get("type") == "match" and match_id is not None:
                row = _roster_minutes_for_match(
                    player=player,
                    match_id=int(match_id),
                    minutes_by_match=minutes_by_match,
                )
                if row:
                    player_rows_by_match[int(match_id)] = row
                    play_minutes = float(row.get("minutes") or 0.0)
                    if play_minutes > 0:
                        total_minutes += play_minutes
                        sessions_played += 1

            cells[str(session["id"])] = _effective_entry(
                player_id=player_id,
                session=session,
                manual_entries=dict(session.get("entries") or {}),
                injuries=injuries,
                play_minutes=play_minutes,
                has_player_identity=True,
            )

        availability = _availability_rates(cells, merged_sessions)
        impact = _on_pitch_impact(
            matches,
            player_rows_by_match,
            competition=competition,
            games_available=availability.get("games_available"),
        )
        history_records = _enrich_injury_records(history_bucket.get(player_id), merged_sessions)
        total_days_injured = sum(
            int(row.get("days_out") or 0)
            for row in history_records
            if row.get("days_out") is not None
        )

        player_rows.append(
            {
                "id": player_id,
                "name": player.get("name"),
                "position_group": player.get("position_group"),
                "sort_order": player.get("sort_order") or 0,
                "impect_id": impect_id,
                "highlight": player.get("highlight"),
                "active": player.get("active", True) is not False,
                "photo_url": _photo_url_for_name(str(player.get("name") or "")),
                "injury": injuries.get(player_id),
                "injury_history": history_records,
                "injury_episodes": len(history_records),
                "total_days_injured": total_days_injured,
                "away_from_club": bool(
                    isinstance(injuries.get(player_id), dict)
                    and injuries[player_id].get("away_from_club")
                    and str(injuries[player_id].get("status") or "").upper() == "INJ"
                ),
                "bracket": _minutes_bracket(total_minutes, sessions_played),
                "season_minutes": int(round(total_minutes)),
                "availability": availability,
                "impact": impact,
                "days_injured": _days_injured(injuries.get(player_id)),
                "cells": cells,
            }
        )

    session_columns = [
        {
            "id": str(session["id"]),
            "type": session.get("type"),
            "date": session.get("date"),
            "label": session.get("label") or session.get("date"),
            "match_id": session.get("match_id"),
            "match_category": session.get("match_category"),
            "competition": session.get("competition"),
            "result": session.get("result"),
            "score": session.get("score"),
            "complete": session.get("complete", False),
            "source": session.get("source"),
        }
        for session in merged_sessions
    ]

    return {
        "season": season,
        "iteration_id": iteration_id,
        "updated_at": store.get("updated_at"),
        "roster": player_rows,
        "sessions": session_columns,
        "injuries": injuries,
        "match_count": len([row for row in merged_sessions if row.get("type") == "match"]),
        "league_match_count": len(
            [row for row in merged_sessions if row.get("type") == "match" and row.get("match_category") == "league"]
        ),
        "training_count": 0,
        "competition": competition,
        "fixture_source": "fotmob",
    }


def sync_roster_positions_from_impect(*, season: str) -> dict[str, Any]:
    season = _validate_season(season)
    # 26/27 first-team groups come from port-vale.co.uk, not Impect (catalog empty).
    if season == "26/27":
        return {"updated": 0, "total": 0, "skipped": True, "reason": "club-website"}

    iteration = _resolve_iteration(season)
    iteration_id = int(iteration["id"])
    squad_id = _resolve_squad_id(iteration_id)

    store = _load_store()
    roster = _roster_for_season(store, season)
    primary_positions = _impect_primary_positions(iteration_id)
    match_player_data = _match_player_data_by_match(iteration_id, squad_id)
    position_minutes = _position_minutes_by_player(match_player_data)

    updated = 0
    for player in roster:
        impect_id = player.get("impect_id")
        if impect_id is None:
            continue
        next_group = _resolve_player_position_group(
            int(impect_id),
            primary_positions=primary_positions,
            position_minutes=position_minutes,
            default=None,
        )
        if next_group is None:
            continue
        if player.get("position_group") != next_group:
            player["position_group"] = next_group
            updated += 1

    store["roster"][season] = roster
    _save_store(store)
    return {"updated": updated, "total": len(roster)}


def import_roster_from_impect(*, season: str, replace: bool = False) -> dict[str, Any]:
    season = _validate_season(season)
    fetched = _impect_squad_players_for_season(season)
    squad_players = list(fetched["players"] or [])
    if not squad_players:
        raise HTTPException(
            status_code=502,
            detail=f"Impect returned no Port Vale players for {season}.",
        )

    iteration_id = int(fetched["iteration_id"])
    squad_id = int(fetched["squad_id"])
    source_season = str(fetched["source_season"] or season)
    using_prior_season = source_season != season

    pre_match = _pre_match()
    primary_positions = _impect_primary_positions(iteration_id)
    match_player_data = _match_player_data_by_match(iteration_id, squad_id)
    position_minutes = _position_minutes_by_player(match_player_data)
    squad_players.sort(
        key=lambda row: (
            str(row.get("commonname") or pre_match._player_display_name(row)).casefold()
        )
    )

    store = _load_store()
    roster = [] if replace else _roster_for_season(store, season)
    existing_impect = {
        int(player["impect_id"]): player
        for player in roster
        if player.get("impect_id") is not None
    }
    existing_names = {str(player.get("name") or "").casefold(): player for player in roster}

    added = 0
    updated = 0
    reactivated = 0
    seen_impect_ids: set[int] = set()
    seen_names: set[str] = set()
    for index, player in enumerate(squad_players):
        impect_id = int(player["id"])
        name = (
            str(player.get("commonname") or "").strip()
            or pre_match._player_display_name(player)
        )
        seen_impect_ids.add(impect_id)
        seen_names.add(name.casefold())
        catalog_position = None
        positions = player.get("positions") or []
        if positions:
            catalog_position = str(positions[0] or "")
        elif player.get("position"):
            catalog_position = str(player.get("position") or "")

        position_group = _resolve_player_position_group(
            impect_id,
            primary_positions=primary_positions,
            position_minutes=position_minutes,
            catalog_position=catalog_position,
        )

        if impect_id in existing_impect:
            existing = existing_impect[impect_id]
            existing["name"] = name
            existing["impect_id"] = impect_id
            if existing.get("active") is False:
                existing["active"] = True
                reactivated += 1
            if existing.get("position_group") != position_group:
                existing["position_group"] = position_group
                updated += 1
            continue
        if name.casefold() in existing_names:
            existing = existing_names[name.casefold()]
            existing["impect_id"] = impect_id
            existing["name"] = name
            if existing.get("active") is False:
                existing["active"] = True
                reactivated += 1
            if existing.get("position_group") != position_group:
                existing["position_group"] = position_group
                updated += 1
            continue

        roster.append(
            {
                "id": _player_id(),
                "name": name,
                "position_group": position_group,
                "sort_order": len(roster) + index,
                "impect_id": impect_id,
                "highlight": None,
                "active": True,
            }
        )
        added += 1

    left_club = 0
    # Only mark departed when the Impect list is for this season. A prior-season
    # fallback would incorrectly flag new signings as leavers.
    if not using_prior_season:
        for player in roster:
            impect_id = player.get("impect_id")
            name_key = str(player.get("name") or "").casefold()
            still_here = (
                (impect_id is not None and int(impect_id) in seen_impect_ids)
                or name_key in seen_names
            )
            if still_here:
                continue
            if player.get("active", True) is not False:
                player["active"] = False
                left_club += 1

    store["roster"][season] = roster
    _save_store(store)
    result = {
        "added": added,
        "updated": updated,
        "reactivated": reactivated,
        "left_club": left_club,
        "total": len(_active_roster(roster)),
        "total_including_inactive": len(roster),
        "source": "impect",
        "source_season": source_season,
    }
    if fetched.get("warning"):
        result["warning"] = fetched["warning"]
    return result


def import_roster_from_club_website(*, season: str) -> dict[str, Any]:
    season = _validate_season(season)
    try:
        club_players = fetch_club_squad_roster(force=True)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not club_players:
        raise HTTPException(status_code=502, detail="Could not load squad from port-vale.co.uk.")

    from app.squad_photos import _normalize_name_key, _name_tokens

    store = _load_store()
    roster = _roster_for_season(store, season)
    by_club_id = {
        str(player.get("club_player_id")): player
        for player in roster
        if player.get("club_player_id") is not None
    }
    by_name = {str(player.get("name") or "").casefold(): player for player in roster}
    by_norm = {
        _normalize_name_key(str(player.get("name") or "")): player
        for player in roster
        if _normalize_name_key(str(player.get("name") or ""))
    }
    last_name_index: dict[str, list[dict[str, Any]]] = {}
    for player in roster:
        _, last = _name_tokens(str(player.get("name") or ""))
        if last:
            last_name_index.setdefault(last, []).append(player)

    def _match_existing(name: str, club_player_id: str) -> dict[str, Any] | None:
        existing = by_club_id.get(club_player_id) or by_name.get(name.casefold())
        if existing is not None:
            return existing
        norm = _normalize_name_key(name)
        if norm and norm in by_norm:
            return by_norm[norm]
        first, last = _name_tokens(name)
        if not last:
            return None
        candidates = last_name_index.get(last) or []
        if len(candidates) == 1:
            return candidates[0]
        if first and candidates:
            tight = [
                row
                for row in candidates
                if _name_tokens(str(row.get("name") or ""))[0][:3] == first[:3]
            ]
            if len(tight) == 1:
                return tight[0]
        return None

    club_ids_seen: set[str] = set()
    matched_roster_ids: set[str] = set()

    added = 0
    updated = 0
    reactivated = 0
    for index, club_player in enumerate(club_players):
        club_player_id = str(club_player["club_player_id"])
        club_ids_seen.add(club_player_id)
        name = str(club_player["name"])
        position_group = _validate_position_group(str(club_player["position_group"]))
        highlight = club_player.get("highlight")

        existing = _match_existing(name, club_player_id)
        if existing is not None:
            matched_roster_ids.add(str(existing["id"]))
            changed = False
            if existing.get("name") != name:
                existing["name"] = name
                changed = True
            if existing.get("position_group") != position_group:
                existing["position_group"] = position_group
                changed = True
            if existing.get("highlight") != highlight:
                existing["highlight"] = highlight
                changed = True
            if str(existing.get("club_player_id") or "") != club_player_id:
                existing["club_player_id"] = club_player_id
                changed = True
            if existing.get("active") is False:
                existing["active"] = True
                reactivated += 1
                changed = True
            if changed:
                updated += 1
            by_club_id[club_player_id] = existing
            by_name[name.casefold()] = existing
            by_norm[_normalize_name_key(name)] = existing
            continue

        player = {
            "id": _player_id(),
            "name": name,
            "position_group": position_group,
            "sort_order": len(roster) + index,
            "impect_id": None,
            "club_player_id": club_player_id,
            "highlight": highlight,
            "active": True,
        }
        roster.append(player)
        matched_roster_ids.add(str(player["id"]))
        by_club_id[club_player_id] = player
        by_name[name.casefold()] = player
        by_norm[_normalize_name_key(name)] = player
        added += 1

    left_club = 0
    for player in roster:
        if str(player.get("id")) in matched_roster_ids:
            continue
        if player.get("active", True) is not False:
            player["active"] = False
            left_club += 1
            updated += 1

    store["roster"][season] = roster
    _save_store(store)
    squad_photo_map(force=True)

    impect_linked = _link_impect_ids_onto_roster(season=season)
    store = _load_store()
    roster = _roster_for_season(store, season)

    return {
        "added": added,
        "updated": updated,
        "reactivated": reactivated,
        "left_club": left_club,
        "impect_linked": impect_linked,
        "total": len(_active_roster(roster)),
        "total_including_inactive": len(roster),
        "source": "port-vale.co.uk",
    }


def _link_impect_ids_onto_roster(*, season: str) -> int:
    """Attach Impect player IDs to roster rows by name when missing."""
    try:
        fetched = _impect_squad_players_for_season(season)
    except HTTPException:
        return 0
    squad_players = list(fetched.get("players") or [])
    if not squad_players:
        return 0

    from app.squad_photos import _normalize_name_key, _name_tokens

    pre_match = _pre_match()
    store = _load_store()
    roster = _roster_for_season(store, season)
    by_norm = {
        _normalize_name_key(str(player.get("name") or "")): player
        for player in roster
        if player.get("active", True) is not False
        and _normalize_name_key(str(player.get("name") or ""))
    }
    last_name_index: dict[str, list[dict[str, Any]]] = {}
    for player in roster:
        if player.get("active", True) is False:
            continue
        _, last = _name_tokens(str(player.get("name") or ""))
        if last:
            last_name_index.setdefault(last, []).append(player)

    linked = 0
    for row in squad_players:
        try:
            impect_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        name = (
            str(row.get("commonname") or "").strip()
            or pre_match._player_display_name(row)
        )
        if not name:
            continue
        target = by_norm.get(_normalize_name_key(name))
        if target is None:
            first, last = _name_tokens(name)
            candidates = last_name_index.get(last) or []
            if len(candidates) == 1:
                target = candidates[0]
            elif first and candidates:
                tight = [
                    player
                    for player in candidates
                    if _name_tokens(str(player.get("name") or ""))[0][:3] == first[:3]
                ]
                if len(tight) == 1:
                    target = tight[0]
        if target is None:
            continue
        if target.get("impect_id") == impect_id:
            continue
        target["impect_id"] = impect_id
        linked += 1

    if linked:
        store["roster"][season] = roster
        _save_store(store)
    return linked


def add_roster_player(*, season: str, body: RosterPlayerCreate) -> dict[str, Any]:
    season = _validate_season(season)
    position_group = _validate_position_group(body.position_group)
    store = _load_store()
    roster = _roster_for_season(store, season)
    player = {
        "id": _player_id(),
        "name": body.name.strip(),
        "position_group": position_group,
        "sort_order": len(roster),
        "impect_id": body.impect_id,
        "highlight": body.highlight,
        "active": True,
    }
    roster.append(player)
    _save_store(store)
    return player


def update_roster_player(*, season: str, player_id: str, body: RosterPlayerUpdate) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _roster_for_season(store, season)
    player = _find_player(roster, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    if body.name is not None:
        player["name"] = body.name.strip()
    if body.position_group is not None:
        player["position_group"] = _validate_position_group(body.position_group)
    if body.sort_order is not None:
        player["sort_order"] = body.sort_order
    if body.impect_id is not None:
        player["impect_id"] = body.impect_id
    if body.highlight is not None:
        player["highlight"] = body.highlight or None
    _save_store(store)
    return player


def remove_roster_player(*, season: str, player_id: str) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _roster_for_season(store, season)
    next_roster = [player for player in roster if str(player.get("id")) != player_id]
    if len(next_roster) == len(roster):
        raise HTTPException(status_code=404, detail="Player not found.")
    store["roster"][season] = next_roster
    injuries = _season_bucket(store, "injuries", season)
    if isinstance(injuries, dict):
        injuries.pop(player_id, None)
    history_bucket = _injury_history_for_season(store, season)
    if isinstance(history_bucket, dict):
        history_bucket.pop(player_id, None)
    _save_store(store)
    return {"removed": player_id}


def remove_inactive_roster_players(*, season: str) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _roster_for_season(store, season)
    keep: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    for player in roster:
        if player.get("active", True) is False:
            removed_ids.append(str(player.get("id")))
        else:
            keep.append(player)
    if not removed_ids:
        return {"removed": 0, "total": len(keep)}

    injuries = _season_bucket(store, "injuries", season)
    history_bucket = _injury_history_for_season(store, season)
    if isinstance(injuries, dict):
        for player_id in removed_ids:
            injuries.pop(player_id, None)
    if isinstance(history_bucket, dict):
        for player_id in removed_ids:
            history_bucket.pop(player_id, None)

    store["roster"][season] = keep
    _save_store(store)
    return {"removed": len(removed_ids), "total": len(keep)}


def reorder_roster(*, season: str, body: RosterReorderRequest) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _roster_for_season(store, season)
    lookup = {str(player["id"]): player for player in roster}
    ordered: list[dict[str, Any]] = []
    for index, player_id in enumerate(body.player_ids):
        player = lookup.get(player_id)
        if player is None:
            continue
        player["sort_order"] = index
        ordered.append(player)
    for player in roster:
        if player not in ordered:
            player["sort_order"] = len(ordered)
            ordered.append(player)
    store["roster"][season] = ordered
    _save_store(store)
    return {"count": len(ordered)}


def set_player_injury(*, season: str, player_id: str, body: InjuryUpdate) -> dict[str, Any]:
    season = _validate_season(season)
    status = _validate_status(body.status)
    store = _load_store()
    roster = _roster_for_season(store, season)
    if _find_player(roster, player_id) is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    injuries = _season_bucket(store, "injuries", season)
    history_bucket = _injury_history_for_season(store, season)
    records = history_bucket.setdefault(player_id, [])
    if not isinstance(records, list):
        records = []
        history_bucket[player_id] = records

    if status == "AVAIL":
        if isinstance(injuries, dict):
            injuries.pop(player_id, None)
        _close_open_injury_record(records, datetime.now(UTC).date().isoformat())
    else:
        since = (body.since or datetime.now(UTC).date().isoformat())[:10]
        _close_open_injury_record(records, since)
        injuries[player_id] = {
            "status": status,
            "return_date": body.return_date,
            "notes": body.notes.strip(),
            "since": since,
            "away_from_club": bool(body.away_from_club) and status == "INJ",
        }
        records.append(
            {
                "id": _injury_history_id(),
                "status": status,
                "since": since,
                "return_date": body.return_date,
                "ended_at": None,
                "notes": body.notes.strip(),
                "away_from_club": bool(body.away_from_club) and status == "INJ",
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        )
    _save_store(store)
    return injuries.get(player_id) or {"status": "AVAIL"}


def get_player_injury_detail(*, season: str, player_id: str) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _roster_for_season(store, season)
    player = _find_player(roster, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    injuries = _season_bucket(store, "injuries", season)
    history_bucket = _injury_history_for_season(store, season)
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        sessions = []
    stored_sessions = [
        session
        for session in sessions
        if str(session.get("type")) in {"training", "match"}
    ]
    history = _enrich_injury_records(history_bucket.get(player_id), stored_sessions)
    return {
        "player": {
            "id": player_id,
            "name": player.get("name"),
            "position_group": player.get("position_group"),
            "photo_url": _photo_url_for_name(str(player.get("name") or "")),
            "injury": injuries.get(player_id) if isinstance(injuries, dict) else None,
        },
        "history": history,
        "total_days_injured": sum(int(row.get("days_out") or 0) for row in history),
        "total_missed_training": sum(int(row.get("missed_training") or 0) for row in history),
        "total_missed_matches": sum(int(row.get("missed_matches") or 0) for row in history),
    }


def clear_player_injury(*, season: str, player_id: str) -> dict[str, Any]:
    return set_player_injury(
        season=season,
        player_id=player_id,
        body=InjuryUpdate(status="AVAIL"),
    )


def _manual_match_label(category: str, opponent: str, venue: str) -> str:
    opponent_name = opponent.strip().upper() or "TBC"
    prefix = "FRIENDLY" if category == "friendly" else "CUP"
    return f"{prefix} vs {opponent_name} ({venue})"


def _session_entries_from_request(
    *,
    roster: list[dict[str, Any]],
    injuries: dict[str, Any],
    entries: dict[str, dict[str, Any]],
    session_date: str,
    apply_injuries: bool,
) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for player in roster:
        player_id = str(player["id"])
        provided = entries.get(player_id) if isinstance(entries, dict) else None
        if isinstance(provided, dict) and provided.get("status"):
            resolved[player_id] = {"status": _validate_status(str(provided["status"]))}
            continue
        if apply_injuries and isinstance(injuries, dict) and _injury_applies(injuries.get(player_id), session_date):
            resolved[player_id] = {"status": str(injuries[player_id].get("status") or "INJ").upper()}
        elif (
            apply_injuries
            and isinstance(injuries, dict)
            and _managed_minutes_applies(injuries.get(player_id), session_date)
        ):
            # Still selectable — default the log pill to MM so staff see managed status.
            resolved[player_id] = {"status": "MM"}
        else:
            resolved[player_id] = {"status": "AVAIL"}
    return resolved


def create_training_session(*, season: str, body: TrainingLogRequest) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _active_roster(_roster_for_season(store, season))
    injuries = _season_bucket(store, "injuries", season)
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        sessions = []

    label = body.label.strip() or "Training"
    session_date = body.date[:10]
    entries = _session_entries_from_request(
        roster=roster,
        injuries=injuries if isinstance(injuries, dict) else {},
        entries=body.entries,
        session_date=session_date,
        apply_injuries=body.apply_injuries,
    )

    session: dict[str, Any] | None = None
    if body.session_id:
        session = next((row for row in sessions if str(row.get("id")) == body.session_id), None)
    if session is None:
        session = next(
            (
                row
                for row in sessions
                if str(row.get("type")) == "training"
                and str(row.get("date") or "")[:10] == session_date
                and str(row.get("label") or "").strip() == label
            ),
            None,
        )

    if session is None:
        session = {
            "id": _session_id("t"),
            "type": "training",
            "date": session_date,
            "label": label,
            "entries": entries,
        }
        sessions.append(session)
    else:
        session["date"] = session_date
        session["label"] = label
        session["entries"] = entries

    store["sessions"][season] = sessions
    _save_store(store)
    return session


def create_match_session(*, season: str, body: MatchLogRequest) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    roster = _active_roster(_roster_for_season(store, season))
    injuries = _season_bucket(store, "injuries", season)
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        sessions = []

    entries = _session_entries_from_request(
        roster=roster,
        injuries=injuries if isinstance(injuries, dict) else {},
        entries=body.entries,
        session_date=body.date[:10],
        apply_injuries=body.apply_injuries,
    )

    if body.match_category == "league":
        if body.match_id is None and body.session_id:
            session = next((row for row in sessions if str(row.get("id")) == body.session_id), None)
            if session is None and body.session_id.startswith("m-") and body.session_id[2:].isdigit():
                session = {
                    "id": body.session_id,
                    "type": "match",
                    "match_category": "league",
                    "match_id": int(body.session_id[2:]),
                    "date": body.date[:10],
                    "label": body.label.strip(),
                    "entries": {},
                }
                sessions.append(session)
        elif body.match_id is not None:
            session_id = body.session_id or f"m-{int(body.match_id)}"
            session = next((row for row in sessions if str(row.get("id")) == session_id), None)
            if session is None:
                session = {
                    "id": session_id,
                    "type": "match",
                    "match_category": "league",
                    "match_id": int(body.match_id),
                    "date": body.date[:10],
                    "label": body.label.strip(),
                    "entries": {},
                }
                sessions.append(session)
        else:
            raise HTTPException(status_code=400, detail="League match requires a fixture.")
        session["date"] = body.date[:10]
        if body.label.strip():
            session["label"] = body.label.strip()
        session["entries"] = entries
        store["sessions"][season] = sessions
        _save_store(store)
        return session

    opponent = body.opponent.strip()
    if not opponent:
        raise HTTPException(status_code=400, detail="Opponent is required for friendly and cup games.")
    venue = str(body.venue or "H").upper()
    label = body.label.strip() or _manual_match_label(body.match_category, opponent, venue)
    session = {
        "id": _session_id("f" if body.match_category == "friendly" else "c"),
        "type": "match",
        "match_category": body.match_category,
        "date": body.date[:10],
        "label": label,
        "opponent": opponent,
        "venue": venue,
        "complete": False,
        "entries": entries,
    }
    sessions.append(session)
    store["sessions"][season] = sessions
    _save_store(store)
    return session


def upsert_session_entries(*, season: str, session_id: str, body: SessionEntriesUpdate) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        raise HTTPException(status_code=404, detail="Session not found.")

    session = next((row for row in sessions if str(row.get("id")) == session_id), None)
    if session is None:
        if session_id.startswith("m-") and session_id[2:].isdigit():
            match_id = int(session_id[2:])
            session = {
                "id": session_id,
                "type": "match",
                "date": "",
                "match_id": match_id,
                "entries": {},
            }
            sessions.append(session)
        else:
            raise HTTPException(status_code=404, detail="Session not found.")

    entries = dict(session.get("entries") or {})
    for player_id, payload in (body.entries or {}).items():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip()
        if not status or status.upper() == "AVAIL":
            entries.pop(player_id, None)
        else:
            entries[player_id] = {"status": _validate_status(status)}
    session["entries"] = entries
    _save_store(store)
    return session


def delete_training_session(*, season: str, session_id: str) -> dict[str, Any]:
    season = _validate_season(season)
    store = _load_store()
    sessions = _season_bucket(store, "sessions", season)
    if not isinstance(sessions, list):
        raise HTTPException(status_code=404, detail="Session not found.")
    kept = [row for row in sessions if str(row.get("id")) != session_id]
    if len(kept) == len(sessions):
        raise HTTPException(status_code=404, detail="Session not found.")
    store["sessions"][season] = kept
    _save_store(store)
    return {"deleted": session_id}


def register_availability_tracker_routes(app: FastAPI) -> None:
    @app.get("/availability-tracker", response_class=HTMLResponse)
    def availability_tracker_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "availability-tracker.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Availability tracker UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/availability/meta")
    def availability_meta_route() -> dict[str, Any]:
        return availability_meta()

    @app.get("/api/availability/board")
    def availability_board_route(
        season: str = Query(DEFAULT_SEASON),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        return build_availability_payload(season=season, refresh=refresh)

    @app.post("/api/availability/roster/import")
    def availability_roster_import_route(
        season: str = Query(DEFAULT_SEASON),
        replace: bool = Query(False),
    ) -> dict[str, Any]:
        # Current season: official club site (names + headshots). Older seasons: Impect.
        if season == "26/27":
            try:
                result = import_roster_from_club_website(season=season)
                if result.get("total"):
                    return result
            except HTTPException as club_exc:
                if club_exc.status_code < 500:
                    raise
                club_error = str(club_exc.detail)
            else:
                club_error = "port-vale.co.uk returned an empty squad."

            store = _load_store()
            if _store_has_active_roster(store, season):
                roster = _active_roster(_roster_for_season(store, season))
                return {
                    "added": 0,
                    "updated": 0,
                    "reactivated": 0,
                    "left_club": 0,
                    "total": len(roster),
                    "total_including_inactive": len(_roster_for_season(store, season)),
                    "source": "cached",
                    "warning": f"{club_error} Using the squad already saved on this machine.",
                }

            try:
                result = import_roster_from_impect(season=season, replace=replace)
                result["warning"] = (
                    f"{club_error} Fell back to Impect"
                    + (
                        f" ({result.get('source_season')})"
                        if result.get("source_season")
                        else ""
                    )
                    + "."
                )
                return result
            except HTTPException:
                raise HTTPException(status_code=502, detail=club_error) from None
        return import_roster_from_impect(season=season, replace=replace)

    @app.post("/api/availability/roster/import-club")
    def availability_roster_import_club_route(
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return import_roster_from_club_website(season=season)

    @app.delete("/api/availability/roster/inactive")
    def availability_roster_delete_inactive_route(
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return remove_inactive_roster_players(season=season)

    @app.post("/api/availability/roster/sync-positions")
    def availability_roster_sync_positions_route(
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return sync_roster_positions_from_impect(season=season)

    @app.post("/api/availability/roster")
    def availability_roster_add_route(
        body: RosterPlayerCreate,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return add_roster_player(season=season, body=body)

    @app.patch("/api/availability/roster/{player_id}")
    def availability_roster_update_route(
        player_id: str,
        body: RosterPlayerUpdate,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return update_roster_player(season=season, player_id=player_id, body=body)

    @app.delete("/api/availability/roster/{player_id}")
    def availability_roster_delete_route(
        player_id: str,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return remove_roster_player(season=season, player_id=player_id)

    @app.put("/api/availability/roster/reorder")
    def availability_roster_reorder_route(
        body: RosterReorderRequest,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return reorder_roster(season=season, body=body)

    @app.put("/api/availability/injury/{player_id}")
    def availability_injury_route(
        player_id: str,
        body: InjuryUpdate,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return set_player_injury(season=season, player_id=player_id, body=body)

    @app.delete("/api/availability/injury/{player_id}")
    def availability_injury_clear_route(
        player_id: str,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return clear_player_injury(season=season, player_id=player_id)

    @app.get("/api/availability/injury-history/{player_id}")
    def availability_injury_history_route(
        player_id: str,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return get_player_injury_detail(season=season, player_id=player_id)

    @app.post("/api/availability/training")
    def availability_training_route(
        body: TrainingLogRequest,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return create_training_session(season=season, body=body)

    @app.post("/api/availability/match")
    def availability_match_route(
        body: MatchLogRequest,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return create_match_session(season=season, body=body)

    @app.patch("/api/availability/session/{session_id}")
    def availability_session_patch_route(
        session_id: str,
        body: SessionEntriesUpdate,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return upsert_session_entries(season=season, session_id=session_id, body=body)

    @app.delete("/api/availability/session/{session_id}")
    def availability_session_delete_route(
        session_id: str,
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return delete_training_session(season=season, session_id=session_id)

    @app.get("/api/availability/photo")
    def availability_photo_route(name: str = Query(..., min_length=1)) -> Response:
        # Prefer compact club-site crops. Local uploads can be multi‑MB originals.
        source_url = resolve_squad_photo_url(name)
        if source_url:
            try:
                image_bytes, content_type = fetch_photo_bytes(source_url)
                return Response(
                    content=image_bytes,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"},
                )
            except RuntimeError:
                pass

        local_path = resolve_local_photo_path(name)
        if local_path is not None:
            content_type = "image/jpeg"
            if local_path.suffix.lower() == ".png":
                content_type = "image/png"
            elif local_path.suffix.lower() == ".webp":
                content_type = "image/webp"
            data = local_path.read_bytes()
            # Skip bloated local originals when a club crop should exist.
            if len(data) <= 750_000 or source_url is None:
                return Response(
                    content=data,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400"},
                )

        if source_url:
            raise HTTPException(status_code=502, detail=f"Could not download squad photo for {name}")
        raise HTTPException(status_code=404, detail=f"No squad photo found for {name}")

    @app.post("/api/availability/photo/{player_id}")
    async def availability_photo_upload_route(
        player_id: str,
        season: str = Query(DEFAULT_SEASON),
        image: bytes = Body(...),
    ) -> dict[str, Any]:
        season = _validate_season(season)
        store = _load_store()
        roster = _roster_for_season(store, season)
        player = _find_player(roster, player_id)
        if player is None:
            raise HTTPException(status_code=404, detail="Player not found.")
        try:
            save_local_player_photo(str(player.get("name") or ""), image)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"photo_url": _photo_url_for_name(str(player.get("name") or ""))}
