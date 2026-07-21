from __future__ import annotations

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.post_match.ball_progression import (
    _average_metric_values,
    _iteration_kpi_values,
    _load_match_team_data,
    _performance_band,
    _rank_for_value,
    _top7_average,
)
from app.post_match.impect_client import impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids
from app.post_match.shot_xg_consistency import (
    POST_SHOT_METRIC_IDS,
    SHOT_BASED_METRIC_IDS,
    validate_shots_payload,
)

SHOT_XG_KPI_ID = 82
PACKING_XG_KPI_ID = 83
POSTSHOT_XG_KPI_ID = 1401
KPI_BYPASSED_DEFENDERS = 2
KPI_FINAL_THIRD_ENTRIES = 284
KPI_SUFFERED_BYPASSED_DEFENDERS = 40
KPI_FINAL_THIRD_ENTRIES_AGAINST = 149
KPI_CONCEDED_PACKING_XG = 1464
KPI_CONCEDED_SHOT_XG = 1463
KPI_CONCEDED_POSTSHOT_XG = 1462

PITCH_GOAL_X = 52.5
PITCH_WIDTH_M = 68.0
PITCH_HALF_WIDTH_M = PITCH_WIDTH_M / 2.0
FINAL_THIRD_MIN_X = 17.5

PHASE_BUCKETS: dict[str, str] = {
    "IN_POSSESSION": "Possession",
    "SECOND_BALL": "Possession",
    "ATTACKING_TRANSITION": "Transition",
    "DEFENSIVE_TRANSITION": "Transition",
    "SET_PIECE": "Set Play",
}

SET_PLAY_ACTIONS = frozenset({
    "DIRECT_FREE_KICK",
    "INDIRECT_FREE_KICK",
    "CORNER",
    "THROW_IN",
    "PENALTY",
})

PHASE_ORDER: tuple[str, ...] = ("Possession", "Transition", "Set Play")


def _shot_phase_bucket(impect_phase: str | None, action: str | None) -> str:
    """Map Impect event phase (+ shot action) to deck buckets.

    Set-piece restarts (corners, direct FKs, etc.) stay in Set Play; other
    shots tagged SET_PIECE in the feed (e.g. follow-up strikes) count as Possession.
    """
    phase = str(impect_phase or "").upper()
    act = str(action or "").upper()
    if phase == "SET_PIECE":
        return "Set Play" if act in SET_PLAY_ACTIONS else "Possession"
    return PHASE_BUCKETS.get(phase, "Transition")

TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "bypassedDefenders",
        "label": "Bypassed Defenders",
        "metricColor": "#22c55e",
        "kpiId": KPI_BYPASSED_DEFENDERS,
        "format": "int",
        "higherIsBetter": True,
        "source": "kpi",
    },
    {
        "id": "finalThirdEntries",
        "label": "Final 3rd Entries",
        "metricColor": "#e11d48",
        "kpiId": KPI_FINAL_THIRD_ENTRIES,
        "format": "int",
        "higherIsBetter": True,
        "source": "kpi",
    },
    {
        "id": "nonShotXg",
        "label": "Non Shot xG",
        "metricColor": "#db2777",
        "kpiId": PACKING_XG_KPI_ID,
        "format": "decimal",
        "higherIsBetter": True,
        "source": "kpi",
    },
    {
        "id": "shotBasedXg",
        "label": "Shot Based xG",
        "metricColor": "#2563eb",
        "kpiId": SHOT_XG_KPI_ID,
        "format": "decimal",
        "higherIsBetter": True,
        "source": "shots",
    },
    {
        "id": "postShotXg",
        "label": "Post Shot xG",
        "metricColor": "#0d9488",
        "kpiId": POSTSHOT_XG_KPI_ID,
        "format": "decimal",
        "higherIsBetter": True,
        "source": "shots",
    },
)


