from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

CROSS_ACTIONS = frozenset({"HIGH_CROSS", "LOW_CROSS"})

# Squad KPIs — defenders bypassed from each lane (Impect lane order).
LANE_BYPASS_KPIS: tuple[tuple[str, str, int], ...] = (
    ("leftWing", "Left Wing", 216),
    ("leftHalfSpace", "Left Half-Space", 215),
    ("center", "Centre", 214),
    ("rightHalfSpace", "Right Half-Space", 213),
    ("rightWing", "Right Wing", 212),
)

# Compact cross-map buckets on the attacking third.
PACKING_ZONE_TO_MAP_BUCKET: dict[str, str] = {
    "WL": "leftWide",
    "AML": "leftCentre",
    "CML": "leftCentre",
    "CMR": "centre",
    "AMC": "centre",
    "AMR": "rightWide",
    "WR": "rightWide",
    "FBL": "leftWide",
    "FBR": "rightWide",
}

# Impect pitch: 105m x 68m. adjCoordinates: +x attacks the goal at x=52.5, +y is left wing.
# Frontend maps to SVG with goal at top and +y → screen left (see crossImpectToSvg).
PITCH_GOAL_X = 52.5
PITCH_WIDTH_M = 68.0
PITCH_HALF_WIDTH_M = PITCH_WIDTH_M / 2.0
FINAL_THIRD_MIN_X = 17.5
LANE_WIDTH_M = PITCH_WIDTH_M / 5.0
PITCH_CHANNEL_BOUNDARIES_M: tuple[float, ...] = (
    -PITCH_HALF_WIDTH_M + LANE_WIDTH_M,
    -LANE_WIDTH_M,
    LANE_WIDTH_M,
    PITCH_HALF_WIDTH_M - LANE_WIDTH_M,
)

MAP_BUCKET_LABELS: dict[str, str] = {
    "leftWide": "Left wide",
    "leftCentre": "Left centre",
    "rightWide": "Right wide",
}

MAP_BUCKET_BOUNDS: dict[str, dict[str, float]] = {
    "leftWide": {"xMin": 26.0, "xMax": PITCH_GOAL_X, "yMin": 11.0, "yMax": PITCH_HALF_WIDTH_M},
    "leftCentre": {"xMin": FINAL_THIRD_MIN_X, "xMax": PITCH_GOAL_X, "yMin": 0.0, "yMax": 11.0},
    "rightWide": {"xMin": FINAL_THIRD_MIN_X, "xMax": PITCH_GOAL_X, "yMin": -PITCH_HALF_WIDTH_M, "yMax": 0.0},
}

MAP_BUCKET_ORDER: tuple[str, ...] = ("leftWide", "leftCentre", "rightWide")

EVENT_KPI_ALTERED_THREAT = 1404  # PXT_PASS on cross events → altered threat total


def _player_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _altered_threat_by_event(
    event_kpis: list[dict[str, Any]],
    cross_event_ids: set[int],
) -> dict[int, float]:
    totals: dict[int, float] = defaultdict(float)
    for row in event_kpis:
        event_id = int(row.get("eventId") or 0)
        if event_id not in cross_event_ids:
            continue
        if int(row.get("kpiId") or -1) != EVENT_KPI_ALTERED_THREAT:
            continue
        totals[event_id] += float(row.get("value") or 0)
    return totals


def _is_cross_event(event: dict[str, Any]) -> bool:
    return event.get("action") in CROSS_ACTIONS


