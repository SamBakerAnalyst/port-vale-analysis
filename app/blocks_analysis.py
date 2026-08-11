"""League Two blocks of five — posters, editable Silver targets, live KPIs."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.paths import BLOCKS_ANALYSIS_DATA_DIR
from app.post_match.ball_progression import _top7_average
from app.post_match.config import PORT_VALE_SQUAD_ID
from app.post_match.duels import (
    KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS,
    KPI_LOST_AERIAL_DUELS,
    KPI_LOST_GROUND_DUELS,
    KPI_WON_AERIAL_DUELS,
    KPI_WON_GROUND_DUELS,
    OFFENSIVE_INTERVENTION_ACTION_KPIS,
)
from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.report import KPI_BYPASSED_DEFENDERS_RAW, _flatten_squad_kpis
from app.post_match.season_matches import build_season_matches
from app.scouting import SCOUTING_DIR

# League Two 26/27. Keep these here — post-match DEFAULT_ITERATION_ID may still
# point at a previous season on some deploys.
BLOCKS_ITERATION_ID = 2120
BLOCKS_SEASON_LABEL = "26/27"
PREVIOUS_LEAGUE_TWO_ITERATION_ID = 1464  # 25/26 — top-7 requirement until 26/27 has games

LONDON = ZoneInfo("Europe/London")
BLOCK_COUNT = 9
GAMES_PER_BLOCK = 5
KPI_SHOT_XG = 82
MATCH_KPI_CACHE_TTL = 6 * 3600
PAYLOAD_CACHE_TTL = 45
BENCHMARK_CACHE_TTL = 600
LEAGUE_LABEL = "League Two"
LEAGUE_SHORT = "LG2"

DATA_DIR = BLOCKS_ANALYSIS_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
TARGETS_PATH = DATA_DIR / "targets.json"
KPI_CACHE_PATH = DATA_DIR / "match-kpis.json"

_store_lock = threading.Lock()
_payload_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_benchmark_cache: tuple[float, dict[str, Any]] | None = None

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
    offensive = sum(_kpi_value(kpis, kpi_id) for kpi_id in OFFENSIVE_INTERVENTION_ACTION_KPIS)
    return {
        "defendersBypassed": _kpi_value(kpis, KPI_BYPASSED_DEFENDERS_RAW),
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
    offensive = sum(
        int(round(_kpi_value(kpis, kpi_id))) for kpi_id in OFFENSIVE_INTERVENTION_ACTION_KPIS
    )
    return {
        "defendersBypassed": int(round(_kpi_value(kpis, KPI_BYPASSED_DEFENDERS_RAW))),
        "offensiveInterventions": offensive,
        "duelWon": int(round(won)),
        "duelTotal": int(round(duel_total)),
        "duelRate": duel_rate,
        "ballWinsFromOppDefenders": int(
            round(_kpi_value(kpis, KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS))
        ),
        "xg": round(_kpi_value(kpis, KPI_SHOT_XG), 2),
    }


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _benchmark_entry(
    per_squad: dict[int, float],
    *,
    higher_better: bool,
    digits: int,
    rate: bool = False,
) -> dict[str, Any]:
    team = per_squad.get(PORT_VALE_SQUAD_ID)
    top7 = _top7_average(per_squad, higher_is_better=higher_better)
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

    def column(key: str) -> dict[int, float]:
        values: dict[int, float] = {}
        for squad_id, row in extracted.items():
            value = row.get(key)
            if value is None:
                continue
            values[squad_id] = float(value)
        return values

    return {
        "goalsAgainst": _benchmark_entry(
            {sid: row["goalsAgainst"] for sid, row in defence.items()},
            higher_better=False,
            digits=1,
        ),
        "cleanSheets": _benchmark_entry(
            {sid: row["cleanSheets"] for sid, row in defence.items()},
            higher_better=True,
            digits=1,
        ),
        "defendersBypassed": _benchmark_entry(
            column("defendersBypassed"), higher_better=True, digits=1
        ),
        "offensiveInterventions": _benchmark_entry(
            column("offensiveInterventions"), higher_better=True, digits=1
        ),
        "duelRate": _benchmark_entry(
            column("duelRate"), higher_better=True, digits=1, rate=True
        ),
        "ballWinsFromOppDefenders": _benchmark_entry(
            column("ballWinsFromOppDefenders"), higher_better=True, digits=1
        ),
        "xg": _benchmark_entry(column("xg"), higher_better=True, digits=2),
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
    if all(row.get("top7") is None for row in payload.values()):
        older = _benchmarks_for_iteration(PREVIOUS_LEAGUE_TWO_ITERATION_ID)
        for key, row in payload.items():
            if row.get("top7") is None and older.get(key, {}).get("top7") is not None:
                row["top7"] = older[key]["top7"]
                row["top7From"] = "previous"

    _benchmark_cache = (now, payload)
    return payload


def _fetch_squad_kpis(match_id: int) -> dict[int, float]:
    raw = impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))
    lookup = _flatten_squad_kpis(raw["data"])
    return lookup.get(PORT_VALE_SQUAD_ID) or {}


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
            and cached.get("fingerprint") == fingerprint
            and now - float(cached.get("fetchedAt") or 0) < MATCH_KPI_CACHE_TTL
            and cached.get("stats")
        ):
            result[match_id] = cached["stats"]
            continue
        to_fetch.append(match)

    if to_fetch:
        workers = min(8, len(to_fetch))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch_squad_kpis, int(match["matchId"])): match
                for match in to_fetch
            }
            for future in as_completed(futures):
                match = futures[future]
                match_id = int(match["matchId"])
                try:
                    kpis = future.result()
                    stats = _extract_match_kpis(kpis) if kpis else _empty_kpi_stats()
                except Exception:  # noqa: BLE001 — keep the poster live if one match fails
                    stats = _empty_kpi_stats()
                result[match_id] = stats
                disk[str(match_id)] = {
                    "fingerprint": _score_fingerprint(match),
                    "fetchedAt": now,
                    "stats": stats,
                }
        _save_kpi_disk_cache(disk)

    return result


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
            int(round(_sum_optional([(row.get("stats") or {}).get("defendersBypassed") for row in played]) or 0))
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
    }


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
