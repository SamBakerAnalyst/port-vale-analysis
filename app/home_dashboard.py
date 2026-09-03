"""Home dashboard — team activity feed + app changelog + recruitment/strategy tabs."""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query

from app.fixture_planner import get_fixture_assignments, get_scouting_reports
from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs

logger = logging.getLogger(__name__)

CHANGELOG_PATH = DATA_ROOT / "app-changelog.json"
REPO_CHANGELOG_PATH = STANDALONE_DIR / "app-changelog.json"
UPTIME_JOKE_PATH = STANDALONE_DIR / "hub-uptime-joke.json"
FEEDBACK_LOG = DATA_ROOT / "feedback.jsonl"
RECRUITMENT_DISK_CACHE = DATA_ROOT / "home-recruitment-cache.json"
STANDOUTS_DISK_CACHE = DATA_ROOT / "home-standouts-cache.json"

# Recruitment Stand outs — reuse Player Search / POTM overall (equal-weighted profile avg).
STANDOUTS_DEFAULT_MIN_SCORE = 85.0
STANDOUTS_SEASON_MIN_MINUTES = 0.0
STANDOUTS_MONTH_MIN_MINUTES = 0.0
STANDOUTS_LEAGUES: tuple[str, ...] = (
    "League One",
    "League Two",
    "National League",
    "Scottish Prem",
    "PL2",
    "Irish Prem",
)
STANDOUTS_PER_LEAGUE_LIMIT = 10
STANDOUTS_CACHE_VERSION = 4
STANDOUTS_VIEW_CACHE_TTL = 120.0
STANDOUTS_CACHE_TTL = 6 * 3600.0

# Strategy Report play-off (7th) 4-season averages ÷ 46 games — goals per game by phase.
PLAYOFF_PHASE_GF_PG = {
    "possession": 0.59,
    "transition": 0.52,
    "set_play": 0.46,
}
PLAYOFF_PHASE_GA_PG = {
    "possession": 0.44,
    "transition": 0.43,
    "set_play": 0.30,
}
PHASE_LABELS = {
    "possession": "Possession",
    "transition": "Transition",
    "set_play": "Set play",
}

_recruitment_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_standouts_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_standouts_view_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_strategy_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_fixtures_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_recruitment_refresh_lock = threading.Lock()
_recruitment_refreshing = False
_standouts_refresh_lock = threading.Lock()
_standouts_refreshing: set[str] = set()
_standouts_month_options_cache: tuple[float, list[dict[str, Any]]] | None = None
_resolve_standouts_month_cache: tuple[float, tuple[int, int, str]] | None = None
_strategy_refresh_lock = threading.Lock()
_strategy_refreshing: set[str] = set()
HOME_TAB_CACHE_TTL = 1800.0
RECRUITMENT_DISK_TTL = 6 * 3600.0
FIXTURES_CACHE_TTL = 900.0
STRATEGY_DISK_CACHE = DATA_ROOT / "home-strategy-cache.json"

PORT_VALE_FOTMOB_ID = "9799"
PORT_VALE_NAME = "Port Vale"
# League Two 26/27 (current) + League One 25/26 (history) + cups via team feed.
PV_FOTMOB_LEAGUE_SEASONS: tuple[tuple[str, str, str], ...] = (
    ("League Two", "26/27", "109"),
    ("League One", "25/26", "108"),
)


def _parse_when(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _fixture_label(assignment: dict[str, Any], fixture_id: str) -> str:
    home = str(assignment.get("home") or "").strip()
    away = str(assignment.get("away") or "").strip()
    if home and away:
        return f"{home} vs {away}"
    parts = [p for p in str(fixture_id).split("|") if p]
    if len(parts) >= 3:
        return f"{parts[1].title()} vs {parts[2].title()}"
    return fixture_id


def _league_from_fixture_id(fixture_id: str, assignment: dict[str, Any] | None = None) -> str:
    if assignment:
        league = str(assignment.get("league") or "").strip()
        if league:
            return league
    parts = str(fixture_id).split("|")
    return parts[0] if parts else ""


def build_activity_feed(*, limit: int = 40) -> dict[str, Any]:
    events: list[dict[str, Any]] = []

    assignments = get_fixture_assignments().get("assignments") or {}
    for fixture_id, row in assignments.items():
        if not isinstance(row, dict):
            continue
        staff = ", ".join(
            part
            for part in (
                [str(row.get("staff") or "").strip()]
                if not isinstance(row.get("staff"), list)
                else [str(name or "").strip() for name in row.get("staff") or []]
            )
            if part
        )
        watch = str(row.get("watch_type") or "").strip().upper()
        when = _parse_when(row.get("updated_at")) or _parse_when(row.get("date"))
        label = _fixture_label(row, str(fixture_id))
        league = _league_from_fixture_id(str(fixture_id), row)
        date_key = str(row.get("date") or "")[:10]

        if staff and watch:
            events.append(
                {
                    "id": f"assign:{fixture_id}",
                    "kind": "assignment",
                    "icon": "📅",
                    "title": f"{staff} → {watch}",
                    "detail": f"{label}" + (f" · {date_key}" if date_key else ""),
                    "meta": league,
                    "at": when.isoformat() if when else None,
                    "href": "/played-fixtures" if watch == "VIDEO" else "/fixture-planner",
                }
            )

        for player in row.get("watched_players") or []:
            if not isinstance(player, dict):
                continue
            name = str(player.get("name") or player.get("player_name") or "").strip()
            if not name:
                continue
            player_when = _parse_when(player.get("updated_at") or player.get("marked_at")) or when
            events.append(
                {
                    "id": f"watch:{fixture_id}:{player.get('id') or name}",
                    "kind": "watched",
                    "icon": "👀",
                    "title": f"{staff or 'Scout'} watched {name}",
                    "detail": label + (f" · {date_key}" if date_key else ""),
                    "meta": league,
                    "at": player_when.isoformat() if player_when else None,
                    "href": "/played-fixtures",
                }
            )

    reports_store = get_scouting_reports().get("reports") or {}
    for fixture_id, fixture_reports in reports_store.items():
        if not isinstance(fixture_reports, dict):
            continue
        label = _fixture_label({}, str(fixture_id))
        league = _league_from_fixture_id(str(fixture_id))
        for player_key, row in fixture_reports.items():
            if not isinstance(row, dict):
                continue
            staff = str(row.get("staff") or "Scout").strip() or "Scout"
            player = str(row.get("player_name") or "").strip() or f"Player {player_key}"
            team = str(row.get("team") or "").strip()
            date_key = str(row.get("fixture_date") or "")[:10]
            when = _parse_when(row.get("marked_at"))
            events.append(
                {
                    "id": f"report:{fixture_id}:{player_key}",
                    "kind": "report",
                    "icon": "📝",
                    "title": f"{staff} logged report · {player}",
                    "detail": (f"{team} · " if team else "") + label + (f" · {date_key}" if date_key else ""),
                    "meta": league,
                    "at": when.isoformat() if when else None,
                    "href": "/played-fixtures",
                }
            )

    # Recent feedback as lightweight “team notes”
    if FEEDBACK_LOG.exists():
        try:
            lines = FEEDBACK_LOG.read_text(encoding="utf-8").splitlines()[-20:]
            for line in lines:
                if not line.strip():
                    continue
                row = json.loads(line)
                when = _parse_when(row.get("created_at") or row.get("ts") or row.get("at"))
                message = str(row.get("message") or "").strip()
                if len(message) > 90:
                    message = message[:87] + "…"
                who = str(row.get("display_name") or row.get("username") or "").strip()
                title = "Suggestion / bug logged"
                if who:
                    title = f"Suggestion from {who}"
                events.append(
                    {
                        "id": f"feedback:{row.get('id') or when}",
                        "kind": "feedback",
                        "icon": "💬",
                        "title": title,
                        "detail": message or "Feedback submitted",
                        "meta": str(row.get("page") or "Hub"),
                        "at": when.isoformat() if when else None,
                        "href": "/",
                    }
                )
        except (OSError, json.JSONDecodeError):
            pass

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("at") or "")

    events.sort(key=sort_key, reverse=True)
    events = events[: max(1, min(limit, 100))]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(events),
        "events": events,
    }


def _person_name_key(name: str) -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _empty_scout_counts() -> dict[str, int]:
    return {"live_watches": 0, "video_watches": 0, "report_count": 0}


def _merge_scout_counts(*rows: dict[str, int] | None) -> dict[str, int]:
    merged = _empty_scout_counts()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in merged:
            merged[key] += int(row.get(key) or 0)
    return merged


def _build_player_scout_coverage() -> dict[int, dict[str, int]]:
    """Live / video watches + report counts keyed by Impect player_id.

    Manual fixtures use synthetic (negative) player IDs — those are indexed by
    normalised player name instead and merged in `_attach_scout_coverage`.
    """
    by_id, _by_name = _build_player_scout_coverage_maps()
    return by_id


