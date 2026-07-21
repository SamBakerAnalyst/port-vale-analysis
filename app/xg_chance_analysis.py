from __future__ import annotations

import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.pre_match import (
    _completed_opponent_fixtures,
    _is_port_vale,
    _match_day_index,
    _match_day_label,
    _match_is_complete,
    _resolve_port_vale_squad_id,
    _squads_map,
    _unwrap_items,
)
from app.scouting import SCOUTING_DIR
from app.squad_review import (
    _available_port_vale_seasons,
    _default_port_vale_season,
    _resolve_port_vale_iteration,
)

SHOT_XG_KPI_ID = 82

_STOPPAGE_RE = re.compile(r"\(\+(\d+):(\d+(?:\.\d+)?)\)")
_CLOCK_RE = re.compile(r"(\d+):(\d+(?:\.\d+)?)")

CHANCE_BUCKETS: tuple[dict[str, Any], ...] = (
    {"id": "excellent", "label": "Excellent", "min": 0.35, "max": None, "color": "#166534"},
    {"id": "very_good", "label": "Very Good", "min": 0.19, "max": 0.35, "color": "#22c55e"},
    {"id": "ok", "label": "OK", "min": 0.09, "max": 0.19, "color": "#facc15"},
    {"id": "poor", "label": "Poor", "min": 0.04, "max": 0.09, "color": "#f97316"},
    {"id": "very_poor", "label": "Very Poor", "min": None, "max": 0.04, "color": "#ef4444"},
)

GAME_STATE_LABELS = {
    "winning": "WINNING",
    "drawing": "DRAWING",
    "losing": "LOSING",
}

RED_CARD_ACTIONS = frozenset({"RED_CARD", "SECOND_YELLOW_CARD", "SECOND_YELLOW"})

ALLOWED_SEASONS = ("26/27", "25/26")

_match_events_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_ekpi_cache: dict[int, tuple[float, dict[int, float]]] = {}
_player_directory_cache: dict[int, tuple[float, dict[int, str]]] = {}


def _impect():
    from app import main as impect_main

    return impect_main


def _parse_impect_minute(game_time: dict[str, Any]) -> float:
    gt_str = str(game_time.get("gameTime") or "")
    stoppage = _STOPPAGE_RE.search(gt_str)
    if stoppage:
        base_minute = 90 if gt_str.startswith("90:") else 45
        extra = int(stoppage.group(1)) + float(stoppage.group(2)) / 60.0
        return base_minute + extra

    clock = _CLOCK_RE.match(gt_str)
    if clock:
        return int(clock.group(1)) + float(clock.group(2)) / 60.0

    seconds = float(game_time.get("gameTimeInSec") or 0)
    if seconds >= 10000:
        return (seconds - 10000) / 60.0 + 45.0
    return seconds / 60.0


def _is_first_half(game_time: dict[str, Any]) -> bool:
    gt_str = str(game_time.get("gameTime") or "")
    if "(+" in gt_str and gt_str.startswith("45:"):
        return True
    seconds = float(game_time.get("gameTimeInSec") or 0)
    return seconds < 10000


def _event_seconds(event: dict[str, Any]) -> float:
    game_time = event.get("gameTime") or {}
    try:
        return float(game_time.get("gameTimeInSec") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    cached = _match_events_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/matches/{match_id}/events"
    )["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    events = [item for item in (raw if isinstance(raw, list) else _unwrap_items(raw)) if isinstance(item, dict)]
    events.sort(key=lambda row: (_event_seconds(row), int(row.get("id") or 0)))
    _match_events_cache[match_id] = (now, events)
    return events


def _fetch_shot_xg_by_event(match_id: int) -> dict[int, float]:
    cached = _ekpi_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/matches/{match_id}/event-kpis"
    )["data"]
    rows = raw.get("data") if isinstance(raw, dict) else raw
    xg_by_event: dict[int, float] = defaultdict(float)
    if isinstance(rows, list):
        for row in rows:
            if int(row.get("kpiId") or -1) != SHOT_XG_KPI_ID:
                continue
            event_id = int(row.get("eventId") or 0)
            if event_id:
                xg_by_event[event_id] += float(row.get("value") or 0)

    _ekpi_cache[match_id] = (now, dict(xg_by_event))
    return dict(xg_by_event)


def _classify_chance(xg: float) -> dict[str, Any]:
    for bucket in CHANCE_BUCKETS:
        min_val = bucket.get("min")
        max_val = bucket.get("max")
        if min_val is not None and xg < min_val:
            continue
        if max_val is not None and xg >= max_val:
            continue
        return {
            "id": bucket["id"],
            "label": bucket["label"],
            "color": bucket["color"],
        }
    return {
        "id": CHANCE_BUCKETS[-1]["id"],
        "label": CHANCE_BUCKETS[-1]["label"],
        "color": CHANCE_BUCKETS[-1]["color"],
    }