DEFENSIVE_TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "bypassedDefendersAgainst",
        "label": "Bypassed Defenders Against",
        "metricColor": "#22c55e",
        "kpiId": KPI_SUFFERED_BYPASSED_DEFENDERS,
        "format": "int",
        "higherIsBetter": False,
        "source": "kpi",
    },
    {
        "id": "finalThirdEntriesAgainst",
        "label": "Final 3rd Entries Against",
        "metricColor": "#e11d48",
        "kpiId": KPI_FINAL_THIRD_ENTRIES_AGAINST,
        "format": "int",
        "higherIsBetter": False,
        "source": "kpi",
    },
    {
        "id": "nonShotXgAgainst",
        "label": "Non Shot xG Against",
        "metricColor": "#db2777",
        "kpiId": KPI_CONCEDED_PACKING_XG,
        "format": "decimal",
        "higherIsBetter": False,
        "source": "kpi",
    },
    {
        "id": "shotBasedXgAgainst",
        "label": "Shot Based xG Against",
        "metricColor": "#2563eb",
        "kpiId": KPI_CONCEDED_SHOT_XG,
        "format": "decimal",
        "higherIsBetter": False,
        "source": "shots",
    },
    {
        "id": "postShotXgAgainst",
        "label": "Post Shot xG Against",
        "metricColor": "#0d9488",
        "kpiId": KPI_CONCEDED_POSTSHOT_XG,
        "format": "decimal",
        "higherIsBetter": False,
        "source": "shots",
    },
)


def _player_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _format_metric_value(value: float | None, fmt: str) -> str | None:
    if value is None:
        return None
    if fmt == "decimal":
        rounded = round(value, 2)
        if rounded == int(rounded):
            return str(int(rounded))
        return f"{rounded:.2f}".rstrip("0").rstrip(".")
    return str(int(round(value)))


def _shot_outcome(event: dict[str, Any]) -> str:
    if str(event.get("result") or "").upper() == "SUCCESS":
        return "scored"
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
        return "saved"
    if position == "OPPONENT_BOX" and end_x >= 49.5 and end_y <= 4.0:
        return "saved"
    return "off_target"


def _match_shot_aggregates(match_id: int, focus_squad_id: int) -> dict[str, Any]:
    """Per-match shot totals, phase splits, and outcome counts."""
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    empty_phases = {label: {"shots": 0, "xg": 0.0} for label in PHASE_ORDER}
    if not isinstance(events, list):
        return {
            "shotBasedXg": 0.0,
            "postShotXg": 0.0,
            "phases": empty_phases,
            "totalShots": 0,
            "goals": 0,
            "onTarget": 0,
        }

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    shot_xg_by_event: dict[int, float] = defaultdict(float)
    post_shot_by_event: dict[int, float] = defaultdict(float)
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            event_id = int(row.get("eventId") or 0)
            if not event_id:
                continue
            kpi_id = int(row.get("kpiId") or -1)
            value = float(row.get("value") or 0)
            if kpi_id == SHOT_XG_KPI_ID:
                shot_xg_by_event[event_id] += value
            elif kpi_id == POSTSHOT_XG_KPI_ID:
                post_shot_by_event[event_id] += value

    phases = {label: {"shots": 0, "xg": 0.0} for label in PHASE_ORDER}
    shot_based_xg = 0.0
    post_shot_xg = 0.0
    goals = 0
    on_target = 0
    total_shots = 0

    for event in events:
        if event.get("actionType") != "SHOT":
            continue
        if int(event.get("squadId") or 0) != focus_squad_id:
            continue

        event_id = int(event["id"])
        xg = shot_xg_by_event.get(event_id, 0.0)
        shot_based_xg += xg
        post_shot_xg += post_shot_by_event.get(event_id, 0.0)
        total_shots += 1

        outcome = _shot_outcome(event)
        if outcome == "scored":
            goals += 1
            on_target += 1
        elif outcome == "saved":
            on_target += 1

        impect_phase = str(event.get("phase") or "")
        action = str(event.get("action") or "")
        phase_label = _shot_phase_bucket(impect_phase, action)
        if phase_label in phases:
            phases[phase_label]["shots"] += 1
            phases[phase_label]["xg"] += xg

    return {
        "shotBasedXg": round(shot_based_xg, 4),
        "postShotXg": round(post_shot_xg, 4),
        "phases": {
            label: {
                "shots": row["shots"],
                "xg": round(row["xg"], 4),
            }
            for label, row in phases.items()
        },
        "totalShots": total_shots,
        "goals": goals,
        "onTarget": on_target,
    }


