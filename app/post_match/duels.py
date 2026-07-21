from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.post_match.ball_progression import (
    _average_metric_values,
    _build_team_metric_row,
    _iteration_kpi_values,
    _iteration_score_values,
    _load_match_team_data,
    _metric_value,
    _performance_band,
    _rank_for_value,
)
from app.post_match.impect_client import impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

KPI_BALL_WIN_REMOVED_OPPONENTS = 24
KPI_WON_GROUND_DUELS = 94
KPI_LOST_GROUND_DUELS = 95
KPI_WON_AERIAL_DUELS = 96
KPI_LOST_AERIAL_DUELS = 97
KPI_BALL_WIN_ADDED_TEAMMATES = 23
KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS = 25

OFFENSIVE_INTERVENTION_ACTION_KPIS: tuple[int, ...] = (
    963,  # BALL_WIN_NUMBER_BY_ACTION_DUEL
    964,  # BALL_WIN_NUMBER_BY_ACTION_LOOSE_BALL_REGAIN
    965,  # BALL_WIN_NUMBER_BY_ACTION_INTERCEPTION
    966,  # BALL_WIN_NUMBER_BY_ACTION_HEADER
)

SQUAD_SCORE_RATIO_GROUND_DUELS = 28
SQUAD_SCORE_RATIO_AERIAL_DUELS = 29
SQUAD_SCORE_RATIO_SECOND_BALL_WINS = 96
SQUAD_SCORE_MEAN_PRESSURE_HEIGHT = 57

SQUAD_SCORE_PRESSURE_BUILD_UP_INTENSITY = 58
SQUAD_SCORE_COUNTER_PRESS_INTENSITY = 61
SQUAD_SCORE_PRESSURE_BUILD_UP_PERCENT = 62
SQUAD_SCORE_OPENING_BALLS_PRESSED_PERCENT = 63
SQUAD_SCORE_HIGH_PRESSURE_BTL_PERCENT = 67
KPI_NUMBER_OF_PRESSES = 1536
PITCH_HALF_LENGTH_M = 52.5
PITCH_HALF_WIDTH_M = 34.0
PITCH_WIDTH_M = 68.0
PITCH_LENGTH_M = 105.0

# Must stay in sync with `_zone_label` / frontend zone heat cells.
OOP_ZONE_KEYS: tuple[str, ...] = (
    "Attacking third · left",
    "Attacking third · centre",
    "Attacking third · right",
    "Middle third · left",
    "Middle third · centre",
    "Middle third · right",
    "Defensive third · left",
    "Defensive third · centre",
    "Defensive third · right",
)

ACTIVITY_LAYERS: tuple[dict[str, Any], ...] = (
    {
        "id": "press",
        "label": "Pressure on ball",
        "title": "Pressure Map",
        "kpiIds": frozenset({KPI_NUMBER_OF_PRESSES}),
        "color": "#f59e0b",
        "shape": "circle",
        "renderMode": "zoneHeat",
        "breakdownMode": "zone",
        "note": "% = share of all presses. Darker zone = more volume.",
    },
    {
        "id": "defenderRegain",
        "label": "Regain vs defenders",
        "title": "Regains vs Defenders",
        "kpiIds": frozenset({KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS}),
        "color": "#e11d48",
        "shape": "diamond",
        "breakdownMode": "subtype",
        "note": "Pink diamonds = ball wins that removed opposition defenders (initials on marker). Split by how the regain was won.",
    },
    {
        "id": "duelWin",
        "label": "Duel won",
        "title": "Duels Won",
        "kpiIds": frozenset({KPI_WON_GROUND_DUELS, KPI_WON_AERIAL_DUELS}),
        "color": "#facc15",
        "shape": "square",
        "breakdownMode": "subtype",
        "note": "Yellow = ground duel won · Blue = aerial duel won (initials on marker).",
    },
)

REGAIN_SUBTYPE_LABELS: dict[str, str] = {
    "INTERCEPTION": "Interception",
    "LOOSE_BALL_REGAIN": "Loose ball",
    "GROUND_DUEL": "Ground duel",
    "AERIAL_DUEL": "Aerial duel",
    "HEADER": "Header",
    "DUEL": "Duel",
    "BLOCK": "Block",
}