def _shot_outcome(event: dict[str, Any]) -> str:
    if str(event.get("result") or "").upper() == "SUCCESS":
        return "goal"
    end = event.get("end") or {}
    zone = str(end.get("packingZone") or "").upper()
    position = str(end.get("pitchPosition") or "").upper()
    coords = end.get("adjCoordinates") or end.get("coordinates") or {}
    try:
        end_x = float(coords.get("x") or 0)
        end_y = abs(float(coords.get("y") or 0))
    except (TypeError, ValueError):
        end_x = 0.0
        end_y = 0.0
    if zone in {"OPP_GKC", "OPP_CBC"}:
        return "on_target"
    if position == "OPPONENT_BOX" and end_x >= 49.5 and end_y <= 4.0:
        return "on_target"
    return "miss"


def _in_box(event: dict[str, Any]) -> bool:
    start = event.get("start") or {}
    position = str(start.get("pitchPosition") or "").upper()
    if position == "OPPONENT_BOX":
        return True
    zone = str(start.get("packingZone") or "").upper()
    return zone in {"OPP_CBC", "OPP_GKC"}


def _game_state_for_team(team_goals: int, opponent_goals: int) -> str:
    if team_goals > opponent_goals:
        return "winning"
    if team_goals < opponent_goals:
        return "losing"
    return "drawing"


def _manpower_label(vale_on: int, opp_on: int) -> str:
    return f"{vale_on} v {opp_on}"


def _player_name(event: dict[str, Any], player_names: dict[int, str]) -> str:
    player = event.get("player") or {}
    player_id = int(player.get("id") or 0)
    if player_id and player_names.get(player_id):
        return player_names[player_id]
    fallback = str(player.get("commonname") or player.get("name") or "").strip()
    if fallback:
        return fallback
    return f"Player {player_id}" if player_id else "Unknown"


def _player_directory(iteration_id: int) -> dict[int, str]:
    now = time.time()
    cached = _player_directory_cache.get(iteration_id)
    if cached and now - cached[0] < 3600 and cached[1]:
        return cached[1]

    from app.pre_match import _player_names_map

    impect = _impect()
    players = _unwrap_items(
        impect._impect_get(impect._players_path(iteration_id))["data"]
    )
    mapping = _player_names_map(players)
    if not mapping:
        from app.fixture_planner import _player_names_for_iteration

        mapping = _player_names_for_iteration(iteration_id)

    _player_directory_cache[iteration_id] = (now, mapping)
    return mapping


def _format_kickoff(scheduled: str | None) -> str:
    if not scheduled:
        return ""
    try:
        normalized = str(scheduled).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt.strftime("%a %-d %b")
    except (TypeError, ValueError):
        return str(scheduled)[:10]


def _empty_bucket_summary() -> dict[str, dict[str, Any]]:
    return {
        bucket["id"]: {
            "id": bucket["id"],
            "label": bucket["label"],
            "color": bucket["color"],
            "goals": 0,
            "count": 0,
            "cumulativeXg": 0.0,
        }
        for bucket in CHANCE_BUCKETS
    }


