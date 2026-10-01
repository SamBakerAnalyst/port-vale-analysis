from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
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
from app.paths import STANDALONE_DIR
from app.scouting import SCOUTING_DIR
from app.squad_review import (
    _available_port_vale_seasons,
    _default_port_vale_season,
    _resolve_port_vale_iteration,
)

logger = logging.getLogger(__name__)

SHOT_XG_KPI_ID = 82

# League table columns. Same bands and thresholds as CHANCE_BUCKETS — not a new model.
LEAGUE_TABLE_BAND_IDS: tuple[str, ...] = ("excellent", "very_good", "ok")

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
PENALTY_ACTIONS = frozenset({"PENALTY", "PENALTY_KICK"})
# Cached reports built before isPenalty existed: typical spot-kick xG sits in this band.
PENALTY_XG_MIN = 0.72
PENALTY_XG_MAX = 0.83

ALLOWED_SEASONS = ("26/27", "25/26")

_match_events_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_ekpi_cache: dict[int, tuple[float, dict[int, float]]] = {}
_player_directory_cache: dict[int, tuple[float, dict[int, str]]] = {}
_iteration_matches_cache: dict[int, tuple[float, dict[int, dict[str, Any]]]] = {}


def _impect():
    from app import main as impect_main

    return impect_main


def _iteration_matches_by_id(iteration_id: int) -> dict[int, dict[str, Any]]:
    now = time.time()
    cached = _iteration_matches_cache.get(iteration_id)
    if cached and now - cached[0] < 300 and cached[1]:
        return cached[1]
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(
            f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
        )["data"]
    )
    mapping = {int(m["id"]): m for m in matches if m.get("id") is not None}
    _iteration_matches_cache[iteration_id] = (now, mapping)
    return mapping


def _competition_iteration_ids(primary_iteration_id: int) -> list[int]:
    ids = [int(primary_iteration_id)]
    try:
        from app.post_match.config import POST_MATCH_COMPETITIONS

        for row in POST_MATCH_COMPETITIONS:
            iid = int(row.get("iterationId") or 0)
            if iid and iid not in ids:
                ids.append(iid)
    except Exception:
        pass
    return ids


def _locate_matches(
    match_ids: list[int], primary_iteration_id: int
) -> list[tuple[int, dict[str, Any]]]:
    found: dict[int, tuple[int, dict[str, Any]]] = {}
    for iid in _competition_iteration_ids(primary_iteration_id):
        mapping = _iteration_matches_by_id(iid)
        for mid in match_ids:
            if mid in mapping and mid not in found:
                found[mid] = (iid, mapping[mid])
    missing = [mid for mid in match_ids if mid not in found]
    if missing:
        raise ValueError(f"No completed matches found for this selection: {missing}")
    return [found[mid] for mid in match_ids]


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


