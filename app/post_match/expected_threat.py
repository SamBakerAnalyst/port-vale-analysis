from __future__ import annotations

from typing import Any

from app.post_match.ball_progression import (
    _average_metric_values,
    _build_team_metric_row,
    _iteration_kpi_values,
    _iteration_score_values,
    _load_match_team_data,
    _metric_value,
)
from app.post_match.impect_client import impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

# Squad-level Packing Expected Threat (positive) = Impect score 48.
SQUAD_SCORE_PXT_POSITIVE = 48

# Action-type breakdown of positive developed threat (matches Impect "PXT positive" drill-down).
TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "expectedThreat",
        "label": "Expected Threat",
        "metricColor": "#0d9488",
        "source": "score",
        "key": SQUAD_SCORE_PXT_POSITIVE,
        "higherIsBetter": True,
        "format": "decimal",
    },
    {
        "id": "progressivePasses",
        "label": "Progressive Passes",
        "metricColor": "#16a34a",
        "source": "kpi",
        "key": 1422,  # PXT_PASS_PRO
        "higherIsBetter": True,
        "format": "decimal2",
    },
    {
        "id": "progressiveDribbles",
        "label": "Progressive Dribbles",
        "metricColor": "#2563eb",
        "source": "kpi",
        "key": 1425,  # PXT_DRIBBLE_PRO
        "higherIsBetter": True,
        "format": "decimal2",
    },
    {
        "id": "ballWins",
        "label": "Ball Wins",
        "metricColor": "#ca8a04",
        "source": "kpi",
        "key": 1409,  # PXT_BALL_WIN
        "higherIsBetter": True,
        "format": "decimal2",
    },
    {
        "id": "progressiveSetPieces",
        "label": "Progressive Set Pieces",
        "metricColor": "#9333ea",
        "source": "kpi",
        "key": 1428,  # PXT_SETPIECE_PRO
        "higherIsBetter": True,
        "format": "decimal2",
    },
)

# Player Offensive PXT columns (Impect "Offensive IMPECT PXT" style).
PLAYER_PXT_COLUMNS: tuple[dict[str, Any], ...] = (
    {"id": "passes", "label": "Passes", "kpiId": 1404},
    {"id": "dribbles", "label": "Dribbles", "kpiId": 1405},
    {"id": "shots", "label": "Shots", "kpiId": 1408},
    {"id": "receptions", "label": "Receptions", "kpiId": 1412},
    {"id": "ballWins", "label": "Ball Wins", "kpiId": 1409},
    {"id": "setPieces", "label": "Set Pieces", "kpiId": 1406},
)


def _format_player_avg(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f} avg"


