"""League Two blocks of five — posters, editable Silver targets, live KPIs."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.paths import BLOCKS_ANALYSIS_DATA_DIR
from app.post_match.ball_progression import _top7_average
from app.post_match.config import PORT_VALE_SQUAD_ID
from app.post_match.duels import (
    KPI_BALL_WIN_ADDED_TEAMMATES,
    KPI_BALL_WIN_REMOVED_OPPONENTS,
    KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS,
    KPI_LOST_AERIAL_DUELS,
    KPI_LOST_GROUND_DUELS,
    KPI_WON_AERIAL_DUELS,
    KPI_WON_GROUND_DUELS,
)
from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.report import (
    _consolidate_player_match_rows,
    _flatten_player_kpis,
    _flatten_squad_kpis,
    _player_directory,
)
from app.post_match.field_tilt import (
    BLOCK_MINUTES,
    _block_focus_tilts,
    _iteration_match_lookup,
    _overall_focus_tilt,
    build_field_tilt,
)
from app.post_match.offensive_touches_zones import build_offensive_touches_zones
from app.post_match.phase_analysis import (
    PHASE_ORDER,
    _fetch_match_events,
    _phase_durations_from_events,
    _recent_squad_match_ids,
    build_game_by_phase,
)
from app.post_match.season_matches import build_season_matches
from app.post_match.xg_race import build_xg_race
from app.scouting import SCOUTING_DIR

# League Two 26/27. Keep these here — post-match DEFAULT_ITERATION_ID may still
# point at a previous season on some deploys.
BLOCKS_ITERATION_ID = 2120
BLOCKS_SEASON_LABEL = "26/27"
PREVIOUS_LEAGUE_TWO_ITERATION_ID = 1464  # 25/26 — top-7 requirement until 26/27 has games
DEMO_CUP_ITERATION_ID = 2227  # EFL Cup 26/27
DEMO_MATCH_ID = 285444  # Wolves 7 Aug — demo until League Two is played

LONDON = ZoneInfo("Europe/London")
BLOCK_COUNT = 9
GAMES_PER_BLOCK = 5
LEAGUE_TABLE_GAMES = 46
# Impect weighted bypassed defenders — matches platform league averages (~45/game).
# KPI 1400 (raw) reads ~65/game and must not be used for Req / team backline beaten.
KPI_BYPASSED_DEFENDERS = 2
KPI_SHOT_XG = 82
MATCH_KPI_CACHE_TTL = 6 * 3600
MATCH_STATS_CACHE_VERSION = 13
# Shot actions stripped from match + player xG boards (open-play / set-piece delivery only).
XG_VS_EXCLUDED_ACTIONS = frozenset({
    "PENALTY",
    "PENALTY_KICK",
    "DIRECT_FREE_KICK",
})
PHASE_SHORT_LABELS = {
    "IN_POSSESSION": "In possession",
    "OUT_OF_POSSESSION": "Out of possession",
    "ATTACKING_TRANSITION": "Att. transition",
    "DEFENSIVE_TRANSITION": "Def. transition",
    "SECOND_BALL": "Second ball",
    "SET_PIECE": "Set piece",
}
FROM_ZONE_LABELS = {
    "WL": "Wide left",
    "AM": "Attacking mid",
    "WR": "Wide right",
}
PAYLOAD_CACHE_TTL = 45
PLAYER_NAMES_TTL = 6 * 3600
BENCHMARK_CACHE_TTL = 600
UNIT_TOP7_TTL = 24 * 3600
UNIT_TOP7_VERSION = 4
UNIT_TOP7_GAMES_PER_SQUAD = 8
FORM_BASELINE_GAMES = 7
UNITS: tuple[str, ...] = ("DEF", "MID", "ATT")
POSITION_TO_UNIT: dict[str, str | None] = {
    "GOALKEEPER": None,
    "CENTRAL_DEFENDER": "DEF",
    "LEFT_WINGBACK_DEFENDER": "WB",
    "RIGHT_WINGBACK_DEFENDER": "WB",
    "DEFENSE_MIDFIELD": "MID",
    "CENTRAL_MIDFIELD": "MID",
    "ATTACKING_MIDFIELD": "ATT",
    "LEFT_WINGER": "ATT",
    "RIGHT_WINGER": "ATT",
    "CENTER_FORWARD": "ATT",
    "SECOND_STRIKER": "ATT",
}
LEAGUE_LABEL = "League Two"
LEAGUE_SHORT = "LG2"

DATA_DIR = BLOCKS_ANALYSIS_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
TARGETS_PATH = DATA_DIR / "targets.json"
KPI_CACHE_PATH = DATA_DIR / "match-kpis.json"
UNIT_TOP7_PATH = DATA_DIR / "unit-top7.json"

_store_lock = threading.Lock()
_payload_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_benchmark_cache: tuple[float, dict[str, Any]] | None = None
_player_names_cache: dict[int, tuple[float, dict[int, str]]] = {}

MEDAL_DEFAULTS: dict[str, dict[str, Any]] = {
    "gold": {
        "id": "gold",
        "label": "GOLD • CHAMPIONS",
        "shortLabel": "Gold",
        "outcome": "Champions",
        "points": 10,
        "cleanSheets": 2,
    },
    "silver": {
        "id": "silver",
        "label": "SILVER • AUTOMATIC",
        "shortLabel": "Silver",
        "outcome": "Automatic",
        "points": 9,
        "cleanSheets": 2,
    },
    "bronze": {
        "id": "bronze",
        "label": "BRONZE • PLAY-OFFS",
        "shortLabel": "Bronze",
        "outcome": "Play-offs",
        "points": 8,
        "cleanSheets": 1,
    },
}

BLOCK_COPY: tuple[dict[str, str], ...] = (
    {
        "title": "FIRST FIVE LEAGUE GAMES",
        "heading": "THE FIRST FIVE – HERE'S THE BLOCK",
        "footer": "FIRST FIVE — SET THE TONE FOR THE SEASON",
    },
    {
        "title": "GAMES 6–10",
        "heading": "BLOCK TWO – KEEP THE STANDARD",
        "footer": "FIVE MORE — SAME DEMAND",
    },
    {
        "title": "GAMES 11–15",
        "heading": "BLOCK THREE – NO DROP-OFF",
        "footer": "STAY ON IT",
    },
    {
        "title": "GAMES 16–20",
        "heading": "BLOCK FOUR – HALFWAY MARK",
        "footer": "KEEP COLLECTING",
    },
    {
        "title": "GAMES 21–25",
        "heading": "BLOCK FIVE – MID-SEASON TEST",
        "footer": "POINTS ON THE BOARD",
    },
    {
        "title": "GAMES 26–30",
        "heading": "BLOCK SIX – SAME STANDARDS",
        "footer": "NO EASY GAMES",
    },
    {
        "title": "GAMES 31–35",
        "heading": "BLOCK SEVEN – RUN-IN BEGINS",
        "footer": "WIN YOUR BLOCK",
    },
    {
        "title": "GAMES 36–40",
        "heading": "BLOCK EIGHT – PROMOTION STRETCH",
        "footer": "FINISH STRONG",
    },
    {
        "title": "THE LAST BLOCK",
        "heading": "BLOCK NINE – FINISH THE JOB",
        "footer": "SEE IT THROUGH",
    },
)


class BlockTargetUpdate(BaseModel):
    block_id: int = Field(alias="blockId", ge=1, le=BLOCK_COUNT)
    medal: str = "silver"
    points: int = Field(ge=0, le=18)
    clean_sheets: int = Field(alias="cleanSheets", ge=0, le=6)

    model_config = {"populate_by_name": True}


class BlocksExportPage(BaseModel):
    image_data: str = Field(default="", alias="imageData")
    width: int = 0
    height: int = 0

    model_config = {"populate_by_name": True}


class BlocksExportRequest(BaseModel):
    pages: list[BlocksExportPage] = Field(default_factory=list)
    filename: str | None = None
    document_title: str | None = None

    model_config = {"populate_by_name": True}


def _empty_targets() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": None,
        "blocks": {
            str(i): {
                "medal": "silver",
                "points": int(MEDAL_DEFAULTS["silver"]["points"]),
                "cleanSheets": int(MEDAL_DEFAULTS["silver"]["cleanSheets"]),
            }
            for i in range(1, BLOCK_COUNT + 1)
        },
    }


def _normalize_targets(payload: dict[str, Any] | None) -> dict[str, Any]:
    store = _empty_targets()
    if not isinstance(payload, dict):
        return store
    raw_blocks = payload.get("blocks")
    if not isinstance(raw_blocks, dict):
        return store
    for i in range(1, BLOCK_COUNT + 1):
        row = raw_blocks.get(str(i)) or raw_blocks.get(i)
        if not isinstance(row, dict):
            continue
        medal = str(row.get("medal") or "silver").strip().lower()
        if medal not in MEDAL_DEFAULTS:
            medal = "silver"
        defaults = MEDAL_DEFAULTS[medal]
        try:
            points = int(row.get("points"))
        except (TypeError, ValueError):
            points = int(defaults["points"])
        try:
            clean_sheets = int(row.get("cleanSheets", row.get("clean_sheets")))
        except (TypeError, ValueError):
            clean_sheets = int(defaults["cleanSheets"])
        store["blocks"][str(i)] = {
            "medal": medal,
            "points": max(0, min(18, points)),
            "cleanSheets": max(0, min(6, clean_sheets)),
        }
    store["updated_at"] = payload.get("updated_at")
    return store


def _load_targets() -> dict[str, Any]:
    with _store_lock:
        if not TARGETS_PATH.exists():
            return _empty_targets()
        try:
            payload = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_targets()
        return _normalize_targets(payload)


def _save_targets(payload: dict[str, Any]) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = _normalize_targets(payload)
    cleaned["version"] = 1
    cleaned["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = TARGETS_PATH.with_suffix(".json.tmp")
    with _store_lock:
        temp_path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
        temp_path.replace(TARGETS_PATH)
    _payload_cache.clear()
    return cleaned


def _load_kpi_disk_cache() -> dict[str, Any]:
    if not KPI_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(KPI_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_kpi_disk_cache(cache: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = KPI_CACHE_PATH.with_suffix(".json.tmp")
    with _store_lock:
        temp_path.write_text(json.dumps(cache), encoding="utf-8")
        temp_path.replace(KPI_CACHE_PATH)


def _load_unit_top7_disk() -> dict[str, Any]:
    if not UNIT_TOP7_PATH.exists():
        return {}
    try:
        payload = json.loads(UNIT_TOP7_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_unit_top7_disk(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = UNIT_TOP7_PATH.with_suffix(".json.tmp")
    with _store_lock:
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        temp_path.replace(UNIT_TOP7_PATH)


def _normalize_position(position: Any) -> str:
    return str(position or "").strip().upper().replace("-", "_").replace(" ", "_")


def _is_wingback_position(position: Any) -> bool:
    text = _normalize_position(position)
    return bool(text) and ("WINGBACK" in text or "WING_BACK" in text)


def _unit_for_position(position: Any) -> str | None:
    text = _normalize_position(position)
    if _is_wingback_position(text):
        return "WB"
    if text in POSITION_TO_UNIT:
        return POSITION_TO_UNIT[text]
    if not text or "GOAL" in text:
        return None
    if "WINGER" in text or "FORWARD" in text or "STRIKER" in text:
        return "ATT"
    if "DEFEND" in text or "FULL_BACK" in text or "FULLBACK" in text:
        return "DEF"
    if "MID" in text:
        return "MID"
    return None


def _unit_shares_for_position(position: Any) -> list[tuple[str, float]]:
    """Wing-backs count half as full-backs (DEF) and half as wingers (ATT)."""
    if _is_wingback_position(position):
        return [("DEF", 0.5), ("ATT", 0.5)]
    unit = _unit_for_position(position)
    if unit in UNITS:
        return [(unit, 1.0)]
    return []


def _empty_unit_row() -> dict[str, Any]:
    return {
        "defendersBypassed": None,
        "duelWon": None,
        "duelTotal": None,
        "duelRate": None,
    }


def _empty_units() -> dict[str, dict[str, Any]]:
    return {unit: _empty_unit_row() for unit in UNITS}


def _finalize_unit_row(row: dict[str, float]) -> dict[str, Any]:
    won = float(row.get("duelWon") or 0)
    total = float(row.get("duelTotal") or 0)
    bypassed = float(row.get("defendersBypassed") or 0)
    return {
        "defendersBypassed": round(bypassed, 1) if bypassed or total or won else None,
        "duelWon": round(won, 1) if total or won else None,
        "duelTotal": round(total, 1) if total or won else None,
        "duelRate": round((won / total) * 100, 1) if total > 0 else None,
    }


def _units_from_players(players: list[dict[str, Any]], squad_id: int) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, float]] = {
        unit: {"defendersBypassed": 0.0, "duelWon": 0.0, "duelTotal": 0.0}
        for unit in UNITS
    }
    seen = False
    for row in _consolidate_player_match_rows(
        [item for item in players if int(item.get("squadId") or 0) == int(squad_id)]
    ):
        shares = _unit_shares_for_position(row.get("position"))
        if not shares:
            continue
        kpis = row.get("kpis") or {}
        won = _kpi_value(kpis, KPI_WON_GROUND_DUELS) + _kpi_value(kpis, KPI_WON_AERIAL_DUELS)
        lost = _kpi_value(kpis, KPI_LOST_GROUND_DUELS) + _kpi_value(kpis, KPI_LOST_AERIAL_DUELS)
        bypassed = _kpi_value(kpis, KPI_BYPASSED_DEFENDERS)
        duel_total = won + lost
        for unit, share in shares:
            buckets[unit]["defendersBypassed"] += bypassed * share
            buckets[unit]["duelWon"] += won * share
            buckets[unit]["duelTotal"] += duel_total * share
        seen = True
    if not seen:
        return _empty_units()
    return {unit: _finalize_unit_row(values) for unit, values in buckets.items()}


def _blocks_player_names(iteration_id: int = BLOCKS_ITERATION_ID) -> dict[int, str]:
    now = time.time()
    cached = _player_names_cache.get(iteration_id)
    if cached and now - cached[0] < PLAYER_NAMES_TTL:
        return cached[1]
    try:
        names = _player_directory(iteration_id)
    except Exception:  # noqa: BLE001
        names = {}
    _player_names_cache[iteration_id] = (now, names)
    return names


def _merged_player_names() -> dict[int, str]:
    names = dict(_blocks_player_names(BLOCKS_ITERATION_ID))
    names.update(_blocks_player_names(DEMO_CUP_ITERATION_ID))
    return names


def _player_match_report(
    players: list[dict[str, Any]],
    squad_id: int,
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _consolidate_player_match_rows(
        [item for item in players if int(item.get("squadId") or 0) == int(squad_id)]
    ):
        minutes = float(row.get("minutes") or 0)
        if minutes <= 0:
            continue
        kpis = row.get("kpis") or {}
        won = _kpi_value(kpis, KPI_WON_GROUND_DUELS) + _kpi_value(kpis, KPI_WON_AERIAL_DUELS)
        lost = _kpi_value(kpis, KPI_LOST_GROUND_DUELS) + _kpi_value(kpis, KPI_LOST_AERIAL_DUELS)
        total = won + lost
        player_id = int(row["playerId"])
        name = (
            player_names.get(player_id)
            or str(row.get("name") or "").strip()
            or f"Player {player_id}"
        )
        rows.append(
            {
                "playerId": player_id,
                "name": name,
                "unit": _unit_for_position(row.get("position")),
                "minutes": round(minutes, 1),
                "xg": round(_kpi_value(kpis, KPI_SHOT_XG), 2),
                "offensiveInterventions": int(
                    round(_kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS))
                ),
                "defensiveInterventions": int(round(_kpi_value(kpis, KPI_BALL_WIN_ADDED_TEAMMATES))),
                "regainsFromDefenders": int(
                    round(_kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS))
                ),
                "defendersBypassed": round(_kpi_value(kpis, KPI_BYPASSED_DEFENDERS), 1),
                "duelWon": int(round(won)),
                "duelTotal": int(round(total)),
                "duelRate": round((won / total) * 100, 1) if total > 0 else None,
            }
        )
    rows.sort(key=lambda item: (-float(item["minutes"]), str(item["name"])))
    return rows


def _kpi_value(kpis: dict[int, float], kpi_id: int) -> float:
    raw = kpis.get(kpi_id)
    if raw is None:
        raw = kpis.get(str(kpi_id))  # type: ignore[call-overload]
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _extract_rate_kpis(kpis: dict[int, float]) -> dict[str, Any]:
    """Per-match rates from iteration squad-kpis — keep decimals for averages."""
    won = _kpi_value(kpis, KPI_WON_GROUND_DUELS) + _kpi_value(kpis, KPI_WON_AERIAL_DUELS)
    lost = _kpi_value(kpis, KPI_LOST_GROUND_DUELS) + _kpi_value(kpis, KPI_LOST_AERIAL_DUELS)
    duel_total = won + lost
    duel_rate = (won / duel_total) * 100 if duel_total > 0 else None
    offensive = _kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS)
    return {
        "defendersBypassed": _kpi_value(kpis, KPI_BYPASSED_DEFENDERS),
        "offensiveInterventions": offensive,
        "duelRate": duel_rate,
        "ballWinsFromOppDefenders": _kpi_value(
            kpis, KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS
        ),
        "xg": _kpi_value(kpis, KPI_SHOT_XG),
    }


def _extract_match_kpis(kpis: dict[int, float]) -> dict[str, Any]:
    won = _kpi_value(kpis, KPI_WON_GROUND_DUELS) + _kpi_value(kpis, KPI_WON_AERIAL_DUELS)
    lost = _kpi_value(kpis, KPI_LOST_GROUND_DUELS) + _kpi_value(kpis, KPI_LOST_AERIAL_DUELS)
    duel_total = won + lost
    duel_rate = round((won / duel_total) * 100, 1) if duel_total > 0 else None
    offensive = int(round(_kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS)))
    return {
        "defendersBypassed": round(_kpi_value(kpis, KPI_BYPASSED_DEFENDERS), 1),
        "offensiveInterventions": offensive,
        "duelWon": int(round(won)),
        "duelTotal": int(round(duel_total)),
        "duelRate": duel_rate,
        "ballWinsFromOppDefenders": int(
            round(_kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS))
        ),
        "xg": round(_kpi_value(kpis, KPI_SHOT_XG), 2),
        "units": _empty_units(),
    }


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _average_for_squads(per_squad: dict[int, float], squad_ids: list[int]) -> float | None:
    values = [float(per_squad[squad_id]) for squad_id in squad_ids if squad_id in per_squad]
    return _mean_or_none(values)


def _iteration_table_top7_ids(iteration_id: int) -> list[int]:
    """League-table top 7 (points, then GD) — first 46 league games per club."""
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/matches"))["data"])
    completed = [
        row
        for row in rows
        if (row.get("goals") or {}).get("home", {}).get("fullTime") is not None
    ]
    completed.sort(key=lambda row: str(row.get("scheduledDate") or ""))
    points: dict[int, int] = {}
    goal_diff: dict[int, int] = {}
    played: dict[int, int] = defaultdict(int)
    for row in completed:
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        goals = row.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
        for squad_id, gf, ga in (
            (home_id, home_goals, away_goals),
            (away_id, away_goals, home_goals),
        ):
            if squad_id <= 0 or played[squad_id] >= LEAGUE_TABLE_GAMES:
                continue
            played[squad_id] += 1
            if gf > ga:
                points[squad_id] = points.get(squad_id, 0) + 3
            elif gf < ga:
                pass
            else:
                points[squad_id] = points.get(squad_id, 0) + 1
            goal_diff[squad_id] = goal_diff.get(squad_id, 0) + gf - ga
    ordered = sorted(
        points,
        key=lambda squad_id: (points.get(squad_id, 0), goal_diff.get(squad_id, 0)),
        reverse=True,
    )
    return ordered[:7]


def _benchmark_entry(
    per_squad: dict[int, float],
    *,
    higher_better: bool,
    digits: int,
    rate: bool = False,
    top7_ids: list[int] | None = None,
) -> dict[str, Any]:
    team = per_squad.get(PORT_VALE_SQUAD_ID)
    top7 = (
        _average_for_squads(per_squad, top7_ids)
        if top7_ids
        else _top7_average(per_squad, higher_is_better=higher_better)
    )
    return {
        "team": _round_or_none(team, digits),
        "top7": _round_or_none(top7, digits),
        "higherBetter": higher_better,
        "rate": rate,
        "digits": digits,
    }


def _iteration_all_squad_kpis(iteration_id: int) -> dict[int, dict[int, float]]:
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/squad-kpis"))["data"])
    lookup: dict[int, dict[int, float]] = {}
    for row in rows:
        squad_id = int(row.get("squadId") or 0)
        if not squad_id:
            continue
        parsed: dict[int, float] = {}
        for item in row.get("kpis") or []:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("kpiId")
            value = item.get("value")
            if raw_id is None or value is None:
                continue
            try:
                parsed[int(raw_id)] = float(value)
            except (TypeError, ValueError):
                continue
        if parsed:
            lookup[squad_id] = parsed
    return lookup


def _league_defensive_rates(iteration_id: int) -> dict[int, dict[str, float]]:
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/matches"))["data"])
    table: dict[int, dict[str, int]] = {}

    def bucket(squad_id: int) -> dict[str, int]:
        return table.setdefault(squad_id, {"played": 0, "ga": 0, "cs": 0})

    for row in rows:
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        goals = row.get("goals") or {}
        home_ft = (goals.get("home") or {}).get("fullTime")
        away_ft = (goals.get("away") or {}).get("fullTime")
        if home_id <= 0 or away_id <= 0 or home_ft is None or away_ft is None:
            continue
        home_goals = int(home_ft)
        away_goals = int(away_ft)
        bucket(home_id)["played"] += 1
        bucket(away_id)["played"] += 1
        bucket(home_id)["ga"] += away_goals
        bucket(away_id)["ga"] += home_goals
        if away_goals == 0:
            bucket(home_id)["cs"] += 1
        if home_goals == 0:
            bucket(away_id)["cs"] += 1

    rates: dict[int, dict[str, float]] = {}
    for squad_id, row in table.items():
        played = int(row["played"])
        if played <= 0:
            continue
        rates[squad_id] = {
            "goalsAgainst": row["ga"] / played,
            "cleanSheets": row["cs"] / played,
        }
    return rates


def _empty_benchmarks() -> dict[str, Any]:
    return {
        "goalsAgainst": _benchmark_entry({}, higher_better=False, digits=1),
        "cleanSheets": _benchmark_entry({}, higher_better=True, digits=1),
        "defendersBypassed": _benchmark_entry({}, higher_better=True, digits=1),
        "offensiveInterventions": _benchmark_entry({}, higher_better=True, digits=1),
        "duelRate": _benchmark_entry({}, higher_better=True, digits=1, rate=True),
        "ballWinsFromOppDefenders": _benchmark_entry({}, higher_better=True, digits=1),
        "xg": _benchmark_entry({}, higher_better=True, digits=2),
    }


def _benchmarks_for_iteration(iteration_id: int) -> dict[str, Any]:
    try:
        kpi_lookup = _iteration_all_squad_kpis(iteration_id)
        defence = _league_defensive_rates(iteration_id)
    except Exception:  # noqa: BLE001
        return _empty_benchmarks()

    extracted: dict[int, dict[str, Any]] = {
        squad_id: _extract_rate_kpis(kpis) for squad_id, kpis in kpi_lookup.items()
    }
    try:
        top7_ids = _iteration_table_top7_ids(iteration_id)
    except Exception:  # noqa: BLE001
        top7_ids = []

    def column(key: str) -> dict[int, float]:
        values: dict[int, float] = {}
        for squad_id, row in extracted.items():
            value = row.get(key)
            if value is None:
                continue
            values[squad_id] = float(value)
        return values

    def entry(values: dict[int, float], *, higher_better: bool, digits: int, rate: bool = False) -> dict[str, Any]:
        return _benchmark_entry(
            values,
            higher_better=higher_better,
            digits=digits,
            rate=rate,
            top7_ids=top7_ids,
        )

    return {
        "goalsAgainst": entry(
            {sid: row["goalsAgainst"] for sid, row in defence.items()},
            higher_better=False,
            digits=1,
        ),
        "cleanSheets": entry(
            {sid: row["cleanSheets"] for sid, row in defence.items()},
            higher_better=True,
            digits=1,
        ),
        "defendersBypassed": entry(column("defendersBypassed"), higher_better=True, digits=1),
        "offensiveInterventions": entry(
            column("offensiveInterventions"), higher_better=True, digits=1
        ),
        "duelRate": entry(column("duelRate"), higher_better=True, digits=1, rate=True),
        "ballWinsFromOppDefenders": entry(
            column("ballWinsFromOppDefenders"), higher_better=True, digits=1
        ),
        "xg": entry(column("xg"), higher_better=True, digits=2),
    }


def build_block_benchmarks(
    iteration_id: int = BLOCKS_ITERATION_ID,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    global _benchmark_cache
    now = time.time()
    if (
        not force_refresh
        and _benchmark_cache
        and now - _benchmark_cache[0] < BENCHMARK_CACHE_TTL
    ):
        return _benchmark_cache[1]

    payload = _benchmarks_for_iteration(iteration_id)
    older = None
    for key, row in payload.items():
        if row.get("top7") is not None and row.get("team") is not None:
            continue
        if older is None:
            older = _benchmarks_for_iteration(PREVIOUS_LEAGUE_TWO_ITERATION_ID)
        prev = older.get(key) or {}
        if row.get("top7") is None and prev.get("top7") is not None:
            row["top7"] = prev["top7"]
            row["top7From"] = "previous"
        if row.get("team") is None and prev.get("team") is not None:
            row["team"] = prev["team"]
            row["teamFrom"] = "previous"

    _benchmark_cache = (now, payload)
    return payload


def _fetch_squad_kpis(match_id: int) -> dict[int, float]:
    raw = impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))
    lookup = _flatten_squad_kpis(raw["data"])
    return lookup.get(PORT_VALE_SQUAD_ID) or {}


def _open_play_xg_total(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        action = str(row.get("action") or "").upper()
        if action in XG_VS_EXCLUDED_ACTIONS:
            continue
        total += float(row.get("xg") or 0)
    return round(total, 2)


def _player_open_play_xg(shots: list[dict[str, Any]], squad_id: int) -> dict[int, float]:
    """Per-player shot xG excluding penalties and direct free kicks."""
    totals: dict[int, float] = {}
    for row in shots:
        if int(row.get("squadId") or 0) != int(squad_id):
            continue
        if str(row.get("action") or "").upper() in XG_VS_EXCLUDED_ACTIONS:
            continue
        try:
            player_id = int(row.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id:
            continue
        totals[player_id] = totals.get(player_id, 0.0) + float(row.get("xg") or 0)
    return {pid: round(value, 2) for pid, value in totals.items()}


def _apply_open_play_player_xg(
    players: list[dict[str, Any]],
    shots: list[dict[str, Any]],
    squad_id: int,
) -> None:
    if not players or not shots:
        return
    if not any(row.get("playerId") for row in shots):
        return
    open_xg = _player_open_play_xg(shots, squad_id)
    for player in players:
        try:
            player_id = int(player.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id:
            continue
        player["xg"] = open_xg.get(player_id, 0.0)


def _half_time_xg(series: list[dict[str, Any]]) -> float:
    first = [row for row in series if row.get("half") == "first"]
    if first:
        return float(first[-1].get("xg") or 0)
    last = 0.0
    for row in series:
        if float(row.get("minute") or 0) <= 45.01:
            last = float(row.get("xg") or 0)
    return last


def _compact_race_series(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "minute": round(float(row.get("minute") or 0), 1),
            "xg": round(float(row.get("xg") or 0), 3),
            "isGoal": bool(row.get("isGoal")),
        }
        for row in series
    ]


def _match_story(
    match_id: int,
    *,
    squad_id: int,
    home_squad_id: int,
    away_squad_id: int,
    home_name: str,
    away_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not home_squad_id or not away_squad_id:
        return None, None
    try:
        race = build_xg_race(
            match_id,
            home_squad_id,
            away_squad_id,
            home_name,
            away_name,
        )
    except Exception:  # noqa: BLE001
        return None, None

    vale_home = home_squad_id == squad_id
    vale = race["home"] if vale_home else race["away"]
    opp = race["away"] if vale_home else race["home"]
    shots = race.get("shots") or []
    vale_shots = [row for row in shots if int(row.get("squadId") or 0) == squad_id]
    opp_shots = [row for row in shots if int(row.get("squadId") or 0) != squad_id]

    vale_open_xg = _open_play_xg_total(vale_shots)
    opp_open_xg = _open_play_xg_total(opp_shots)
    open_shots = [
        row for row in shots
        if str(row.get("action") or "").upper() not in XG_VS_EXCLUDED_ACTIONS
    ]
    biggest = max(open_shots, key=lambda row: float(row.get("xg") or 0), default=None)
    goals = [row for row in shots if row.get("isGoal")]
    first_goal = min(goals, key=lambda row: float(row.get("minute") or 0), default=None)
    timeline = race.get("timeline") or {}
    vale_goals = sum(1 for row in vale_shots if row.get("isGoal"))
    compact = {
        "endMinute": float(timeline.get("secondHalfEnd") or 90),
        "htMinute": float(timeline.get("firstHalfEnd") or 45),
        "vale": {
            "name": "Port Vale",
            "isHome": vale_home,
            "totalXg": round(float(vale.get("totalXg") or 0), 2),
            "series": _compact_race_series(vale.get("series") or []),
        },
        "opp": {
            "name": (away_name if vale_home else home_name) or "Opponent",
            "isHome": not vale_home,
            "totalXg": round(float(opp.get("totalXg") or 0), 2),
            "series": _compact_race_series(opp.get("series") or []),
        },
    }
    facts = {
        # VS card uses open-play xG (excl. penalties + direct free kicks).
        "valeXg": vale_open_xg,
        "oppXg": opp_open_xg,
        "valeXgAll": compact["vale"]["totalXg"],
        "oppXgAll": compact["opp"]["totalXg"],
        "xgExcludes": "PK & DFK",
        "valeShots": len(vale_shots),
        "oppShots": len(opp_shots),
        "valeGoals": vale_goals,
        "valeHtXg": round(_half_time_xg(vale.get("series") or []), 2),
        "oppHtXg": round(_half_time_xg(opp.get("series") or []), 2),
        "biggestChance": (
            {
                "xg": round(float(biggest.get("xg") or 0), 2),
                "minute": round(float(biggest.get("minute") or 0), 0),
                "ours": int(biggest.get("squadId") or 0) == squad_id,
            }
            if biggest and float(biggest.get("xg") or 0) > 0
            else None
        ),
        "firstGoal": (
            {
                "minute": round(float(first_goal.get("minute") or 0), 0),
                "ours": int(first_goal.get("squadId") or 0) == squad_id,
            }
            if first_goal
            else None
        ),
    }
    return compact, facts


_FORM_LOCK = threading.Lock()
_FORM_CACHE: tuple[float, dict[str, Any] | None, dict[str, Any] | None] | None = None


def _compact_field_tilt(
    tilt: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not tilt:
        return None
    avg_by_start: dict[int, float] = {}
    if baseline:
        for row in baseline.get("timeline") or []:
            if row.get("focusTiltPercent") is None:
                continue
            avg_by_start[int(row.get("startMinute") or 0)] = round(
                float(row["focusTiltPercent"]), 1
            )
    avg_overall = None
    if baseline and baseline.get("focusTiltPercent") is not None:
        avg_overall = round(float(baseline["focusTiltPercent"]), 1)
    return {
        "focusPercent": round(float(tilt.get("focusTiltPercent") or 50), 1),
        "avgPercent": avg_overall,
        "avgGames": int(baseline.get("gamesUsed") or 0) if baseline else 0,
        "blocks": [
            {
                "label": f"{int(row.get('endMinute') or 0)}'",
                "focus": round(float(row.get("focusTiltPercent") or 50), 1),
                "avg": avg_by_start.get(int(row.get("startMinute") or 0)),
            }
            for row in (tilt.get("timeline") or [])
        ],
    }


def _compact_phases(
    game: dict[str, Any] | None,
    baseline: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not game:
        return None
    by_id = {row.get("id"): row for row in (game.get("phases") or [])}
    avg_by_id = {
        row.get("id"): row.get("percent")
        for row in ((baseline or {}).get("phases") or [])
        if row.get("id")
    }
    return {
        "avgGames": int(baseline.get("gamesUsed") or 0) if baseline else 0,
        "phases": [
            {
                "id": key,
                "label": PHASE_SHORT_LABELS.get(key, key),
                "percent": round(float((by_id.get(key) or {}).get("percent") or 0), 1),
                "avg": (
                    round(float(avg_by_id[key]), 1)
                    if avg_by_id.get(key) is not None
                    else None
                ),
            }
            for key in PHASE_ORDER
        ],
    }


def _compute_vale_form(squad_id: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for iteration_id in (BLOCKS_ITERATION_ID, PREVIOUS_LEAGUE_TWO_ITERATION_ID):
        match_ids = _recent_squad_match_ids(
            iteration_id,
            squad_id,
            before_match_id=None,
            count=FORM_BASELINE_GAMES,
        )
        if not match_ids:
            continue
        lookup = _iteration_match_lookup(iteration_id)
        phase_sums: dict[str, float] = defaultdict(float)
        phase_counts: dict[str, int] = defaultdict(int)
        tilt_sums: dict[int, float] = defaultdict(float)
        tilt_counts: dict[int, int] = defaultdict(int)
        overall_tilts: list[float] = []
        used = 0
        for match_id in match_ids:
            row = lookup.get(match_id) or {}
            home_id = int(row.get("homeSquadId") or 0)
            away_id = int(row.get("awaySquadId") or 0)
            try:
                events = _fetch_match_events(match_id)
            except Exception:  # noqa: BLE001
                continue
            if not events:
                continue
            durations = _phase_durations_from_events(events, squad_id)
            total = sum(durations.values())
            if total <= 0:
                continue
            used += 1
            for key in PHASE_ORDER:
                phase_sums[key] += (durations.get(key, 0.0) / total) * 100
                phase_counts[key] += 1
            if home_id and away_id:
                overall_tilts.append(
                    _overall_focus_tilt(events, home_id, away_id, squad_id)
                )
                for start, share in _block_focus_tilts(
                    events, home_id, away_id, squad_id, BLOCK_MINUTES
                ).items():
                    tilt_sums[start] += share
                    tilt_counts[start] += 1
        if used == 0:
            continue
        phases = {
            "gamesUsed": used,
            "phases": [
                {
                    "id": key,
                    "percent": round(phase_sums[key] / max(phase_counts[key], 1), 1),
                }
                for key in PHASE_ORDER
            ],
        }
        tilt = {
            "gamesUsed": used,
            "focusTiltPercent": (
                round(sum(overall_tilts) / len(overall_tilts), 1) if overall_tilts else None
            ),
            "timeline": [
                {
                    "startMinute": start,
                    "endMinute": min(start + BLOCK_MINUTES, 90),
                    "focusTiltPercent": (
                        round(tilt_sums[start] / tilt_counts[start], 1)
                        if tilt_counts[start]
                        else None
                    ),
                }
                for start in range(0, 90, BLOCK_MINUTES)
            ],
        }
        return phases, tilt
    return None, None


def _short_player_name(name: str) -> str:
    parts = str(name or "").strip().split()
    if len(parts) >= 2:
        return parts[-1]
    return str(name or "—")


def _compact_players(rows: list[dict[str, Any]], count_key: str, limit: int = 6) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows[:limit]:
        compact.append(
            {
                "name": _short_player_name(str(row.get("playerName") or "")),
                "count": row.get(count_key) or 0,
            }
        )
    return compact


def _compact_in_behind(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return None
    detail = data.get("inBehind") or {}
    ib_zones = [
        {"id": row.get("id"), "value": round(float(row.get("value") or 0), 1)}
        for row in (data.get("zones") or [])
        if row.get("isInBehind")
    ]
    from_zones = [
        {
            "id": row.get("id"),
            "label": FROM_ZONE_LABELS.get(str(row.get("id") or ""), str(row.get("label") or "")),
            "value": round(float(row.get("value") or 0), 1),
        }
        for row in (data.get("conversionZones") or [])
    ]
    touches = detail.get("totalTouches")
    if touches is None:
        touches = round(sum(row["value"] for row in ib_zones), 1)
    return {
        "touches": touches,
        "passes": data.get("totalPassesIntoInBehind") or 0,
        "ibZones": ib_zones,
        "fromZones": from_zones,
        "touchPlayers": _compact_players(detail.get("touchPlayers") or [], "touchCount"),
        "passPlayers": _compact_players(detail.get("passPlayers") or [], "passCount"),
    }


def _vale_form_baselines(
    squad_id: int,
    *,
    force: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    global _FORM_CACHE
    with _FORM_LOCK:
        if (
            not force
            and _FORM_CACHE
            and time.time() - _FORM_CACHE[0] < MATCH_KPI_CACHE_TTL
        ):
            return _FORM_CACHE[1], _FORM_CACHE[2]
        phases, tilt = _compute_vale_form(squad_id)
        _FORM_CACHE = (time.time(), phases, tilt)
        return phases, tilt


def _fetch_match_stats(
    match_id: int,
    squad_id: int = PORT_VALE_SQUAD_ID,
    player_names: dict[int, str] | None = None,
    home_squad_id: int = 0,
    away_squad_id: int = 0,
    home_name: str = "Home",
    away_name: str = "Away",
    iteration_id: int = 0,
    form_phases: dict[str, Any] | None = None,
    form_tilt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kpis = _fetch_squad_kpis(match_id)
    stats = _extract_match_kpis(kpis) if kpis else _empty_kpi_stats()
    names = player_names or {}
    try:
        players = _flatten_player_kpis(
            impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"],
            names,
        )
        stats["units"] = _units_from_players(players, squad_id)
        stats["players"] = _player_match_report(players, squad_id, names)
    except Exception:  # noqa: BLE001
        stats["units"] = _empty_units()
        stats["players"] = []
    race, facts = _match_story(
        match_id,
        squad_id=squad_id,
        home_squad_id=home_squad_id,
        away_squad_id=away_squad_id,
        home_name=home_name,
        away_name=away_name,
    )
    stats["xgRace"] = race
    stats["facts"] = facts
    if race and facts:
        _apply_open_play_player_xg(stats.get("players") or [], race.get("shots") or [], squad_id)
        # Keep team xG aligned with the VS card / player boards.
        if facts.get("valeXg") is not None:
            stats["xg"] = facts["valeXg"]
    stats["fieldTilt"] = None
    stats["phases"] = None
    stats["inBehind"] = None
    if home_squad_id and away_squad_id:
        try:
            stats["fieldTilt"] = _compact_field_tilt(
                build_field_tilt(
                    match_id,
                    home_squad_id,
                    away_squad_id,
                    squad_id,
                    home_name,
                    away_name,
                ),
                form_tilt,
            )
        except Exception:  # noqa: BLE001
            stats["fieldTilt"] = None
        try:
            stats["phases"] = _compact_phases(
                build_game_by_phase(match_id, squad_id),
                form_phases,
            )
        except Exception:  # noqa: BLE001
            stats["phases"] = None
        try:
            stats["inBehind"] = _compact_in_behind(
                build_offensive_touches_zones(
                    match_id,
                    squad_id,
                    int(iteration_id or BLOCKS_ITERATION_ID),
                )
            )
        except Exception:  # noqa: BLE001
            stats["inBehind"] = None
    return stats


def _score_fingerprint(match: dict[str, Any]) -> str:
    home = (match.get("home") or {}).get("score")
    away = (match.get("away") or {}).get("score")
    available = bool(match.get("available"))
    return f"{home}:{away}:{int(available)}"


def _empty_kpi_stats() -> dict[str, Any]:
    return {
        "defendersBypassed": None,
        "offensiveInterventions": None,
        "duelWon": None,
        "duelTotal": None,
        "duelRate": None,
        "ballWinsFromOppDefenders": None,
        "xg": None,
        "units": _empty_units(),
        "players": [],
        "xgRace": None,
        "facts": None,
        "fieldTilt": None,
        "phases": None,
        "inBehind": None,
    }


def _load_match_kpis(
    matches: list[dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[int, dict[str, Any]]:
    disk = {} if force_refresh else _load_kpi_disk_cache()
    now = time.time()
    result: dict[int, dict[str, Any]] = {}
    to_fetch: list[dict[str, Any]] = []

    for match in matches:
        match_id = int(match.get("matchId") or 0)
        if not match_id:
            continue
        if match.get("outcome") is None and not match.get("available"):
            continue
        fingerprint = _score_fingerprint(match)
        cached = disk.get(str(match_id))
        if (
            isinstance(cached, dict)
            and cached.get("v") == MATCH_STATS_CACHE_VERSION
            and cached.get("fingerprint") == fingerprint
            and now - float(cached.get("fetchedAt") or 0) < MATCH_KPI_CACHE_TTL
            and cached.get("stats")
            and isinstance((cached.get("stats") or {}).get("units"), dict)
            and isinstance((cached.get("stats") or {}).get("players"), list)
        ):
            result[match_id] = cached["stats"]
            continue
        to_fetch.append(match)

    if to_fetch:
        names = _merged_player_names()
        form_phases, form_tilt = _vale_form_baselines(
            PORT_VALE_SQUAD_ID, force=force_refresh
        )
        workers = min(8, len(to_fetch))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _fetch_match_stats,
                    int(match["matchId"]),
                    PORT_VALE_SQUAD_ID,
                    names,
                    int((match.get("home") or {}).get("squadId") or 0),
                    int((match.get("away") or {}).get("squadId") or 0),
                    str((match.get("home") or {}).get("name") or "Home"),
                    str((match.get("away") or {}).get("name") or "Away"),
                    int(match.get("iterationId") or BLOCKS_ITERATION_ID),
                    form_phases,
                    form_tilt,
                ): match
                for match in to_fetch
            }
            for future in as_completed(futures):
                match = futures[future]
                match_id = int(match["matchId"])
                try:
                    stats = future.result()
                except Exception:  # noqa: BLE001 — keep the poster live if one match fails
                    stats = _empty_kpi_stats()
                result[match_id] = stats
                disk[str(match_id)] = {
                    "v": MATCH_STATS_CACHE_VERSION,
                    "fingerprint": _score_fingerprint(match),
                    "fetchedAt": now,
                    "stats": stats,
                }
        _save_kpi_disk_cache(disk)

    return result


def _iteration_completed_matches(iteration_id: int) -> list[dict[str, Any]]:
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/matches"))["data"])
    completed: list[dict[str, Any]] = []
    for row in rows:
        goals = row.get("goals") or {}
        home_ft = (goals.get("home") or {}).get("fullTime")
        away_ft = (goals.get("away") or {}).get("fullTime")
        if home_ft is None or away_ft is None:
            continue
        match_id = int(row.get("id") or 0)
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        if not match_id or home_id <= 0 or away_id <= 0:
            continue
        completed.append(
            {
                "matchId": match_id,
                "scheduledDate": str(row.get("scheduledDate") or ""),
                "homeSquadId": home_id,
                "awaySquadId": away_id,
            }
        )
    completed.sort(key=lambda item: item["scheduledDate"], reverse=True)
    return completed


def _iteration_top7_sample_matches(
    iteration_id: int,
    top7_ids: set[int],
    *,
    games_per_squad: int = UNIT_TOP7_GAMES_PER_SQUAD,
) -> list[dict[str, Any]]:
    if not top7_ids:
        return []
    picked: dict[int, list[dict[str, Any]]] = {squad_id: [] for squad_id in top7_ids}
    for match in _iteration_completed_matches(iteration_id):
        for squad_id in (int(match["homeSquadId"]), int(match["awaySquadId"])):
            if squad_id in top7_ids and len(picked[squad_id]) < games_per_squad:
                picked[squad_id].append(match)
        if all(len(rows) >= games_per_squad for rows in picked.values()):
            break
    unique: dict[int, dict[str, Any]] = {}
    for rows in picked.values():
        for match in rows:
            unique[int(match["matchId"])] = match
    return list(unique.values())


def _fetch_match_player_units(
    match_id: int,
    squad_ids: list[int],
) -> dict[int, dict[str, dict[str, Any]]]:
    players = _flatten_player_kpis(
        impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"],
        {},
    )
    return {int(squad_id): _units_from_players(players, int(squad_id)) for squad_id in squad_ids}


def _empty_unit_benchmarks() -> dict[str, dict[str, Any]]:
    return {
        unit: {
            "defendersBypassed": {
                "team": None,
                "top7": None,
                "higherBetter": True,
                "rate": False,
                "digits": 1,
            },
            "duelRate": {
                "team": None,
                "top7": None,
                "higherBetter": True,
                "rate": True,
                "digits": 1,
            },
        }
        for unit in UNITS
    }


def _unit_averages_from_stats_list(
    stats_list: list[dict[str, Any]],
) -> dict[str, dict[str, float | None]]:
    bypass: dict[str, list[float]] = {unit: [] for unit in UNITS}
    won: dict[str, float] = {unit: 0.0 for unit in UNITS}
    total: dict[str, float] = {unit: 0.0 for unit in UNITS}
    for stats in stats_list:
        units = (stats or {}).get("units") or {}
        for unit in UNITS:
            row = units.get(unit) or {}
            if row.get("defendersBypassed") is not None:
                bypass[unit].append(float(row["defendersBypassed"]))
            duel_total = row.get("duelTotal")
            if duel_total:
                won[unit] += float(row.get("duelWon") or 0)
                total[unit] += float(duel_total)
    out: dict[str, dict[str, float | None]] = {}
    for unit in UNITS:
        out[unit] = {
            "defendersBypassed": _round_or_none(
                (sum(bypass[unit]) / len(bypass[unit])) if bypass[unit] else None,
                1,
            ),
            "duelRate": _round_or_none(
                (100.0 * won[unit] / total[unit]) if total[unit] > 0 else None,
                1,
            ),
        }
    return out


def _build_unit_top7_from_sample(
    iteration_id: int,
) -> tuple[dict[str, dict[str, float | None]], dict[str, dict[str, float | None]]]:
    top7_ids = set(_iteration_table_top7_ids(iteration_id))
    matches = _iteration_top7_sample_matches(iteration_id, top7_ids)
    acc: dict[int, dict[str, dict[str, Any]]] = {}

    def cell(squad_id: int, unit: str) -> dict[str, Any]:
        squad = acc.setdefault(squad_id, {})
        return squad.setdefault(unit, {"bypass": [], "won": 0.0, "total": 0.0})

    if matches:
        workers = min(8, len(matches))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _fetch_match_player_units,
                    int(match["matchId"]),
                    [sid for sid in (int(match["homeSquadId"]), int(match["awaySquadId"])) if sid in top7_ids],
                ): match
                for match in matches
            }
            for future in as_completed(futures):
                match = futures[future]
                try:
                    by_squad = future.result()
                except Exception:  # noqa: BLE001
                    continue
                for squad_id in (int(match["homeSquadId"]), int(match["awaySquadId"])):
                    if squad_id not in top7_ids:
                        continue
                    units = by_squad.get(squad_id) or {}
                    for unit in UNITS:
                        row = units.get(unit) or {}
                        bucket = cell(squad_id, unit)
                        if row.get("defendersBypassed") is not None:
                            bucket["bypass"].append(float(row["defendersBypassed"]))
                        if row.get("duelTotal"):
                            bucket["won"] += float(row.get("duelWon") or 0)
                            bucket["total"] += float(row["duelTotal"])

    per_squad: dict[int, dict[str, dict[str, float | None]]] = {}
    for squad_id, units in acc.items():
        per_squad[squad_id] = {}
        for unit in UNITS:
            bucket = units.get(unit) or {}
            bypass_vals = bucket.get("bypass") or []
            duel_total = float(bucket.get("total") or 0)
            duel_won = float(bucket.get("won") or 0)
            per_squad[squad_id][unit] = {
                "defendersBypassed": (
                    sum(bypass_vals) / len(bypass_vals) if bypass_vals else None
                ),
                "duelRate": (100.0 * duel_won / duel_total) if duel_total > 0 else None,
            }

    top7: dict[str, dict[str, float | None]] = {}
    for unit in UNITS:
        bypass_vals = [
            float(per_squad[squad_id][unit]["defendersBypassed"])
            for squad_id in top7_ids
            if squad_id in per_squad
            and per_squad[squad_id].get(unit, {}).get("defendersBypassed") is not None
        ]
        duel_vals = [
            float(per_squad[squad_id][unit]["duelRate"])
            for squad_id in top7_ids
            if squad_id in per_squad
            and per_squad[squad_id].get(unit, {}).get("duelRate") is not None
        ]
        top7[unit] = {
            "defendersBypassed": _round_or_none(_mean_or_none(bypass_vals), 1),
            "duelRate": _round_or_none(_mean_or_none(duel_vals), 1),
        }

    pv_raw = per_squad.get(PORT_VALE_SQUAD_ID) or {}
    pv_avg = {
        unit: {
            "defendersBypassed": _round_or_none(
                (pv_raw.get(unit) or {}).get("defendersBypassed"), 1
            ),
            "duelRate": _round_or_none((pv_raw.get(unit) or {}).get("duelRate"), 1),
        }
        for unit in UNITS
    }
    return top7, pv_avg


def build_unit_benchmarks(
    kpi_by_match: dict[int, dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    payload = _empty_unit_benchmarks()
    pv_now = _unit_averages_from_stats_list(list(kpi_by_match.values()))
    disk = {} if force_refresh else _load_unit_top7_disk()
    now = time.time()
    top7 = disk.get("top7") if isinstance(disk.get("top7"), dict) else None
    pv_prev = disk.get("teamPrevious") if isinstance(disk.get("teamPrevious"), dict) else None
    fresh = (
        not force_refresh
        and disk.get("v") == UNIT_TOP7_VERSION
        and disk.get("iterationId") == PREVIOUS_LEAGUE_TWO_ITERATION_ID
        and now - float(disk.get("fetchedAt") or 0) < UNIT_TOP7_TTL
        and isinstance(top7, dict)
        and top7
    )
    if not fresh:
        try:
            top7, pv_prev = _build_unit_top7_from_sample(PREVIOUS_LEAGUE_TWO_ITERATION_ID)
            _save_unit_top7_disk(
                {
                    "v": UNIT_TOP7_VERSION,
                    "fetchedAt": now,
                    "iterationId": PREVIOUS_LEAGUE_TWO_ITERATION_ID,
                    "top7": top7,
                    "teamPrevious": pv_prev,
                }
            )
        except Exception:  # noqa: BLE001 — keep the dashboard live without unit top-7
            top7 = top7 or {}
            pv_prev = pv_prev or {}

    for unit in UNITS:
        team_row = pv_now.get(unit) or {}
        prev_row = (pv_prev or {}).get(unit) or {}
        top_row = (top7 or {}).get(unit) or {}
        team_bypass = team_row.get("defendersBypassed")
        team_duel = team_row.get("duelRate")
        if team_bypass is None:
            team_bypass = prev_row.get("defendersBypassed")
            if team_bypass is not None:
                payload[unit]["defendersBypassed"]["teamFrom"] = "previous"
        if team_duel is None:
            team_duel = prev_row.get("duelRate")
            if team_duel is not None:
                payload[unit]["duelRate"]["teamFrom"] = "previous"
        payload[unit]["defendersBypassed"]["team"] = team_bypass
        payload[unit]["defendersBypassed"]["top7"] = top_row.get("defendersBypassed")
        payload[unit]["duelRate"]["team"] = team_duel
        payload[unit]["duelRate"]["top7"] = top_row.get("duelRate")
        if top_row.get("defendersBypassed") is not None:
            payload[unit]["defendersBypassed"]["top7From"] = "previous"
        if top_row.get("duelRate") is not None:
            payload[unit]["duelRate"]["top7From"] = "previous"
    return payload


def _parse_kickoff(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LONDON)


def _date_label(scheduled: str | None) -> str:
    dt = _parse_kickoff(scheduled)
    if not dt:
        return ""
    return dt.strftime("%a %-d %b").upper()


def _opponent_name(match: dict[str, Any]) -> str:
    opponent = match.get("opponent") or {}
    name = str(opponent.get("name") or "").strip()
    name = re.sub(r"^(FC|AFC)\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+FC$", "", name, flags=re.IGNORECASE)
    return name or "TBC"


def _badge_url(match: dict[str, Any]) -> str | None:
    opponent = match.get("opponent") or {}
    return opponent.get("badgeUrl") or opponent.get("imageUrl")


def _result_stats(match: dict[str, Any]) -> dict[str, Any]:
    outcome = match.get("outcome")
    home_score = (match.get("home") or {}).get("score")
    away_score = (match.get("away") or {}).get("score")
    is_home = bool(match.get("isHome"))
    if home_score is None or away_score is None or outcome is None:
        return {
            "played": False,
            "points": 0,
            "goals": 0,
            "goalsAgainst": 0,
            "cleanSheet": False,
        }
    gf = int(home_score if is_home else away_score)
    ga = int(away_score if is_home else home_score)
    points = 3 if outcome == "win" else 1 if outcome == "draw" else 0
    return {
        "played": True,
        "points": points,
        "goals": gf,
        "goalsAgainst": ga,
        "cleanSheet": ga == 0,
    }


def _chunk_matches(matches: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = list(matches)
    blocks: list[list[dict[str, Any]]] = []
    for index in range(BLOCK_COUNT):
        if index < BLOCK_COUNT - 1:
            chunk = remaining[:GAMES_PER_BLOCK]
            remaining = remaining[GAMES_PER_BLOCK:]
        else:
            chunk = remaining
        blocks.append(chunk)
    return blocks


def _games_title(block_index: int, fixtures: list[dict[str, Any]]) -> str:
    copy = BLOCK_COPY[block_index]
    numbers = [row.get("seasonNumber") for row in fixtures if row.get("seasonNumber")]
    if not numbers or block_index == 0:
        return copy["title"]
    first, last = min(numbers), max(numbers)
    scheduled = len(numbers)
    if scheduled < GAMES_PER_BLOCK and block_index < BLOCK_COUNT - 1:
        return copy["title"]
    if first == last:
        return f"GAME {first}"
    return f"GAMES {first}–{last}"


def _serialize_fixture(
    match: dict[str, Any] | None,
    *,
    slot: int,
    season_number: int | None,
    kpis: dict[str, Any] | None,
) -> dict[str, Any]:
    if not match:
        return {
            "slot": slot,
            "seasonNumber": season_number,
            "matchId": None,
            "dateLabel": "",
            "scheduledDate": None,
            "isHome": None,
            "opponentName": "FIXTURE TBC",
            "opponentInitials": "?",
            "badgeUrl": None,
            "outcome": None,
            "scoreLabel": None,
            "available": False,
            "played": False,
            "stats": {
                "played": False,
                "points": 0,
                "goals": 0,
                "goalsAgainst": 0,
                "cleanSheet": False,
                **_empty_kpi_stats(),
            },
        }

    result = _result_stats(match)
    opponent = match.get("opponent") or {}
    stats = {
        **result,
        **(kpis if kpis else _empty_kpi_stats()),
    }
    return {
        "slot": slot,
        "seasonNumber": season_number,
        "matchId": match.get("matchId"),
        "dateLabel": _date_label(match.get("scheduledDate")),
        "scheduledDate": match.get("scheduledDate"),
        "isHome": bool(match.get("isHome")),
        "opponentName": _opponent_name(match),
        "opponentInitials": opponent.get("initials") or "?",
        "badgeUrl": _badge_url(match),
        "outcome": match.get("outcome"),
        "scoreLabel": match.get("scoreLabel"),
        "available": bool(match.get("available")),
        "played": result["played"],
        "stats": stats,
    }


def _sum_optional(values: list[float | int | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return sum(present)


def _aggregate_stats(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    played = [row for row in fixtures if row.get("played")]
    duel_won = _sum_optional([(row.get("stats") or {}).get("duelWon") for row in played])
    duel_total = _sum_optional([(row.get("stats") or {}).get("duelTotal") for row in played])
    duel_rate = (
        round((duel_won / duel_total) * 100, 1)
        if duel_won is not None and duel_total and duel_total > 0
        else None
    )
    xg = _sum_optional([(row.get("stats") or {}).get("xg") for row in played])
    return {
        "played": len(played),
        "points": sum(int((row.get("stats") or {}).get("points") or 0) for row in played),
        "goals": sum(int((row.get("stats") or {}).get("goals") or 0) for row in played),
        "goalsAgainst": sum(int((row.get("stats") or {}).get("goalsAgainst") or 0) for row in played),
        "cleanSheets": sum(
            1 for row in played if (row.get("stats") or {}).get("cleanSheet")
        ),
        "defendersBypassed": (
            round(_sum_optional([(row.get("stats") or {}).get("defendersBypassed") for row in played]) or 0, 1)
            if any((row.get("stats") or {}).get("defendersBypassed") is not None for row in played)
            else None
        ),
        "offensiveInterventions": (
            int(round(_sum_optional([(row.get("stats") or {}).get("offensiveInterventions") for row in played]) or 0))
            if any((row.get("stats") or {}).get("offensiveInterventions") is not None for row in played)
            else None
        ),
        "duelWon": int(round(duel_won)) if duel_won is not None else None,
        "duelTotal": int(round(duel_total)) if duel_total is not None else None,
        "duelRate": duel_rate,
        "ballWinsFromOppDefenders": (
            int(round(_sum_optional([(row.get("stats") or {}).get("ballWinsFromOppDefenders") for row in played]) or 0))
            if any((row.get("stats") or {}).get("ballWinsFromOppDefenders") is not None for row in played)
            else None
        ),
        "xg": round(xg, 2) if xg is not None else None,
        "units": _aggregate_units(played),
    }


def _aggregate_units(played: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not played:
        return _empty_units()
    totals = {
        unit: {
            "defendersBypassed": 0.0,
            "duelWon": 0.0,
            "duelTotal": 0.0,
            "seenBypass": False,
            "seenDuel": False,
        }
        for unit in UNITS
    }
    for row in played:
        units = (row.get("stats") or {}).get("units") or {}
        for unit in UNITS:
            data = units.get(unit) or {}
            if data.get("defendersBypassed") is not None:
                totals[unit]["defendersBypassed"] += float(data["defendersBypassed"])
                totals[unit]["seenBypass"] = True
            if data.get("duelWon") is not None or data.get("duelTotal") is not None:
                totals[unit]["duelWon"] += float(data.get("duelWon") or 0)
                totals[unit]["duelTotal"] += float(data.get("duelTotal") or 0)
                totals[unit]["seenDuel"] = True
    result: dict[str, dict[str, Any]] = {}
    for unit in UNITS:
        bucket = totals[unit]
        if not bucket["seenBypass"] and not bucket["seenDuel"]:
            result[unit] = _empty_unit_row()
            continue
        won = float(bucket["duelWon"])
        total = float(bucket["duelTotal"])
        result[unit] = {
            "defendersBypassed": (
                round(bucket["defendersBypassed"], 1) if bucket["seenBypass"] else None
            ),
            "duelWon": round(won, 1) if bucket["seenDuel"] else None,
            "duelTotal": round(total, 1) if bucket["seenDuel"] else None,
            "duelRate": (
                round((won / total) * 100, 1) if bucket["seenDuel"] and total > 0 else None
            ),
        }
    return result


def _target_payload(block_id: int, saved: dict[str, Any]) -> dict[str, Any]:
    row = (saved.get("blocks") or {}).get(str(block_id)) or {}
    medal = str(row.get("medal") or "silver").lower()
    if medal not in MEDAL_DEFAULTS:
        medal = "silver"
    defaults = MEDAL_DEFAULTS[medal]
    return {
        "medal": medal,
        "label": defaults["label"],
        "shortLabel": defaults["shortLabel"],
        "outcome": defaults["outcome"],
        "points": int(row.get("points", defaults["points"])),
        "cleanSheets": int(row.get("cleanSheets", defaults["cleanSheets"])),
        "defaults": {
            key: {
                "points": int(spec["points"]),
                "cleanSheets": int(spec["cleanSheets"]),
                "label": spec["label"],
            }
            for key, spec in MEDAL_DEFAULTS.items()
        },
    }


def _load_demo_fixture(*, force_refresh: bool = False) -> dict[str, Any] | None:
    """Wolves EFL Cup — preview the 2-page report before League Two starts."""
    try:
        matches = build_season_matches(
            DEMO_CUP_ITERATION_ID,
            PORT_VALE_SQUAD_ID,
            include_upcoming=True,
            competition_label="EFL Cup",
            competition_short="Cup",
            season_label=BLOCKS_SEASON_LABEL,
        )
    except Exception:  # noqa: BLE001
        return None
    match = next(
        (row for row in matches if int(row.get("matchId") or 0) == DEMO_MATCH_ID),
        None,
    )
    if match is None:
        match = next((row for row in matches if row.get("outcome")), None)
    if match is None:
        return None
    kpis = _load_match_kpis([match], force_refresh=force_refresh).get(int(match["matchId"]))
    if not kpis or not kpis.get("players"):
        return None
    fixture = _serialize_fixture(match, slot=0, season_number=None, kpis=kpis)
    fixture["demo"] = True
    fixture["competitionShort"] = "CUP"
    fixture["competitionLabel"] = "EFL Cup"
    return fixture


def build_blocks_analysis_payload(*, force_refresh: bool = False) -> dict[str, Any]:
    cache_key = "default"
    now = time.time()
    if not force_refresh:
        cached = _payload_cache.get(cache_key)
        if cached and now - cached[0] < PAYLOAD_CACHE_TTL:
            return cached[1]

    matches = build_season_matches(
        BLOCKS_ITERATION_ID,
        PORT_VALE_SQUAD_ID,
        include_upcoming=True,
        competition_label=LEAGUE_LABEL,
        competition_short=LEAGUE_SHORT,
        season_label=BLOCKS_SEASON_LABEL,
    )
    kpi_by_match = _load_match_kpis(matches, force_refresh=force_refresh)
    benchmarks = build_block_benchmarks(BLOCKS_ITERATION_ID, force_refresh=force_refresh)
    try:
        benchmarks["units"] = build_unit_benchmarks(
            kpi_by_match, force_refresh=force_refresh
        )
    except Exception:  # noqa: BLE001
        benchmarks["units"] = _empty_unit_benchmarks()
    saved = _load_targets()
    chunks = _chunk_matches(matches)

    blocks: list[dict[str, Any]] = []
    season_cursor = 0
    for index, chunk in enumerate(chunks):
        block_id = index + 1
        copy = BLOCK_COPY[index]
        fixtures: list[dict[str, Any]] = []
        slot_count = max(GAMES_PER_BLOCK, len(chunk))
        for slot in range(1, slot_count + 1):
            match = chunk[slot - 1] if slot - 1 < len(chunk) else None
            if match:
                season_cursor += 1
                season_number = season_cursor
                match_id = int(match.get("matchId") or 0)
                kpis = kpi_by_match.get(match_id)
            else:
                season_number = None
                kpis = None
            fixtures.append(
                _serialize_fixture(
                    match,
                    slot=slot,
                    season_number=season_number,
                    kpis=kpis,
                )
            )
        totals = _aggregate_stats(fixtures)
        target = _target_payload(block_id, saved)
        played = int(totals["played"])
        blocks.append(
            {
                "id": block_id,
                "title": _games_title(index, fixtures),
                "heading": copy["heading"],
                "footer": copy["footer"],
                "target": target,
                "fixtures": fixtures,
                "demoFixtures": [],
                "totals": totals,
                "status": (
                    "complete"
                    if played >= len([row for row in fixtures if row.get("matchId")])
                    and any(row.get("matchId") for row in fixtures)
                    else "live"
                    if played
                    else "upcoming"
                ),
                "pointsLabel": f"{totals['points']} / {target['points']}",
            }
        )

    current_block_id = 1
    for block in blocks:
        if block["status"] in {"live", "upcoming"}:
            current_block_id = int(block["id"])
            break
        current_block_id = int(block["id"])

    demo = _load_demo_fixture(force_refresh=force_refresh)
    if demo:
        for block in blocks:
            if int(block["id"]) == current_block_id:
                block["demoFixtures"] = [demo]
                break

    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": BLOCKS_SEASON_LABEL,
        "competition": LEAGUE_LABEL,
        "iterationId": BLOCKS_ITERATION_ID,
        "focusSquadId": PORT_VALE_SQUAD_ID,
        "currentBlockId": current_block_id,
        "medals": [
            {
                "id": key,
                "label": spec["label"],
                "shortLabel": spec["shortLabel"],
                "points": spec["points"],
                "cleanSheets": spec["cleanSheets"],
            }
            for key, spec in MEDAL_DEFAULTS.items()
        ],
        "blocks": blocks,
        "benchmarks": benchmarks,
        "matchCount": len(matches),
        "playedCount": sum(1 for match in matches if match.get("outcome")),
    }
    _payload_cache[cache_key] = (now, payload)
    return payload


def register_blocks_analysis_routes(app: FastAPI) -> None:
    @app.get("/blocks-analysis", response_class=HTMLResponse)
    def blocks_analysis_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "blocks-analysis.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Blocks Analysis UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/blocks-analysis")
    def blocks_analysis_payload_route(
        refresh: bool = Query(False),
    ) -> JSONResponse:
        try:
            payload = build_blocks_analysis_payload(force_refresh=refresh)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Blocks Analysis failed to load fixtures: {exc}",
            ) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.put("/api/blocks-analysis/targets")
    def blocks_analysis_save_target(body: BlockTargetUpdate) -> dict[str, Any]:
        medal = body.medal.strip().lower()
        if medal not in MEDAL_DEFAULTS:
            raise HTTPException(status_code=400, detail="medal must be gold, silver, or bronze")
        store = _load_targets()
        store["blocks"][str(body.block_id)] = {
            "medal": medal,
            "points": body.points,
            "cleanSheets": body.clean_sheets,
        }
        saved = _save_targets(store)
        return {"ok": True, "targets": saved}

    @app.post("/api/blocks-analysis/export-pdf")
    def blocks_analysis_export_pdf(body: BlocksExportRequest) -> Response:
        from app.handout_export import build_a4_landscape_pdf
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pdf_bytes = build_a4_landscape_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = _safe_export_filename(
            body.filename or "port-vale-match-report.pdf"
        )
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