def _build_player_scout_coverage_maps() -> tuple[dict[int, dict[str, int]], dict[str, dict[str, int]]]:
    by_id: dict[int, dict[str, int]] = {}
    by_name: dict[str, dict[str, int]] = {}

    def bump_id(player_id: int, field: str) -> None:
        if player_id <= 0:
            return
        entry = by_id.setdefault(player_id, _empty_scout_counts())
        entry[field] += 1

    def bump_name(name: str, field: str) -> None:
        key = _person_name_key(name)
        if not key:
            return
        entry = by_name.setdefault(key, _empty_scout_counts())
        entry[field] += 1

    def bump_player(*, player_id: int, name: str, field: str) -> None:
        # Real Impect IDs count by id; manual / synthetic IDs count by name so
        # Who To Scout / home standouts can still match typed players.
        if player_id > 0:
            bump_id(player_id, field)
        else:
            bump_name(name, field)

    assignments = get_fixture_assignments().get("assignments") or {}
    for row in assignments.values():
        if not isinstance(row, dict):
            continue
        watch = str(row.get("watch_type") or "").strip().upper()
        if watch not in {"LIVE", "VIDEO"}:
            continue
        field = "live_watches" if watch == "LIVE" else "video_watches"
        for player in row.get("watched_players") or []:
            if not isinstance(player, dict):
                continue
            try:
                player_id = int(player.get("player_id") or 0)
            except (TypeError, ValueError):
                player_id = 0
            name = str(player.get("player_name") or player.get("name") or "").strip()
            bump_player(player_id=player_id, name=name, field=field)

    # Manual fixtures also store watched players (covers cases where assignment
    # sync is missing but the manual card still has the names).
    try:
        from app.fixture_planner import list_manual_fixtures

        for fixture in list_manual_fixtures():
            watch = str(fixture.get("watch_type") or "").strip().upper()
            if watch not in {"LIVE", "VIDEO"}:
                # Fall back to assignment watch type for the same fixture id.
                assignment = assignments.get(str(fixture.get("fixture_id") or "")) or {}
                watch = str(assignment.get("watch_type") or "").strip().upper()
            if watch not in {"LIVE", "VIDEO"}:
                continue
            field = "live_watches" if watch == "LIVE" else "video_watches"
            fixture_id = str(fixture.get("fixture_id") or "")
            assignment_players = {
                int(p.get("player_id") or 0)
                for p in (assignments.get(fixture_id) or {}).get("watched_players") or []
                if isinstance(p, dict)
            }
            assignment_names = {
                _person_name_key(str(p.get("player_name") or p.get("name") or ""))
                for p in (assignments.get(fixture_id) or {}).get("watched_players") or []
                if isinstance(p, dict)
            }
            for player in fixture.get("watched_players") or []:
                if not isinstance(player, dict):
                    continue
                try:
                    player_id = int(player.get("player_id") or 0)
                except (TypeError, ValueError):
                    player_id = 0
                name = str(player.get("player_name") or player.get("name") or "").strip()
                # Skip if already counted via the assignment row for this fixture.
                if player_id > 0 and player_id in assignment_players:
                    continue
                if player_id <= 0 and _person_name_key(name) in assignment_names:
                    continue
                bump_player(player_id=player_id, name=name, field=field)
    except Exception:
        logger.exception("Could not include manual fixtures in scout coverage")

    reports_store = get_scouting_reports().get("reports") or {}
    for fixture_id, fixture_reports in reports_store.items():
        if not isinstance(fixture_reports, dict):
            continue
        fixture_token = str(fixture_id or "")
        assignment = assignments.get(fixture_token) or {}
        watch = str(assignment.get("watch_type") or "").strip().upper()
        if watch not in {"LIVE", "VIDEO"}:
            try:
                from app.fixture_planner import get_manual_fixture

                manual = get_manual_fixture(fixture_token)
            except Exception:
                manual = None
            if isinstance(manual, dict):
                watch = str(manual.get("watch_type") or "").strip().upper()
        watch_field = (
            "live_watches" if watch == "LIVE" else "video_watches" if watch == "VIDEO" else None
        )

        already_ids: set[int] = set()
        already_names: set[str] = set()
        for player in assignment.get("watched_players") or []:
            if not isinstance(player, dict):
                continue
            try:
                pid = int(player.get("player_id") or 0)
            except (TypeError, ValueError):
                pid = 0
            if pid > 0:
                already_ids.add(pid)
            name_key = _person_name_key(str(player.get("player_name") or player.get("name") or ""))
            if name_key:
                already_names.add(name_key)

        for player_key, row in fixture_reports.items():
            if not isinstance(row, dict):
                continue
            try:
                player_id = int(row.get("player_id") or player_key or 0)
            except (TypeError, ValueError):
                player_id = 0
            name = str(row.get("player_name") or "").strip()
            bump_player(player_id=player_id, name=name, field="report_count")

            # Pitch / squad report marks also count as a LIVE or VIDEO watch for
            # that fixture's coverage type (without double-counting assign picks).
            if not watch_field:
                continue
            name_key = _person_name_key(name)
            if player_id > 0 and player_id in already_ids:
                continue
            if player_id <= 0 and name_key and name_key in already_names:
                continue
            bump_player(player_id=player_id, name=name, field=watch_field)
            if player_id > 0:
                already_ids.add(player_id)
            if name_key:
                already_names.add(name_key)

    return by_id, by_name


def _attach_scout_coverage(players: list[dict[str, Any]]) -> None:
    by_id, by_name = _build_player_scout_coverage_maps()
    for player in players:
        try:
            player_id = int(player.get("playerId") or 0)
        except (TypeError, ValueError):
            player_id = 0
        name_key = _person_name_key(str(player.get("name") or ""))
        scout = _merge_scout_counts(
            by_id.get(player_id) if player_id > 0 else None,
            by_name.get(name_key) if name_key else None,
        )
        player["scout"] = scout
        player["scout_total"] = (
            int(scout["live_watches"])
            + int(scout["video_watches"])
            + int(scout["report_count"])
        )


def _default_changelog() -> list[dict[str, Any]]:
    return [
        {
            "date": "2026-07-23",
            "title": "Player pages from home search",
            "detail": "Search any Impect player on Home to open their dossier — photo, profiles, reports, recent games, and scores.",
            "tag": "Hub",
        },
        {
            "date": "2026-07-23",
            "title": "Home dashboard relaunch",
            "detail": "Left app ribbon plus live league table, form, and squad-vs-league widgets.",
            "tag": "Hub",
        },
        {
            "date": "2026-07-23",
            "title": "Home tabs + live team activity",
            "detail": "Performance / Recruitment / Strategy tabs, plus live scout watches, reports, and assignments.",
            "tag": "Hub",
        },
        {
            "date": "2026-07-22",
            "title": "Played Fixtures + Scout Summary",
            "detail": "VIDEO coverage, player reports, and scout summary now flow from Fixture Planner.",
            "tag": "Scouts",
        },
        {
            "date": "2026-07-21",
            "title": "Club Strategy + Availability",
            "detail": "League standings/xG strategy board and squad availability tracker added under Strategy.",
            "tag": "Strategy",
        },
    ]


def _read_changelog_entries(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("entries") if isinstance(payload, dict) else payload
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    return []


def load_changelog(*, limit: int = 20) -> dict[str, Any]:
    """Release notes shipped with the repo (staging → live). Data override optional."""
    ensure_data_dirs()
    entries: list[dict[str, Any]] = []
    # Repo file wins so every Live promote can ship fresh notes with the code.
    if REPO_CHANGELOG_PATH.exists():
        entries = _read_changelog_entries(REPO_CHANGELOG_PATH)
    if not entries and CHANGELOG_PATH.exists():
        entries = _read_changelog_entries(CHANGELOG_PATH)
    if not entries:
        entries = _default_changelog()
        REPO_CHANGELOG_PATH.write_text(
            json.dumps({"version": 1, "entries": entries}, indent=2) + "\n",
            encoding="utf-8",
        )

    def entry_key(row: dict[str, Any]) -> str:
        return str(row.get("date") or row.get("at") or "")

    entries = sorted(entries, key=entry_key, reverse=True)[: max(1, min(limit, 50))]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(entries),
        "entries": entries,
    }


def load_days_since_broke() -> dict[str, Any]:
    """Joke counter for the hub top bar — edit standalone/hub-uptime-joke.json to reset."""
    last_broke = date(2026, 9, 3)
    if UPTIME_JOKE_PATH.exists():
        try:
            payload = json.loads(UPTIME_JOKE_PATH.read_text(encoding="utf-8"))
            raw = str(payload.get("last_broke") or "").strip()[:10]
            if raw:
                last_broke = date.fromisoformat(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    today = datetime.now(UTC).date()
    days = max(0, (today - last_broke).days)
    label = "day" if days == 1 else "days"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "last_broke": last_broke.isoformat(),
        "days": days,
        "label": f"{days} {label} since we last broke",
    }


def _pct(part: float, whole: float) -> float | None:
    if whole <= 0:
        return None
    return round(100.0 * part / whole, 1)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 1)


def _safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 1)


def _age_band(age: int) -> str:
    if age < 21:
        return "U21"
    if age <= 25:
        return "21–25"
    if age <= 29:
        return "26–29"
    return "30+"