def _match_shot_totals(match_id: int, focus_squad_id: int) -> dict[str, float]:
    aggregates = _match_shot_aggregates(match_id, focus_squad_id)
    return {
        "shotBasedXg": aggregates["shotBasedXg"],
        "postShotXg": aggregates["postShotXg"],
    }


def _load_conceded_shot_baselines(
    match_ids: list[int],
    focus_squad_id: int,
    iteration_id: int,
) -> dict[int, dict[str, Any]]:
    from app.post_match.report import _match_meta

    loaded: dict[int, dict[str, Any]] = {}
    if not match_ids:
        return loaded
    opponents: dict[int, int] = {}
    for match_id in match_ids:
        meta = _match_meta(match_id, iteration_id)
        home_id = int(meta["home"]["squadId"] or 0)
        away_id = int(meta["away"]["squadId"] or 0)
        if focus_squad_id == home_id and away_id:
            opponents[match_id] = away_id
        elif focus_squad_id == away_id and home_id:
            opponents[match_id] = home_id
    if not opponents:
        return loaded
    workers = min(8, len(opponents))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_match_shot_aggregates, match_id, opponent_id): match_id
            for match_id, opponent_id in opponents.items()
        }
        for future in as_completed(futures):
            match_id = futures[future]
            loaded[match_id] = future.result()
    return loaded


def _load_shot_metric_baselines(
    match_ids: list[int],
    focus_squad_id: int,
) -> dict[int, dict[str, Any]]:
    loaded: dict[int, dict[str, Any]] = {}
    if not match_ids:
        return loaded
    workers = min(8, len(match_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_match_shot_aggregates, match_id, focus_squad_id): match_id
            for match_id in match_ids
        }
        for future in as_completed(futures):
            match_id = futures[future]
            loaded[match_id] = future.result()
    return loaded


def _average_phase_baselines(
    match_ids: list[int],
    shot_baselines: dict[int, dict[str, Any]],
) -> dict[str, dict[str, float | None]]:
    """7-game average shots and xG per phase bucket."""
    totals = {
        label: {"shots": 0.0, "xg": 0.0, "games": 0}
        for label in PHASE_ORDER
    }
    for match_id in match_ids:
        aggregates = shot_baselines.get(match_id)
        if not aggregates:
            continue
        for label in PHASE_ORDER:
            phase_row = aggregates.get("phases", {}).get(label, {})
            totals[label]["shots"] += float(phase_row.get("shots") or 0)
            totals[label]["xg"] += float(phase_row.get("xg") or 0)
            totals[label]["games"] += 1

    averaged: dict[str, dict[str, float | None]] = {}
    for label in PHASE_ORDER:
        games = totals[label]["games"]
        if games:
            avg_shots = totals[label]["shots"] / games
            avg_xg = totals[label]["xg"] / games
        else:
            avg_shots = None
            avg_xg = None
        averaged[label] = {
            "avgShots": round(avg_shots, 2) if avg_shots is not None else None,
            "avgXg": round(avg_xg, 4) if avg_xg is not None else None,
        }
    return averaged


def _format_shot_xg(value: float) -> str:
    return f"{round(value, 2):.2f}"


def _shot_metric_display(value: float | None, metric_id: str) -> str | None:
    if value is None:
        return None
    if metric_id in SHOT_BASED_METRIC_IDS or metric_id in POST_SHOT_METRIC_IDS:
        return _format_shot_xg(float(value))
    return _format_metric_value(value, "decimal")


