"""Loans Watch — every club's current loanees, with playing time and Impect score."""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.efl_transfer_report import badge_url, load_report
from app.paths import STANDALONE_DIR
from app import transfer_status

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 5 * 60

LEAGUE_ORDER: tuple[str, ...] = (
    "league-two",
    "league-one",
    "national-league",
    "scottish-prem",
    "irish-prem",
    "pl2",
    "other",
)
LEAGUE_COLORS: dict[str, str] = {
    "league-two": "#22c55e",
    "league-one": "#3d8bfd",
    "national-league": "#a78bfa",
    "scottish-prem": "#f59e0b",
    "irish-prem": "#f472b6",
    "pl2": "#06b6d4",
    "other": "#9ca3af",
}
LEAGUE_LABELS: dict[str, str] = {
    "league-two": "League Two",
    "league-one": "League One",
    "national-league": "National League",
    "scottish-prem": "Scottish Prem",
    "irish-prem": "Irish Prem",
    "pl2": "PL2",
    "other": "Other",
}
LEAGUE_NAME_TO_ID: dict[str, str] = {
    "League Two": "league-two",
    "League One": "league-one",
    "National League": "national-league",
    "Scottish Prem": "scottish-prem",
    "Irish Prem": "irish-prem",
    "PL2": "pl2",
}

REPORT_LEAGUE_IDS = frozenset(
    {"league-one", "league-two", "national-league", "scottish-prem"}
)

POSITION_GROUPS: tuple[tuple[str, str], ...] = (
    ("gk", "GK"),
    ("cb", "CB"),
    ("fb", "FB"),
    ("dm", "DM"),
    ("cm", "CM"),
    ("am", "AM"),
    ("w", "W"),
    ("st", "ST"),
)
_POSITION_CODE_TO_GROUP: dict[str, str] = {
    "GOALKEEPER": "gk",
    "GK": "gk",
    "RIGHT_WINGBACK_DEFENDER": "fb",
    "LEFT_WINGBACK_DEFENDER": "fb",
    "RB": "fb",
    "LB": "fb",
    "RWB": "fb",
    "LWB": "fb",
    "FB": "fb",
    "WB": "fb",
    "CENTRAL_DEFENDER": "cb",
    "CB": "cb",
    "CH": "cb",
    "CD": "cb",
    "DEFENSE_MIDFIELD": "dm",
    "DEFENSIVE_MIDFIELD": "dm",
    "DM": "dm",
    "CDM": "dm",
    "CENTRAL_MIDFIELD": "cm",
    "CM": "cm",
    "ATTACKING_MIDFIELD": "am",
    "AM": "am",
    "CAM": "am",
    "LEFT_WINGER": "w",
    "RIGHT_WINGER": "w",
    "LW": "w",
    "RW": "w",
    "LM": "w",
    "RM": "w",
    "W": "w",
    "WI": "w",
    "CENTER_FORWARD": "st",
    "CENTRE_FORWARD": "st",
    "CENTRAL_FORWARD": "st",
    "SECOND_STRIKER": "st",
    "ST": "st",
    "CF": "st",
    "FW": "st",
    "SS": "st",
}
_POSITION_LABEL_HINTS: tuple[tuple[str, str], ...] = (
    ("goalkeeper", "gk"),
    ("keeper", "gk"),
    ("centre-back", "cb"),
    ("center-back", "cb"),
    ("centre back", "cb"),
    ("center back", "cb"),
    ("central defender", "cb"),
    ("right-back", "fb"),
    ("left-back", "fb"),
    ("right back", "fb"),
    ("left back", "fb"),
    ("wing-back", "fb"),
    ("wingback", "fb"),
    ("full-back", "fb"),
    ("fullback", "fb"),
    ("full back", "fb"),
    ("defensive mid", "dm"),
    ("holding mid", "dm"),
    ("central mid", "cm"),
    ("centre mid", "cm"),
    ("center mid", "cm"),
    ("attacking mid", "am"),
    ("left winger", "w"),
    ("right winger", "w"),
    ("winger", "w"),
    ("centre-forward", "st"),
    ("center-forward", "st"),
    ("centre forward", "st"),
    ("center forward", "st"),
    ("second striker", "st"),
    ("striker", "st"),
    ("forward", "st"),
)