def _start_coords(event: dict[str, Any]) -> tuple[float, float] | None:
    start = event.get("start") or {}
    coords = start.get("adjCoordinates") or start.get("coordinates") or {}
    x, y = coords.get("x"), coords.get("y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def _map_bucket_for_event(event: dict[str, Any]) -> str:
    start = event.get("start") or {}
    packing_zone = str(start.get("packingZone") or "").upper()
    if packing_zone in PACKING_ZONE_TO_MAP_BUCKET:
        return PACKING_ZONE_TO_MAP_BUCKET[packing_zone]
    lane = str(start.get("lane") or "").upper()
    if lane == "LEFT_WING":
        return "leftWide"
    if lane == "RIGHT_WING":
        return "rightWide"
    if lane in {"LEFT_HALF_SPACE", "CENTER", "RIGHT_HALF_SPACE"}:
        return "leftCentre" if lane != "RIGHT_HALF_SPACE" else "rightWide"
    return "leftCentre"


def _cross_event_ids(events: list[dict[str, Any]], focus_squad_id: int) -> set[int]:
    return {
        int(event["id"])
        for event in events
        if _is_cross_event(event) and int(event.get("squadId") or 0) == focus_squad_id
    }


def _altered_threat_by_player(
    event_kpis: list[dict[str, Any]],
    cross_event_ids: set[int],
) -> dict[int, float]:
    totals: dict[int, float] = defaultdict(float)
    for row in event_kpis:
        event_id = int(row.get("eventId") or 0)
        if event_id not in cross_event_ids:
            continue
        if int(row.get("kpiId") or -1) != EVENT_KPI_ALTERED_THREAT:
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        totals[player_id] += float(row.get("value") or 0)
    return totals


def _cross_counts_by_player(events: list[dict[str, Any]], focus_squad_id: int) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for event in events:
        if not _is_cross_event(event):
            continue
        if int(event.get("squadId") or 0) != focus_squad_id:
            continue
        player_id = int((event.get("player") or {}).get("id") or 0)
        if player_id:
            counts[player_id] += 1
    return counts


def _match_cross_altered_threat(match_id: int, focus_squad_id: int) -> float:
    events = extract_rows(impect_get(v5_path(f"/matches/{match_id}/events"))["data"])
    event_kpis = extract_rows(impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"])
    cross_event_ids = _cross_event_ids(events, focus_squad_id)
    total = 0.0
    for row in event_kpis:
        if int(row.get("eventId") or 0) not in cross_event_ids:
            continue
        if int(row.get("kpiId") or -1) != EVENT_KPI_ALTERED_THREAT:
            continue
        total += float(row.get("value") or 0)
    return round(total * 100.0, 2)


def _match_lane_bypass_values(match_id: int, focus_squad_id: int) -> dict[str, float]:
    from app.post_match.report import _flatten_squad_kpis

    squad_kpis = _flatten_squad_kpis(
        impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"]
    )
    focus_kpis = squad_kpis.get(focus_squad_id, {})
    return {
        lane_id: float(focus_kpis.get(kpi_id, 0))
        for lane_id, _label, kpi_id in LANE_BYPASS_KPIS
    }


def _match_cross_baseline_metrics(
    match_id: int,
    focus_squad_id: int,
) -> tuple[float, dict[str, float]]:
    altered_threat = _match_cross_altered_threat(match_id, focus_squad_id)
    lane_values = _match_lane_bypass_values(match_id, focus_squad_id)
    return altered_threat, lane_values


def _crosses_baseline_against(
    iteration_id: int,
    focus_squad_id: int,
    *,
    before_match_id: int,
    game_count: int = 7,
) -> dict[str, Any]:
    """7-game average of opponent lane bypass in the focus team's recent matches."""
    from app.post_match.report import _match_meta

    recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )
    if not recent_ids:
        return {"alteredThreatAvg": None, "gameCount": 0, "lanes": []}

    threat_values: list[float] = []
    lane_totals: dict[str, list[float]] = defaultdict(list)
    for recent_id in recent_ids:
        meta = _match_meta(recent_id, iteration_id)
        home_id = int(meta["home"]["squadId"] or 0)
        away_id = int(meta["away"]["squadId"] or 0)
        if focus_squad_id == home_id and away_id:
            opponent_id = away_id
        elif focus_squad_id == away_id and home_id:
            opponent_id = home_id
        else:
            continue
        altered_threat, lane_values = _match_cross_baseline_metrics(recent_id, opponent_id)
        threat_values.append(altered_threat)
        for lane_id, value in lane_values.items():
            lane_totals[lane_id].append(value)

    if not threat_values:
        return {"alteredThreatAvg": None, "gameCount": 0, "lanes": []}

    baseline_lanes: list[dict[str, Any]] = []
    baseline_lane_values: list[int] = []
    for lane_id, label, _kpi_id in LANE_BYPASS_KPIS:
        samples = lane_totals.get(lane_id, [])
        avg_value = (sum(samples) / len(samples)) if samples else 0.0
        rounded = int(round(avg_value))
        baseline_lane_values.append(rounded)
        baseline_lanes.append(
            {
                "id": lane_id,
                "label": label,
                "value": rounded,
                "avgValue": round(avg_value, 1),
            }
        )

    return {
        "alteredThreatAvg": round(sum(threat_values) / len(threat_values), 2),
        "gameCount": len(threat_values),
        "lanes": baseline_lanes,
        "maxLaneValue": max(baseline_lane_values, default=1) or 1,
    }


def _crosses_baseline(
    iteration_id: int,
    focus_squad_id: int,
    *,
    before_match_id: int,
    game_count: int = 7,
) -> dict[str, Any]:
    recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )
    if not recent_ids:
        return {"alteredThreatAvg": None, "gameCount": 0, "lanes": []}

    threat_values: list[float] = []
    lane_totals: dict[str, list[float]] = defaultdict(list)
    workers = min(8, len(recent_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_match_cross_baseline_metrics, mid, focus_squad_id): mid
            for mid in recent_ids
        }
        for future in as_completed(futures):
            altered_threat, lane_values = future.result()
            threat_values.append(altered_threat)
            for lane_id, value in lane_values.items():
                lane_totals[lane_id].append(value)

    if not threat_values:
        return {"alteredThreatAvg": None, "gameCount": 0, "lanes": []}

    baseline_lanes: list[dict[str, Any]] = []
    baseline_lane_values: list[int] = []
    for lane_id, label, _kpi_id in LANE_BYPASS_KPIS:
        samples = lane_totals.get(lane_id, [])
        avg_value = (sum(samples) / len(samples)) if samples else 0.0
        rounded = int(round(avg_value))
        baseline_lane_values.append(rounded)
        baseline_lanes.append(
            {
                "id": lane_id,
                "label": label,
                "value": rounded,
                "avgValue": round(avg_value, 1),
            }
        )

    return {
        "alteredThreatAvg": round(sum(threat_values) / len(threat_values), 2),
        "gameCount": len(threat_values),
        "lanes": baseline_lanes,
        "maxLaneValue": max(baseline_lane_values, default=1) or 1,
    }


