from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, unwrap_match_payload, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

KPI_BYPASSED_OPPONENTS_RAW = 1399
KPI_BYPASSED_DEFENDERS_RAW = 1400
KPI_BALL_LOSS_REMOVED_TEAMMATES = 21
KPI_CRITICAL_BALL_LOSS = 49

SQUAD_SCORE_BALL_POSSESSION = 23
SQUAD_SCORE_EXPECTED_THREAT = 48

TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "ballProgression",
        "label": "Ball Progression",
        "metricColor": "#22c55e",
        "source": "kpi",
        "key": KPI_BYPASSED_OPPONENTS_RAW,
        "higherIsBetter": True,
        "format": "int",
    },
    {
        "id": "defensiveBallControl",
        "label": "Defensive Ball Control",
        "metricColor": "#e11d48",
        "source": "kpi",
        "key": KPI_BALL_LOSS_REMOVED_TEAMMATES,
        "higherIsBetter": False,
        "format": "int",
    },
    {
        "id": "criticalBallLoss",
        "label": "Critical Ball Loss",
        "metricColor": "#db2777",
        "source": "kpi",
        "key": KPI_CRITICAL_BALL_LOSS,
        "higherIsBetter": False,
        "format": "int",
    },
    {
        "id": "ballPossession",
        "label": "Ball Possession",
        "metricColor": "#2563eb",
        "source": "score",
        "key": SQUAD_SCORE_BALL_POSSESSION,
        "higherIsBetter": True,
        "format": "percent",
    },
    {
        "id": "expectedThreat",
        "label": "Expected Threat",
        "metricColor": "#0d9488",
        "source": "score",
        "key": SQUAD_SCORE_EXPECTED_THREAT,
        "higherIsBetter": True,
        "format": "decimal",
    },
)

PLAYER_KPI_BREAKING = KPI_BYPASSED_DEFENDERS_RAW
PLAYER_KPI_PROGRESSION = KPI_BYPASSED_OPPONENTS_RAW
PLAYER_KPI_DEFENSIVE_CONTROL = KPI_BALL_LOSS_REMOVED_TEAMMATES


def _flatten_squad_scores_for_match(raw_data: Any) -> dict[int, dict[int, float]]:
    lookup: dict[int, dict[int, float]] = {}
    payload = unwrap_match_payload(raw_data) or {}

    if payload.get("squadHome") or payload.get("squadAway"):
        for key in ("squadHome", "squadAway"):
            squad = payload.get(key) or {}
            squad_id = squad.get("id")
            if squad_id is None:
                continue
            scores: dict[int, float] = {}
            for item in squad.get("squadScores") or []:
                score_id = item.get("squadScoreId")
                value = item.get("value")
                if score_id is None or value is None:
                    continue
                scores[int(score_id)] = float(value)
            lookup[int(squad_id)] = scores
        return lookup

    for row in extract_rows(raw_data):
        squad_id = row.get("squadId") or row.get("squad_id")
        if squad_id is None:
            continue
        scores: dict[int, float] = {}
        for item in row.get("squadScores") or row.get("scores") or []:
            score_id = item.get("squadScoreId") or item.get("scoreId")
            value = item.get("value")
            if score_id is None or value is None:
                continue
            scores[int(score_id)] = float(value)
        lookup[int(squad_id)] = scores

    return lookup


def _iteration_kpi_values(iteration_id: int, kpi_id: int) -> dict[int, float]:
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/squad-kpis"))["data"])
    values: dict[int, float] = {}
    for row in rows:
        squad_id = int(row.get("squadId") or 0)
        if not squad_id:
            continue
        for item in row.get("kpis") or []:
            raw_id = item.get("kpiId")
            if raw_id is None or int(raw_id) != kpi_id:
                continue
            value = item.get("value")
            if value is not None:
                values[squad_id] = float(value)
    return values