SCORING_NOTE = (
    "Current squad loans from Transfermarkt. Minutes are total played. "
    "Score is the Impect profile (same overall as Who To Scout), with that "
    "profile's minutes in brackets. Starts and matches come from Impect when "
    "the feed has them; otherwise they are estimated from total minutes."
)

_payload_mem: tuple[float, dict[str, Any]] | None = None
_payload_lock = threading.Lock()

MATCH_KEYS = (
    "matchCount",
    "matches",
    "numberOfMatches",
    "games",
    "appearances",
    "matchAppearances",
)
START_KEYS = (
    "starts",
    "gamesStarted",
    "numberOfStarts",
    "startingAppearances",
    "matchesStarted",
)


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return " ".join(html.unescape(str(value or "")).split())


def _team_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-") or "club"


def _row_count(row: dict[str, Any] | None, keys: tuple[str, ...]) -> int | None:
    if not isinstance(row, dict):
        return None
    for key in keys:
        number = _as_int(row.get(key))
        if number is not None and number >= 0:
            return number
    return None


def infer_matches(minutes: int | None, match_count: int | None) -> tuple[int | None, bool]:
    """Appearances this season. Prefer the Impect count; else 90-minute games."""
    if match_count is not None:
        return max(0, match_count), False
    if minutes is None or minutes <= 0:
        return None, False
    return max(1, int(round(minutes / 90.0))), True


def infer_starts(
    minutes: int | None,
    matches: int | None,
    starts: int | None = None,
) -> tuple[int | None, bool]:
    """Starts this season. Prefer an Impect count; else mix of XI vs sub minutes."""
    if starts is not None:
        if matches is not None:
            return max(0, min(matches, starts)), False
        return max(0, starts), False
    if minutes is None or minutes <= 0:
        if matches == 0:
            return 0, False
        return None, False
    if not matches:
        if minutes < 45:
            return 0, True
        return max(1, int(round(minutes / 85.0))), True
    average = minutes / matches
    if average >= 70:
        return matches, True
    if average <= 20:
        return 0, True
    # A start is ~85', a sub ~20': minutes = 20M + 65S.
    estimated = int(round((minutes - 20.0 * matches) / 65.0))
    return max(0, min(matches, estimated)), True


def playing_time(
    *,
    minutes: float | None,
    match_count: int | None = None,
    starts: int | None = None,
) -> dict[str, Any]:
    mins = _as_int(minutes)
    if mins is not None and mins < 0:
        mins = 0
    matches, matches_estimated = infer_matches(mins, match_count)
    start_n, starts_estimated = infer_starts(mins, matches, starts)
    return {
        "minutes": mins,
        "matches": matches,
        "starts": start_n,
        "matches_estimated": bool(matches_estimated),
        "starts_estimated": bool(starts_estimated),
    }


def loan_watch_score(
    *,
    overall: float | None,
    minutes: int | None,
    starts: int | None,
    matches: int | None,
    age: int | None,
) -> float | None:
    """Rank loans we should actually watch — playing time first, then quality."""
    if overall is None:
        return None
    minutes_w = min(1.0, max(0.0, float(minutes or 0) / 450.0))
    start_w = 1.0
    if matches:
        start_w = 0.45 + 0.55 * (float(starts or 0) / float(matches))
    if age is None:
        age_w = 0.9
    elif age <= 21:
        age_w = 1.0
    elif age <= 23:
        age_w = 0.96
    elif age <= 26:
        age_w = 0.86
    else:
        age_w = 0.55
    return round(float(overall) * (0.4 + 0.6 * minutes_w) * start_w * age_w, 1)