def _aggregate_from_shot_points(
    shot_points: list[dict[str, Any]],
    phase_baselines: dict[str, dict[str, float | None]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    players: dict[int, dict[str, Any]] = {}
    phases: dict[str, dict[str, Any]] = {
        label: {"label": label, "shots": 0, "xg": 0.0}
        for label in PHASE_ORDER
    }

    for point in shot_points:
        xg = float(point["xg"])
        phase_label = point["phase"]
        if phase_label in phases:
            phases[phase_label]["shots"] += 1
            phases[phase_label]["xg"] += xg

        player_id = point.get("playerId")
        if player_id:
            row = players.setdefault(
                int(player_id),
                {
                    "playerId": int(player_id),
                    "playerName": point.get("playerName") or f"Player {player_id}",
                    "shots": 0,
                    "xg": 0.0,
                },
            )
            row["shots"] += 1
            row["xg"] += xg

    player_rows = sorted(
        players.values(),
        key=lambda row: (-row["xg"], -row["shots"], row["playerName"]),
    )
    top_xg = sorted({row["xg"] for row in player_rows}, reverse=True)[:1]
    for row in player_rows:
        row["xg"] = round(row["xg"], 4)
        row["highlightXg"] = row["xg"] in top_xg and row["xg"] > 0
        row["xgDisplay"] = _format_shot_xg(row["xg"])

    phase_baselines = phase_baselines or {}
    phase_rows: list[dict[str, Any]] = []
    total_shots = 0
    total_xg = 0.0
    total_avg_shots = 0.0
    total_avg_xg = 0.0
    for label in PHASE_ORDER:
        row = phases[label]
        total_shots += row["shots"]
        total_xg += row["xg"]
        baseline = phase_baselines.get(label, {})
        avg_shots = baseline.get("avgShots")
        avg_xg = baseline.get("avgXg")
        if avg_shots is not None:
            total_avg_shots += float(avg_shots)
        if avg_xg is not None:
            total_avg_xg += float(avg_xg)
        phase_rows.append(
            {
                "label": row["label"],
                "shots": row["shots"],
                "xg": round(row["xg"], 4),
                "xgDisplay": _format_shot_xg(row["xg"]),
                "avgShots": avg_shots,
                "avgShotsDisplay": _format_metric_value(avg_shots, "decimal") if avg_shots is not None else None,
                "avgXg": avg_xg,
                "avgXgDisplay": _format_shot_xg(avg_xg) if avg_xg is not None else None,
            }
        )
    phase_rows.append(
        {
            "label": "Total",
            "shots": total_shots,
            "xg": round(total_xg, 4),
            "xgDisplay": _format_shot_xg(total_xg),
            "avgShots": round(total_avg_shots, 2) if phase_baselines else None,
            "avgShotsDisplay": _format_metric_value(total_avg_shots, "decimal") if phase_baselines else None,
            "avgXg": round(total_avg_xg, 4) if phase_baselines else None,
            "avgXgDisplay": _format_shot_xg(total_avg_xg) if phase_baselines else None,
            "isTotal": True,
        }
    )
    return player_rows, phase_rows


def _fetch_focus_shots(
    match_id: int,
    focus_squad_id: int,
    player_names: dict[int, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return [], [], []

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    shot_xg_by_event: dict[int, float] = defaultdict(float)
    post_shot_by_event: dict[int, float] = defaultdict(float)
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            event_id = int(row.get("eventId") or 0)
            if not event_id:
                continue
            kpi_id = int(row.get("kpiId") or -1)
            value = float(row.get("value") or 0)
            if kpi_id == SHOT_XG_KPI_ID:
                shot_xg_by_event[event_id] += value
            elif kpi_id == POSTSHOT_XG_KPI_ID:
                post_shot_by_event[event_id] += value

    shot_points: list[dict[str, Any]] = []

    for event in events:
        if event.get("actionType") != "SHOT":
            continue
        if int(event.get("squadId") or 0) != focus_squad_id:
            continue

        event_id = int(event["id"])
        start = event.get("start") or {}
        coords = start.get("adjCoordinates") or start.get("coordinates") or {}
        has_location = True
        try:
            impect_x = float(coords.get("x"))
            impect_y = float(coords.get("y"))
        except (TypeError, ValueError):
            has_location = False
            impect_x = None
            impect_y = None

        player = event.get("player") or {}
        player_id = int(player.get("id") or 0)
        player_name = player_names.get(player_id) if player_id else None
        if not player_name:
            player_name = str(player.get("commonname") or player.get("name") or "").strip()
        xg = round(shot_xg_by_event.get(event_id, 0.0), 4)
        outcome = _shot_outcome(event)
        impect_phase = str(event.get("phase") or "")
        action = str(event.get("action") or "")
        phase_label = _shot_phase_bucket(impect_phase, action)

        shot_points.append(
            {
                "eventId": event_id,
                "impectX": impect_x,
                "impectY": impect_y,
                "hasLocation": has_location,
                "outcome": outcome,
                "phase": phase_label,
                "impectPhase": impect_phase,
                "action": action,
                "xg": xg,
                "xgDisplay": _format_shot_xg(xg),
                "playerId": player_id or None,
                "playerName": player_name or None,
                "playerInitials": _player_initials(player_name),
            }
        )

    player_rows, phase_rows = _aggregate_from_shot_points(shot_points)
    return shot_points, player_rows, phase_rows


def build_shots(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None,
    *,
    opponent_name: str | None = None,
    opponent_squad_id: int | None = None,
    game_count: int = 7,
    title: str = "In-Possession — Shots",
    defensive: bool = False,
) -> dict[str, Any]:
    if not iteration_id:
        return {
            "title": title,
            "description": "Shot map, team xG metrics, and player breakdown",
            "opponentLabel": opponent_name or "Opponent",
            "teamMetrics": [],
            "shotPoints": [],
            "players": [],
            "phases": [],
            "pitch": {},
            "legend": [],
        }

    from app.post_match.report import _flatten_squad_kpis, _player_directory, _iteration_goalkeeper_ids, _exclude_goalkeeper_ids

    iteration_id = int(iteration_id)
    player_names = _player_directory(iteration_id)
    goalkeeper_ids = _iteration_goalkeeper_ids(iteration_id)
    metric_specs = DEFENSIVE_TEAM_METRIC_SPECS if defensive else TEAM_METRIC_SPECS
    shot_squad_id = (
        int(opponent_squad_id)
        if defensive and opponent_squad_id
        else focus_squad_id
    )

    shot_points, player_rows, _ = _fetch_focus_shots(
        match_id,
        shot_squad_id,
        player_names,
    )
    player_rows = _exclude_goalkeeper_ids(player_rows, goalkeeper_ids)

    focus_recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=match_id,
        count=game_count,
    )
    needed_matches = set(focus_recent_ids)
    needed_matches.add(match_id)

    match_data = _load_match_team_data(needed_matches)
    if defensive:
        shot_baselines = _load_conceded_shot_baselines(
            focus_recent_ids,
            focus_squad_id,
            iteration_id,
        )
    else:
        shot_baselines = _load_shot_metric_baselines(focus_recent_ids, focus_squad_id)
    phase_baselines = _average_phase_baselines(focus_recent_ids, shot_baselines)
    _, phase_rows = _aggregate_from_shot_points(shot_points, phase_baselines)

    match_aggregates = _match_shot_aggregates(match_id, shot_squad_id)
    total_shot_xg = float(match_aggregates["shotBasedXg"])
    total_post_shot_xg = float(match_aggregates["postShotXg"])
    total_shots = int(match_aggregates["totalShots"])
    goals = int(match_aggregates["goals"])
    on_target = int(match_aggregates["onTarget"])

    match_kpis = _flatten_squad_kpis(
        impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"],
    ).get(focus_squad_id, {})

    team_metrics: list[dict[str, Any]] = []
    for spec in metric_specs:
        source = spec["source"]
        higher_is_better = bool(spec["higherIsBetter"])
        if source == "kpi":
            focus_values_clean: list[float] = []
            for recent_id in focus_recent_ids:
                kpis_by_squad, _ = match_data.get(recent_id, ({}, {}))
                value = kpis_by_squad.get(focus_squad_id, {}).get(int(spec["kpiId"]))
                if value is not None:
                    focus_values_clean.append(float(value))
            avg_value = _average_metric_values(focus_values_clean)
            match_value = match_kpis.get(int(spec["kpiId"]))
        else:
            metric_key = "shotBasedXg" if spec["id"] in {
                "shotBasedXg",
                "shotBasedXgAgainst",
            } else "postShotXg"
            focus_values_clean = [
                float(shot_baselines.get(recent_id, {}).get(metric_key, 0.0))
                for recent_id in focus_recent_ids
                if recent_id in shot_baselines
            ]
            avg_value = _average_metric_values(focus_values_clean)
            if spec["id"] in SHOT_BASED_METRIC_IDS:
                match_value = total_shot_xg
            else:
                match_value = total_post_shot_xg

        rank_values = _iteration_kpi_values(iteration_id, int(spec["kpiId"]))
        top7_value = _top7_average(rank_values, higher_is_better=higher_is_better)
        metric_id = spec["id"]
        uses_shot_display = metric_id in SHOT_BASED_METRIC_IDS or metric_id in POST_SHOT_METRIC_IDS
        team_metrics.append(
            {
                "id": metric_id,
                "label": spec["label"],
                "metricColor": spec["metricColor"],
                "avgValue": avg_value,
                "avgDisplay": (
                    _shot_metric_display(avg_value, metric_id)
                    if uses_shot_display
                    else _format_metric_value(avg_value, spec["format"])
                ),
                "avgRank": _rank_for_value(
                    rank_values,
                    focus_squad_id,
                    higher_is_better=higher_is_better,
                ),
                "top7AvgValue": top7_value,
                "top7AvgDisplay": _format_metric_value(top7_value, spec["format"]),
                "matchValue": match_value,
                "matchDisplay": _shot_metric_display(
                    float(match_value) if match_value is not None else None,
                    metric_id,
                ) if uses_shot_display else _format_metric_value(
                    float(match_value) if match_value is not None else None,
                    spec["format"],
                ),
                "matchBand": _performance_band(
                    float(match_value) if match_value is not None else None,
                    avg_value,
                    higher_is_better=higher_is_better,
                ),
                "matchTop7Band": _performance_band(
                    float(match_value) if match_value is not None else None,
                    top7_value,
                    higher_is_better=higher_is_better,
                ),
                "higherIsBetter": higher_is_better,
            }
        )

    rank_kpi_id = KPI_CONCEDED_SHOT_XG if defensive else SHOT_XG_KPI_ID
    league_size = len(_iteration_kpi_values(iteration_id, rank_kpi_id)) or 24

    avg_shot_values = [
        float(shot_baselines[recent_id]["totalShots"])
        for recent_id in focus_recent_ids
        if recent_id in shot_baselines
    ]
    avg_xg_values = [
        float(shot_baselines[recent_id]["shotBasedXg"])
        for recent_id in focus_recent_ids
        if recent_id in shot_baselines
    ]
    avg_shots = _average_metric_values(avg_shot_values)
    avg_xg = _average_metric_values(avg_xg_values)

    payload = {
        "title": title,
        "description": (
            "Shots conceded, defensive xG metrics, and opponent shot breakdown"
            if defensive
            else "Shot locations, team xG metrics, and phase breakdown"
        ),
        "opponentLabel": opponent_name or "Opponent",
        "defensive": defensive,
        "leagueSize": league_size,
        "summary": {
            "totalShots": total_shots,
            "totalXg": total_shot_xg,
            "totalXgDisplay": _format_shot_xg(total_shot_xg),
            "goals": goals,
            "onTarget": on_target,
            "avgShots": avg_shots,
            "avgShotsDisplay": _format_metric_value(avg_shots, "decimal")
            if avg_shots is not None
            else None,
            "avgXg": avg_xg,
            "avgXgDisplay": _format_shot_xg(avg_xg) if avg_xg is not None else None,
            "baselineGameCount": len(focus_recent_ids),
        },
        "teamMetrics": team_metrics,
        "shotPoints": shot_points,
        "players": player_rows,
        "phases": phase_rows,
        "totalShotXg": total_shot_xg,
        "totalShotXgDisplay": _format_shot_xg(total_shot_xg),
        "pitch": {
            "goalX": PITCH_GOAL_X,
            "minX": FINAL_THIRD_MIN_X,
            "widthM": PITCH_WIDTH_M,
            "depthM": PITCH_GOAL_X - FINAL_THIRD_MIN_X,
            "penaltySpotM": 11.0,
            "penaltyArcM": 9.15,
            "penaltyBoxDepthM": 16.5,
        },
        "legend": [
            {"id": "off_target", "label": "Blocked / Off Target", "color": "#ef4444"},
            {"id": "saved", "label": "Saved", "color": "#facc15"},
            {"id": "scored", "label": "Scored", "color": "#22c55e"},
        ],
        "phaseLegend": [
            {"id": "Possession", "label": "Possession", "shape": "circle"},
            {"id": "Transition", "label": "Transition", "shape": "diamond"},
            {"id": "Set Play", "label": "Set Play", "shape": "square"},
        ],
        "phaseSource": "Impect match events (actionType=SHOT) · phase field with set-play action split",
        "gameCount": len(focus_recent_ids),
    }
    validate_shots_payload(payload, context=title)
    return payload