def _fetch_match_events(match_id: int, *, refresh: bool = False) -> list[dict[str, Any]]:
    from app.analysis_cache import PACKET_TTL_SECONDS, read_list, write_list

    mid = int(match_id)
    now = time.time()
    if not refresh:
        cached = _match_events_cache.get(mid)
        if cached and cached[1]:
            return cached[1]
        disk = read_list("xg-events", str(mid), ttl=PACKET_TTL_SECONDS, allow_stale=True)
        # Empty disk is not trusted: Impect often marks a match available before
        # the event packet lands (Exeter vs Barnet 1 Sep 2026 — lineups yes, events later).
        if disk:
            _match_events_cache[mid] = (now, disk)
            return disk

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/matches/{mid}/events"
    )["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    events = [item for item in (raw if isinstance(raw, list) else _unwrap_items(raw)) if isinstance(item, dict)]
    events.sort(key=lambda row: (_event_seconds(row), int(row.get("id") or 0)))
    now = time.time()
    _match_events_cache[mid] = (now, events)
    write_list("xg-events", str(mid), events)
    return events


def _fetch_shot_xg_by_event(match_id: int, *, refresh: bool = False) -> dict[int, float]:
    from app.analysis_cache import PACKET_TTL_SECONDS, read_json, write_json

    mid = int(match_id)
    if not refresh:
        cached = _ekpi_cache.get(mid)
        now = time.time()
        if cached:
            return cached[1]
        disk = read_json("xg-ekpi", str(mid), ttl=PACKET_TTL_SECONDS, allow_stale=True)
        if disk is not None:
            mapped = {int(k): float(v) for k, v in disk.items()}
            _ekpi_cache[mid] = (now, mapped)
            return mapped
        return {}

    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/matches/{mid}/event-kpis"
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

    mapped = dict(xg_by_event)
    now = time.time()
    _ekpi_cache[mid] = (now, mapped)
    write_json("xg-ekpi", str(mid), {str(k): v for k, v in mapped.items()})
    return mapped


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


def _event_action(event: dict[str, Any]) -> str:
    return str(event.get("action") or event.get("actionType") or "").upper()


def _is_penalty_event(event: dict[str, Any]) -> bool:
    action = _event_action(event)
    if action in PENALTY_ACTIONS:
        return True
    payload = event.get("setPiece") or event.get("inferredSetPiece") or {}
    if not isinstance(payload, dict):
        return False
    category = str(
        payload.get("category")
        or payload.get("setPieceCategory")
        or payload.get("type")
        or ""
    ).upper()
    return "PENALTY" in category


def _shot_in_box(shot: dict[str, Any]) -> bool:
    if shot.get("inBox") is True:
        return True
    if shot.get("inBox") is False:
        return False
    return str(shot.get("inBoxLabel") or "").upper() == "IN"


def _looks_like_penalty_xg(shot: dict[str, Any]) -> bool:
    try:
        xg = float(shot.get("xg") or 0)
    except (TypeError, ValueError):
        return False
    return _shot_in_box(shot) and PENALTY_XG_MIN <= xg <= PENALTY_XG_MAX


def _is_penalty_shot(shot: dict[str, Any]) -> bool:
    if shot.get("isPenalty") is True:
        return True
    action = str(shot.get("action") or "").upper()
    if action in PENALTY_ACTIONS:
        return True
    if shot.get("isPenalty") is False:
        return False
    return _looks_like_penalty_xg(shot)


def _annotate_shot_penalties(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for shot in shots:
        flagged = _is_penalty_shot(shot)
        shot["isPenalty"] = flagged
        if flagged and not shot.get("action"):
            shot["action"] = "PENALTY_KICK"
    return shots


def _penalty_summary(shots: list[dict[str, Any]]) -> dict[str, Any]:
    pens = [shot for shot in shots if _is_penalty_shot(shot)]
    vale = [shot for shot in pens if shot.get("team") == "vale"]
    opp = [shot for shot in pens if shot.get("team") != "vale"]

    def _row(shot: dict[str, Any]) -> dict[str, Any]:
        return {
            "eventId": shot.get("eventId"),
            "matchId": shot.get("matchId"),
            "team": shot.get("team"),
            "playerName": shot.get("playerName"),
            "minute": shot.get("minute"),
            "xg": shot.get("xg"),
            "outcome": shot.get("outcome"),
            "outcomeLabel": shot.get("outcomeLabel") or ("GOAL" if shot.get("outcome") == "goal" else "MISS"),
        }

    return {
        "count": len(pens),
        "valeCount": len(vale),
        "oppCount": len(opp),
        "valeXg": round(sum(float(shot.get("xg") or 0) for shot in vale), 3),
        "oppXg": round(sum(float(shot.get("xg") or 0) for shot in opp), 3),
        "valeGoals": sum(1 for shot in vale if shot.get("outcome") == "goal"),
        "oppGoals": sum(1 for shot in opp if shot.get("outcome") == "goal"),
        "shots": [_row(shot) for shot in pens],
        "excluded": False,
    }


def _resequence_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counters: dict[tuple[Any, str], dict[str, Any]] = {}
    ordered = sorted(
        shots,
        key=lambda shot: (
            int(shot.get("matchId") or 0),
            float(shot.get("seconds") or 0),
            int(shot.get("eventId") or 0),
        ),
    )
    for shot in ordered:
        key = (shot.get("matchId"), str(shot.get("team") or ""))
        bucket = counters.setdefault(key, {"n": 0, "xg": 0.0})
        bucket["n"] += 1
        bucket["xg"] += float(shot.get("xg") or 0)
        shot["shotNumber"] = bucket["n"]
        shot["cumulativeXg"] = round(bucket["xg"], 3)
    return ordered


def _build_hero_stats(shots: list[dict[str, Any]]) -> dict[str, Any]:
    vale = [shot for shot in shots if shot.get("team") == "vale"]
    opp = [shot for shot in shots if shot.get("team") != "vale"]
    vale_xg = round(sum(float(shot.get("xg") or 0) for shot in vale), 3)
    opp_xg = round(sum(float(shot.get("xg") or 0) for shot in opp), 3)
    hq = [
        shot
        for shot in vale
        if str((shot.get("chanceRating") or {}).get("id") or "") in {"excellent", "very_good"}
    ]
    on_target = [shot for shot in vale if shot.get("onTarget")]
    in_box = [shot for shot in vale if _shot_in_box(shot)]
    best = max(vale, key=lambda shot: float(shot.get("xg") or 0), default=None)
    vale_n = len(vale)
    return {
        "xgDiff": round(vale_xg - opp_xg, 3),
        "valeXg": vale_xg,
        "oppXg": opp_xg,
        "valeShots": vale_n,
        "oppShots": len(opp),
        "valeOnTarget": len(on_target),
        "valeOnTargetPct": round((len(on_target) / vale_n) * 100) if vale_n else 0,
        "valeInBox": len(in_box),
        "valeInBoxPct": round((len(in_box) / vale_n) * 100) if vale_n else 0,
        "valeHighQuality": len(hq),
        "valeHighQualityPct": round((len(hq) / vale_n) * 100, 1) if vale_n else 0.0,
        "valeAvgXg": round(vale_xg / vale_n, 3) if vale_n else 0.0,
        "bestChance": {
            "playerName": best.get("playerName"),
            "xg": best.get("xg"),
            "isPenalty": _is_penalty_shot(best),
            "outcome": best.get("outcome"),
            "team": best.get("team"),
        }
        if best
        else None,
    }


def apply_penalty_filter(report: dict[str, Any], *, exclude_penalties: bool = False) -> dict[str, Any]:
    """Copy a report, flag penalties, optionally drop them, then rebuild summaries."""
    out = dict(report or {})
    shots = [dict(shot) for shot in (out.get("shots") or [])]
    _annotate_shot_penalties(shots)
    penalty = _penalty_summary(shots)
    penalty["excluded"] = bool(exclude_penalties)

    if exclude_penalties:
        shots = _resequence_shots([shot for shot in shots if not shot.get("isPenalty")])
    else:
        shots = _resequence_shots(shots)

    vale_shots = [shot for shot in shots if shot.get("team") == "vale"]
    opp_shots = [shot for shot in shots if shot.get("team") != "vale"]
    xg_created = _summarize_buckets(vale_shots)
    xg_against = _summarize_buckets(opp_shots)

    matches = [dict(row) for row in (out.get("matches") or [])]
    for match in matches:
        mid = match.get("matchId")
        match_shots = [shot for shot in shots if shot.get("matchId") == mid] if mid is not None else shots
        match_vale = [shot for shot in match_shots if shot.get("team") == "vale"]
        match_opp = [shot for shot in match_shots if shot.get("team") != "vale"]
        match["shotCount"] = len(match_shots)
        match["valeShots"] = len(match_vale)
        match["oppShots"] = len(match_opp)
        match["valeXg"] = round(sum(float(shot.get("xg") or 0) for shot in match_vale), 3)
        match["oppXg"] = round(sum(float(shot.get("xg") or 0) for shot in match_opp), 3)

    match_trend_rows = [
        _build_match_trend_row(match, [shot for shot in shots if shot.get("matchId") == match.get("matchId")])
        for match in matches
    ]

    out["shots"] = shots
    out["matches"] = matches
    out["matchTrends"] = match_trend_rows
    out["averages"] = _build_averages(match_trend_rows)
    out["trends"] = _build_trends(match_trend_rows)
    out["xgCreated"] = xg_created
    out["xgAgainst"] = xg_against
    out["gameStateBreakdown"] = {
        "vale": _summarize_game_states(shots, vale_only=True),
        "opp": _summarize_game_states(shots, vale_only=False),
    }
    out["playerBreakdown"] = {
        "vale": _summarize_players(shots, vale_only=True),
        "opp": _summarize_players(shots, vale_only=False),
    }
    out["periodBreakdown"] = _summarize_periods(shots)
    out["penaltySummary"] = penalty
    out["heroStats"] = _build_hero_stats(shots)
    out["excludePenalties"] = bool(exclude_penalties)
    out["shotCount"] = len(shots)
    return out


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
            "penaltyCount": 0,
            "penaltyXg": 0.0,
        }
        for bucket in CHANCE_BUCKETS
    }