def _snapshot_updated() -> str:
    path = next(
        (candidate for candidate in transfer_status.LOAN_SNAPSHOT_CANDIDATES if candidate.is_file()),
        None,
    )
    if path is None:
        return ""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(body.get("updated") or "") if isinstance(body, dict) else ""


def _impect_players() -> list[dict[str, Any]]:
    try:
        from app.who_to_scout import _load_standouts_raw_payload
    except Exception:  # noqa: BLE001
        logger.exception("Could not import standouts loader")
        return []
    try:
        payload = _load_standouts_raw_payload(period="season")
    except Exception:  # noqa: BLE001
        logger.exception("Could not load Who To Scout season scores")
        return []
    rows = payload.get("players") if isinstance(payload, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


def _player_index(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for row in players:
        name = _clean_text(row.get("name"))
        club = _clean_text(row.get("club"))
        if not name:
            continue
        indexed.append(row)
        row.setdefault("_name_keys", set(transfer_status.name_keys(name)))
        row.setdefault("_club_key", transfer_status.club_key(club))
    return indexed


def _match_impect_player(
    name: str,
    club: str,
    players: list[dict[str, Any]],
) -> dict[str, Any] | None:
    keys = set(transfer_status.name_keys(name))
    if not keys:
        return None
    last = transfer_status.name_key(name).split()[-1] if transfer_status.name_key(name) else ""
    club_hits: list[dict[str, Any]] = []
    last_hits: list[dict[str, Any]] = []
    for row in players:
        row_keys = row.get("_name_keys") or set(transfer_status.name_keys(row.get("name")))
        same_club = transfer_status._clubs_match(club, row.get("club"))
        if not (row_keys & keys):
            if same_club and last:
                entry_last = (
                    transfer_status.name_key(row.get("name")).split()[-1]
                    if transfer_status.name_key(row.get("name"))
                    else ""
                )
                if entry_last == last:
                    last_hits.append(row)
            continue
        if same_club:
            return row
        club_hits.append(row)
    unique_last: list[dict[str, Any]] = []
    seen: set[int] = set()
    for hit in last_hits:
        stamp = id(hit)
        if stamp in seen:
            continue
        seen.add(stamp)
        unique_last.append(hit)
    if len(unique_last) == 1:
        return unique_last[0]
    if len(club_hits) == 1:
        return club_hits[0]
    return None


def _player_id(row: dict[str, Any] | None) -> int | None:
    if not isinstance(row, dict):
        return None
    return _as_int(row.get("playerId") or row.get("player_id") or row.get("id"))


def _related_impect_rows(
    primary: dict[str, Any] | None,
    players: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(primary, dict):
        return []
    player_id = _player_id(primary)
    if player_id is not None:
        hits = [row for row in players if _player_id(row) == player_id]
        if hits:
            return hits
    keys = primary.get("_name_keys") or set(transfer_status.name_keys(primary.get("name")))
    if not keys:
        return [primary]
    hits = [
        row
        for row in players
        if (row.get("_name_keys") or set(transfer_status.name_keys(row.get("name")))) & keys
    ]
    return hits or [primary]


def _primary_profile_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rows,
        key=lambda row: (
            float(row.get("overall")) if row.get("overall") is not None else -1.0,
            float(row.get("minutes") or 0),
        ),
    )


def _best_count(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> int | None:
    best: int | None = None
    for row in rows:
        number = _row_count(row, keys)
        if number is None:
            continue
        if best is None or number > best:
            best = number
    return best


def loan_playing_minutes(
    rows: list[dict[str, Any]],
    primary: dict[str, Any],
) -> tuple[int | None, int | None]:
    """Total played minutes, plus the minutes behind the shown profile score."""
    by_position: dict[str, int] = {}
    for index, row in enumerate(rows):
        minutes = _as_int(row.get("minutes"))
        if minutes is None:
            continue
        position = str(row.get("position") or row.get("positionLabel") or "").strip()
        key = position or f"row-{index}"
        by_position[key] = max(by_position.get(key, 0), minutes)
    profile_minutes = _as_int(primary.get("minutes"))
    total = sum(by_position.values()) if by_position else profile_minutes
    if profile_minutes is not None and (total is None or total < profile_minutes):
        total = profile_minutes
    return total, profile_minutes


def _loans_for_club(
    snapshot: dict[str, Any],
    club_name: str,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, payload in (snapshot or {}).items():
        if not transfer_status._clubs_match(name, club_name) and name != club_name:
            continue
        for entry in transfer_status._loan_entries(payload):
            key = transfer_status.name_key(entry.get("name"))
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "name": _clean_text(entry.get("name")),
                    "from": _clean_text(entry.get("from")),
                }
            )
    return rows


def _report_loans(team: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in team.get("signed") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().casefold()
        if kind != "loan":
            continue
        name = _clean_text(item.get("player"))
        key = transfer_status.name_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "from": _clean_text(item.get("other"))})
    return rows


def _merge_loan_lists(*groups: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            key = transfer_status.name_key(row.get("name"))
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def _league_id_for_label(label: str) -> str:
    text = str(label or "").strip()
    if text in LEAGUE_NAME_TO_ID:
        return LEAGUE_NAME_TO_ID[text]
    key = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return key if key in LEAGUE_LABELS else "other"


def loan_position_group(code: Any, label: Any = "") -> str:
    for value in (code, label):
        text = str(value or "").strip()
        if not text:
            continue
        compact = text.upper().replace(" ", "_").replace("-", "_")
        mapped = _POSITION_CODE_TO_GROUP.get(compact) or _POSITION_CODE_TO_GROUP.get(text.upper())
        if mapped:
            return mapped
        folded = text.casefold().replace("–", "-").replace("—", "-")
        mapped = _POSITION_CODE_TO_GROUP.get(folded.upper().replace(" ", "_").replace("-", "_"))
        if mapped:
            return mapped
        for hint, group in _POSITION_LABEL_HINTS:
            if hint in folded:
                return group
    return ""


def _enrich_loan(
    *,
    name: str,
    from_club: str,
    club: str,
    league: str,
    league_id: str,
    team_id: str,
    badge: str,
    players: list[dict[str, Any]],
) -> dict[str, Any]:
    matched = _match_impect_player(name, club, players)
    related = _related_impect_rows(matched, players)
    primary = _primary_profile_row(related) if related else matched
    total_minutes, profile_minutes = loan_playing_minutes(related, primary or {})
    age = _as_int((primary or {}).get("age"))
    overall = _as_float((primary or {}).get("overall"))
    if overall is not None:
        overall = round(overall, 1)
    time_row = playing_time(
        minutes=total_minutes,
        match_count=_best_count(related, MATCH_KEYS),
        starts=_best_count(related, START_KEYS),
    )
    player_id = _player_id(primary)
    position_code = str((primary or {}).get("position") or "").strip()
    position = str(
        (primary or {}).get("positionLabel")
        or position_code
        or ""
    ).strip()
    position_group = loan_position_group(position_code, position)
    watch = loan_watch_score(
        overall=overall,
        minutes=time_row["minutes"],
        starts=time_row["starts"],
        matches=time_row["matches"],
        age=age,
    )
    minutes_n = time_row["minutes"] or 0
    matches_n = time_row["matches"] or 0
    starts_n = time_row["starts"] or 0
    if minutes_n >= 450 or (matches_n and starts_n / matches_n >= 0.6 and minutes_n >= 180):
        usage = "regular"
    elif minutes_n >= 90 or starts_n >= 1:
        usage = "rotation"
    else:
        usage = "unused"
    return {
        "id": f"{team_id}:{transfer_status.name_key(name).replace(' ', '-')}",
        "player": name,
        "from_club": from_club,
        "club": club,
        "team_id": team_id,
        "league": league,
        "league_id": league_id,
        "badge_url": badge,
        "age": age,
        "position": position,
        "position_group": position_group,
        "minutes": time_row["minutes"],
        "profile_minutes": profile_minutes,
        "matches": time_row["matches"],
        "starts": time_row["starts"],
        "matches_estimated": time_row["matches_estimated"],
        "starts_estimated": time_row["starts_estimated"],
        "overall": overall,
        "watch_score": watch,
        "usage": usage,
        "player_id": player_id,
        "dossier_href": f"/player/{player_id}" if player_id else "",
        "u21": age is not None and age <= 21,
        "u23": age is not None and age <= 23,
        "u25": age is not None and age <= 25,
        "has_score": overall is not None,
    }


def _club_seen(name: str, used_keys: set[str], used_names: list[str]) -> bool:
    if transfer_status.club_key(name) in used_keys:
        return True
    return any(transfer_status._clubs_match(name, other) for other in used_names)


def _empty_totals() -> dict[str, int]:
    return {
        "teams": 0,
        "loans": 0,
        "scored": 0,
        "regular": 0,
        "unused": 0,
        "u23": 0,
    }


def _sort_loans(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            -(float(row["overall"]) if row.get("overall") is not None else -1.0),
            -(row.get("minutes") or 0),
            -(row.get("watch_score") or 0),
            str(row.get("player") or ""),
        )
    )
    return rows


def build_loans_watch(
    *,
    report: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    players: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else load_report()
    loans_by_club = snapshot if isinstance(snapshot, dict) else transfer_status.load_loan_snapshot()
    pool = _player_index(players if players is not None else _impect_players())

    used_clubs: set[str] = set()
    used_names: list[str] = []
    leagues_out: list[dict[str, Any]] = []
    all_loans: list[dict[str, Any]] = []
    totals = _empty_totals()

    for league in payload.get("leagues") or []:
        if not isinstance(league, dict):
            continue
        league_id = str(league.get("id") or "").strip()
        if league_id not in REPORT_LEAGUE_IDS:
            continue
        league_name = str(league.get("name") or LEAGUE_LABELS.get(league_id, league_id))
        teams_out: list[dict[str, Any]] = []
        for team in league.get("teams") or []:
            if not isinstance(team, dict):
                continue
            club = _clean_text(team.get("name"))
            if not club:
                continue
            team_id = str(team.get("id") or "").strip() or _team_id(club)
            badge = str(team.get("badge_url") or badge_url(team_id) or "")
            tm_loans = _loans_for_club(loans_by_club, club)
            loans = _merge_loan_lists(
                tm_loans,
                [] if tm_loans else _report_loans(team),
            )
            used_clubs.add(transfer_status.club_key(club))
            used_names.append(club)
            rows = [
                _enrich_loan(
                    name=item["name"],
                    from_club=item["from"],
                    club=club,
                    league=league_name,
                    league_id=league_id,
                    team_id=team_id,
                    badge=badge,
                    players=pool,
                )
                for item in loans
            ]
            _sort_loans(rows)
            teams_out.append(
                {
                    "id": team_id,
                    "name": club,
                    "badge_url": badge,
                    "loan_count": len(rows),
                    "loans": rows,
                }
            )
            all_loans.extend(rows)
        teams_out.sort(key=lambda row: str(row.get("name") or ""))
        leagues_out.append(
            {
                "id": league_id,
                "name": league_name,
                "color": LEAGUE_COLORS.get(league_id, "#9ca3af"),
                "loan_count": sum(team["loan_count"] for team in teams_out),
                "teams": teams_out,
            }
        )

    extra_by_league: dict[str, list[dict[str, Any]]] = {}
    for club_name, payload_loans in (loans_by_club or {}).items():
        club = _clean_text(club_name)
        if not club or _club_seen(club, used_clubs, used_names):
            continue
        entries = transfer_status._loan_entries(payload_loans)
        if not entries:
            continue
        team_id = _team_id(club)
        sample = _match_impect_player(entries[0]["name"], club, pool) if entries else None
        league_label = str((sample or {}).get("league") or "Other").strip() or "Other"
        league_id = _league_id_for_label(league_label)
        if league_id in REPORT_LEAGUE_IDS:
            # Same league as a report club, different spelling — keep it visible.
            league_label = LEAGUE_LABELS.get(league_id, league_label)
        rows = [
            _enrich_loan(
                name=_clean_text(item.get("name")),
                from_club=_clean_text(item.get("from")),
                club=club,
                league=league_label if league_id != "other" else "Other",
                league_id=league_id,
                team_id=team_id,
                badge=badge_url(team_id),
                players=pool,
            )
            for item in entries
            if _clean_text(item.get("name"))
        ]
        _sort_loans(rows)
        extra_by_league.setdefault(league_id, []).append(
            {
                "id": team_id,
                "name": club,
                "badge_url": badge_url(team_id),
                "loan_count": len(rows),
                "loans": rows,
            }
        )
        used_clubs.add(transfer_status.club_key(club))
        used_names.append(club)
        all_loans.extend(rows)

    existing = {row["id"] for row in leagues_out}
    for league_id, teams in extra_by_league.items():
        teams.sort(key=lambda row: str(row.get("name") or ""))
        if league_id in existing:
            host = next(row for row in leagues_out if row["id"] == league_id)
            host["teams"].extend(teams)
            host["teams"].sort(key=lambda row: str(row.get("name") or ""))
            host["loan_count"] = sum(team["loan_count"] for team in host["teams"])
            continue
        leagues_out.append(
            {
                "id": league_id,
                "name": LEAGUE_LABELS.get(league_id, league_id.replace("-", " ").title()),
                "color": LEAGUE_COLORS.get(league_id, "#9ca3af"),
                "loan_count": sum(team["loan_count"] for team in teams),
                "teams": teams,
            }
        )

    order = {key: index for index, key in enumerate(LEAGUE_ORDER)}
    leagues_out.sort(key=lambda row: (order.get(row["id"], 99), str(row.get("name") or "")))
    _sort_loans(all_loans)

    scored = [row for row in all_loans if row.get("overall") is not None]
    totals["teams"] = sum(len(league["teams"]) for league in leagues_out)
    totals["loans"] = len(all_loans)
    totals["scored"] = len(scored)
    totals["regular"] = sum(1 for row in all_loans if row.get("usage") == "regular")
    totals["unused"] = sum(1 for row in all_loans if row.get("usage") == "unused")
    totals["u23"] = sum(1 for row in all_loans if row.get("u23"))

    meta = transfer_status.report_meta()
    return {
        "title": "Loans Watch",
        "season": str(payload.get("season") or ""),
        "updated": _snapshot_updated() or str(payload.get("updated") or ""),
        "scoring": {"note": SCORING_NOTE},
        "totals": totals,
        "leagues": leagues_out,
        "positions": [{"id": key, "label": label} for key, label in POSITION_GROUPS],
        "loans": all_loans,
        "transfer_check": meta,
    }


def cached_loans_watch_payload() -> dict[str, Any]:
    global _payload_mem
    now = time.time()
    with _payload_lock:
        if _payload_mem and now - _payload_mem[0] < CACHE_TTL_SECONDS:
            return _payload_mem[1]
    payload = build_loans_watch()
    with _payload_lock:
        _payload_mem = (now, payload)
    return payload


def register_loans_watch_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "loans-watch.html"

    @app.get("/loans-watch", response_class=HTMLResponse)
    def loans_watch_page() -> HTMLResponse:
        if not page_path.is_file():
            raise RuntimeError(f"Missing page: {page_path}")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/loans-watch")
    def loans_watch_data() -> dict[str, Any]:
        return cached_loans_watch_payload()