def _iteration_score_values(iteration_id: int, score_id: int) -> dict[int, float]:
    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/squad-scores"))["data"])
    values: dict[int, float] = {}
    for row in rows:
        squad_id = int(row.get("squadId") or 0)
        if not squad_id:
            continue
        for item in row.get("squadScores") or []:
            raw_id = item.get("squadScoreId")
            if raw_id is None or int(raw_id) != score_id:
                continue
            value = item.get("value")
            if value is not None:
                values[squad_id] = float(value)
    return values


def _fetch_match_team_data(match_id: int) -> tuple[int, dict[int, dict[int, float]], dict[int, dict[int, float]]]:
    from app.post_match.report import _flatten_squad_kpis

    kpis = _flatten_squad_kpis(impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"])
    scores = _flatten_squad_scores_for_match(
        impect_get(v5_path(f"/matches/{match_id}/squad-scores"))["data"]
    )
    return match_id, kpis, scores


def _load_match_team_data(match_ids: set[int]) -> dict[int, tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]]:
    if not match_ids:
        return {}
    loaded: dict[int, tuple[dict[int, dict[int, float]], dict[int, dict[int, float]]]] = {}
    workers = min(12, len(match_ids))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_match_team_data, mid): mid for mid in match_ids}
        for future in as_completed(futures):
            match_id, kpis, scores = future.result()
            loaded[match_id] = (kpis, scores)
    return loaded


def _metric_value(
    spec: dict[str, Any],
    kpis: dict[int, float],
    scores: dict[int, float],
) -> float | None:
    key = int(spec["key"])
    if spec["source"] == "kpi":
        return kpis.get(key)
    return scores.get(key)