def _ordinal_rank(rank: int) -> str:
    if 10 <= (rank % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def _squad_minutes_for_roster(
    *,
    iteration_id: int,
    squad_id: int,
    roster_ids: set[int],
    impect: Any,
) -> dict[int, float]:
    """Minutes by player for one squad; only players on that club's roster."""
    minutes_by_player: dict[int, float] = {}
    if not roster_ids:
        return minutes_by_player
    try:
        score_rows, _ = impect._fetch_profile_scores(
            iteration_id,
            int(squad_id),
            list(impect.ALLOWED_POSITIONS),
            0,
        )
    except Exception:  # noqa: BLE001
        return minutes_by_player

    for row in score_rows:
        if not isinstance(row, dict) or row.get("playerId") is None:
            continue
        player_id = int(row["playerId"])
        if player_id not in roster_ids:
            continue
        minutes = float(impect._play_duration_minutes(row) or 0.0)
        if minutes <= 0:
            continue
        minutes_by_player[player_id] = max(minutes_by_player.get(player_id, 0.0), minutes)
    return minutes_by_player


def _profile_from_minutes(
    *,
    squad_id: int,
    squad_name: str,
    roster_ids: set[int],
    minutes_by_player: dict[int, float],
    age_by_id: dict[int, int],
    name_by_id: dict[int, str],
) -> dict[str, Any]:
    roster_ages = [float(age_by_id[pid]) for pid in roster_ids if pid in age_by_id]
    weighted_age_num = 0.0
    weighted_age_den = 0.0
    band_minutes = {"U21": 0.0, "21–25": 0.0, "26–29": 0.0, "30+": 0.0}
    u21_minutes = 0.0
    u23_minutes = 0.0
    u25_minutes = 0.0
    total_minutes = 0.0
    u25_regulars = 0
    used_count = 0

    for player_id, minutes in minutes_by_player.items():
        if minutes <= 0:
            continue
        age = age_by_id.get(player_id)
        if age is None:
            continue
        used_count += 1
        total_minutes += minutes
        weighted_age_num += age * minutes
        weighted_age_den += minutes
        band_minutes[_age_band(age)] += minutes
        if age < 21:
            u21_minutes += minutes
        if age < 23:
            u23_minutes += minutes
        if age < 25:
            u25_minutes += minutes
        if age < 25 and minutes >= 500:
            u25_regulars += 1

    band_rows = []
    for label in ("U21", "21–25", "26–29", "30+"):
        mins = band_minutes[label]
        band_rows.append(
            {
                "label": label,
                "minutes": int(round(mins)),
                "share_pct": _pct(mins, total_minutes),
            }
        )

    youngest = None
    oldest = None
    by_age = [
        (
            age_by_id[pid],
            name_by_id.get(pid, f"Player {pid}"),
            int(round(minutes_by_player.get(pid, 0))),
        )
        for pid in minutes_by_player
        if pid in age_by_id and minutes_by_player.get(pid, 0) > 0
    ]
    if by_age:
        by_age.sort(key=lambda row: (row[0], row[1]))
        youngest = {"age": by_age[0][0], "name": by_age[0][1], "minutes": by_age[0][2]}
        oldest = {"age": by_age[-1][0], "name": by_age[-1][1], "minutes": by_age[-1][2]}

    return {
        "squad_id": int(squad_id),
        "squad_name": squad_name,
        "roster_size": len(roster_ids),
        "players_with_minutes": used_count,
        "total_minutes": int(round(total_minutes)),
        "avg_age": _safe_mean(roster_ages),
        "median_age": _safe_median(roster_ages),
        "minutes_weighted_age": (
            round(weighted_age_num / weighted_age_den, 1) if weighted_age_den else None
        ),
        "u21_minutes_pct": _pct(u21_minutes, total_minutes),
        "u23_minutes_pct": _pct(u23_minutes, total_minutes),
        "u25_minutes_pct": _pct(u25_minutes, total_minutes),
        "u25_regulars_500": u25_regulars,
        "age_bands": band_rows,
        "youngest_regular": youngest,
        "oldest_regular": oldest,
    }


def _league_metric_row(
    profiles: list[dict[str, Any]],
    *,
    key: str,
    label: str,
    focus_squad_id: int,
    higher_is_better: bool,
    digits: int = 1,
    suffix: str = "",
) -> dict[str, Any] | None:
    scored: list[tuple[int, float, str]] = []
    for profile in profiles:
        value = profile.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        scored.append(
            (
                int(profile["squad_id"]),
                numeric,
                str(profile.get("squad_name") or profile["squad_id"]),
            )
        )
    if not scored:
        return None

    scored.sort(key=lambda row: row[1], reverse=higher_is_better)
    focus = next((row for row in scored if row[0] == int(focus_squad_id)), None)
    if focus is None:
        return None
    rank = next(i for i, row in enumerate(scored, 1) if row[0] == int(focus_squad_id))
    league_avg = round(statistics.mean(row[1] for row in scored), digits)
    us = round(focus[1], digits)
    standings = [
        {
            "rank": index,
            "squad_id": squad_id,
            "club": club,
            "value": round(value, digits),
            "focus": squad_id == int(focus_squad_id),
        }
        for index, (squad_id, value, club) in enumerate(scored, 1)
    ]
    return {
        "key": key,
        "label": label,
        "us": us,
        "league_avg": league_avg,
        "delta": round(us - league_avg, digits),
        "rank": rank,
        "rank_label": _ordinal_rank(rank),
        "squads": len(scored),
        "higher_is_better": higher_is_better,
        "digits": digits,
        "suffix": suffix,
        "standings": standings,
    }


def _league_band_rows(
    profiles: list[dict[str, Any]],
    *,
    focus_squad_id: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in ("U21", "21–25", "26–29", "30+"):
        scored: list[tuple[int, float]] = []
        focus_minutes = None
        for profile in profiles:
            band = next(
                (b for b in (profile.get("age_bands") or []) if b.get("label") == label),
                None,
            )
            if not band or band.get("share_pct") is None:
                continue
            share = float(band["share_pct"])
            scored.append((int(profile["squad_id"]), share))
            if int(profile["squad_id"]) == int(focus_squad_id):
                focus_minutes = band.get("minutes")
        if not scored:
            continue
        # Youth bands: more share ranks higher. Older bands: more share ranks higher
        # too (descriptive), with higher_is_better for U21/21-25 only in UI tint.
        higher_is_better = label in {"U21", "21–25"}
        scored.sort(key=lambda row: row[1], reverse=True)
        focus = next((row for row in scored if row[0] == int(focus_squad_id)), None)
        if focus is None:
            continue
        rank = next(i for i, row in enumerate(scored, 1) if row[0] == int(focus_squad_id))
        league_avg = round(statistics.mean(row[1] for row in scored), 1)
        us = round(focus[1], 1)
        name_by_squad = {
            int(profile["squad_id"]): str(profile.get("squad_name") or profile["squad_id"])
            for profile in profiles
        }
        standings = [
            {
                "rank": index,
                "squad_id": squad_id,
                "club": name_by_squad.get(squad_id, str(squad_id)),
                "value": round(share, 1),
                "focus": squad_id == int(focus_squad_id),
            }
            for index, (squad_id, share) in enumerate(scored, 1)
        ]
        rows.append(
            {
                "label": label,
                "us_pct": us,
                "league_avg_pct": league_avg,
                "delta_pp": round(us - league_avg, 1),
                "minutes": focus_minutes,
                "rank": rank,
                "rank_label": _ordinal_rank(rank),
                "squads": len(scored),
                "higher_is_better": higher_is_better,
                "standings": standings,
            }
        )
    return rows


def _load_recruitment_disk() -> tuple[float, dict[str, Any]] | None:
    try:
        if not RECRUITMENT_DISK_CACHE.exists():
            return None
        raw = json.loads(RECRUITMENT_DISK_CACHE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        payload = raw.get("payload")
        saved_at = float(raw.get("saved_at") or 0)
        if not isinstance(payload, dict) or not payload:
            return None
        return saved_at, payload
    except Exception:  # noqa: BLE001
        return None


def _save_recruitment_disk(payload: dict[str, Any]) -> None:
    try:
        ensure_data_dirs()
        RECRUITMENT_DISK_CACHE.write_text(
            json.dumps(
                {"saved_at": time.time(), "payload": payload},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write recruitment disk cache")


def _schedule_recruitment_refresh() -> None:
    global _recruitment_refreshing
    with _recruitment_refresh_lock:
        if _recruitment_refreshing:
            return
        _recruitment_refreshing = True

    def _run() -> None:
        global _recruitment_refreshing
        try:
            build_recruitment_snapshot(force_refresh=True, _from_background=True)
        except Exception:  # noqa: BLE001
            logger.exception("Background recruitment refresh failed")
        finally:
            with _recruitment_refresh_lock:
                _recruitment_refreshing = False

    threading.Thread(target=_run, name="recruitment-refresh", daemon=True).start()


def _recruitment_building_payload() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "building": True,
        "error": None,
        "season": None,
        "competition": None,
        "league_metrics": [],
        "league_age_bands": [],
        "age_bands": [],
        "league_squads": 0,
    }


def build_recruitment_snapshot(
    *,
    force_refresh: bool = False,
    _from_background: bool = False,
) -> dict[str, Any]:
    """Squad age + minutes-by-age recruitment KPIs, with league avg + rank tables."""
    cache_key = "recruitment"
    cached = _recruitment_cache.get(cache_key)
    now = time.time()
    if not force_refresh and cached and now - cached[0] < HOME_TAB_CACHE_TTL:
        return cached[1]

    if not force_refresh:
        disk = _load_recruitment_disk()
        if disk is not None:
            saved_at, payload = disk
            _recruitment_cache[cache_key] = (saved_at, payload)
            if now - saved_at >= HOME_TAB_CACHE_TTL and not _from_background:
                _schedule_recruitment_refresh()
            return payload
        # Never block the HTTP request on a cold full-league crawl (causes 502s).
        if not _from_background:
            _schedule_recruitment_refresh()
            return _recruitment_building_payload()

    from app import main as impect
    from app.squad_review import (
        _resolve_port_vale_iteration,
        _resolve_port_vale_squad_id,
        _squad_minutes_cache,
    )

    iteration = _resolve_port_vale_iteration()
    iteration_id = int(iteration["id"])
    season = str(iteration.get("season") or "").strip()
    competition = str(iteration.get("competition_name") or "").strip()
    squad_names = impect._fetch_squad_names(iteration_id)
    port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
    if port_vale_squad_id is None:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "error": "Could not resolve Port Vale squad for this season.",
            "season": season,
            "competition": competition,
        }
        _recruitment_cache[cache_key] = (now, payload)
        return payload

    players = impect._fetch_players_for_iteration(iteration_id)
    age_by_id: dict[int, int] = {}
    name_by_id: dict[int, str] = {}
    roster_by_squad: dict[int, set[int]] = {}
    for player in players:
        if not isinstance(player, dict) or player.get("id") is None:
            continue
        player_id = int(player["id"])
        squad_id = impect._extract_squad_id_from_player(player)
        age = impect._player_age(player)
        if age is not None:
            age_by_id[player_id] = int(age)
        name = impect._extract_player_name(player)
        if name:
            name_by_id[player_id] = name
        if squad_id is None:
            continue
        roster_by_squad.setdefault(int(squad_id), set()).add(player_id)

    squad_ids = [int(sid) for sid in impect._fetch_squad_ids(iteration_id)]
    if int(port_vale_squad_id) not in squad_ids:
        squad_ids.append(int(port_vale_squad_id))

    minutes_by_squad: dict[int, dict[int, float]] = {}

    def load_squad_minutes(squad_id: int) -> tuple[int, dict[int, float]]:
        return squad_id, _squad_minutes_for_roster(
            iteration_id=iteration_id,
            squad_id=squad_id,
            roster_ids=roster_by_squad.get(int(squad_id), set()),
            impect=impect,
        )

    max_workers = min(8, max(len(squad_ids), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(load_squad_minutes, sid) for sid in squad_ids]
        for future in as_completed(futures):
            squad_id, minutes_map = future.result()
            minutes_by_squad[int(squad_id)] = minutes_map

    pv_minutes = minutes_by_squad.get(int(port_vale_squad_id), {})
    _squad_minutes_cache[(iteration_id, port_vale_squad_id)] = pv_minutes

    profiles: list[dict[str, Any]] = []
    for squad_id in squad_ids:
        profiles.append(
            _profile_from_minutes(
                squad_id=squad_id,
                squad_name=str(squad_names.get(squad_id) or f"Squad {squad_id}"),
                roster_ids=roster_by_squad.get(int(squad_id), set()),
                minutes_by_player=minutes_by_squad.get(int(squad_id), {}),
                age_by_id=age_by_id,
                name_by_id=name_by_id,
            )
        )

    pv = next(
        (p for p in profiles if int(p["squad_id"]) == int(port_vale_squad_id)),
        None,
    )
    if pv is None:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "error": "Could not build Port Vale recruitment profile.",
            "season": season,
            "competition": competition,
        }
        _recruitment_cache[cache_key] = (now, payload)
        return payload

    metric_defs = [
        ("avg_age", "Avg squad age", False, 1, ""),
        ("median_age", "Median squad age", False, 1, ""),
        ("minutes_weighted_age", "Mins-weighted age", False, 1, ""),
        ("u25_minutes_pct", "Minutes from U25", True, 1, "%"),
        ("u23_minutes_pct", "Minutes from U23", True, 1, "%"),
        ("u21_minutes_pct", "Minutes from U21", True, 1, "%"),
        ("u25_regulars_500", "U25 with 500+ mins", True, 0, ""),
        ("total_minutes", "Total minutes", True, 0, ""),
    ]
    league_metrics = []
    for key, label, higher, digits, suffix in metric_defs:
        row = _league_metric_row(
            profiles,
            key=key,
            label=label,
            focus_squad_id=int(port_vale_squad_id),
            higher_is_better=higher,
            digits=digits,
            suffix=suffix,
        )
        if row:
            league_metrics.append(row)

    league_bands = _league_band_rows(profiles, focus_squad_id=int(port_vale_squad_id))
    u25_row = next((r for r in league_metrics if r["key"] == "u25_minutes_pct"), None)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "season": season,
        "competition": competition,
        "squad_id": port_vale_squad_id,
        "roster_size": pv["roster_size"],
        "players_with_minutes": pv["players_with_minutes"],
        "total_minutes": pv["total_minutes"],
        "avg_age": pv["avg_age"],
        "median_age": pv["median_age"],
        "minutes_weighted_age": pv["minutes_weighted_age"],
        "u21_minutes_pct": pv["u21_minutes_pct"],
        "u23_minutes_pct": pv["u23_minutes_pct"],
        "u25_minutes_pct": pv["u25_minutes_pct"],
        "league_u25_minutes_pct": u25_row["league_avg"] if u25_row else None,
        "u25_vs_league": u25_row["delta"] if u25_row else None,
        "u25_regulars_500": pv["u25_regulars_500"],
        "age_bands": pv["age_bands"],
        "youngest_regular": pv["youngest_regular"],
        "oldest_regular": pv["oldest_regular"],
        "league_metrics": league_metrics,
        "league_age_bands": league_bands,
        "league_squads": len(profiles),
    }
    _recruitment_cache[cache_key] = (now, payload)
    if not payload.get("error"):
        _save_recruitment_disk(payload)
    return payload


def _phase_rows(
    summary: dict[str, Any],
    *,
    matches: int,
    side: str,
    benchmark: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("possession", "transition", "set_play"):
        goals = float(summary.get(f"{key}_{'for' if side == 'for' else 'against'}") or 0)
        per_game = round(goals / matches, 2) if matches else None
        bench = benchmark[key]
        delta = round(per_game - bench, 2) if per_game is not None else None
        rows.append(
            {
                "key": key,
                "label": PHASE_LABELS[key],
                "goals": int(goals),
                "per_game": per_game,
                "benchmark_per_game": bench,
                "delta_vs_playoff": delta,
                "on_track": (
                    (delta is not None and delta >= -0.05)
                    if side == "for"
                    else (delta is not None and delta <= 0.05)
                ),
            }
        )
    return rows


def _load_strategy_disk(competition: str) -> tuple[float, dict[str, Any]] | None:
    try:
        if not STRATEGY_DISK_CACHE.exists():
            return None
        raw = json.loads(STRATEGY_DISK_CACHE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        by_comp = raw.get("by_competition") or {}
        entry = by_comp.get(competition)
        if not isinstance(entry, dict):
            return None
        payload = entry.get("payload")
        saved_at = float(entry.get("saved_at") or 0)
        if not isinstance(payload, dict) or not payload:
            return None
        return saved_at, payload
    except Exception:  # noqa: BLE001
        return None


def _save_strategy_disk(competition: str, payload: dict[str, Any]) -> None:
    try:
        ensure_data_dirs()
        raw: dict[str, Any] = {"by_competition": {}}
        if STRATEGY_DISK_CACHE.exists():
            try:
                existing = json.loads(STRATEGY_DISK_CACHE.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(existing.get("by_competition"), dict):
                    raw = existing
            except Exception:  # noqa: BLE001
                pass
        raw.setdefault("by_competition", {})[competition] = {
            "saved_at": time.time(),
            "payload": payload,
        }
        STRATEGY_DISK_CACHE.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write strategy disk cache")


def _schedule_strategy_refresh(competition: str) -> None:
    with _strategy_refresh_lock:
        if competition in _strategy_refreshing:
            return
        _strategy_refreshing.add(competition)

    def _run() -> None:
        try:
            build_strategy_snapshot(
                competition=competition,
                force_refresh=True,
                detail=True,
                _from_background=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Background strategy refresh failed")
        finally:
            with _strategy_refresh_lock:
                _strategy_refreshing.discard(competition)

    threading.Thread(
        target=_run, name=f"strategy-refresh-{competition}", daemon=True
    ).start()


def build_strategy_snapshot(
    *,
    competition: str = "League Two",
    force_refresh: bool = False,
    detail: bool = True,
    _from_background: bool = False,
) -> dict[str, Any]:
    """PPG pace + optional phase goals / first-goal game state for the Strategy tab."""
    cache_key = f"strategy:{competition}:{'full' if detail else 'fast'}"
    cached = _strategy_cache.get(cache_key)
    now = time.time()
    if not force_refresh and cached and now - cached[0] < HOME_TAB_CACHE_TTL:
        return cached[1]

    if detail and not force_refresh:
        disk = _load_strategy_disk(competition)
        if disk is not None:
            saved_at, payload = disk
            _strategy_cache[cache_key] = (saved_at, payload)
            if now - saved_at >= HOME_TAB_CACHE_TTL and not _from_background:
                _schedule_strategy_refresh(competition)
            return payload
        # Cold path: don't block the request on 46-match event scans.
        if not _from_background:
            fast = build_strategy_snapshot(
                competition=competition,
                force_refresh=force_refresh,
                detail=False,
                _from_background=True,
            )
            deferred = {
                **fast,
                "detail": True,
                "phases": {
                    "matches": 0,
                    "scored": [],
                    "conceded": [],
                    "deferred": True,
                },
                "game_state": {"deferred": True},
            }
            _schedule_strategy_refresh(competition)
            return deferred

    from app.club_strategy import (
        build_club_strategy_report,
        build_first_goal_report,
        club_strategy_meta,
    )
    from app.pre_match_goals import build_goals_analysis
    from app.squad_review import _resolve_port_vale_squad_id
    from app import main as impect

    meta = club_strategy_meta(competition)
    iteration_id = int(meta.get("default_iteration_id") or 0)
    if not iteration_id:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "error": f"No iteration found for {competition}.",
            "competition": competition,
        }
        _strategy_cache[cache_key] = (now, payload)
        return payload

    season_label = next(
        (
            str(row.get("label") or row.get("season") or "")
            for row in (meta.get("seasons") or [])
            if int(row.get("iteration_id") or 0) == iteration_id
        ),
        competition,
    )

    report = build_club_strategy_report(iteration_id)
    standings = report.get("standings") or []
    averages = report.get("averages") or {}
    pv = next((row for row in standings if row.get("focus")), None)
    if pv is None and standings:
        pv = next(
            (row for row in standings if "vale" in str(row.get("club") or "").casefold()),
            standings[-1],
        )

    auto_row = standings[2] if len(standings) >= 3 else None
    playoff_row = standings[5] if len(standings) >= 6 else None
    safety_row = standings[-4] if len(standings) >= 4 else None

    ppg = float(pv.get("ppg") or 0) if pv else None
    playoff_ppg = float(playoff_row.get("ppg") or 0) if playoff_row else None
    auto_ppg = float(auto_row.get("ppg") or 0) if auto_row else None
    safety_ppg = float(safety_row.get("ppg") or 0) if safety_row else None
    on_track_playoff = (
        ppg is not None and playoff_ppg is not None and ppg + 1e-9 >= playoff_ppg
    )
    pts_gap_playoff = None
    if pv and playoff_row:
        pts_gap_playoff = int(pv.get("points") or 0) - int(playoff_row.get("points") or 0)

    squad_id = None
    try:
        squad_names = impect._fetch_squad_names(iteration_id)
        squad_id = _resolve_port_vale_squad_id(squad_names)
    except Exception:  # noqa: BLE001
        squad_id = None
    if squad_id is None and pv:
        try:
            squad_id = int(pv.get("squad_id") or pv.get("id") or 0) or None
        except (TypeError, ValueError):
            squad_id = None

    phases: dict[str, Any] = {"matches": 0, "scored": [], "conceded": [], "deferred": not detail}
    game_state: dict[str, Any] = {"deferred": not detail}

    if detail:
        if squad_id:
            try:
                goals = build_goals_analysis(iteration_id, int(squad_id))
                matches = int(goals.get("matches") or 0)
                summary = goals.get("summary") or {}
                phases = {
                    "matches": matches,
                    "goals_for": int(summary.get("goals_for") or 0),
                    "goals_against": int(summary.get("goals_against") or 0),
                    "scored": _phase_rows(
                        summary, matches=matches, side="for", benchmark=PLAYOFF_PHASE_GF_PG
                    ),
                    "conceded": _phase_rows(
                        summary,
                        matches=matches,
                        side="against",
                        benchmark=PLAYOFF_PHASE_GA_PG,
                    ),
                    "benchmark_label": "Play-off (7th) Strategy Report avg",
                }
            except Exception as exc:  # noqa: BLE001
                phases = {"matches": 0, "scored": [], "conceded": [], "error": str(exc)}

        try:
            first_goal = build_first_goal_report(iteration_id)
            rows = first_goal.get("rows") or first_goal.get("standings") or []
            fg_avg = first_goal.get("averages") or {}
            fg_pv = next((row for row in rows if row.get("focus")), None)
            if fg_pv is None and squad_id is not None:
                fg_pv = next(
                    (
                        row
                        for row in rows
                        if int(row.get("squad_id") or row.get("id") or 0) == int(squad_id)
                    ),
                    None,
                )
            if fg_pv:
                game_state = {
                    "scored_first": int(fg_pv.get("fg_scored") or 0),
                    "conceded_first": int(fg_pv.get("fg_conceded") or 0),
                    "ppg_scored_first": fg_pv.get("fgs_ppg"),
                    "ppg_conceded_first": fg_pv.get("fgc_ppg"),
                    "league_ppg_scored_first": fg_avg.get("fgs_ppg"),
                    "league_ppg_conceded_first": fg_avg.get("fgc_ppg"),
                    "clean_sheet_pct": pv.get("clean_sheet_pct") if pv else None,
                    "league_clean_sheet_pct": averages.get("clean_sheet_pct"),
                }
        except Exception as exc:  # noqa: BLE001
            game_state = {"error": str(exc)}

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": competition,
        "season": season_label,
        "iteration_id": iteration_id,
        "squad_id": squad_id,
        "detail": detail,
        "pace": {
            "position": pv.get("position") if pv else None,
            "played": pv.get("played") if pv else None,
            "points": pv.get("points") if pv else None,
            "ppg": pv.get("ppg") if pv else None,
            "ppg_x46": pv.get("ppg_x46") if pv else None,
            "xppg": pv.get("xppg") if pv else None,
            "xppg_x46": pv.get("xppg_x46") if pv else None,
            "xp_vs_actual": pv.get("xp_vs_actual") if pv else None,
            "league_ppg": averages.get("ppg"),
            "auto_ppg": auto_ppg,
            "auto_club": auto_row.get("club") if auto_row else None,
            "playoff_ppg": playoff_ppg,
            "playoff_club": playoff_row.get("club") if playoff_row else None,
            "safety_ppg": safety_ppg,
            "safety_club": safety_row.get("club") if safety_row else None,
            "on_track_playoff": on_track_playoff,
            "pts_vs_playoff": pts_gap_playoff,
            "ppg_vs_playoff": (
                round(ppg - playoff_ppg, 2)
                if ppg is not None and playoff_ppg is not None
                else None
            ),
        },
        "phases": phases,
        "game_state": game_state,
        "vs_league": {
            "ppg": {"us": pv.get("ppg") if pv else None, "league": averages.get("ppg")},
            "xg_difference": {
                "us": pv.get("xg_difference") if pv else None,
                "league": averages.get("xg_difference"),
            },
            "goals_for": {
                "us": pv.get("goals_for") if pv else None,
                "league": averages.get("goals_for"),
            },
            "goals_against": {
                "us": pv.get("goals_against") if pv else None,
                "league": averages.get("goals_against"),
            },
            "sot_pct": {
                "us": pv.get("sot_pct") if pv else None,
                "league": averages.get("sot_pct"),
            },
            "xp_vs_actual": {
                "us": pv.get("xp_vs_actual") if pv else None,
                "league": averages.get("xp_vs_actual"),
            },
        },
    }
    _strategy_cache[cache_key] = (now, payload)
    if detail and not payload.get("error") and not (payload.get("phases") or {}).get("deferred"):
        _save_strategy_disk(competition, payload)
    return payload


def _club_is_port_vale(name: Any, fotmob_id: Any = None) -> bool:
    if str(fotmob_id or "").strip() == PORT_VALE_FOTMOB_ID:
        return True
    text = str(name or "").casefold().strip()
    return "port vale" in text or text == "vale"


def _parse_kickoff(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _outcome_for_port_vale(
    *,
    is_home: bool,
    home_score: int | None,
    away_score: int | None,
) -> str | None:
    if home_score is None or away_score is None:
        return None
    pv = home_score if is_home else away_score
    opp = away_score if is_home else home_score
    if pv > opp:
        return "win"
    if pv < opp:
        return "loss"
    return "draw"


def _normalize_pv_fixture(row: dict[str, Any], *, competition: str | None = None) -> dict[str, Any] | None:
    home = row.get("home") or {}
    away = row.get("away") or {}
    home_name = str(home.get("name") or "").strip()
    away_name = str(away.get("name") or "").strip()
    is_home = _club_is_port_vale(home_name, home.get("fotmob_id") or home.get("id"))
    is_away = _club_is_port_vale(away_name, away.get("fotmob_id") or away.get("id"))
    if not is_home and not is_away:
        return None

    kickoff = row.get("kickoff_utc") or row.get("scheduled_date")
    kickoff_dt = _parse_kickoff(kickoff)
    finished = str(row.get("status") or "") == "completed"
    home_score = row.get("home_score")
    away_score = row.get("away_score")
    try:
        home_score_i = int(home_score) if home_score is not None else None
    except (TypeError, ValueError):
        home_score_i = None
    try:
        away_score_i = int(away_score) if away_score is not None else None
    except (TypeError, ValueError):
        away_score_i = None

    opponent = away_name if is_home else home_name
    home_team_id = str(home.get("fotmob_id") or home.get("id") or "").strip() or None
    away_team_id = str(away.get("fotmob_id") or away.get("id") or "").strip() or None
    opponent_id = away_team_id if is_home else home_team_id

    # FotMob often returns 0-0 placeholders on unplayed fixtures — only keep scores when finished.
    score = None
    outcome = None
    if finished:
        score = str(row.get("score") or "").strip() or None
        if score is None and home_score_i is not None and away_score_i is not None:
            score = f"{home_score_i} - {away_score_i}"
        outcome = _outcome_for_port_vale(
            is_home=is_home,
            home_score=home_score_i,
            away_score=away_score_i,
        )
    else:
        home_score_i = None
        away_score_i = None

    fotmob_id = None
    source_ids = row.get("source_ids") or {}
    if isinstance(source_ids, dict):
        fotmob_id = source_ids.get("fotmob")
    page_url = row.get("fotmob_page_url")
    if page_url and not str(page_url).startswith("http"):
        page_url = f"https://www.fotmob.com{page_url}"

    def _badge_url(team_id: str | None, *, is_port_vale: bool) -> str | None:
        if is_port_vale:
            return "/standalone/port-vale-badge.png?v=2"
        if not team_id:
            return None
        return f"https://images.fotmob.com/image_resources/logo/teamlogo/{team_id}.png"

    return {
        "id": fotmob_id or f"{row.get('date')}|{home_name}|{away_name}",
        "date": str(row.get("date") or (str(kickoff or "")[:10])),
        "scheduledDate": kickoff,
        "kickoff_utc": kickoff,
        "competition": competition or str(row.get("league") or row.get("competition") or "").strip(),
        "season": str(row.get("season") or "").strip() or None,
        "isHome": is_home,
        "opponent": {
            "name": opponent or "TBC",
            "fotmob_id": opponent_id,
            "badge": _badge_url(opponent_id, is_port_vale=False),
        },
        "home": home_name,
        "away": away_name,
        "home_fotmob_id": home_team_id,
        "away_fotmob_id": away_team_id,
        "home_badge": _badge_url(home_team_id, is_port_vale=is_home),
        "away_badge": _badge_url(away_team_id, is_port_vale=not is_home),
        "score": score,
        "scoreLabel": score,
        "home_score": home_score_i,
        "away_score": away_score_i,
        "outcome": outcome,
        "status": "completed" if finished else "scheduled",
        "fotmob_id": fotmob_id,
        "fotmob_url": page_url,
        "source": "fotmob",
        "_sort": kickoff_dt.isoformat() if kickoff_dt else str(row.get("date") or ""),
    }


def _fetch_team_fixtures_fotmob(team_id: str = PORT_VALE_FOTMOB_ID) -> list[dict[str, Any]]:
    """Rolling team fixture list from FotMob (includes cups + cross-season window)."""
    from app.fixture_planner import _http

    response = _http.get(
        "https://www.fotmob.com/api/data/teams",
        params={"id": team_id},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    if not response.ok:
        return []
    payload = response.json()
    raw = (
        ((payload.get("fixtures") or {}).get("allFixtures") or {}).get("fixtures")
        or []
    )
    rows: list[dict[str, Any]] = []
    for match in raw:
        if not isinstance(match, dict):
            continue
        home = match.get("home") or {}
        away = match.get("away") or {}
        status = match.get("status") or {}
        tournament = match.get("tournament") or {}
        kickoff = status.get("utcTime")
        page_url = str(match.get("pageUrl") or "").strip() or None
        rows.append(
            {
                "league": str(tournament.get("name") or "").strip() or "Competition",
                "season": None,
                "scheduled_date": kickoff,
                "date": str(kickoff or "")[:10],
                "kickoff_utc": kickoff,
                "home": {
                    "name": str(home.get("name") or "").strip(),
                    "fotmob_id": str(home.get("id") or "").strip() or None,
                    "score": home.get("score"),
                },
                "away": {
                    "name": str(away.get("name") or "").strip(),
                    "fotmob_id": str(away.get("id") or "").strip() or None,
                    "score": away.get("score"),
                },
                "status": "completed" if status.get("finished") else "scheduled",
                "score": str(status.get("scoreStr") or "").strip() or None,
                "home_score": home.get("score"),
                "away_score": away.get("score"),
                "source_ids": {"fotmob": str(match.get("id") or "")},
                "fotmob_page_url": page_url,
            }
        )
    return rows


def build_port_vale_fixtures(*, force_refresh: bool = False) -> dict[str, Any]:
    """Port Vale played + upcoming fixtures from FotMob (league seasons + team cups)."""
    cache_key = "pv-fotmob"
    cached = _fixtures_cache.get(cache_key)
    now = time.time()
    if not force_refresh and cached and now - cached[0] < FIXTURES_CACHE_TTL:
        return cached[1]

    from app.fixture_planner import FIXTURE_LEAGUE_BY_UI, _fetch_fotmob_fixtures

    by_id: dict[str, dict[str, Any]] = {}

    def _load_league(league_ui: str, season: str) -> list[dict[str, Any]]:
        config = FIXTURE_LEAGUE_BY_UI.get(league_ui) or {}
        try:
            return _fetch_fotmob_fixtures(
                int(config["fotmob_id"]),
                league_ui=league_ui,
                season=season,
                calendar_year=bool(config.get("calendar_year")),
            )
        except Exception:  # noqa: BLE001
            return []

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_load_league, league_ui, season): (league_ui, season)
            for league_ui, season, _league_id in PV_FOTMOB_LEAGUE_SEASONS
        }
        futures[pool.submit(_fetch_team_fixtures_fotmob)] = ("__team__", None)
        for future in as_completed(futures):
            kind, season = futures[future]
            try:
                rows = future.result()
            except Exception:  # noqa: BLE001
                continue
            if kind == "__team__":
                for row in rows:
                    normalized = _normalize_pv_fixture(
                        row, competition=str(row.get("league") or "")
                    )
                    if not normalized:
                        continue
                    existing = by_id.get(str(normalized["id"]))
                    if existing is None:
                        by_id[str(normalized["id"])] = normalized
                    else:
                        if not existing.get("competition") and normalized.get("competition"):
                            existing["competition"] = normalized["competition"]
                        if not existing.get("score") and normalized.get("score"):
                            existing["score"] = normalized["score"]
                            existing["scoreLabel"] = normalized["score"]
                            existing["home_score"] = normalized.get("home_score")
                            existing["away_score"] = normalized.get("away_score")
                            existing["outcome"] = normalized.get("outcome")
                continue
            for row in rows:
                normalized = _normalize_pv_fixture(row, competition=kind)
                if not normalized:
                    continue
                if not normalized.get("season"):
                    normalized["season"] = season
                by_id[str(normalized["id"])] = normalized

    all_rows = sorted(by_id.values(), key=lambda row: str(row.get("_sort") or ""))
    now_dt = datetime.now(UTC)
    played: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    for row in all_rows:
        kickoff_dt = _parse_kickoff(row.get("kickoff_utc") or row.get("scheduledDate"))
        finished = row.get("status") == "completed" or (
            kickoff_dt is not None
            and kickoff_dt < now_dt
            and row.get("score")
            and row.get("home_score") is not None
            and row.get("away_score") is not None
        )
        if finished and row.get("status") != "completed":
            row["status"] = "completed"
            if row.get("outcome") is None:
                row["outcome"] = _outcome_for_port_vale(
                    is_home=bool(row.get("isHome")),
                    home_score=row.get("home_score"),
                    away_score=row.get("away_score"),
                )
        elif row.get("status") != "completed":
            # Drop placeholder scores on fixtures that have not finished.
            row["score"] = None
            row["scoreLabel"] = None
            row["home_score"] = None
            row["away_score"] = None
            row["outcome"] = None
        clean = {k: v for k, v in row.items() if not str(k).startswith("_")}
        if row.get("status") == "completed":
            played.append(clean)
        else:
            upcoming.append(clean)

    next_match = upcoming[0] if upcoming else None
    last_match = played[-1] if played else None
    form = played[-6:] if played else []

    # Calendar markers for the home month grid (include badges + H/A + kick-off).
    calendar = [
        {
            "date": row.get("date"),
            "status": row.get("status"),
            "isHome": row.get("isHome"),
            "opponent": (row.get("opponent") or {}).get("name"),
            "opponent_badge": (row.get("opponent") or {}).get("badge"),
            "home": row.get("home"),
            "away": row.get("away"),
            "home_badge": row.get("home_badge"),
            "away_badge": row.get("away_badge"),
            "competition": row.get("competition"),
            "kickoff_utc": row.get("kickoff_utc") or row.get("scheduledDate"),
            "scheduledDate": row.get("scheduledDate") or row.get("kickoff_utc"),
            "score": (row.get("scoreLabel") or row.get("score")) if row.get("status") == "completed" else None,
            "outcome": row.get("outcome"),
        }
        for row in (played + upcoming)
        if row.get("date")
    ]

    # Keep full lists for recent/upcoming widgets, but don't ship every field twice.
    matches = [
        {
            "scheduledDate": row.get("scheduledDate") or row.get("kickoff_utc"),
            "date": row.get("date"),
            "isHome": row.get("isHome"),
            "opponent": row.get("opponent"),
            "outcome": row.get("outcome"),
            "scoreLabel": row.get("scoreLabel") or row.get("score"),
            "competition": row.get("competition"),
            "status": row.get("status"),
        }
        for row in (played[-12:] + upcoming[:16])
    ]

    fixtures = played + upcoming
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "fotmob",
        "club": PORT_VALE_NAME,
        "fotmob_team_id": PORT_VALE_FOTMOB_ID,
        "played_count": len(played),
        "upcoming_count": len(upcoming),
        "played": played[-8:],
        "upcoming": upcoming[:12],
        "fixtures": fixtures,
        "form": form,
        "next": next_match,
        "last": last_match,
        "calendar": calendar,
        "matches": matches,
    }
    _fixtures_cache[cache_key] = (now, payload)
    return payload


def _overall_from_profile_scores(profile_scores: dict[str, Any] | None) -> float | None:
    """Equal-weighted average — same Overall as Player Search / POTM."""
    if not isinstance(profile_scores, dict):
        return None
    values = [float(v) for v in profile_scores.values() if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _standouts_disk_store() -> dict[str, Any]:
    try:
        if not STANDOUTS_DISK_CACHE.exists():
            return {}
        raw = json.loads(STANDOUTS_DISK_CACHE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _load_standouts_disk(cache_key: str) -> tuple[float, dict[str, Any]] | None:
    store = _standouts_disk_store()
    entry = store.get(cache_key)
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    saved_at = float(entry.get("saved_at") or 0)
    if not isinstance(payload, dict) or not payload:
        return None
    return saved_at, payload


def _save_standouts_disk(cache_key: str, payload: dict[str, Any]) -> None:
    try:
        ensure_data_dirs()
        store = _standouts_disk_store()
        store[cache_key] = {"saved_at": time.time(), "payload": payload}
        STANDOUTS_DISK_CACHE.write_text(
            json.dumps(store, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write standouts disk cache")


def _standouts_building_payload(
    *,
    period: str,
    position: str,
    min_score: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "building": True,
        "period": period,
        "position": position or "ALL",
        "min_score": min_score,
        "players": [],
        "player_count": 0,
        "by_league": [],
        "positions": [],
        "leagues": list(STANDOUTS_LEAGUES),
        "scoring": {
            "method": "equal_weighted_profile_average",
            "note": (
                "Overall = equal-weighted average of Impect PV profile scores "
                "(same as Player Search / Player of the Month)."
            ),
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _slim_standout_player(row: dict[str, Any]) -> dict[str, Any]:
    """Drop heavy profile score blobs before sending to the browser."""
    keep = (
        "id",
        "playerId",
        "name",
        "age",
        "club",
        "league",
        "season",
        "minutes",
        "matchCount",
        "position",
        "positionLabel",
        "overall",
        "bestProfile",
        "bestProfileScore",
        "scout",
        "scout_total",
        "above_threshold",
    )
    return {key: row[key] for key in keep if key in row}


def _standouts_view_cache_key(
    *,
    period: str,
    position: str,
    threshold: float,
    year: int | None = None,
    month: int | None = None,
    profile: str | None = None,
    max_age: float | None = None,
) -> str:
    prof = f":{profile}" if profile else ""
    age = f":u{int(max_age)}" if max_age is not None else ""
    if period == "month" and year is not None and month is not None:
        return f"month:{year}:{month}:{position}:{threshold:.1f}{prof}{age}"
    return f"{period}:{position}:{threshold:.1f}{prof}{age}"


def _standouts_raw_cache_key(
    period: str,
    *,
    year: int | None = None,
    month: int | None = None,
) -> str:
    if period == "month":
        y, m, _ = _normalize_standouts_month(year, month)
        return f"standouts:month:{y}:{m}"
    return f"standouts:{period}"


def _normalize_standouts_month(
    year: int | None,
    month: int | None,
) -> tuple[int, int, str]:
    """Resolve calendar month for monthly stand-outs (defaults to latest with matches)."""
    import calendar

    if year is not None and month is not None:
        try:
            y = int(year)
            m = int(month)
        except (TypeError, ValueError):
            pass
        else:
            if 1 <= m <= 12:
                return y, m, f"{calendar.month_name[m]} {y}"

    default_y, default_m, default_label = _resolve_standouts_month()
    try:
        y = int(year) if year is not None else default_y
        m = int(month) if month is not None else default_m
    except (TypeError, ValueError):
        return default_y, default_m, default_label
    if m < 1 or m > 12:
        return default_y, default_m, default_label
    label = f"{calendar.month_name[m]} {y}"
    return y, m, label


def _standouts_month_options(*, count: int = 12) -> list[dict[str, Any]]:
    """Recent calendar months for the monthly stand-outs picker."""
    import calendar

    from app.scouting_monthly import monthly_meta_defaults

    global _standouts_month_options_cache
    now = time.time()
    if _standouts_month_options_cache and now - _standouts_month_options_cache[0] < 3600:
        return _standouts_month_options_cache[1]

    defaults = monthly_meta_defaults()
    end_year = int(defaults.get("default_year") or datetime.now(UTC).year)
    end_month = int(defaults.get("default_month") or datetime.now(UTC).month)
    options: list[dict[str, Any]] = []
    year, month = end_year, end_month
    for _ in range(max(1, count)):
        options.append(
            {
                "year": year,
                "month": month,
                "label": f"{calendar.month_abbr[month]} {year}",
                "value": f"{year}-{month:02d}",
            }
        )
        if month == 1:
            year -= 1
            month = 12
        else:
            month -= 1
    _standouts_month_options_cache = (now, options)
    return options


def _standouts_leagues_present(payload: dict[str, Any]) -> set[str]:
    return {
        str(row.get("league") or "").strip()
        for row in payload.get("players") or []
        if isinstance(row, dict) and str(row.get("league") or "").strip()
    }


def _standouts_missing_leagues(payload: dict[str, Any]) -> list[str]:
    present = _standouts_leagues_present(payload)
    return [league for league in STANDOUTS_LEAGUES if league not in present]


def _standouts_gk_incomplete(payload: dict[str, Any]) -> bool:
    """True when a league has outfield players but no keepers (partial cache build)."""
    gk_leagues: set[str] = set()
    active_leagues: set[str] = set()
    for row in payload.get("players") or []:
        if not isinstance(row, dict):
            continue
        league = str(row.get("league") or "").strip()
        if league not in STANDOUTS_LEAGUES:
            continue
        active_leagues.add(league)
        if str(row.get("position") or "") == "GOALKEEPER":
            gk_leagues.add(league)
    return any(league not in gk_leagues for league in active_leagues)


def _standouts_cache_is_stale(payload: dict[str, Any]) -> bool:
    try:
        version = int(payload.get("cache_version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version < STANDOUTS_CACHE_VERSION:
        return True
    if str(payload.get("period") or "season") != "month":
        from app.scouting import _scouting_season_titles

        current, _previous = _scouting_season_titles()
        label = str(payload.get("season_label") or "")
        mode = str(payload.get("season_mode") or "")
        if mode == "previous" or (current and current not in label):
            return True
    if _standouts_gk_incomplete(payload):
        return True
    return bool(_standouts_missing_leagues(payload))


def _standouts_positions() -> list[dict[str, str]]:
    from app.scouting import _scouting_position_label
    from app import main as impect

    return [
        {"value": position, "label": _scouting_position_label(position)}
        for position in impect.ALLOWED_POSITIONS
    ]


def _normalize_standouts_position(position: str | None) -> str:
    from app import main as impect

    key = str(position or "ALL").strip().upper()
    if not key or key in {"ALL", "*", "ANY"}:
        return "ALL"
    if key not in impect.ALLOWED_POSITIONS:
        return "ALL"
    return key


def _resolve_standouts_season_mode() -> tuple[str, str]:
    """Prefer current season label for standouts.

    If the current shell is empty (mid-shell shells), the season builder
    falls back to `previous` once.
    """
    from app.scouting import _scouting_season_mode_options

    options = _scouting_season_mode_options()
    label_by_mode = {
        str(row.get("value")): str(row.get("label") or row.get("value")) for row in options
    }
    return "current", label_by_mode.get("current", "current")


def _resolve_standouts_month() -> tuple[int, int, str]:
    """Latest calendar month with matches in the standouts league pool."""
    import calendar

    global _resolve_standouts_month_cache
    now = time.time()
    if _resolve_standouts_month_cache and now - _resolve_standouts_month_cache[0] < 3600:
        return _resolve_standouts_month_cache[1]

    from app.scouting import SCOUTING_LEAGUE_TO_COMPETITION, _scouting_iteration_rows
    from app.scouting_monthly import (
        _fetch_iteration_matches,
        _matches_in_calendar_month,
        monthly_meta_defaults,
    )

    defaults = monthly_meta_defaults()
    year = int(defaults["default_year"])
    month = int(defaults["default_month"])
    competitions = [
        SCOUTING_LEAGUE_TO_COMPETITION[league]
        for league in STANDOUTS_LEAGUES
        if league in SCOUTING_LEAGUE_TO_COMPETITION
    ]
    # Check current + previous season shells — spring months often sit on the
    # previous competition season while meta defaults point at midsummer.
    iteration_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for season_offset in (0, 1):
        for row in _scouting_iteration_rows(
            competitions, season_offset=season_offset, combine_seasons=False
        ):
            iteration_id = int(row["id"])
            if iteration_id in seen_ids:
                continue
            seen_ids.add(iteration_id)
            iteration_rows.append(row)

    for _ in range(18):
        for iteration in iteration_rows:
            try:
                matches = _fetch_iteration_matches(int(iteration["id"]))
                month_matches = _matches_in_calendar_month(matches, year=year, month=month)
            except Exception:  # noqa: BLE001
                continue
            if month_matches:
                label = f"{calendar.month_name[month]} {year}"
                resolved = (year, month, label)
                _resolve_standouts_month_cache = (now, resolved)
                return resolved
        if month == 1:
            year -= 1
            month = 12
        else:
            month -= 1

    label = f"{calendar.month_name[int(defaults['default_month'])]} {int(defaults['default_year'])}"
    resolved = (int(defaults["default_year"]), int(defaults["default_month"]), label)
    _resolve_standouts_month_cache = (now, resolved)
    return resolved


def _player_rows_from_scouting_list(
    data: dict[str, Any],
    *,
    position: str,
    position_label: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in data.get("players") or []:
        if not isinstance(player, dict):
            continue
        overall = _overall_from_profile_scores(player.get("profileScores"))
        if overall is None:
            continue
        scores = player.get("profileScores") or {}
        best_name = None
        best_value = None
        for name, value in scores.items():
            if value is None:
                continue
            numeric = float(value)
            if best_value is None or numeric > best_value:
                best_value = numeric
                best_name = name
        rows.append(
            {
                "id": player.get("id"),
                "playerId": player.get("playerId"),
                "name": player.get("name"),
                "age": player.get("age"),
                "height": player.get("height"),
                "foot": player.get("foot"),
                "club": player.get("club"),
                "league": player.get("league"),
                "season": player.get("season"),
                "minutes": player.get("minutes"),
                "matchCount": player.get("matchCount"),
                "position": position,
                "positionLabel": position_label,
                "overall": overall,
                "bestProfile": best_name,
                "bestProfileScore": best_value,
                "profileScores": scores,
            }
        )
    return rows


def _load_season_position_players(
    position: str,
    *,
    season_mode: str,
) -> tuple[list[dict[str, Any]], str | None]:
    from app.scouting import (
        ScoutingLongListRequest,
        _scouting_position_label,
        build_scouting_long_list,
    )
    from fastapi import HTTPException

    request = ScoutingLongListRequest(
        position=position,
        leagues=list(STANDOUTS_LEAGUES),
        min_minutes=STANDOUTS_SEASON_MIN_MINUTES,
        season_mode=season_mode,
    )
    label = _scouting_position_label(position)
    for attempt in range(4):
        try:
            data = build_scouting_long_list(request)
        except HTTPException as exc:
            if exc.status_code == 429 and attempt < 3:
                time.sleep(min(60.0, 5.0 * (2**attempt)))
                continue
            return [], f"{label}: {exc.detail}"
        return (
            _player_rows_from_scouting_list(
                data,
                position=position,
                position_label=label,
            ),
            None,
        )
    return [], f"{label}: Impect API rate limit — retries exhausted."


def _build_standouts_season_payload() -> dict[str, Any]:
    from app import main as impect

    season_mode, season_label = _resolve_standouts_season_mode()
    warnings: list[str] = []
    players: list[dict[str, Any]] = []

    # Load one position at a time — parallel long-list builds hit Impect rate limits
    # and Goalkeeper pools were coming back empty for most leagues.
    for index, position in enumerate(impect.ALLOWED_POSITIONS):
        rows, warning = _load_season_position_players(position, season_mode=season_mode)
        players.extend(rows)
        if warning:
            warnings.append(warning)
        if index + 1 < len(impect.ALLOWED_POSITIONS):
            time.sleep(2.0)

    players.sort(key=lambda row: (-float(row["overall"]), str(row.get("name") or "")))
    highest = players[0]["overall"] if players else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "building": False,
        "cache_version": STANDOUTS_CACHE_VERSION,
        "period": "season",
        "period_label": f"Full season · {season_label}",
        "season_mode": season_mode,
        "season_label": season_label,
        "min_minutes": STANDOUTS_SEASON_MIN_MINUTES,
        "leagues": list(STANDOUTS_LEAGUES),
        "positions": _standouts_positions(),
        "players": players,
        "player_count": len(players),
        "highest_overall": highest,
        "warnings": warnings,
        "scoring": {
            "method": "impect_profile_score_average",
            "note": (
                "Overall = equal-weighted average of Impect exact PV profile ratings (0–100), "
                "same as Player Search season long lists."
            ),
        },
    }


def _build_standouts_month_payload(
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    from app.scouting import _scouting_position_label
    from app.scouting_monthly import ScoutingMonthlyListRequest, build_scouting_monthly_list
    from app import main as impect
    from fastapi import HTTPException

    year, month, month_label = _normalize_standouts_month(year, month)
    warnings: list[str] = []
    players: list[dict[str, Any]] = []

    def load_position(position: str) -> list[dict[str, Any]]:
        try:
            data = build_scouting_monthly_list(
                ScoutingMonthlyListRequest(
                    position=position,
                    leagues=list(STANDOUTS_LEAGUES),
                    year=year,
                    month=month,
                    min_minutes=STANDOUTS_MONTH_MIN_MINUTES,
                )
            )
        except HTTPException as exc:
            warnings.append(f"{_scouting_position_label(position)}: {exc.detail}")
            return []
        return _player_rows_from_scouting_list(
            data,
            position=position,
            position_label=_scouting_position_label(position),
        )

    with ThreadPoolExecutor(max_workers=min(3, len(impect.ALLOWED_POSITIONS))) as pool:
        futures = [pool.submit(load_position, position) for position in impect.ALLOWED_POSITIONS]
        for future in as_completed(futures):
            players.extend(future.result())

    players.sort(key=lambda row: (-float(row["overall"]), str(row.get("name") or "")))
    highest = players[0]["overall"] if players else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "building": False,
        "cache_version": STANDOUTS_CACHE_VERSION,
        "period": "month",
        "period_label": f"Monthly · {month_label}",
        "year": year,
        "month": month,
        "month_label": month_label,
        "min_minutes": STANDOUTS_MONTH_MIN_MINUTES,
        "leagues": list(STANDOUTS_LEAGUES),
        "positions": _standouts_positions(),
        "players": players,
        "player_count": len(players),
        "highest_overall": highest,
        "warnings": warnings,
        "scoring": {
            "method": "monthly_league_relative_percentile_average",
            "note": (
                "Overall = equal-weighted average of league-relative monthly profile percentiles "
                "(same as Player Search monthly / Player of the Month)."
            ),
        },
    }


def _schedule_standouts_refresh(
    period: str,
    *,
    year: int | None = None,
    month: int | None = None,
) -> None:
    cache_key = _standouts_raw_cache_key(period, year=year, month=month)
    with _standouts_refresh_lock:
        if cache_key in _standouts_refreshing:
            return
        _standouts_refreshing.add(cache_key)

    def _run() -> None:
        try:
            build_recruitment_standouts(
                period=period,
                year=year,
                month=month,
                force_refresh=True,
                _from_background=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Background standouts refresh failed (%s)", cache_key)
        finally:
            with _standouts_refresh_lock:
                _standouts_refreshing.discard(cache_key)

    thread_name = cache_key.replace(":", "-")
    threading.Thread(target=_run, name=thread_name, daemon=True).start()


def _filter_standouts_by_threshold(
    players: list[dict[str, Any]],
    *,
    threshold: float,
) -> tuple[list[dict[str, Any]], float, str, float | None]:
    """Filter + sort stand-outs; apply percent-of-pool fallback within this pool."""
    pool_highest: float | None = None
    if players:
        pool_highest = max(
            float(row["overall"])
            for row in players
            if row.get("overall") is not None
        )

    requested_threshold = threshold
    effective_threshold = threshold
    min_score_mode = "absolute"

    filtered = [
        row
        for row in players
        if row.get("overall") is not None
        and float(row["overall"]) + 1e-9 >= effective_threshold
    ]

    if (
        not filtered
        and pool_highest is not None
        and requested_threshold > pool_highest
        and requested_threshold >= 10
    ):
        effective_threshold = pool_highest * (requested_threshold / 100.0)
        min_score_mode = "percent_of_pool"
        filtered = [
            row
            for row in players
            if row.get("overall") is not None
            and float(row["overall"]) + 1e-9 >= effective_threshold
        ]

    filtered.sort(key=lambda row: (-float(row["overall"]), str(row.get("name") or "")))
    return filtered, round(float(effective_threshold), 1), min_score_mode, pool_highest


def _build_standouts_by_league(
    players: list[dict[str, Any]],
    *,
    threshold: float,
    limit: int = STANDOUTS_PER_LEAGUE_LIMIT,
    loading_leagues: set[str] | None = None,
    always_top_n: bool = True,
    rank_profile: str | None = None,
) -> list[dict[str, Any]]:
    """One stand-outs block per league — threshold is relative to that league's pool.

    When always_top_n is True (default), each box always shows the top `limit`
    players by overall — even if some sit below the 85%-of-pool cut-off —
    so position filters never return empty boxes.
    """
    blocks: list[dict[str, Any]] = []
    loading = loading_leagues or set()
    players_by_league: dict[str, list[dict[str, Any]]] = {name: [] for name in STANDOUTS_LEAGUES}
    for row in players:
        league = str(row.get("league") or "").strip()
        if league in players_by_league:
            players_by_league[league].append(row)

    def _sort_key(row: dict[str, Any]) -> tuple[float, str]:
        if rank_profile:
            scores = row.get("profileScores") or {}
            val = scores.get(rank_profile)
            score = float(val) if val is not None else 0.0
        else:
            score = float(row.get("overall") or 0)
        return (-score, str(row.get("name") or ""))

    for league_name in STANDOUTS_LEAGUES:
        league_players = players_by_league.get(league_name) or []
        if rank_profile:
            league_players = sorted(league_players, key=_sort_key)
        filtered, effective, mode, highest = _filter_standouts_by_threshold(
            league_players,
            threshold=threshold,
        )
        if rank_profile:
            filtered = sorted(league_players, key=_sort_key)[:limit]
            mode = "profile_rank"
            effective = 0.0
        shown = list(filtered[:limit])
        if not rank_profile and always_top_n and len(shown) < limit and league_players:
            ranked = sorted(
                league_players,
                key=lambda row: (-float(row.get("overall") or 0), str(row.get("name") or "")),
            )
            seen = {
                str(row.get("id") or row.get("playerId") or row.get("name") or "")
                for row in shown
            }
            for row in ranked:
                if len(shown) >= limit:
                    break
                key = str(row.get("id") or row.get("playerId") or row.get("name") or "")
                if key in seen:
                    continue
                seen.add(key)
                shown.append(row)
            if not filtered and shown:
                mode = "top_n_fill"
        _attach_scout_coverage(shown)
        slim_shown = []
        for row in shown:
            slim = _slim_standout_player(row)
            if "scout" in row:
                slim["scout"] = row["scout"]
            if "scout_total" in row:
                slim["scout_total"] = row["scout_total"]
            try:
                ovr = float(row.get("overall") or 0)
            except (TypeError, ValueError):
                ovr = 0.0
            slim["above_threshold"] = ovr + 1e-9 >= float(effective) if not rank_profile else True
            if rank_profile:
                scores = row.get("profileScores") or {}
                val = scores.get(rank_profile)
                slim["profile_score"] = round(float(val), 1) if val is not None else None
            slim_shown.append(slim)
        blocks.append(
            {
                "league": league_name,
                "players": slim_shown,
                "player_count": len(filtered),
                "pool_count": len(league_players),
                "highest_overall": highest,
                "min_score": threshold,
                "min_score_effective": effective,
                "min_score_mode": mode,
                "loading": league_name in loading and not league_players,
            }
        )

    return blocks


def build_recruitment_standouts(
    *,
    period: str = "season",
    position: str = "ALL",
    min_score: float = STANDOUTS_DEFAULT_MIN_SCORE,
    year: int | None = None,
    month: int | None = None,
    profile: str | None = None,
    max_age: float | None = None,
    force_refresh: bool = False,
    _from_background: bool = False,
) -> dict[str, Any]:
    """Players with Overall ≥ min_score for Recruitment → Stand outs."""
    period_key = str(period or "season").strip().casefold()
    if period_key in {"monthly", "month", "m"}:
        period_key = "month"
    else:
        period_key = "season"

    month_year: int | None = None
    month_num: int | None = None
    month_label: str | None = None
    if period_key == "month":
        month_year, month_num, month_label = _normalize_standouts_month(year, month)

    position_key = _normalize_standouts_position(position)
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        threshold = STANDOUTS_DEFAULT_MIN_SCORE

    now = time.time()
    rank_profile = profile.strip() if profile else None
    view_key = _standouts_view_cache_key(
        period=period_key,
        position=position_key,
        threshold=threshold,
        year=month_year,
        month=month_num,
        profile=rank_profile,
        max_age=max_age,
    )
    view_cached = _standouts_view_cache.get(view_key)
    if not force_refresh and view_cached and now - view_cached[0] < STANDOUTS_VIEW_CACHE_TTL:
        return view_cached[1]

    cache_key = _standouts_raw_cache_key(period_key, year=month_year, month=month_num)
    cached = _standouts_cache.get(cache_key)

    raw_payload: dict[str, Any] | None = None
    if not force_refresh and cached and now - cached[0] < STANDOUTS_CACHE_TTL:
        raw_payload = cached[1]
    elif not force_refresh:
        disk = _load_standouts_disk(cache_key)
        if disk is not None:
            saved_at, payload = disk
            _standouts_cache[cache_key] = (saved_at, payload)
            raw_payload = payload
            if now - saved_at >= HOME_TAB_CACHE_TTL and not _from_background:
                _schedule_standouts_refresh(period_key, year=month_year, month=month_num)

    if raw_payload is None:
        month_extra: dict[str, Any] = {}
        if period_key == "month":
            month_extra = {
                "year": month_year,
                "month": month_num,
                "month_label": month_label,
                "month_options": _standouts_month_options(),
            }
        if not _from_background and not force_refresh:
            _schedule_standouts_refresh(period_key, year=month_year, month=month_num)
            return _standouts_building_payload(
                period=period_key,
                position=position_key,
                min_score=threshold,
                extra={"positions": _standouts_positions(), **month_extra},
            )
        raw_payload = (
            _build_standouts_month_payload(year=month_year, month=month_num)
            if period_key == "month"
            else _build_standouts_season_payload()
        )
        _standouts_cache[cache_key] = (time.time(), raw_payload)
        _save_standouts_disk(cache_key, raw_payload)

    players = list(raw_payload.get("players") or [])
    if position_key != "ALL":
        players = [row for row in players if row.get("position") == position_key]
    if max_age is not None:
        players = [
            row for row in players
            if row.get("age") is not None and float(row["age"]) < max_age
        ]

    missing_leagues = _standouts_missing_leagues(raw_payload)
    cache_stale = _standouts_cache_is_stale(raw_payload)
    if cache_stale and not _from_background and not force_refresh:
        _schedule_standouts_refresh(period_key, year=month_year, month=month_num)

    by_league = _build_standouts_by_league(
        players,
        threshold=threshold,
        loading_leagues=set(missing_leagues),
        rank_profile=rank_profile,
    )
    all_filtered = [row for block in by_league for row in block.get("players") or []]
    pool_highest = None
    if players:
        pool_highest = max(
            float(row["overall"])
            for row in players
            if row.get("overall") is not None
        )

    # Include available profiles for the selected position
    profiles_for_pos: list[dict[str, str]] = []
    if position_key != "ALL":
        from app.who_to_scout import _profiles_meta_for_position
        profiles_for_pos = _profiles_meta_for_position(position_key)

    rank_label = None
    if rank_profile:
        from app.label_utils import humanize_profile_name
        rank_label = humanize_profile_name(rank_profile)

    scoring_note = (
        f"Ranked by {rank_label}. "
        f"Top {STANDOUTS_PER_LEAGUE_LIMIT} per league."
    ) if rank_profile else (
        "Overall = equal-weighted Impect PV profile average (same as Player Search). "
        f"Top {STANDOUTS_PER_LEAGUE_LIMIT} per league by overall "
        f"(fills below ≥{int(threshold)}% of that league's pool when needed)."
    )

    result = {
        **{k: v for k, v in raw_payload.items() if k not in {"players", "player_count", "highest_overall"}},
        "building": False,
        "period": period_key,
        "position": position_key,
        "min_score": threshold,
        "min_score_effective": threshold,
        "min_score_mode": "per_league_percent",
        "view": "by_league",
        "by_league": by_league,
        "cache_stale": cache_stale,
        "missing_leagues": missing_leagues,
        "player_count": len(all_filtered),
        "pool_count": len(players),
        "highest_overall": pool_highest,
        "positions": raw_payload.get("positions") or _standouts_positions(),
        "profiles": profiles_for_pos,
        "profile": rank_profile,
        "per_league_limit": STANDOUTS_PER_LEAGUE_LIMIT,
        "scoring": {
            **(raw_payload.get("scoring") or {}),
            "note": scoring_note,
        },
    }
    if period_key == "month":
        result["year"] = raw_payload.get("year") or month_year
        result["month"] = raw_payload.get("month") or month_num
        result["month_label"] = raw_payload.get("month_label") or month_label
        result["month_options"] = _standouts_month_options()
    _standouts_view_cache[view_key] = (time.time(), result)
    return result


def register_home_dashboard_routes(app: FastAPI) -> None:
    @app.get("/api/home/activity")
    def home_activity_route(limit: int = Query(40, ge=1, le=100)) -> dict[str, Any]:
        return build_activity_feed(limit=limit)

    @app.get("/api/home/changelog")
    def home_changelog_route(limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
        return load_changelog(limit=limit)

    @app.get("/api/home/days-since-broke")
    def home_days_since_broke_route() -> dict[str, Any]:
        return load_days_since_broke()

    @app.get("/api/home/recruitment")
    def home_recruitment_route(refresh: bool = Query(False)) -> dict[str, Any]:
        try:
            if refresh:
                # Refresh in background; serve cache (or building stub) so the tab never 502s.
                _schedule_recruitment_refresh()
                disk = _load_recruitment_disk()
                if disk is not None:
                    return disk[1]
                cached = _recruitment_cache.get("recruitment")
                if cached:
                    return cached[1]
                return _recruitment_building_payload()
            return build_recruitment_snapshot(force_refresh=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Recruitment snapshot failed")
            disk = _load_recruitment_disk()
            if disk is not None:
                return disk[1]
            return {
                "generated_at": datetime.now(UTC).isoformat(),
                "error": f"Could not build recruitment league comparison: {exc}",
            }

    @app.get("/api/home/recruitment/standouts")
    def home_recruitment_standouts_route(
        period: str = Query("season"),
        position: str = Query("ALL"),
        min_score: float = Query(STANDOUTS_DEFAULT_MIN_SCORE),
        year: int | None = Query(None),
        month: int | None = Query(None, ge=1, le=12),
        profile: str | None = Query(None),
        max_age: float | None = Query(None),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        try:
            period_key = "month" if str(period).strip().casefold() in {"month", "monthly", "m"} else "season"
            cache_key = _standouts_raw_cache_key(period_key, year=year, month=month)
            if refresh:
                _schedule_standouts_refresh(period_key, year=year, month=month)
                cached = _standouts_cache.get(cache_key)
                if cached:
                    return build_recruitment_standouts(
                        period=period_key,
                        position=position,
                        min_score=min_score,
                        year=year,
                        month=month,
                        profile=profile,
                        max_age=max_age,
                        force_refresh=False,
                    )
                disk = _load_standouts_disk(cache_key)
                if disk is not None:
                    _standouts_cache[cache_key] = disk
                    return build_recruitment_standouts(
                        period=period_key,
                        position=position,
                        min_score=min_score,
                        year=year,
                        month=month,
                        profile=profile,
                        max_age=max_age,
                        force_refresh=False,
                    )
                month_extra: dict[str, Any] = {}
                if period_key == "month":
                    y, m, label = _normalize_standouts_month(year, month)
                    month_extra = {
                        "year": y,
                        "month": m,
                        "month_label": label,
                        "month_options": _standouts_month_options(),
                    }
                return _standouts_building_payload(
                    period=period_key,
                    position=_normalize_standouts_position(position),
                    min_score=float(min_score),
                    extra={"positions": _standouts_positions(), **month_extra},
                )
            return build_recruitment_standouts(
                period=period_key,
                position=position,
                min_score=min_score,
                year=year,
                month=month,
                profile=profile,
                max_age=max_age,
                force_refresh=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Recruitment standouts failed")
            return {
                "generated_at": datetime.now(UTC).isoformat(),
                "error": f"Could not build stand outs: {exc}",
                "players": [],
                "player_count": 0,
                "period": period,
                "position": position,
                "min_score": min_score,
            }

    @app.get("/api/home/strategy")
    def home_strategy_route(
        competition: str = Query("League Two"),
        refresh: bool = Query(False),
        detail: bool = Query(True),
    ) -> dict[str, Any]:
        return build_strategy_snapshot(
            competition=competition,
            force_refresh=refresh,
            detail=detail,
        )

    @app.get("/api/home/fixtures")
    def home_fixtures_route(refresh: bool = Query(False)) -> dict[str, Any]:
        return build_port_vale_fixtures(force_refresh=refresh)

    # Warm league recruitment + strategy detail caches in the background.
    # Stand outs warm on first tab open (heavy Impect traffic — avoid 429s at boot).
    _schedule_recruitment_refresh()
    _schedule_strategy_refresh("League Two")