def _summarize_buckets(shots: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = _empty_bucket_summary()
    total_shots = 0
    total_xg = 0.0
    total_goals = 0

    for shot in shots:
        rating = shot.get("chanceRating") if isinstance(shot.get("chanceRating"), dict) else {}
        bucket_id = str(rating.get("id") or "")
        if bucket_id not in buckets:
            try:
                bucket_id = _classify_chance(float(shot.get("xg") or 0))["id"]
            except (TypeError, ValueError):
                bucket_id = CHANCE_BUCKETS[-1]["id"]
        buckets[bucket_id]["count"] += 1
        xg_value = float(shot.get("xg") or 0)
        buckets[bucket_id]["cumulativeXg"] += xg_value
        if _is_penalty_shot(shot):
            buckets[bucket_id]["penaltyCount"] += 1
            buckets[bucket_id]["penaltyXg"] += xg_value
        if shot.get("outcome") == "goal":
            buckets[bucket_id]["goals"] += 1
            total_goals += 1
        total_shots += 1
        total_xg += xg_value

    rows = []
    for bucket in CHANCE_BUCKETS:
        row = buckets[bucket["id"]]
        count = row["count"]
        rows.append(
            {
                **row,
                "cumulativeXg": round(row["cumulativeXg"], 3),
                "penaltyCount": int(row.get("penaltyCount") or 0),
                "penaltyXg": round(float(row.get("penaltyXg") or 0), 3),
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
    filtered = [s for s in shots if (s.get("team") == "vale") == vale_only] if vale_only else shots
    by_state: dict[str, dict[str, Any]] = {
        key: {"id": key, "label": GAME_STATE_LABELS[key], "shots": 0, "xg": 0.0, "goals": 0}
        for key in GAME_STATE_LABELS
    }
    for shot in filtered:
        state = shot.get("gameState") or "drawing"
        if state not in by_state:
            continue
        by_state[state]["shots"] += 1
        by_state[state]["xg"] += float(shot.get("xg") or 0)
        if shot.get("outcome") == "goal":
            by_state[state]["goals"] += 1

    return [
        {
            **row,
            "xg": round(row["xg"], 3),
        }
        for row in by_state.values()
    ]


def _summarize_players(shots: list[dict[str, Any]], *, vale_only: bool = True) -> list[dict[str, Any]]:
    filtered = [s for s in shots if s.get("team") == "vale"] if vale_only else [s for s in shots if s.get("team") == "opp"]
    players: dict[str, dict[str, Any]] = {}
    for shot in filtered:
        name = shot.get("playerName") or "Unknown"
        row = players.setdefault(
            name,
            {
                "playerName": name,
                "shots": 0,
                "xg": 0.0,
                "goals": 0,
                "highQualityShots": 0,
                "lowQualityShots": 0,
                "penalties": 0,
                "penaltyXg": 0.0,
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
        row["xg"] += float(shot.get("xg") or 0)
        if _is_penalty_shot(shot):
            row["penalties"] += 1
            row["penaltyXg"] += float(shot.get("xg") or 0)
        if shot.get("outcome") == "goal":
            row["goals"] += 1
        rating = shot.get("chanceRating") if isinstance(shot.get("chanceRating"), dict) else {}
        rating_id = str(rating.get("id") or "")
        if rating_id in row["chanceCounts"]:
            row["chanceCounts"][rating_id] += 1
        if rating_id in {"excellent", "very_good"}:
            row["highQualityShots"] += 1
        elif rating_id in {"poor", "very_poor"}:
            row["lowQualityShots"] += 1

    rows = sorted(players.values(), key=lambda r: (-r["xg"], -r["shots"], r["playerName"]))
    for row in rows:
        row["xg"] = round(row["xg"], 3)
        row["penaltyXg"] = round(row["penaltyXg"], 3)
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
        half_key = "first" if shot.get("half") == "first" else "second"
        team_key = "vale" if shot.get("team") == "vale" else "opp"
        xg_value = float(shot.get("xg") or 0)
        halves[half_key][f"{team_key}Shots"] += 1
        halves[half_key][f"{team_key}Xg"] += xg_value

        mp = shot.get("manpower") or "11 v 11"
        if mp == "11 v 11":
            bucket = manpower["elevenEleven"]
        elif shot.get("team") == "vale" and str(mp).startswith("10"):
            bucket = manpower["valeDown"]
        elif shot.get("team") == "opp" and str(mp).endswith("10"):
            bucket = manpower["oppDown"]
        else:
            bucket = manpower["elevenEleven"]
        bucket[f"{team_key}Shots"] += 1
        bucket[f"{team_key}Xg"] += xg_value

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
    *,
    refresh: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _fetch_match_events(match_id, refresh=refresh)
    xg_by_event = _fetch_shot_xg_by_event(match_id, refresh=refresh)

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
        is_penalty = _is_penalty_event(event)

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
                "action": action,
                "isPenalty": is_penalty,
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


def _fixtures_from_xg_reports(season: str | None = None) -> list[dict[str, Any]]:
    from app.analysis_cache import all_json

    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for report in all_json("xg-report"):
        if season and str(report.get("season") or "") not in {"", str(season)}:
            continue
        for summary in report.get("matches") or []:
            match_id = summary.get("matchId")
            if match_id in seen:
                continue
            seen.add(match_id)
            opponent = summary.get("opponent") or {"name": summary.get("opponentName")}
            rows.append(
                {
                    "matchId": match_id,
                    "matchDay": summary.get("matchDay"),
                    "dateLabel": summary.get("dateLabel") or summary.get("kickoffLabel"),
                    "kickoffLabel": summary.get("kickoffLabel"),
                    "isHome": summary.get("isHome"),
                    "venue": summary.get("venue") or ("Home" if summary.get("isHome") else "Away"),
                    "opponent": opponent,
                    "score": summary.get("score") or "",
                }
            )
    return rows


def build_xg_chance_fixtures(
    season: str | None, *, refresh: bool = False
) -> list[dict[str, Any]]:
    from app.analysis_cache import REPORT_TTL_SECONDS, all_json, read_json, write_json

    cache_key = (season or "default").replace("/", "-")
    if not refresh:
        cached = read_json(
            "xg-fixtures", cache_key, ttl=REPORT_TTL_SECONDS, allow_stale=True
        )
        if cached and isinstance(cached.get("fixtures"), list) and cached["fixtures"]:
            return list(cached["fixtures"])
        for body in all_json("xg-fixtures"):
            rows = body.get("fixtures")
            if isinstance(rows, list) and rows:
                return list(rows)
        recovered = _fixtures_from_xg_reports(season)
        if recovered:
            return recovered

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
    write_json("xg-fixtures", cache_key, {"fixtures": rows})
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
    refresh: bool = False,
    exclude_penalties: bool = False,
) -> dict[str, Any]:
    from app.analysis_cache import REPORT_TTL_SECONDS, read_json, write_json

    scope_token = (scope or "").strip().lower() or ("match" if match_id or not match_ids else "custom")
    ids_token = ",".join(str(i) for i in (match_ids or [])) or str(match_id or "auto")
    cache_key = f"report_{(season or 'default').replace('/', '-')}_{scope_token}_{ids_token}"
    if not refresh:
        cached = read_json(
            "xg-report", cache_key, ttl=REPORT_TTL_SECONDS, allow_stale=True
        )
        if not cached:
            from app.analysis_cache import all_json, newest_json

            wanted_season = str(season or "")
            for report in all_json("xg-report"):
                if wanted_season and str(report.get("season") or "") not in {"", wanted_season}:
                    continue
                if scope_token and str(report.get("scope") or "") not in {"", scope_token}:
                    continue
                cached = report
                break
            if not cached:
                cached = newest_json("xg-report")
        if cached:
            cached = dict(cached)
            cached["cache"] = {"hit": True, "refreshed": False}
            return apply_penalty_filter(cached, exclude_penalties=exclude_penalties)

    report = _build_xg_chance_report_uncached(
        season=season,
        match_id=match_id,
        match_ids=match_ids,
        scope=scope,
        refresh=refresh,
    )
    write_json("xg-report", cache_key, report)
    report = dict(report)
    report["cache"] = {"hit": False, "refreshed": bool(refresh)}
    return apply_penalty_filter(report, exclude_penalties=exclude_penalties)


def _build_xg_chance_report_uncached(
    *,
    season: str | None = None,
    match_id: int | None = None,
    match_ids: list[int] | None = None,
    scope: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    iteration = _resolve_port_vale_iteration(season)
    iteration_id = int(iteration["id"])
    port_vale_id = _resolve_port_vale_squad_id(iteration_id)
    if port_vale_id is None:
        raise ValueError("Port Vale squad not found for this iteration.")

    league_matches_by_id = _iteration_matches_by_id(iteration_id)
    completed_ids = _completed_vale_match_ids(
        list(league_matches_by_id.values()), league_matches_by_id, port_vale_id
    )

    normalized_scope = (scope or "").strip().lower()
    located: list[tuple[int, dict[str, Any]]] | None = None
    if match_ids:
        located = _locate_matches([int(mid) for mid in match_ids], iteration_id)
        selected_ids = [int(match["id"]) for _, match in located]
        normalized_scope = normalized_scope or ("match" if len(selected_ids) == 1 else "custom")
    elif normalized_scope == "last6":
        selected_ids = completed_ids[-6:]
    elif normalized_scope == "season":
        selected_ids = completed_ids
    elif match_id:
        located = _locate_matches([int(match_id)], iteration_id)
        selected_ids = [int(match["id"]) for _, match in located]
        normalized_scope = "match"
    elif normalized_scope == "match" and completed_ids:
        selected_ids = [completed_ids[-1]]
    else:
        selected_ids = completed_ids[-1:] if completed_ids else []
        normalized_scope = "match"

    if not selected_ids:
        raise ValueError("No completed matches found for this selection.")
    if located is None:
        located = [(iteration_id, league_matches_by_id[mid]) for mid in selected_ids]
    located_by_id = {int(match["id"]): (iid, match) for iid, match in located}

    def _process_match(mid: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        match_iteration_id, match = located_by_id[mid]
        squads = _squads_map(match_iteration_id)
        player_names = _player_directory(match_iteration_id)
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        meta = _match_meta(match, port_vale_id, squads)
        shots, dismissals = _build_match_shots(
            mid,
            match_iteration_id,
            port_vale_id,
            home_id,
            away_id,
            player_names,
            refresh=refresh,
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
        "penaltySummary": _penalty_summary(all_shots),
        "heroStats": _build_hero_stats(all_shots),
        "excludePenalties": False,
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
    refresh: bool = False
    exclude_penalties: bool = Field(default=False, alias="excludePenalties")

    model_config = {"populate_by_name": True}


def _xg_chance_seasons() -> list[dict[str, Any]]:
    allowed = set(ALLOWED_SEASONS)
    return [row for row in _available_port_vale_seasons() if row.get("value") in allowed]


def _xg_chance_default_season() -> str:
    seasons = _xg_chance_seasons()
    values = {str(row.get("value")) for row in seasons}
    # Prefer 26/27 whenever listed — season has started.
    for preferred in ALLOWED_SEASONS:
        if preferred in values:
            return preferred
    return seasons[0]["value"] if seasons else _default_port_vale_season()


def xg_chance_meta(*, refresh: bool = False) -> dict[str, Any]:
    from app.analysis_cache import REPORT_TTL_SECONDS, read_json, write_json

    if not refresh:
        cached = read_json("xg-meta", "default", ttl=REPORT_TTL_SECONDS, allow_stale=True)
        if cached and (cached.get("seasons") or cached.get("defaultSeason")):
            return cached
        from app.analysis_cache import all_json, newest_json

        newest = newest_json("xg-meta")
        if newest and (newest.get("seasons") or newest.get("defaultSeason")):
            return newest
        seasons: list[dict[str, Any]] = []
        seen: set[str] = set()
        for report in all_json("xg-report"):
            value = str(report.get("season") or "").strip()
            if value and value not in seen:
                seen.add(value)
                seasons.append({"value": value, "label": value})
        for value in ALLOWED_SEASONS:
            if value not in seen:
                seasons.append({"value": value, "label": value})
        default_season = next(
            (value for value in ALLOWED_SEASONS if value in {row["value"] for row in seasons}),
            seasons[0]["value"] if seasons else "",
        )
        return {
            "seasons": seasons,
            "defaultSeason": default_season,
            "season": default_season,
            "competition": "",
            "chanceBuckets": list(CHANCE_BUCKETS),
            "gameStates": [
                {"id": key, "label": label}
                for key, label in GAME_STATE_LABELS.items()
            ],
        }

    seasons = _xg_chance_seasons()
    default_season = _xg_chance_default_season()
    iteration = _resolve_port_vale_iteration(default_season or None)
    meta = {
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
    write_json("xg-meta", "default", meta)
    return meta


def _league_table_bands() -> list[dict[str, Any]]:
    return [dict(bucket) for bucket in CHANCE_BUCKETS if bucket["id"] in LEAGUE_TABLE_BAND_IDS]


def _band_threshold_label(bucket: dict[str, Any]) -> str:
    label = str(bucket.get("label") or bucket.get("id") or "")
    min_val = bucket.get("min")
    max_val = bucket.get("max")
    if min_val is not None and max_val is None:
        return f"{label} ≥ {float(min_val):.2f} xG"
    if min_val is not None and max_val is not None:
        return f"{label} {float(min_val):.2f}–{float(max_val):.2f} xG"
    if max_val is not None:
        return f"{label} < {float(max_val):.2f} xG"
    return label


def _new_team_tally() -> dict[str, Any]:
    return {
        "matches": 0,
        "shots": 0,
        "penalties": 0,
        "bands": {
            bucket["id"]: {"count": 0, "penalties": 0}
            for bucket in CHANCE_BUCKETS
        },
    }


def tally_league_matches(match_rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Count shots per squad. Ratings must already be page band ids."""
    known = {bucket["id"] for bucket in CHANCE_BUCKETS}
    teams: dict[int, dict[str, Any]] = {}

    def ensure(squad_id: int) -> dict[str, Any]:
        row = teams.get(squad_id)
        if row is None:
            row = _new_team_tally()
            teams[squad_id] = row
        return row

    for match in match_rows:
        home = int(match.get("homeSquadId") or 0)
        away = int(match.get("awaySquadId") or 0)
        if home <= 0 or away <= 0:
            continue
        ensure(home)["matches"] += 1
        if away != home:
            ensure(away)["matches"] += 1
        for shot in match.get("shots") or []:
            squad_id = int(shot.get("squadId") or 0)
            if squad_id not in {home, away}:
                continue
            rating = str(shot.get("ratingId") or "")
            if rating not in known:
                continue
            row = ensure(squad_id)
            is_penalty = bool(shot.get("isPenalty"))
            row["shots"] += 1
            if is_penalty:
                row["penalties"] += 1
            band = row["bands"][rating]
            band["count"] += 1
            if is_penalty:
                band["penalties"] += 1
    return teams


def _visible_band_count(band: dict[str, Any], *, exclude_penalties: bool) -> int:
    count = int(band.get("count") or 0)
    if exclude_penalties:
        count -= int(band.get("penalties") or 0)
    return max(0, count)


def _shot_share(count: int, shots: int) -> float:
    if shots <= 0:
        return 0.0
    return round((count / shots) * 100, 1)


def _per_match(count: int, matches: int) -> float:
    if matches <= 0:
        return 0.0
    return round(count / matches, 2)


def league_rows_from_tallies(
    tallies: dict[int, dict[str, Any]],
    names: dict[int, str],
    *,
    exclude_penalties: bool = False,
) -> list[dict[str, Any]]:
    """Rank teams by Excellent, then Very Good, then OK (counts)."""
    rows: list[dict[str, Any]] = []
    for squad_id, tally in tallies.items():
        shots = int(tally.get("shots") or 0)
        penalties = int(tally.get("penalties") or 0)
        if exclude_penalties:
            shots = max(0, shots - penalties)
        matches = int(tally.get("matches") or 0)
        bands: dict[str, Any] = {}
        stored = tally.get("bands") or {}
        for bucket in CHANCE_BUCKETS:
            band_id = bucket["id"]
            count = _visible_band_count(stored.get(band_id) or {}, exclude_penalties=exclude_penalties)
            bands[band_id] = {
                "id": band_id,
                "label": bucket["label"],
                "count": count,
                "share": _shot_share(count, shots),
                "perMatch": _per_match(count, matches),
            }
        quality = sum(bands[band_id]["count"] for band_id in LEAGUE_TABLE_BAND_IDS)
        name = str(names.get(squad_id) or f"Squad {squad_id}")
        rows.append(
            {
                "squadId": squad_id,
                "teamName": name,
                "isPortVale": _is_port_vale(name),
                "matches": matches,
                "shots": shots,
                "bands": bands,
                "qualityCount": quality,
                "qualityShare": _shot_share(quality, shots),
                "qualityPerMatch": _per_match(quality, matches),
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row["bands"]["excellent"]["count"]),
            -int(row["bands"]["very_good"]["count"]),
            -int(row["bands"]["ok"]["count"]),
            str(row["teamName"]).casefold(),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def _league_table_payload(
    *,
    season: str,
    competition: str,
    match_count: int,
    skipped_match_count: int,
    rows: list[dict[str, Any]],
    exclude_penalties: bool,
    updated_at: str | None = None,
) -> dict[str, Any]:
    competition_label = competition.strip()
    season_label = season.strip()
    window_bits = [bit for bit in (competition_label, season_label) if bit]
    window = " ".join(window_bits) if window_bits else "Selected season"
    bands = []
    for bucket in _league_table_bands():
        bands.append(
            {
                "id": bucket["id"],
                "label": bucket["label"],
                "min": bucket.get("min"),
                "max": bucket.get("max"),
                "color": bucket.get("color"),
                "thresholdLabel": _band_threshold_label(bucket),
            }
        )
    return {
        "season": season_label,
        "competition": competition_label,
        "windowLabel": f"{window} · all completed matches",
        "scopeNote": (
            "Every completed match in this competition and season. "
            "Share is the percentage of that team's shots. "
            "The match and last-6 controls apply to the Vale views only."
        ),
        "sort": {
            "columns": list(LEAGUE_TABLE_BAND_IDS),
            "direction": "desc",
            "label": "Most Excellent, then Very Good, then OK",
        },
        "bands": bands,
        "excludePenalties": exclude_penalties,
        "matchCount": match_count,
        "skippedMatchCount": skipped_match_count,
        "teamCount": len(rows),
        "rows": rows,
        "updatedAt": updated_at or datetime.now(UTC).isoformat(),
    }


def _shot_xg_map(match_id: int, *, refresh: bool = False) -> dict[int, float]:
    """Shot xG by event. Fetches on a cache miss; the shared helper does not."""
    mid = int(match_id)
    if not refresh:
        cached = _ekpi_cache.get(mid)
        if cached:
            return cached[1]
        from app.analysis_cache import PACKET_TTL_SECONDS, read_json

        disk = read_json("xg-ekpi", str(mid), ttl=PACKET_TTL_SECONDS, allow_stale=True)
        if disk is not None:
            return _fetch_shot_xg_by_event(mid, refresh=False)
    return _fetch_shot_xg_by_event(mid, refresh=True)


def _league_shots_for_match(match_id: int, *, refresh: bool = False) -> list[dict[str, Any]]:
    events = _fetch_match_events(match_id, refresh=refresh)
    xg_by_event = _shot_xg_map(match_id, refresh=refresh)
    shots: list[dict[str, Any]] = []
    for event in events:
        if event.get("actionType") != "SHOT":
            continue
        event_id = int(event.get("id") or 0)
        try:
            xg = round(float(xg_by_event.get(event_id, 0.0)), 3)
        except (TypeError, ValueError):
            xg = 0.0
        rating = _classify_chance(xg)
        minimal = {
            "xg": xg,
            "inBox": _in_box(event),
            "action": _event_action(event),
            "isPenalty": _is_penalty_event(event),
        }
        shots.append(
            {
                "squadId": int(event.get("squadId") or 0),
                "ratingId": rating["id"],
                "isPenalty": _is_penalty_shot(minimal),
            }
        )
    return shots


def _completed_league_matches(matches_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in matches_by_id.values():
        if match.get("id") is None or not _match_is_complete(match):
            continue
        home = int(match.get("homeSquadId") or -1)
        away = int(match.get("awaySquadId") or -1)
        if home <= 0 or away <= 0 or home == away:
            continue
        rows.append(match)
    rows.sort(key=_match_day_index)
    return rows


def _league_cache_key(season: str) -> str:
    token = (season or "default").replace("/", "-")
    return f"league_{token}"


def _tallies_from_cache(cached: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, str]]:
    tallies: dict[int, dict[str, Any]] = {}
    for key, tally in (cached.get("teams") or {}).items():
        if not isinstance(tally, dict):
            continue
        tallies[int(key)] = tally
    names = {
        int(key): str(name)
        for key, name in (cached.get("squads") or {}).items()
        if name
    }
    return tallies, names


def build_xg_chance_league_table(
    season: str | None = None,
    *,
    exclude_penalties: bool = False,
    refresh: bool = False,
) -> dict[str, Any]:
    """Rank every team in the selected competition/season by chance-quality bands."""
    from app.analysis_cache import REPORT_TTL_SECONDS, read_json, write_json

    def _read_cache(key: str) -> dict[str, Any] | None:
        if refresh:
            return None
        stored = read_json("xg-league", key, ttl=REPORT_TTL_SECONDS, allow_stale=True)
        if isinstance(stored, dict) and stored.get("teams"):
            return stored
        return None

    cached = _read_cache(_league_cache_key(season or "default")) if season else None
    iteration: dict[str, Any] | None = None
    if cached is None:
        iteration = _resolve_port_vale_iteration(season)
        season_label = str(iteration.get("season") or season or "")
        competition = str(iteration.get("competition_name") or "")
        cached = _read_cache(_league_cache_key(season_label or (season or "default")))
    else:
        season_label = str(cached.get("season") or season or "")
        competition = str(cached.get("competition") or "")

    if cached is None:
        assert iteration is not None
        iteration_id = int(iteration["id"])
        matches_by_id = _iteration_matches_by_id(iteration_id)
        completed = _completed_league_matches(matches_by_id)
        squads = _squads_map(iteration_id)
        names = {
            int(squad_id): str(squad.get("name") or f"Squad {squad_id}")
            for squad_id, squad in squads.items()
        }

        match_rows: list[dict[str, Any]] = []
        skipped: list[int] = []

        def _one(match: dict[str, Any]) -> dict[str, Any]:
            mid = int(match["id"])
            return {
                "homeSquadId": int(match.get("homeSquadId") or 0),
                "awaySquadId": int(match.get("awaySquadId") or 0),
                "shots": _league_shots_for_match(mid, refresh=refresh),
            }

        if len(completed) <= 1:
            for match in completed:
                try:
                    match_rows.append(_one(match))
                except Exception:
                    logger.exception("League table skipped match %s", match.get("id"))
                    skipped.append(int(match["id"]))
        else:
            workers = min(8, len(completed))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_one, match): match for match in completed}
                for future in as_completed(futures):
                    match = futures[future]
                    try:
                        match_rows.append(future.result())
                    except Exception:
                        logger.exception("League table skipped match %s", match.get("id"))
                        skipped.append(int(match["id"]))

        tallies = tally_league_matches(match_rows)
        for squad_id in list(tallies):
            if squad_id not in names:
                names[squad_id] = f"Squad {squad_id}"
        updated_at = datetime.now(UTC).isoformat()
        cached = {
            "season": season_label,
            "competition": competition,
            "matchCount": len(match_rows),
            "skippedMatchCount": len(skipped),
            "teams": {str(squad_id): tally for squad_id, tally in tallies.items()},
            "squads": {str(squad_id): name for squad_id, name in names.items() if squad_id in tallies},
            "updatedAt": updated_at,
        }
        if match_rows and not skipped:
            write_json("xg-league", _league_cache_key(season_label or (season or "default")), cached)

    tallies, names = _tallies_from_cache(cached)
    rows = league_rows_from_tallies(tallies, names, exclude_penalties=exclude_penalties)
    return _league_table_payload(
        season=str(cached.get("season") or season_label),
        competition=str(cached.get("competition") or competition),
        match_count=int(cached.get("matchCount") or 0),
        skipped_match_count=int(cached.get("skippedMatchCount") or 0),
        rows=rows,
        exclude_penalties=exclude_penalties,
        updated_at=str(cached.get("updatedAt") or "") or None,
    )


def register_xg_chance_analysis_routes(app: FastAPI) -> None:
    @app.get("/xg-chance-analysis")
    def xg_chance_analysis_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "xg-chance-analysis.html")

    @app.get("/api/xg-chance-analysis/meta")
    def xg_chance_meta_route() -> dict[str, Any]:
        return xg_chance_meta()

    @app.get("/api/xg-chance-analysis/fixtures")
    def xg_chance_fixtures_route(
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        fixtures = build_xg_chance_fixtures(season, refresh=False)
        return {
            "fixtures": fixtures,
            "defaultMatchId": _default_fixture_match_id(fixtures),
        }

    @app.get("/api/xg-chance-analysis/report")
    def xg_chance_report_route(
        season: str | None = Query(None),
        match_id: int | None = Query(None, alias="matchId"),
        scope: str | None = Query(None),
        refresh: bool = Query(False),
        exclude_penalties: bool = Query(False, alias="excludePenalties"),
    ) -> JSONResponse:
        try:
            payload = build_xg_chance_report(
                season=season,
                match_id=match_id,
                scope=scope,
                refresh=False,
                exclude_penalties=exclude_penalties,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/xg-chance-analysis/league-table")
    def xg_chance_league_table_route(
        season: str | None = Query(None),
        exclude_penalties: bool = Query(False, alias="excludePenalties"),
    ) -> JSONResponse:
        try:
            payload = build_xg_chance_league_table(
                season=season,
                exclude_penalties=exclude_penalties,
                refresh=False,
            )
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
                refresh=False,
                exclude_penalties=body.exclude_penalties,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/xg-chance-analysis/export-pdf")
    def xg_chance_export_pdf_route(
        season: str | None = Query(None),
        scope: str | None = Query("match"),
        match_id: int | None = Query(None, alias="matchId"),
        match_ids: str | None = Query(None, alias="matchIds"),
        exclude_penalties: bool = Query(False, alias="excludePenalties"),
    ) -> Response:
        from app.xg_chance_analysis_pdf import build_xg_chance_analysis_pdf

        normalized = (scope or "match").strip().lower()
        if normalized not in {"match", "last6", "season"}:
            raise HTTPException(status_code=400, detail="scope must be match, last6, or season")

        selected_ids: list[int] | None = None
        if match_ids:
            try:
                selected_ids = [int(part) for part in match_ids.split(",") if part.strip()]
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="matchIds must be integers") from exc

        if selected_ids and len(selected_ids) == 1:
            match_id = selected_ids[0]
            selected_ids = None
            normalized = "match"

        try:
            report = build_xg_chance_report(
                season=season,
                match_id=match_id if not selected_ids else None,
                match_ids=selected_ids,
                scope=None if selected_ids else normalized,
                exclude_penalties=exclude_penalties,
            )
            pdf_scope = "match" if int(report.get("matchCount") or 0) <= 1 else "last6"
            if normalized == "season" and not selected_ids:
                pdf_scope = "season"
            pdf_bytes = build_xg_chance_analysis_pdf(report, scope=pdf_scope)
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