DUEL_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "groundDuels",
        "label": "Ground Duels",
        "metricColor": "#f59e0b",
        "source": "score",
        "key": SQUAD_SCORE_RATIO_GROUND_DUELS,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "aerialDuels",
        "label": "Aerial Duels",
        "metricColor": "#8b5cf6",
        "source": "score",
        "key": SQUAD_SCORE_RATIO_AERIAL_DUELS,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "ballWinsRemovedOpponents",
        "label": "Ball Wins Removed Opponents",
        "metricColor": "#22c55e",
        "source": "kpi",
        "key": KPI_BALL_WIN_REMOVED_OPPONENTS,
        "higherIsBetter": True,
        "format": "int",
    },
    {
        "id": "secondBallWinRate",
        "label": "Second Ball Win Rate %",
        "metricColor": "#f97316",
        "source": "score",
        "key": SQUAD_SCORE_RATIO_SECOND_BALL_WINS,
        "higherIsBetter": True,
        "format": "percent",
    },
)

PRESSING_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "averagePressureHeight",
        "label": "Average Pressure Height",
        "metricColor": "#0ea5e9",
        "source": "score",
        "key": SQUAD_SCORE_MEAN_PRESSURE_HEIGHT,
        "higherIsBetter": True,
        "format": "meters",
    },
    {
        "id": "pressureBuildUpPct",
        "label": "Press in Build-Up %",
        "metricColor": "#06b6d4",
        "source": "score",
        "key": SQUAD_SCORE_PRESSURE_BUILD_UP_PERCENT,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "pressureBuildUpIntensity",
        "label": "Press in Build-Up (intensity)",
        "metricColor": "#0891b2",
        "source": "score",
        "key": SQUAD_SCORE_PRESSURE_BUILD_UP_INTENSITY,
        "higherIsBetter": True,
        "format": "decimal",
    },
    {
        "id": "highPressureBtl",
        "label": "High Press Between Lines %",
        "metricColor": "#6366f1",
        "source": "score",
        "key": SQUAD_SCORE_HIGH_PRESSURE_BTL_PERCENT,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "counterPressIntensity",
        "label": "Counter-Press Intensity",
        "metricColor": "#a855f7",
        "source": "score",
        "key": SQUAD_SCORE_COUNTER_PRESS_INTENSITY,
        "higherIsBetter": True,
        "format": "decimal",
    },
    {
        "id": "openingBallsPressed",
        "label": "Opening Balls Pressed %",
        "metricColor": "#14b8a6",
        "source": "score",
        "key": SQUAD_SCORE_OPENING_BALLS_PRESSED_PERCENT,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "numberOfPresses",
        "label": "Number of Presses",
        "metricColor": "#f59e0b",
        "source": "kpi",
        "key": KPI_NUMBER_OF_PRESSES,
        "higherIsBetter": True,
        "format": "int",
    },
)

TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = DUEL_METRIC_SPECS + PRESSING_METRIC_SPECS


def _format_metric_value(value: float | None, fmt: str) -> str | None:
    if value is None:
        return None
    if fmt == "percent":
        return f"{round(value * 100, 1)}%".replace(".0%", "%")
    if fmt == "meters":
        rounded = round(value, 1)
        display = str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"
        return f"{display}M"
    return str(int(round(value)))


def _duel_fraction(won: float, lost: float) -> tuple[str, int, int]:
    won_i = int(round(won or 0))
    lost_i = int(round(lost or 0))
    total = won_i + lost_i
    if total <= 0:
        if won_i > 0:
            return str(won_i), won_i, 0
        return "0", 0, 0
    return f"{won_i}/{total}", won_i, total