def _format_decimal2(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _format_metric_value(value: float | None, fmt: str) -> str | None:
    if value is None:
        return None
    if fmt == "decimal2":
        return _format_decimal2(value)
    if fmt == "decimal":
        rounded = round(value, 1)
        return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"
    if fmt == "percent":
        return f"{round(value * 100, 1)}%"
    return str(int(round(value)))


def _build_team_row(
    spec: dict[str, Any],
    *,
    avg_value: float | None,
    match_value: float | None,
    rank_values: dict[int, float],
    focus_squad_id: int,
) -> dict[str, Any]:
    row = _build_team_metric_row(
        {**spec, "format": "decimal"},
        avg_value=avg_value,
        match_value=match_value,
        rank_values=rank_values,
        focus_squad_id=focus_squad_id,
    )
    fmt = str(spec["format"])
    row["avgDisplay"] = _format_metric_value(avg_value, fmt)
    row["top7AvgDisplay"] = _format_metric_value(row.get("top7AvgValue"), fmt)
    row["matchDisplay"] = _format_metric_value(match_value, fmt)
    return row


def _kpi_extract(kpi_id: int):
    def _extract(row: dict[str, Any]) -> float | None:
        kpis = row.get("kpis") or {}
        if kpi_id not in kpis and str(kpi_id) not in kpis:
            # Still treat missing as 0 only when player played — kpis present.
            if not kpis:
                return None
            return float(kpis.get(kpi_id) or kpis.get(str(kpi_id)) or 0.0)
        return float(kpis.get(kpi_id) or kpis.get(str(kpi_id)) or 0.0)

    return _extract


def _total_extract(row: dict[str, Any]) -> float | None:
    kpis = row.get("kpis") or {}
    if not kpis:
        return None
    total = 0.0
    for col in PLAYER_PXT_COLUMNS:
        total += float(kpis.get(int(col["kpiId"])) or 0.0)
    return total


def _aggregate_players(
    players: list[dict[str, Any]],
    focus_squad_id: int,
    season_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from app.post_match.player_season_baselines import annotate_metric, position_group
    from app.post_match.report import _consolidate_player_match_rows

    squad_rows = [row for row in players if int(row.get("squadId") or 0) == focus_squad_id]
    consolidated = _consolidate_player_match_rows(squad_rows)
    season_rows = season_rows or []

    rows: list[dict[str, Any]] = []
    for row in consolidated:
        minutes = float(row.get("minutes") or 0) / 60.0
        if minutes <= 0:
            continue
        kpis = row.get("kpis") or {}
        player_id = int(row["playerId"])
        pos_group = position_group(row.get("position"))
        breakdown: dict[str, Any] = {}
        total = 0.0
        for col in PLAYER_PXT_COLUMNS:
            value = float(kpis.get(int(col["kpiId"])) or 0.0)
            value = round(value, 2)
            total += value
            annotation = annotate_metric(
                value,
                season_rows,
                player_id=player_id,
                position_group_key=pos_group,
                extract=_kpi_extract(int(col["kpiId"])),
                focus_squad_id=focus_squad_id,
                format_avg=_format_player_avg,
            )
            breakdown[str(col["id"])] = value
            breakdown[f"{col['id']}AvgDisplay"] = annotation["avgDisplay"]
            breakdown[f"{col['id']}Highlight"] = annotation["highlight"]

        total = round(total, 2)
        total_ann = annotate_metric(
            total,
            season_rows,
            player_id=player_id,
            position_group_key=pos_group,
            extract=_total_extract,
            focus_squad_id=focus_squad_id,
            format_avg=_format_player_avg,
        )
        rows.append(
            {
                "playerId": player_id,
                "playerName": row["name"],
                "minutes": round(minutes, 1),
                "position": row.get("position"),
                "positionGroup": pos_group,
                **breakdown,
                "total": total,
                "totalAvgDisplay": total_ann["avgDisplay"],
                "totalHighlight": total_ann["highlight"],
            }
        )

    rows.sort(key=lambda item: (-item["total"], -item["minutes"], item["playerName"]))
    return rows


def build_expected_threat(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None,
    *,
    opponent_name: str | None = None,
    game_count: int = 7,
) -> dict[str, Any]:
    title = "In-Possession — Expected Threat"
    if not iteration_id:
        return {
            "title": title,
            "description": "Packing Expected Threat breakdown from Impect",
            "opponentLabel": opponent_name or "Opponent",
            "teamMetrics": [],
            "players": [],
            "playerColumns": [
                {"id": col["id"], "label": col["label"]} for col in PLAYER_PXT_COLUMNS
            ],
            "legend": [
                {"id": "blue", "label": "Blue = top 10% of that player's own season"},
                {
                    "id": "gold",
                    "label": "Gold = top 10% for that position across the whole league this season",
                },
            ],
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

    team_metrics: list[dict[str, Any]] = []
    for spec in TEAM_METRIC_SPECS:
        focus_values: list[float] = []
        for recent_id in focus_recent_ids:
            kpis_by_squad, scores_by_squad = match_data.get(recent_id, ({}, {}))
            value = _metric_value(
                spec,
                kpis_by_squad.get(focus_squad_id, {}),
                scores_by_squad.get(focus_squad_id, {}),
            )
            if value is not None:
                focus_values.append(value)
        avg_value = _average_metric_values(focus_values)
        match_value = _metric_value(spec, focus_match_kpis, focus_match_scores)
        if spec["source"] == "kpi":
            rank_values = _iteration_kpi_values(iteration_id, int(spec["key"]))
        else:
            rank_values = _iteration_score_values(iteration_id, int(spec["key"]))
        team_metrics.append(
            _build_team_row(
                spec,
                avg_value=avg_value,
                match_value=match_value,
                rank_values=rank_values,
                focus_squad_id=focus_squad_id,
            )
        )

    from app.post_match.player_season_baselines import load_season_player_rows
    from app.post_match.report import _flatten_player_kpis, _player_directory

    player_names = _player_directory(iteration_id)
    players = _flatten_player_kpis(
        impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"],
        player_names,
    )
    season_rows = load_season_player_rows(
        iteration_id,
        focus_squad_id,
        before_match_id=match_id,
    )
    # Include the current match in personal/position pools so thresholds stay consistent.
    from app.post_match.player_season_baselines import _load_match_player_rows

    season_rows = season_rows + _load_match_player_rows(match_id, player_names)
    player_rows = _aggregate_players(players, focus_squad_id, season_rows)
    league_size = len(_iteration_score_values(iteration_id, SQUAD_SCORE_PXT_POSITIVE)) or 24

    return {
        "title": title,
        "description": (
            "Where threat came from (progressive passes / dribbles / ball wins / set pieces) "
            "and who generated the most Offensive PXT"
        ),
        "opponentLabel": opponent_name or "Opponent",
        "leagueSize": league_size,
        "teamMetrics": team_metrics,
        "players": player_rows,
        "playerColumns": [
            {"id": col["id"], "label": col["label"]} for col in PLAYER_PXT_COLUMNS
        ],
        "legend": [
            {"id": "blue", "label": "Blue = top 10% of that player's own season"},
            {
                "id": "gold",
                "label": "Gold = top 10% for that position across the whole league this season",
            },
        ],
        "gameCount": len(focus_recent_ids),
    }