def build_crosses(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None = None,
    *,
    opponent_squad_id: int | None = None,
    title: str = "In-Possession — Crosses",
    defensive: bool = False,
) -> dict[str, Any]:
    from app.post_match.report import _flatten_squad_kpis, _player_directory, _iteration_goalkeeper_ids, _exclude_goalkeeper_ids

    cross_squad_id = (
        int(opponent_squad_id)
        if defensive and opponent_squad_id
        else focus_squad_id
    )

    events = extract_rows(impect_get(v5_path(f"/matches/{match_id}/events"))["data"])
    event_kpis = extract_rows(impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"])
    squad_kpis = _flatten_squad_kpis(impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"])
    lane_kpis = squad_kpis.get(cross_squad_id, {})

    focus_crosses = [
        event for event in events
        if _is_cross_event(event) and int(event.get("squadId") or 0) == cross_squad_id
    ]
    cross_event_ids = _cross_event_ids(events, cross_squad_id)
    threat_by_event = _altered_threat_by_event(event_kpis, cross_event_ids)

    player_names: dict[int, str] = {}
    goalkeeper_ids: set[int] = set()
    if iteration_id:
        iteration_id = int(iteration_id)
        player_names = _player_directory(iteration_id)
        goalkeeper_ids = _iteration_goalkeeper_ids(iteration_id)

    bucket_counts: dict[str, int] = defaultdict(int)
    cross_points: list[dict[str, Any]] = []
    high_cross = 0
    low_cross = 0
    successful = 0
    for event in focus_crosses:
        bucket_counts[_map_bucket_for_event(event)] += 1
        action = str(event.get("action") or "")
        result = str(event.get("result") or "")
        if action == "HIGH_CROSS":
            high_cross += 1
        elif action == "LOW_CROSS":
            low_cross += 1
        if result == "SUCCESS":
            successful += 1
        coords = _start_coords(event)
        if coords:
            event_id = int(event["id"])
            player = event.get("player") or {}
            player_id = int(player.get("id") or 0)
            player_name = player_names.get(player_id) if player_id else None
            if not player_name:
                player_name = str(player.get("commonname") or player.get("name") or "").strip()
            cross_points.append(
                {
                    "eventId": event_id,
                    "impectX": coords[0],
                    "impectY": coords[1],
                    "action": action,
                    "result": result,
                    "alteredThreat": round(threat_by_event.get(event_id, 0.0) * 100.0, 2),
                    "playerId": player_id or None,
                    "playerName": player_name or None,
                    "playerInitials": _player_initials(player_name),
                }
            )

    map_zones = []
    for bucket_id in MAP_BUCKET_ORDER:
        bounds = MAP_BUCKET_BOUNDS[bucket_id]
        map_zones.append(
            {
                "id": bucket_id,
                "label": MAP_BUCKET_LABELS[bucket_id],
                "count": bucket_counts.get(bucket_id, 0),
                "bounds": bounds,
            }
        )

    lanes = []
    lane_values = []
    for lane_id, label, kpi_id in LANE_BYPASS_KPIS:
        value = int(round(lane_kpis.get(kpi_id, 0)))
        lane_values.append(value)
        lanes.append({"id": lane_id, "label": label, "value": value})

    max_lane = max(lane_values, default=1) or 1

    cross_counts = _cross_counts_by_player(events, cross_squad_id)
    successful_by_player: dict[int, int] = defaultdict(int)
    for event in focus_crosses:
        if str(event.get("result") or "") != "SUCCESS":
            continue
        player_id = int((event.get("player") or {}).get("id") or 0)
        if player_id:
            successful_by_player[player_id] += 1

    altered_threat = _altered_threat_by_player(event_kpis, cross_event_ids)

    players: list[dict[str, Any]] = []
    for player_id, crosses in cross_counts.items():
        threat = altered_threat.get(player_id, 0.0) * 100.0
        players.append(
            {
                "playerId": player_id,
                "playerName": player_names.get(player_id, f"Player {player_id}"),
                "crosses": crosses,
                "successful": successful_by_player.get(player_id, 0),
                "alteredThreat": round(threat, 2),
            }
        )

    players.sort(key=lambda row: (-row["crosses"], -row["alteredThreat"], row["playerName"]))
    players = _exclude_goalkeeper_ids(players, goalkeeper_ids)

    top_threat = sorted({row["alteredThreat"] for row in players}, reverse=True)[:1]
    for row in players:
        row["highlightThreat"] = row["alteredThreat"] in top_threat and row["alteredThreat"] > 0

    match_altered_threat = round(sum(altered_threat.values()) * 100.0, 2)
    if iteration_id:
        if defensive:
            baseline = _crosses_baseline_against(
                int(iteration_id),
                focus_squad_id,
                before_match_id=match_id,
                game_count=7,
            )
        else:
            baseline = _crosses_baseline(
                int(iteration_id),
                focus_squad_id,
                before_match_id=match_id,
                game_count=7,
            )
    else:
        baseline = {"alteredThreatAvg": None, "gameCount": 0, "lanes": [], "maxLaneValue": 1}

    description = (
        "Opponent cross origins, defenders bypassed against us by flank, and crossing threat"
        if defensive
        else "Cross origins, defenders bypassed by flank, and player crossing threat"
    )
    lane_strip_title = (
        "DEFENDERS BYPASSED AGAINST"
        if defensive
        else "DEFENDERS BYPASSED BY FLANK"
    )

    return {
        "title": title,
        "description": description,
        "defensive": defensive,
        "laneStripTitle": lane_strip_title,
        "squadId": cross_squad_id,
        "totalCrosses": len(focus_crosses),
        "summary": {
            "total": len(focus_crosses),
            "highCross": high_cross,
            "lowCross": low_cross,
            "successful": successful,
            "failed": len(focus_crosses) - successful,
            "alteredThreat": match_altered_threat,
            "alteredThreatAvg": baseline.get("alteredThreatAvg"),
            "baselineGameCount": baseline.get("gameCount", 0),
        },
        "mapZones": map_zones,
        "crossPoints": cross_points,
        "pitch": {
            "goalX": PITCH_GOAL_X,
            "minX": FINAL_THIRD_MIN_X,
            "widthM": PITCH_WIDTH_M,
            "depthM": PITCH_GOAL_X - FINAL_THIRD_MIN_X,
            "channelBoundariesM": list(PITCH_CHANNEL_BOUNDARIES_M),
            "penaltySpotM": 11.0,
            "penaltyArcM": 9.15,
            "penaltyBoxDepthM": 16.5,
        },
        "lanes": lanes,
        "maxLaneValue": max_lane,
        "lanesBaseline": baseline.get("lanes", []),
        "maxLaneBaselineValue": baseline.get("maxLaneValue", 1),
        "baselineGameCount": baseline.get("gameCount", 0),
        "players": players,
    }