def _extract_player_metrics(kpis: dict[int, float]) -> dict[str, Any]:
    ground_display, ground_won, ground_total = _duel_fraction(
        kpis.get(KPI_WON_GROUND_DUELS, 0),
        kpis.get(KPI_LOST_GROUND_DUELS, 0),
    )
    aerial_display, aerial_won, aerial_total = _duel_fraction(
        kpis.get(KPI_WON_AERIAL_DUELS, 0),
        kpis.get(KPI_LOST_AERIAL_DUELS, 0),
    )

    total_won = ground_won + aerial_won
    total_attempts = ground_total + aerial_total
    total_win_pct = (
        round((total_won / total_attempts) * 100) if total_attempts > 0 else None
    )

    offensive_interventions = sum(
        int(round(kpis.get(kpi_id, 0) or 0)) for kpi_id in OFFENSIVE_INTERVENTION_ACTION_KPIS
    )
    defensive_interventions = int(round(kpis.get(KPI_BALL_WIN_ADDED_TEAMMATES, 0) or 0))
    ball_wins_from_defenders = int(
        round(kpis.get(KPI_BALL_WIN_REMOVED_OPPONENTS_DEFENDERS, 0) or 0)
    )

    return {
        "groundDuelsWin": ground_display,
        "aerialDuelsWin": aerial_display,
        "totalWinPct": total_win_pct,
        "offensiveInterventions": offensive_interventions,
        "defensiveInterventions": defensive_interventions,
        "ballWinsFromOppositionDefenders": ball_wins_from_defenders,
    }


def _fetch_match_player_rows(
    match_id: int,
    player_names: dict[int, str],
) -> tuple[int, list[dict[str, Any]]]:
    from app.post_match.report import _flatten_player_kpis

    players = _flatten_player_kpis(
        impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"],
        player_names,
    )
    return match_id, players


def _load_match_player_rows(
    match_ids: set[int],
    player_names: dict[int, str],
) -> dict[int, list[dict[str, Any]]]:
    if not match_ids:
        return {}
    loaded: dict[int, list[dict[str, Any]]] = {}
    workers = min(12, len(match_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_match_player_rows, match_id, player_names): match_id
            for match_id in match_ids
        }
        for future in as_completed(futures):
            match_id, players = future.result()
            loaded[match_id] = players
    return loaded


def _compute_player_baselines(
    match_ids: list[int],
    focus_squad_id: int,
    players_by_match: dict[int, list[dict[str, Any]]],
) -> dict[int, dict[str, float | None]]:
    from app.post_match.report import _consolidate_player_match_rows

    totals: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for match_id in match_ids:
        squad_rows = [
            row
            for row in players_by_match.get(match_id, [])
            if int(row.get("squadId") or 0) == focus_squad_id
        ]
        for row in _consolidate_player_match_rows(squad_rows):
            minutes = float(row.get("minutes") or 0) / 60.0
            if minutes <= 0:
                continue
            metrics = _extract_player_metrics(row.get("kpis") or {})
            player_id = int(row["playerId"])
            if metrics["totalWinPct"] is not None:
                totals[player_id]["totalWinPct"].append(float(metrics["totalWinPct"]))
            totals[player_id]["offensiveInterventions"].append(
                float(metrics["offensiveInterventions"])
            )
            totals[player_id]["defensiveInterventions"].append(
                float(metrics["defensiveInterventions"])
            )
            totals[player_id]["ballWinsFromOppositionDefenders"].append(
                float(metrics["ballWinsFromOppositionDefenders"])
            )

    baselines: dict[int, dict[str, float | None]] = {}
    for player_id, metric_lists in totals.items():
        baselines[player_id] = {
            key: _average_metric_values(values) for key, values in metric_lists.items()
        }
    return baselines


def _format_player_avg(value: float | None, *, as_percent: bool = False) -> str | None:
    if value is None:
        return None
    if as_percent:
        return f"{round(value)}% avg"
    rounded = int(round(value))
    return f"{rounded} avg"


def _event_map_coords(event: dict[str, Any]) -> tuple[float, float] | None:
    point = event.get("start") or {}
    coords = point.get("adjCoordinates") or point.get("coordinates") or {}
    try:
        return float(coords["x"]), float(coords["y"])
    except (TypeError, ValueError, KeyError):
        return None


def _normalize_attacking_up(
    x: float,
    y: float,
    event: dict[str, Any],
    focus_squad_id: int,
) -> tuple[float, float]:
    """Flip opponent-attack frames so focus always attacks toward +x (top of map)."""
    try:
        attacking = int(event.get("currentAttackingSquadId") or 0)
    except (TypeError, ValueError):
        attacking = 0
    if attacking and attacking != focus_squad_id:
        return -x, -y
    return x, y


def _zone_label(x: float, y: float) -> str:
    if x < -17.5:
        third = "Defensive third"
    elif x > 17.5:
        third = "Attacking third"
    else:
        third = "Middle third"
    if y > 11:
        side = "left"
    elif y < -11:
        side = "right"
    else:
        side = "centre"
    return f"{third} · {side}"