def _summarize_buckets(shots: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = _empty_bucket_summary()
    total_shots = 0
    total_xg = 0.0
    total_goals = 0

    for shot in shots:
        bucket_id = shot["chanceRating"]["id"]
        buckets[bucket_id]["count"] += 1
        buckets[bucket_id]["cumulativeXg"] += shot["xg"]
        if shot["outcome"] == "goal":
            buckets[bucket_id]["goals"] += 1
            total_goals += 1
        total_shots += 1
        total_xg += shot["xg"]

    rows = []
    for bucket in CHANCE_BUCKETS:
        row = buckets[bucket["id"]]
        count = row["count"]
        rows.append(
            {
                **row,
                "cumulativeXg": round(row["cumulativeXg"], 3),
                "pct": round((count / total_shots) * 100) if total_shots else 0,
            }
        )

    grouped = {
        "highQuality": {
            "label": "Excellent / Very Good",
            "count": sum(buckets[b["id"]]["count"] for b in CHANCE_BUCKETS[:2]),
            "goals": sum(buckets[b["id"]]["goals"] for b in CHANCE_BUCKETS[:2]),
            "cumulativeXg": round(
                sum(buckets[b["id"]]["cumulativeXg"] for b in CHANCE_BUCKETS[:2]), 3
            ),
        },
        "lowQuality": {
            "label": "Poor / Very Poor",
            "count": sum(buckets[b["id"]]["count"] for b in CHANCE_BUCKETS[3:]),
            "goals": sum(buckets[b["id"]]["goals"] for b in CHANCE_BUCKETS[3:]),
            "cumulativeXg": round(
                sum(buckets[b["id"]]["cumulativeXg"] for b in CHANCE_BUCKETS[3:]), 3
            ),
        },
    }

    return {
        "buckets": rows,
        "grouped": grouped,
        "totals": {
            "shots": total_shots,
            "goals": total_goals,
            "cumulativeXg": round(total_xg, 3),
        },
    }


def _summarize_game_states(shots: list[dict[str, Any]], *, vale_only: bool = True) -> list[dict[str, Any]]:
    filtered = [s for s in shots if (s["team"] == "vale") == vale_only] if vale_only else shots
    by_state: dict[str, dict[str, Any]] = {
        key: {"id": key, "label": GAME_STATE_LABELS[key], "shots": 0, "xg": 0.0, "goals": 0}
        for key in GAME_STATE_LABELS
    }
    for shot in filtered:
        state = shot.get("gameState") or "drawing"
        if state not in by_state:
            continue
        by_state[state]["shots"] += 1
        by_state[state]["xg"] += shot["xg"]
        if shot["outcome"] == "goal":
            by_state[state]["goals"] += 1

    return [
        {
            **row,
            "xg": round(row["xg"], 3),
        }
        for row in by_state.values()
    ]


def _summarize_players(shots: list[dict[str, Any]], *, vale_only: bool = True) -> list[dict[str, Any]]:
    filtered = [s for s in shots if s["team"] == "vale"] if vale_only else [s for s in shots if s["team"] == "opp"]
    players: dict[str, dict[str, Any]] = {}
    for shot in filtered:
        name = shot["playerName"]
        row = players.setdefault(
            name,
            {
                "playerName": name,
                "shots": 0,
                "xg": 0.0,
                "goals": 0,
                "highQualityShots": 0,
                "lowQualityShots": 0,
                "avgXg": 0.0,
                "chanceCounts": {
                    "excellent": 0,
                    "very_good": 0,
                    "ok": 0,
                    "poor": 0,
                    "very_poor": 0,
                },
            },
        )
        row["shots"] += 1
        row["xg"] += shot["xg"]
        if shot["outcome"] == "goal":
            row["goals"] += 1
        rating_id = shot["chanceRating"]["id"]
        if rating_id in row["chanceCounts"]:
            row["chanceCounts"][rating_id] += 1
        if rating_id in {"excellent", "very_good"}:
            row["highQualityShots"] += 1
        elif rating_id in {"poor", "very_poor"}:
            row["lowQualityShots"] += 1

    rows = sorted(players.values(), key=lambda r: (-r["xg"], -r["shots"], r["playerName"]))
    for row in rows:
        row["xg"] = round(row["xg"], 3)
        row["avgXg"] = round(row["xg"] / row["shots"], 3) if row["shots"] else 0.0
    return rows


def _summarize_periods(shots: list[dict[str, Any]]) -> dict[str, Any]:
    halves = {
        "first": {"label": "1st Half", "valeShots": 0, "valeXg": 0.0, "oppShots": 0, "oppXg": 0.0},
        "second": {"label": "2nd Half", "valeShots": 0, "valeXg": 0.0, "oppShots": 0, "oppXg": 0.0},
    }
    manpower = {
        "elevenEleven": {"label": "11 v 11", "valeShots": 0, "valeXg": 0.0, "oppShots": 0, "oppXg": 0.0},
        "valeDown": {"label": "10 v 11", "valeShots": 0, "valeXg": 0.0, "oppShots": 0, "oppXg": 0.0},
        "oppDown": {"label": "11 v 10", "valeShots": 0, "valeXg": 0.0, "oppShots": 0, "oppXg": 0.0},
    }

    for shot in shots:
        half_key = "first" if shot["half"] == "first" else "second"
        team_key = "vale" if shot["team"] == "vale" else "opp"
        halves[half_key][f"{team_key}Shots"] += 1
        halves[half_key][f"{team_key}Xg"] += shot["xg"]

        mp = shot.get("manpower") or "11 v 11"
        if mp == "11 v 11":
            bucket = manpower["elevenEleven"]
        elif shot["team"] == "vale" and mp.startswith("10"):
            bucket = manpower["valeDown"]
        elif shot["team"] == "opp" and mp.endswith("10"):
            bucket = manpower["oppDown"]
        else:
            bucket = manpower["elevenEleven"]
        team_key = "vale" if shot["team"] == "vale" else "opp"
        bucket[f"{team_key}Shots"] += 1
        bucket[f"{team_key}Xg"] += shot["xg"]

    for group in (halves, manpower):
        for row in group.values():
            row["valeXg"] = round(row["valeXg"], 3)
            row["oppXg"] = round(row["oppXg"], 3)
    return {"halves": list(halves.values()), "manpower": list(manpower.values())}


def _build_match_shots(
    match_id: int,
    iteration_id: int,
    port_vale_id: int,
    home_id: int,
    away_id: int,
    player_names: dict[int, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _fetch_match_events(match_id)
    xg_by_event = _fetch_shot_xg_by_event(match_id)

    home_goals = 0
    away_goals = 0
    vale_dismissals = 0
    opp_dismissals = 0
    dismissals: list[dict[str, Any]] = []

    shots: list[dict[str, Any]] = []
    vale_shot_num = 0
    opp_shot_num = 0
    vale_cum_xg = 0.0
    opp_cum_xg = 0.0

    for event in events:
        action = str(event.get("action") or event.get("actionType") or "").upper()
        squad_id = int(event.get("squadId") or 0)
        seconds = _event_seconds(event)
        game_time = event.get("gameTime") or {}
        minute = _parse_impect_minute(game_time) if isinstance(game_time, dict) else 0.0
        is_first_half = _is_first_half(game_time) if isinstance(game_time, dict) else minute < 45

        if action in RED_CARD_ACTIONS:
            player = event.get("player") or {}
            player_id = int(player.get("id") or 0)
            name = _player_name(event, player_names)
            if squad_id == port_vale_id:
                vale_dismissals += 1
            elif squad_id in {home_id, away_id} and squad_id != port_vale_id:
                opp_dismissals += 1
            dismissals.append(
                {
                    "playerName": name,
                    "playerId": player_id or None,
                    "team": "vale" if squad_id == port_vale_id else "opp",
                    "minute": round(minute, 1),
                    "seconds": seconds,
                }
            )
            continue

        if event.get("actionType") != "SHOT":
            if str(event.get("result") or "").upper() == "SUCCESS" and action in {"GOAL", "SHOT"}:
                if squad_id == home_id:
                    home_goals += 1
                elif squad_id == away_id:
                    away_goals += 1
            continue

        event_id = int(event.get("id") or 0)
        xg = round(xg_by_event.get(event_id, 0.0), 3)
        is_vale = squad_id == port_vale_id

        if port_vale_id == home_id:
            vale_goals_before = home_goals
            opp_goals_before = away_goals
        else:
            vale_goals_before = away_goals
            opp_goals_before = home_goals

        game_state = _game_state_for_team(vale_goals_before, opp_goals_before)
        vale_on = max(0, 11 - vale_dismissals)
        opp_on = max(0, 11 - opp_dismissals)

        if is_vale:
            vale_shot_num += 1
            vale_cum_xg += xg
            shot_number = vale_shot_num
            cumulative_xg = round(vale_cum_xg, 3)
        else:
            opp_shot_num += 1
            opp_cum_xg += xg
            shot_number = opp_shot_num
            cumulative_xg = round(opp_cum_xg, 3)

        outcome = _shot_outcome(event)
        if outcome == "goal":
            if squad_id == home_id:
                home_goals += 1
            elif squad_id == away_id:
                away_goals += 1

        minute_int = int(minute)
        second_int = int(round((minute - minute_int) * 60))

        shots.append(
            {
                "eventId": event_id,
                "team": "vale" if is_vale else "opp",
                "playerName": _player_name(event, player_names),
                "minute": minute_int,
                "second": second_int,
                "minuteDisplay": f"{minute_int}:{str(second_int).zfill(2)}",
                "xg": xg,
                "xgDisplay": f"{xg:.3f}",
                "chanceRating": _classify_chance(xg),
                "inBox": _in_box(event),
                "inBoxLabel": "IN" if _in_box(event) else "OUT",
                "onTarget": outcome in {"goal", "on_target"},
                "onTargetLabel": "YES" if outcome in {"goal", "on_target"} else "NO",
                "outcome": outcome,
                "outcomeLabel": "GOAL" if outcome == "goal" else "MISS",
                "gameState": game_state,
                "gameStateLabel": GAME_STATE_LABELS[game_state],
                "half": "first" if is_first_half else "second",
                "halfLabel": "1ST" if is_first_half else "2ND",
                "shotNumber": shot_number,
                "cumulativeXg": cumulative_xg,
                "manpower": _manpower_label(vale_on, opp_on),
                "seconds": seconds,
            }
        )

    return shots, dismissals


def _match_meta(match: dict[str, Any], port_vale_id: int, squads: dict[int, dict[str, Any]]) -> dict[str, Any]:
    match_id = int(match["id"])
    home_id = int(match.get("homeSquadId") or -1)
    away_id = int(match.get("awaySquadId") or -1)
    is_home = port_vale_id == home_id
    opponent_id = away_id if is_home else home_id
    opponent = squads.get(opponent_id, {})
    goals = match.get("goals") or {}
    home_ft = (goals.get("home") or {}).get("fullTime")
    away_ft = (goals.get("away") or {}).get("fullTime")
    if is_home:
        vale_goals, opp_goals = home_ft, away_ft
    else:
        vale_goals, opp_goals = away_ft, home_ft
    score = f"{vale_goals}-{opp_goals}" if vale_goals is not None and opp_goals is not None else ""

    return {
        "matchId": match_id,
        "matchDay": _match_day_label(match),
        "dateLabel": _format_kickoff(match.get("scheduledDate")),
        "scheduledDate": match.get("scheduledDate"),
        "isHome": is_home,
        "venue": "Home" if is_home else "Away",
        "opponent": {
            "id": opponent_id,
            "name": str(opponent.get("name") or f"Squad {opponent_id}"),
            "imageUrl": opponent.get("imageUrl"),
        },
        "score": score,
        "valeGoals": int(vale_goals) if vale_goals is not None else None,
        "oppGoals": int(opp_goals) if opp_goals is not None else None,
        "homeSquadId": home_id,
        "awaySquadId": away_id,
    }


def build_xg_chance_fixtures(season: str | None) -> list[dict[str, Any]]:
    iteration = _resolve_port_vale_iteration(season)
    iteration_id = int(iteration["id"])
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    if port_vale_id is None:
        return []

    squads = _squads_map(iteration_id)
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    fixtures = _completed_opponent_fixtures(iteration_id, port_vale_id, squads, matches)
    matches_by_id = {int(m["id"]): m for m in matches if m.get("id") is not None}
    rows = []
    for row in fixtures:
        match_id = int(row["match_id"])
        if match_id in matches_by_id:
            match_day = _match_day_label(matches_by_id[match_id])
        else:
            match_day = int(row.get("match_day") or 0) + 1
        rows.append(
            {
                "matchId": match_id,
                "matchDay": match_day,
                "dateLabel": _format_kickoff(row.get("scheduled_date")),
                "kickoffLabel": row.get("kickoff_label"),
                "isHome": row.get("is_home"),
                "venue": "Home" if row.get("is_home") else "Away",
                "opponent": row.get("opponent"),
                "score": row.get("kickoff_label") if "-" in str(row.get("kickoff_label") or "") else "",
            }
        )
    return rows


def _default_fixture_match_id(fixtures: list[dict[str, Any]]) -> int | None:
    if not fixtures:
        return None
    return int(fixtures[-1]["matchId"])


def _completed_vale_match_ids(
    matches: list[dict[str, Any]],
    matches_by_id: dict[int, dict[str, Any]],
    port_vale_id: int,
) -> list[int]:
    selected_ids = [
        int(m["id"])
        for m in matches
        if m.get("id") is not None
        and _match_is_complete(m)
        and port_vale_id in {int(m.get("homeSquadId") or -1), int(m.get("awaySquadId") or -1)}
    ]
    selected_ids.sort(key=lambda mid: _match_day_index(matches_by_id[mid]))
    return selected_ids


def _bucket_share(summary: dict[str, Any], bucket_ids: set[str]) -> float:
    totals = summary.get("totals") or {}
    shots = float(totals.get("shots") or 0)
    if shots <= 0:
        return 0.0
    count = sum(
        float(row.get("count") or 0)
        for row in (summary.get("buckets") or [])
        if row.get("id") in bucket_ids
    )
    return round((count / shots) * 100, 1)


def _average_metric(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _trend_direction(recent: float | None, earlier: float | None, *, higher_better: bool = True) -> str:
    if recent is None or earlier is None:
        return "flat"
    delta = recent - earlier
    if abs(delta) < 0.05:
        return "flat"
    improving = delta > 0 if higher_better else delta < 0
    return "up" if improving else "down"


def _build_match_trend_row(summary: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    vale_shots = [s for s in shots if s["team"] == "vale"]
    opp_shots = [s for s in shots if s["team"] == "opp"]
    vale_xg = _summarize_buckets(vale_shots)
    opp_xg = _summarize_buckets(opp_shots)
    return {
        "matchId": summary.get("matchId"),
        "matchDay": summary.get("matchDay"),
        "dateLabel": summary.get("dateLabel"),
        "opponent": summary.get("opponent"),
        "venue": summary.get("venue"),
        "score": summary.get("score"),
        "valeShots": summary.get("valeShots", 0),
        "oppShots": summary.get("oppShots", 0),
        "valeXg": summary.get("valeXg", 0.0),
        "oppXg": summary.get("oppXg", 0.0),
        "valeGoals": summary.get("valeGoals"),
        "oppGoals": summary.get("oppGoals"),
        "valeHighQualityPct": _bucket_share(vale_xg, {"excellent", "very_good"}),
        "valeLowQualityPct": _bucket_share(vale_xg, {"poor", "very_poor"}),
        "oppHighQualityPct": _bucket_share(opp_xg, {"excellent", "very_good"}),
        "xgDiff": round(float(summary.get("valeXg") or 0) - float(summary.get("oppXg") or 0), 3),
    }


def _build_averages(match_rows: list[dict[str, Any]]) -> dict[str, Any]:
    games = len(match_rows) or 1
    return {
        "games": len(match_rows),
        "valeShots": _average_metric([float(r.get("valeShots") or 0) for r in match_rows]),
        "oppShots": _average_metric([float(r.get("oppShots") or 0) for r in match_rows]),
        "valeXg": _average_metric([float(r.get("valeXg") or 0) for r in match_rows]),
        "oppXg": _average_metric([float(r.get("oppXg") or 0) for r in match_rows]),
        "valeHighQualityPct": _average_metric(
            [float(r.get("valeHighQualityPct") or 0) for r in match_rows]
        ),
        "valeLowQualityPct": _average_metric(
            [float(r.get("valeLowQualityPct") or 0) for r in match_rows]
        ),
        "xgDiff": _average_metric([float(r.get("xgDiff") or 0) for r in match_rows]),
        "perGameNote": f"Averages across {len(match_rows)} games" if match_rows else "No games",
        "gamesDivisor": games,
    }


def _build_trends(match_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the more recent half of the window vs the earlier half."""
    if len(match_rows) < 2:
        return {
            "windowSize": len(match_rows),
            "recentGames": match_rows,
            "earlierGames": [],
            "insights": ["Not enough matches yet to judge recent trends."],
            "metrics": [],
        }

    split = max(1, len(match_rows) // 2)
    earlier = match_rows[:split]
    recent = match_rows[split:]
    earlier_avg = _build_averages(earlier)
    recent_avg = _build_averages(recent)

    metric_specs = (
        ("valeXg", "xG created", True),
        ("oppXg", "xG against", False),
        ("xgDiff", "xG difference", True),
        ("valeHighQualityPct", "High-quality shot share", True),
        ("valeLowQualityPct", "Low-quality shot share", False),
        ("valeShots", "Shots for", True),
    )
    metrics: list[dict[str, Any]] = []
    insights: list[str] = []
    for key, label, higher_better in metric_specs:
        earlier_val = earlier_avg.get(key)
        recent_val = recent_avg.get(key)
        direction = _trend_direction(recent_val, earlier_val, higher_better=higher_better)
        delta = None
        if recent_val is not None and earlier_val is not None:
            delta = round(float(recent_val) - float(earlier_val), 3)
        metrics.append(
            {
                "id": key,
                "label": label,
                "earlier": earlier_val,
                "recent": recent_val,
                "delta": delta,
                "direction": direction,
                "higherBetter": higher_better,
            }
        )
        if direction == "up":
            insights.append(f"{label} improving recently ({earlier_val} -> {recent_val}).")
        elif direction == "down":
            insights.append(f"{label} dipping recently ({earlier_val} -> {recent_val}).")

    if not insights:
        insights.append("Recent form is broadly steady versus the earlier games in this window.")

    # Overall read
    created = next((m for m in metrics if m["id"] == "valeXg"), None)
    against = next((m for m in metrics if m["id"] == "oppXg"), None)
    quality = next((m for m in metrics if m["id"] == "valeHighQualityPct"), None)
    headline_parts: list[str] = []
    if created and created["direction"] == "up":
        headline_parts.append("creating more")
    elif created and created["direction"] == "down":
        headline_parts.append("creating less")
    if against and against["direction"] == "up":
        headline_parts.append("conceding less xG")
    elif against and against["direction"] == "down":
        headline_parts.append("conceding more xG")
    if quality and quality["direction"] == "up":
        headline_parts.append("taking better chances")
    elif quality and quality["direction"] == "down":
        headline_parts.append("taking lower-quality shots")

    if headline_parts:
        insights.insert(0, "Recent trend: " + ", ".join(headline_parts) + ".")

    return {
        "windowSize": len(match_rows),
        "earlierGames": earlier,
        "recentGames": recent,
        "earlierAvg": earlier_avg,
        "recentAvg": recent_avg,
        "metrics": metrics,
        "insights": insights[:6],
    }


def build_xg_chance_report(
    *,
    season: str | None = None,
    match_id: int | None = None,
    match_ids: list[int] | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    iteration = _resolve_port_vale_iteration(season)
    iteration_id = int(iteration["id"])
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    if port_vale_id is None:
        raise ValueError("Port Vale squad not found for this iteration.")

    squads = _squads_map(iteration_id)
    player_names = _player_directory(iteration_id)
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    matches_by_id = {int(m["id"]): m for m in matches if m.get("id") is not None}
    completed_ids = _completed_vale_match_ids(matches, matches_by_id, port_vale_id)

    normalized_scope = (scope or "").strip().lower()
    if match_ids:
        selected_ids = [int(mid) for mid in match_ids if int(mid) in matches_by_id]
        normalized_scope = normalized_scope or "custom"
    elif normalized_scope == "last6":
        selected_ids = completed_ids[-6:]
    elif normalized_scope == "season":
        selected_ids = completed_ids
    elif match_id:
        selected_ids = [int(match_id)] if int(match_id) in matches_by_id else []
        normalized_scope = "match"
    elif normalized_scope == "match" and completed_ids:
        selected_ids = [completed_ids[-1]]
    else:
        selected_ids = completed_ids[-1:] if completed_ids else []
        normalized_scope = "match"

    if not selected_ids:
        raise ValueError("No completed matches found for this selection.")

    def _process_match(mid: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        match = matches_by_id[mid]
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        meta = _match_meta(match, port_vale_id, squads)
        shots, dismissals = _build_match_shots(
            mid, iteration_id, port_vale_id, home_id, away_id, player_names
        )
        for shot in shots:
            shot["matchId"] = mid
            shot["matchDay"] = meta["matchDay"]
            shot["opponentName"] = meta["opponent"]["name"]
        for dismissal in dismissals:
            dismissal["matchId"] = mid
            dismissal["matchDay"] = meta["matchDay"]
            dismissal["opponentName"] = meta["opponent"]["name"]

        vale_shots = [s for s in shots if s["team"] == "vale"]
        opp_shots = [s for s in shots if s["team"] == "opp"]
        summary = {
            **meta,
            "shotCount": len(shots),
            "valeShots": len(vale_shots),
            "oppShots": len(opp_shots),
            "valeXg": round(sum(s["xg"] for s in vale_shots), 3),
            "oppXg": round(sum(s["xg"] for s in opp_shots), 3),
            "dismissals": dismissals,
        }
        return summary, shots, dismissals

    all_shots: list[dict[str, Any]] = []
    all_dismissals: list[dict[str, Any]] = []
    match_summaries: list[dict[str, Any]] = []
    match_trend_rows: list[dict[str, Any]] = []

    workers = min(8, max(1, len(selected_ids)))
    if len(selected_ids) == 1:
        summary, shots, dismissals = _process_match(selected_ids[0])
        match_summaries.append(summary)
        match_trend_rows.append(_build_match_trend_row(summary, shots))
        all_shots.extend(shots)
        all_dismissals.extend(dismissals)
    else:
        summaries_by_id: dict[int, dict[str, Any]] = {}
        shots_by_id: dict[int, list[dict[str, Any]]] = {}
        dismissals_by_id: dict[int, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_process_match, mid): mid
                for mid in selected_ids
            }
            for future in as_completed(futures):
                mid = futures[future]
                summary, shots, dismissals = future.result()
                summaries_by_id[mid] = summary
                shots_by_id[mid] = shots
                dismissals_by_id[mid] = dismissals
        for mid in selected_ids:
            match_summaries.append(summaries_by_id[mid])
            match_trend_rows.append(_build_match_trend_row(summaries_by_id[mid], shots_by_id[mid]))
            all_shots.extend(shots_by_id[mid])
            all_dismissals.extend(dismissals_by_id[mid])

    vale_shots = [s for s in all_shots if s["team"] == "vale"]
    opp_shots = [s for s in all_shots if s["team"] == "opp"]
    xg_created = _summarize_buckets(vale_shots)
    xg_against = _summarize_buckets(opp_shots)
    averages = _build_averages(match_trend_rows)
    trends = _build_trends(match_trend_rows)

    if normalized_scope == "last6":
        scope_label = f"Last {len(selected_ids)} games"
        scope_key = "last6"
    elif normalized_scope == "season" or len(selected_ids) > 1:
        scope_label = f"Full season · {len(selected_ids)} matches"
        scope_key = "season" if normalized_scope == "season" else "custom"
    else:
        scope_label = match_summaries[0]["opponent"]["name"]
        scope_key = "match"

    return {
        "season": str(iteration.get("season") or ""),
        "competition": str(iteration.get("competition_name") or ""),
        "scope": scope_key,
        "scopeLabel": scope_label,
        "matchCount": len(selected_ids),
        "matches": match_summaries,
        "matchTrends": match_trend_rows,
        "averages": averages,
        "trends": trends,
        "chanceBuckets": list(CHANCE_BUCKETS),
        "shots": all_shots,
        "dismissals": all_dismissals,
        "xgCreated": xg_created,
        "xgAgainst": xg_against,
        "gameStateBreakdown": {
            "vale": _summarize_game_states(all_shots, vale_only=True),
            "opp": _summarize_game_states(all_shots, vale_only=False),
        },
        "playerBreakdown": {
            "vale": _summarize_players(all_shots, vale_only=True),
            "opp": _summarize_players(all_shots, vale_only=False),
        },
        "periodBreakdown": _summarize_periods(all_shots),
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def build_xg_chance_pack(season: str | None = None) -> dict[str, Any]:
    """Build recent game + last 6 + full season payloads for PDF export."""
    recent = build_xg_chance_report(season=season, scope="match")
    last6 = build_xg_chance_report(season=season, scope="last6")
    full = build_xg_chance_report(season=season, scope="season")
    return {
        "season": recent.get("season") or last6.get("season") or full.get("season"),
        "competition": recent.get("competition") or last6.get("competition") or full.get("competition"),
        "recent": recent,
        "last6": last6,
        "seasonReport": full,
        "updatedAt": datetime.now(UTC).isoformat(),
    }


class XgChanceReportRequest(BaseModel):
    season: str | None = None
    match_id: int | None = Field(default=None, alias="matchId")
    match_ids: list[int] | None = Field(default=None, alias="matchIds")
    scope: str | None = None

    model_config = {"populate_by_name": True}


def _xg_chance_seasons() -> list[dict[str, Any]]:
    allowed = set(ALLOWED_SEASONS)
    return [row for row in _available_port_vale_seasons() if row.get("value") in allowed]


def _xg_chance_default_season() -> str:
    seasons = _xg_chance_seasons()
    for preferred in ALLOWED_SEASONS:
        if any(row.get("value") == preferred and row.get("hasData") for row in seasons):
            return preferred
    return seasons[0]["value"] if seasons else _default_port_vale_season()


def xg_chance_meta() -> dict[str, Any]:
    seasons = _xg_chance_seasons()
    default_season = _xg_chance_default_season()
    iteration = _resolve_port_vale_iteration(default_season or None)
    return {
        "seasons": seasons,
        "defaultSeason": default_season,
        "season": str(iteration.get("season") or ""),
        "competition": str(iteration.get("competition_name") or ""),
        "chanceBuckets": list(CHANCE_BUCKETS),
        "gameStates": [
            {"id": key, "label": label}
            for key, label in GAME_STATE_LABELS.items()
        ],
    }


def register_xg_chance_analysis_routes(app: FastAPI) -> None:
    @app.get("/xg-chance-analysis", response_class=HTMLResponse)
    def xg_chance_analysis_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "xg-chance-analysis.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="xG Chance Analysis UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/xg-chance-analysis/meta")
    def xg_chance_meta_route() -> dict[str, Any]:
        return xg_chance_meta()

    @app.get("/api/xg-chance-analysis/fixtures")
    def xg_chance_fixtures_route(
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        fixtures = build_xg_chance_fixtures(season)
        return {
            "fixtures": fixtures,
            "defaultMatchId": _default_fixture_match_id(fixtures),
        }

    @app.get("/api/xg-chance-analysis/report")
    def xg_chance_report_route(
        season: str | None = Query(None),
        match_id: int | None = Query(None, alias="matchId"),
        scope: str | None = Query(None),
    ) -> JSONResponse:
        try:
            payload = build_xg_chance_report(season=season, match_id=match_id, scope=scope)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/xg-chance-analysis/report")
    def xg_chance_report_post(body: XgChanceReportRequest) -> dict[str, Any]:
        try:
            return build_xg_chance_report(
                season=body.season,
                match_id=body.match_id,
                match_ids=body.match_ids,
                scope=body.scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/xg-chance-analysis/export-pdf")
    def xg_chance_export_pdf_route(
        season: str | None = Query(None),
        scope: str | None = Query("match"),
        match_id: int | None = Query(None, alias="matchId"),
    ) -> Response:
        from app.xg_chance_analysis_pdf import build_xg_chance_analysis_pdf

        normalized = (scope or "match").strip().lower()
        if normalized not in {"match", "last6", "season"}:
            raise HTTPException(status_code=400, detail="scope must be match, last6, or season")

        try:
            report = build_xg_chance_report(
                season=season,
                match_id=match_id if normalized == "match" else None,
                scope=normalized,
            )
            pdf_bytes = build_xg_chance_analysis_pdf(report, scope=normalized)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"PDF export failed: {exc}",
            ) from exc

        season_label = str(report.get("season") or "season").replace("/", "-")
        scope_slug = {
            "match": "latest-match",
            "last6": "last-6",
            "season": "full-season",
        }.get(normalized, normalized)
        filename = f"xg-chance-analysis-{season_label}-{scope_slug}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