def _average_metric_values(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _performance_band(
    match_value: float | None,
    avg_value: float | None,
    *,
    higher_is_better: bool,
) -> str:
    if match_value is None or avg_value is None:
        return "neutral"
    if avg_value == 0:
        if higher_is_better:
            return "good" if match_value > 0 else "neutral"
        return "good" if match_value == 0 else "bad"
    delta_pct = ((match_value - avg_value) / abs(avg_value)) * 100
    if higher_is_better:
        if delta_pct > 5:
            return "good"
        if delta_pct < -5:
            return "bad"
        return "neutral"
    if delta_pct < -5:
        return "good"
    if delta_pct > 5:
        return "bad"
    return "neutral"


def _rank_for_value(
    squad_values: dict[int, float],
    focus_squad_id: int,
    *,
    higher_is_better: bool,
) -> int | None:
    if focus_squad_id not in squad_values:
        return None
    ordered = sorted(
        squad_values.items(),
        key=lambda item: item[1],
        reverse=higher_is_better,
    )
    for index, (squad_id, _) in enumerate(ordered, start=1):
        if squad_id == focus_squad_id:
            return index
    return None


def _top7_average(
    squad_values: dict[int, float],
    *,
    higher_is_better: bool,
    top_n: int = 7,
) -> float | None:
    if not squad_values:
        return None
    ordered = sorted(
        squad_values.items(),
        key=lambda item: item[1],
        reverse=higher_is_better,
    )
    top_values = [value for _, value in ordered[:top_n]]
    if not top_values:
        return None
    return sum(top_values) / len(top_values)


def _build_team_metric_row(
    spec: dict[str, Any],
    *,
    avg_value: float | None,
    match_value: float | None,
    rank_values: dict[int, float],
    focus_squad_id: int,
    section: str | None = None,
) -> dict[str, Any]:
    higher_is_better = bool(spec["higherIsBetter"])
    top7_value = _top7_average(rank_values, higher_is_better=higher_is_better)
    row: dict[str, Any] = {
        "id": spec["id"],
        "label": spec["label"],
        "metricColor": spec.get("metricColor"),
        "avgValue": avg_value,
        "avgDisplay": _format_metric_value(avg_value, spec["format"]),
        "avgRank": _rank_for_value(
            rank_values,
            focus_squad_id,
            higher_is_better=higher_is_better,
        ),
        "top7AvgValue": top7_value,
        "top7AvgDisplay": _format_metric_value(top7_value, spec["format"]),
        "matchValue": match_value,
        "matchDisplay": _format_metric_value(match_value, spec["format"]),
        "matchBand": _performance_band(
            match_value,
            avg_value,
            higher_is_better=higher_is_better,
        ),
        "matchTop7Band": _performance_band(
            match_value,
            top7_value,
            higher_is_better=higher_is_better,
        ),
        "higherIsBetter": higher_is_better,
    }
    if section:
        row["section"] = section
    return row


def _format_metric_value(value: float | None, fmt: str) -> str | None:
    if value is None:
        return None
    if fmt == "percent":
        return f"{round(value * 100, 1)}%"
    if fmt == "decimal":
        rounded = round(value, 1)
        return str(int(rounded)) if rounded == int(rounded) else f"{rounded:.1f}"
    return str(int(round(value)))


def _format_player_avg_int(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{int(round(value))} avg"


def _kpi_extractor(kpi_id: int):
    def _extract(row: dict[str, Any]) -> float | None:
        kpis = row.get("kpis") or {}
        if not kpis:
            return None
        return float(kpis.get(kpi_id) or kpis.get(str(kpi_id)) or 0.0)

    return _extract


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

    metric_cols = (
        ("breakingOpponentDefence", PLAYER_KPI_BREAKING),
        ("ballProgression", PLAYER_KPI_PROGRESSION),
        ("defensiveBallControl", PLAYER_KPI_DEFENSIVE_CONTROL),
    )

    rows: list[dict[str, Any]] = []
    for row in consolidated:
        minutes = float(row.get("minutes") or 0) / 60.0
        if minutes <= 0:
            continue
        kpis = row.get("kpis") or {}
        player_id = int(row["playerId"])
        pos_group = position_group(row.get("position"))
        payload: dict[str, Any] = {
            "playerId": player_id,
            "playerName": row["name"],
            "minutes": round(minutes, 1),
            "position": row.get("position"),
            "positionGroup": pos_group,
        }
        for key, kpi_id in metric_cols:
            value = int(round(kpis.get(kpi_id) or 0))
            annotation = annotate_metric(
                float(value),
                season_rows,
                player_id=player_id,
                position_group_key=pos_group,
                extract=_kpi_extractor(kpi_id),
                focus_squad_id=focus_squad_id,
                format_avg=_format_player_avg_int,
            )
            payload[key] = value
            payload[f"{key}AvgDisplay"] = annotation["avgDisplay"]
            payload[f"{key}Highlight"] = annotation["highlight"]
        rows.append(payload)

    rows.sort(
        key=lambda row: (-row["breakingOpponentDefence"], -row["ballProgression"], row["playerName"]),
    )
    return rows


def build_ball_progression(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None,
    *,
    opponent_name: str | None = None,
    game_count: int = 7,
) -> dict[str, Any]:
    if not iteration_id:
        return {
            "title": "In-Possession — Ball Progression",
            "description": "Ball progression metrics from Impect",
            "opponentLabel": opponent_name or "Opponent",
            "teamMetrics": [],
            "players": [],
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
            )
        )

    from app.post_match.player_season_baselines import _load_match_player_rows, load_season_player_rows
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
    ) + _load_match_player_rows(match_id, player_names)
    player_rows = _aggregate_players(players, focus_squad_id, season_rows)

    league_size = len(_iteration_kpi_values(iteration_id, KPI_BYPASSED_OPPONENTS_RAW)) or 24

    return {
        "title": "In-Possession — Ball Progression",
        "description": "Team KPIs vs 7-game average with league rank · player bypassing & progression",
        "opponentLabel": opponent_name or "Opponent",
        "leagueSize": league_size,
        "teamMetrics": team_metrics,
        "players": player_rows,
        "legend": [
            {"id": "blue", "label": "Blue = top 10% of that player's own season"},
            {
                "id": "gold",
                "label": "Gold = top 10% for that position across the whole league this season",
            },
        ],
        "gameCount": len(focus_recent_ids),
    }