def _densest_zone(points: list[dict[str, Any]]) -> str | None:
    if not points:
        return None
    counts: dict[str, int] = defaultdict(int)
    for point in points:
        counts[
            str(point.get("zone") or _zone_label(float(point["impectX"]), float(point["impectY"])))
        ] += 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _zone_heat_cells(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for point in points:
        key = str(point.get("zone") or "Unknown")
        if key in OOP_ZONE_KEYS:
            counts[key] += 1
    total = len(points) or 1
    max_count = max(counts.values()) if counts else 0
    return [
        {
            "key": key,
            "count": counts.get(key, 0),
            "sharePct": round(100.0 * counts.get(key, 0) / total),
            "intensity": round(counts.get(key, 0) / max_count, 3) if max_count else 0.0,
        }
        for key in OOP_ZONE_KEYS
    ]


def _player_display_name(player_id: int, player_names: dict[int, str]) -> str:
    name = str(player_names.get(player_id) or "").strip()
    return name or f"Player {player_id}"


def _player_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _point_subtype(
    layer_id: str,
    kpi_id: int,
    event: dict[str, Any],
) -> tuple[str | None, str | None]:
    if layer_id == "duelWin":
        if kpi_id == KPI_WON_AERIAL_DUELS:
            return "aerial", "Aerial"
        return "ground", "Ground"
    if layer_id == "defenderRegain":
        raw = str(event.get("actionType") or event.get("action") or "").upper()
        label = REGAIN_SUBTYPE_LABELS.get(raw)
        if not label:
            label = raw.replace("_", " ").title() if raw else "Other"
        return raw or "OTHER", label
    return None, None


def _layer_top_players(
    points: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    by_player: dict[int, dict[str, Any]] = {}
    for point in points:
        player_id = int(point.get("playerId") or 0)
        if not player_id:
            continue
        bucket = by_player.setdefault(
            player_id,
            {
                "playerId": player_id,
                "playerName": point.get("playerName") or f"Player {player_id}",
                "count": 0,
                "subtypes": defaultdict(int),
            },
        )
        bucket["count"] += 1
        subtype = point.get("subtypeLabel")
        if subtype:
            bucket["subtypes"][str(subtype)] += 1

    ranked = sorted(
        by_player.values(),
        key=lambda row: (-int(row["count"]), str(row["playerName"]).casefold()),
    )
    total = len(points) or 1
    rows: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        subtype_bits = [
            f"{label} {count}"
            for label, count in sorted(
                row["subtypes"].items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ]
        rows.append(
            {
                "playerId": row["playerId"],
                "playerName": row["playerName"],
                "count": int(row["count"]),
                "sharePct": round(100.0 * int(row["count"]) / total),
                "detail": " · ".join(subtype_bits) if subtype_bits else None,
            }
        )
    return rows


def _layer_breakdown(
    points: list[dict[str, Any]],
    *,
    mode: str,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for point in points:
        if mode == "subtype":
            key = str(point.get("subtypeLabel") or "Other")
        else:
            key = str(point.get("zone") or "Unknown")
        counts[key] += 1
    total = len(points) or 1
    return [
        {
            "label": label,
            "count": count,
            "sharePct": round(100.0 * count / total),
        }
        for label, count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    ]


def _build_oop_activity_map(
    match_id: int,
    focus_squad_id: int,
    focus_player_ids: set[int],
    player_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    names = player_names or {}
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    events = events if isinstance(events, list) else []
    event_lookup: dict[int, dict[str, Any]] = {}
    for event in events:
        event_id = event.get("id")
        if event_id is None:
            continue
        try:
            event_lookup[int(event_id)] = event
        except (TypeError, ValueError):
            continue

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    ekpi_rows = ekpi_rows if isinstance(ekpi_rows, list) else []

    layers_out: list[dict[str, Any]] = []
    for layer in ACTIVITY_LAYERS:
        points: list[dict[str, Any]] = []
        seen_events: set[int] = set()
        for row in ekpi_rows:
            try:
                kpi_id = int(row.get("kpiId") or 0)
                if kpi_id not in layer["kpiIds"]:
                    continue
                if float(row.get("value") or 0) <= 0:
                    continue
                player_id = int(row.get("playerId") or 0)
                if player_id not in focus_player_ids:
                    continue
                event_id = int(row["eventId"])
            except (TypeError, ValueError, KeyError):
                continue
            if event_id in seen_events:
                continue
            event = event_lookup.get(event_id)
            if not event:
                continue
            raw = _event_map_coords(event)
            if not raw:
                continue
            x, y = _normalize_attacking_up(raw[0], raw[1], event, focus_squad_id)
            # Clamp lightly inside pitch bounds for map stability.
            x = max(-PITCH_HALF_LENGTH_M, min(PITCH_HALF_LENGTH_M, x))
            y = max(-PITCH_HALF_WIDTH_M, min(PITCH_HALF_WIDTH_M, y))
            seen_events.add(event_id)
            subtype, subtype_label = _point_subtype(str(layer["id"]), kpi_id, event)
            player_name = _player_display_name(player_id, names)
            points.append(
                {
                    "impectX": round(x, 2),
                    "impectY": round(y, 2),
                    "playerId": player_id,
                    "playerName": player_name,
                    "playerInitials": _player_initials(player_name),
                    "kpiId": kpi_id,
                    "zone": _zone_label(x, y),
                    "subtype": subtype,
                    "subtypeLabel": subtype_label,
                }
            )
        breakdown_mode = str(layer.get("breakdownMode") or "zone")
        render_mode = str(layer.get("renderMode") or "points")
        layers_out.append(
            {
                "id": layer["id"],
                "label": layer["label"],
                "title": layer.get("title") or layer["label"],
                "color": layer["color"],
                "shape": layer.get("shape") or "circle",
                "renderMode": render_mode,
                "count": len(points),
                "densestZone": _densest_zone(points),
                "points": [] if render_mode == "zoneHeat" else points,
                "zoneHeat": _zone_heat_cells(points) if render_mode == "zoneHeat" else [],
                "topPlayers": _layer_top_players(points),
                "breakdown": _layer_breakdown(points, mode=breakdown_mode),
                "breakdownMode": breakdown_mode,
                "note": layer.get("note") or "",
            }
        )

    return {
        "layers": layers_out,
        "pitch": {
            "halfLengthM": PITCH_HALF_LENGTH_M,
            "halfWidthM": PITCH_HALF_WIDTH_M,
            "widthM": PITCH_WIDTH_M,
            "lengthM": PITCH_LENGTH_M,
        },
        "orientationNote": "Pitch oriented with our attack toward the top",
    }


def _attach_player_baselines(
    row: dict[str, Any],
    baseline: dict[str, float | None] | None,
) -> dict[str, Any]:
    if not baseline:
        row["totalWinBand"] = "none" if row.get("totalWinPct") is None else "neutral"
        return row

    metric_specs = (
        ("totalWinPct", "totalWinDisplay", "totalWinPctAvgDisplay", "totalWinBand", True, True),
        (
            "offensiveInterventions",
            None,
            "offensiveInterventionsAvgDisplay",
            "offensiveInterventionsBand",
            False,
            True,
        ),
        (
            "defensiveInterventions",
            None,
            "defensiveInterventionsAvgDisplay",
            "defensiveInterventionsBand",
            False,
            True,
        ),
        (
            "ballWinsFromOppositionDefenders",
            None,
            "ballWinsFromOppositionDefendersAvgDisplay",
            "ballWinsFromOppositionDefendersBand",
            False,
            True,
        ),
    )

    for key, _display_key, avg_display_key, band_key, as_percent, higher in metric_specs:
        avg_value = baseline.get(key)
        match_value = row.get(key)
        row[avg_display_key] = _format_player_avg(avg_value, as_percent=as_percent)
        if match_value is None and key == "totalWinPct":
            row[band_key] = "none"
        else:
            row[band_key] = _performance_band(
                float(match_value) if match_value is not None else None,
                avg_value,
                higher_is_better=higher,
            )

    return row


def _aggregate_players(
    players: list[dict[str, Any]],
    focus_squad_id: int,
    player_baselines: dict[int, dict[str, float | None]] | None = None,
) -> list[dict[str, Any]]:
    from app.post_match.report import _consolidate_player_match_rows

    squad_rows = [row for row in players if int(row.get("squadId") or 0) == focus_squad_id]
    consolidated = _consolidate_player_match_rows(squad_rows)
    baselines = player_baselines or {}

    rows: list[dict[str, Any]] = []
    for row in consolidated:
        minutes = float(row.get("minutes") or 0) / 60.0
        if minutes <= 0:
            continue
        metrics = _extract_player_metrics(row.get("kpis") or {})
        player_row = {
            "playerId": row["playerId"],
            "playerName": row["name"],
            **metrics,
            "totalWinDisplay": (
                f"{metrics['totalWinPct']}%" if metrics["totalWinPct"] is not None else "-"
            ),
        }
        rows.append(
            _attach_player_baselines(player_row, baselines.get(int(row["playerId"])))
        )

    rows.sort(
        key=lambda item: (
            -item["offensiveInterventions"],
            -item["ballWinsFromOppositionDefenders"],
            item["playerName"],
        ),
    )
    return rows


def build_duels(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None,
    *,
    opponent_name: str | None = None,
    game_count: int = 7,
) -> dict[str, Any]:
    if not iteration_id:
        return {
            "title": "Out of Possession — Duels and Pressing",
            "description": "Duels, pressing and ball-win metrics from Impect",
            "opponentLabel": opponent_name or "Opponent",
            "teamMetrics": [],
            "players": [],
            "activityMap": {"layers": [], "pitch": {}},
        }

    iteration_id = int(iteration_id)
    focus_recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=match_id,
        count=game_count,
    )
    needed_matches = set(focus_recent_ids)
    needed_matches.add(match_id)

    match_data = _load_match_team_data(needed_matches)
    match_kpis, match_scores = match_data.get(match_id, ({}, {}))
    focus_match_kpis = match_kpis.get(focus_squad_id, {})
    focus_match_scores = match_scores.get(focus_squad_id, {})

    pressing_ids = {spec["id"] for spec in PRESSING_METRIC_SPECS}

    team_metrics: list[dict[str, Any]] = []
    for spec in TEAM_METRIC_SPECS:
        focus_values_clean: list[float] = []
        for recent_id in focus_recent_ids:
            kpis_by_squad, scores_by_squad = match_data.get(recent_id, ({}, {}))
            value = _metric_value(
                spec,
                kpis_by_squad.get(focus_squad_id, {}),
                scores_by_squad.get(focus_squad_id, {}),
            )
            if value is not None:
                focus_values_clean.append(value)
        avg_value = _average_metric_values(focus_values_clean)
        match_value = _metric_value(spec, focus_match_kpis, focus_match_scores)
        if spec["source"] == "kpi":
            rank_values = _iteration_kpi_values(iteration_id, int(spec["key"]))
        else:
            rank_values = _iteration_score_values(iteration_id, int(spec["key"]))
        team_metrics.append(
            _build_team_metric_row(
                spec,
                avg_value=avg_value,
                match_value=match_value,
                rank_values=rank_values,
                focus_squad_id=focus_squad_id,
                section="pressing" if spec["id"] in pressing_ids else "duels",
            )
        )

    from app.post_match.report import _player_directory

    player_names = _player_directory(iteration_id)
    players_by_match = _load_match_player_rows(needed_matches, player_names)
    player_baselines = _compute_player_baselines(
        focus_recent_ids,
        focus_squad_id,
        players_by_match,
    )
    players = players_by_match.get(match_id, [])
    player_rows = _aggregate_players(players, focus_squad_id, player_baselines)
    focus_player_ids = {
        int(row["playerId"])
        for row in players
        if int(row.get("squadId") or 0) == focus_squad_id and row.get("playerId") is not None
    }
    activity_map = _build_oop_activity_map(
        match_id,
        focus_squad_id,
        focus_player_ids,
        player_names,
    )

    league_size = (
        len(_iteration_score_values(iteration_id, SQUAD_SCORE_RATIO_GROUND_DUELS)) or 24
    )

    return {
        "title": "Out of Possession — Duels and Pressing",
        "description": "Team duels & pressing vs 7-game average · player rows vs personal 7-game avg",
        "opponentLabel": opponent_name or "Opponent",
        "leagueSize": league_size,
        "teamMetrics": team_metrics,
        "duelMetrics": [row for row in team_metrics if row.get("section") == "duels"],
        "pressingMetrics": [row for row in team_metrics if row.get("section") == "pressing"],
        "players": player_rows,
        "activityMap": activity_map,
        "gameCount": len(focus_recent_ids),
    }
