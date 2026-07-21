from __future__ import annotations

import calendar
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.label_utils import humanize_profile_name
from app.profile_resolve import resolve_factor_inverted

MONTHLY_MATCH_PAUSE_SECONDS = 0.4
MONTHLY_BENCHMARK_MINUTES = 90.0
MONTHLY_DEFAULT_MIN_MINUTES = 180.0

_matches_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_match_kpi_cache: dict[int, tuple[float, dict[tuple[int, int], list[dict[str, Any]]]]] = {}
_MATCHES_CACHE_TTL = 3600
_MATCH_KPI_CACHE_TTL = 3600


class ScoutingMonthlyListRequest(BaseModel):
    position: str
    leagues: list[str] = Field(default_factory=list)
    year: int
    month: int = Field(ge=1, le=12)
    min_minutes: float = MONTHLY_DEFAULT_MIN_MINUTES


def _impect():
    from app import main as impect_main

    return impect_main


def _month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def _default_previous_month() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def _parse_scheduled_date(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _fetch_iteration_matches(iteration_id: int) -> list[dict[str, Any]]:
    cached = _matches_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < _MATCHES_CACHE_TTL:
        return cached[1]

    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches")
    rows = impect._extract_rows(raw["data"])
    _matches_cache[iteration_id] = (now, rows)
    return rows


def _matches_in_calendar_month(
    matches: list[dict[str, Any]],
    *,
    year: int,
    month: int,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for match in matches:
        if match.get("available") is False:
            continue
        scheduled = _parse_scheduled_date(match.get("scheduledDate"))
        if scheduled is None:
            continue
        if scheduled.year == year and scheduled.month == month:
            filtered.append(match)
    return filtered


def _unwrap_match_payload(raw_data: Any) -> dict[str, Any]:
    if isinstance(raw_data, dict) and isinstance(raw_data.get("data"), dict):
        return raw_data["data"]
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def _flatten_match_players(payload: dict[str, Any], squad_key: str) -> list[dict[str, Any]]:
    squad = payload.get(squad_key) or {}
    squad_id = squad.get("id")
    rows: list[dict[str, Any]] = []
    for player in squad.get("players") or []:
        if not isinstance(player, dict):
            continue
        row = dict(player)
        player_id = row.pop("id", None)
        if player_id is None:
            continue
        row["playerId"] = int(player_id)
        row["_squadId"] = int(squad_id) if squad_id is not None else None
        rows.append(row)
    return rows


def _fetch_match_position_scores(match_id: int, position: str) -> list[dict[str, Any]]:
    impect = _impect()
    path = (
        f"/v5/{impect._api_prefix()}/matches/{match_id}"
        f"/positions/{position}/player-scores"
    )
    raw = impect._impect_get(path)
    payload = _unwrap_match_payload(raw["data"])
    rows: list[dict[str, Any]] = []
    for squad_key in ("squadHome", "squadAway"):
        rows.extend(_flatten_match_players(payload, squad_key))
    return rows


def _fetch_match_player_kpis(match_id: int) -> dict[tuple[int, int], list[dict[str, Any]]]:
    cached = _match_kpi_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < _MATCH_KPI_CACHE_TTL:
        return cached[1]

    impect = _impect()
    path = f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
    raw = impect._impect_get(path)
    payload = _unwrap_match_payload(raw["data"])
    lookup: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for squad_key in ("squadHome", "squadAway"):
        squad = payload.get(squad_key) or {}
        squad_id = squad.get("id")
        if squad_id is None:
            continue
        squad_id = int(squad_id)
        for player in squad.get("players") or []:
            if not isinstance(player, dict):
                continue
            player_id = player.get("id")
            if player_id is None:
                continue
            kpis = player.get("kpis")
            if isinstance(kpis, list) and kpis:
                lookup[(squad_id, int(player_id))] = kpis

    _match_kpi_cache[match_id] = (now, lookup)
    return lookup


def prefetch_monthly_match_kpis(
    *,
    leagues: list[str],
    year: int,
    month: int,
) -> dict[str, Any]:
    """Warm match lists + KPI cache once before a multi-position monthly report."""
    from app.scouting import (
        SCOUTING_COMPETITION_TO_LEAGUE,
        SCOUTING_LEAGUE_TO_COMPETITION,
        _scouting_iteration_rows,
    )

    selected_competitions: list[str] = []
    for league in leagues:
        competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
        if competition is None:
            raise HTTPException(status_code=400, detail=f"Unknown league: {league}")
        selected_competitions.append(competition)

    iteration_rows = _scouting_iteration_rows(
        selected_competitions,
        season_offset=0,
        combine_seasons=True,
    )

    match_ids: list[int] = []
    warnings: list[str] = []
    for iteration in iteration_rows:
        iteration_id = int(iteration["id"])
        competition_name = str(iteration.get("competition_name", ""))
        league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(competition_name, competition_name)
        season_label = str(iteration.get("season", "")).strip()
        try:
            all_matches = _fetch_iteration_matches(iteration_id)
            month_matches = _matches_in_calendar_month(all_matches, year=year, month=month)
            for match in month_matches:
                match_id = int(match["id"])
                if match_id not in _match_kpi_cache:
                    match_ids.append(match_id)
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            warnings.append(f"{league_label} {season_label}: skipped ({exc.detail}).")

    # Load KPIs once per match — shared by every position in this report.
    for index, match_id in enumerate(match_ids):
        try:
            _fetch_match_player_kpis(match_id)
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            warnings.append(f"Match {match_id} KPI prefetch skipped ({exc.detail}).")
        if index < len(match_ids) - 1:
            time.sleep(MONTHLY_MATCH_PAUSE_SECONDS)

    return {
        "matchCount": len(match_ids),
        "warnings": warnings,
    }


def _accumulate_weighted_metric(
    totals: dict[Any, float],
    weights: dict[Any, float],
    metric_id: Any,
    value: float,
    minutes: float,
) -> None:
    if minutes <= 0:
        return
    totals[metric_id] = totals.get(metric_id, 0.0) + value * minutes
    weights[metric_id] = weights.get(metric_id, 0.0) + minutes


def _finalize_weighted_metrics(
    totals: dict[Any, float],
    weights: dict[Any, float],
) -> dict[Any, float]:
    finalized: dict[Any, float] = {}
    for metric_id, total in totals.items():
        weight = weights.get(metric_id, 0.0)
        if weight > 0:
            finalized[metric_id] = total / weight
    return finalized


def _aggregate_monthly_rows(match_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    impect = _impect()
    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}

    for row in match_rows:
        player_id = row.get("playerId")
        squad_id = row.get("_squadId")
        iteration_id = row.get("_iterationId")
        if player_id is None or squad_id is None or iteration_id is None:
            continue

        key = (int(iteration_id), int(squad_id), int(player_id))
        bucket = grouped.setdefault(
            key,
            {
                "playerId": int(player_id),
                "_squadId": int(squad_id),
                "_iterationId": int(iteration_id),
                "_leagueLabel": row.get("_leagueLabel", ""),
                "_competitionName": row.get("_competitionName", ""),
                "_seasonLabel": row.get("_seasonLabel", ""),
                "_matchCount": 0,
                "_totalMinutes": 0.0,
                "_scoreTotals": defaultdict(float),
                "_scoreWeights": defaultdict(float),
                "_kpiTotals": defaultdict(float),
                "_kpiWeights": defaultdict(float),
            },
        )

        minutes = impect._play_duration_minutes(row) or 0.0
        if minutes <= 0:
            continue

        bucket["_matchCount"] += 1
        bucket["_totalMinutes"] += minutes

        for score in row.get("playerScores") or []:
            if not isinstance(score, dict):
                continue
            score_id = score.get("playerScoreId")
            value = impect._to_number(score.get("value"))
            if score_id is None or value is None:
                continue
            _accumulate_weighted_metric(
                bucket["_scoreTotals"],
                bucket["_scoreWeights"],
                int(score_id),
                value,
                minutes,
            )

        for kpi in row.get("kpis") or []:
            if not isinstance(kpi, dict):
                continue
            kpi_id = kpi.get("kpiId")
            value = impect._to_number(kpi.get("value"))
            if kpi_id is None or value is None:
                continue
            _accumulate_weighted_metric(
                bucket["_kpiTotals"],
                bucket["_kpiWeights"],
                int(kpi_id),
                value,
                minutes,
            )

    aggregated: list[dict[str, Any]] = []
    for bucket in grouped.values():
        score_values = _finalize_weighted_metrics(
            bucket["_scoreTotals"],
            bucket["_scoreWeights"],
        )
        kpi_values = _finalize_weighted_metrics(
            bucket["_kpiTotals"],
            bucket["_kpiWeights"],
        )
        aggregated.append(
            {
                "playerId": bucket["playerId"],
                "_squadId": bucket["_squadId"],
                "_iterationId": bucket["_iterationId"],
                "_leagueLabel": bucket["_leagueLabel"],
                "_competitionName": bucket["_competitionName"],
                "_seasonLabel": bucket["_seasonLabel"],
                "_matchCount": bucket["_matchCount"],
                "playDuration": bucket["_totalMinutes"],
                "playerScores": [
                    {"playerScoreId": score_id, "value": value}
                    for score_id, value in score_values.items()
                ],
                "kpis": [{"kpiId": kpi_id, "value": value} for kpi_id, value in kpi_values.items()],
            }
        )
    return aggregated


def _player_kpi_value(row: dict[str, Any], kpi_id: int) -> float | None:
    for kpi in row.get("kpis") or []:
        if isinstance(kpi, dict) and kpi.get("kpiId") == kpi_id:
            return _impect()._to_number(kpi.get("value"))
    return None


def _kpi_values_for_key(
    cohort_rows: list[dict[str, Any]],
    kpi_id: int,
) -> list[float]:
    values: list[float] = []
    for row in cohort_rows:
        value = _player_kpi_value(row, kpi_id)
        if value is not None:
            values.append(value)
    return values


def _resolve_factor_metric(
    factor: dict[str, Any],
    row: dict[str, Any],
    scores_by_name: dict[str, dict[str, Any]],
    kpi_by_name: dict[str, dict[str, Any]],
) -> tuple[int | None, float | None, str]:
    impect = _impect()
    factor_type = str(factor.get("type") or "SCORE").strip().upper()
    factor_name = str(factor.get("name") or "").strip()

    if factor_type == "KPI":
        kpi_entry = kpi_by_name.get(factor_name.casefold())
        if not kpi_entry:
            return None, None, "kpi"
        kpi_id = int(kpi_entry["id"])
        return kpi_id, _player_kpi_value(row, kpi_id), "kpi"

    score_id = impect._resolve_factor_score_id(factor, scores_by_name)
    if score_id is None:
        return None, None, "score"
    return score_id, impect._player_score_value(row, score_id), "score"


def _profile_score_percentile_from_row(
    profile_name: str,
    row: dict[str, Any],
    cohort_rows: list[dict[str, Any]],
) -> float | None:
    impect = _impect()
    profile_definitions = impect._fetch_player_profile_definitions()
    scores_by_id, scores_by_name = impect._fetch_player_score_catalog()
    kpi_by_name = _fetch_kpi_catalog()
    definition = impect._resolve_profile_definition(profile_name, profile_definitions)
    if definition is None:
        return None

    resolved_factors: list[dict[str, Any]] = []
    for factor in definition.get("factors", []):
        metric_id, value, metric_kind = _resolve_factor_metric(
            factor,
            row,
            scores_by_name,
            kpi_by_name,
        )
        factor_name = str(factor.get("name") or "").strip()
        if metric_id is None or value is None:
            continue

        if metric_kind == "kpi":
            cohort_values = _kpi_values_for_key(cohort_rows, int(metric_id))
            inverted = bool(factor.get("inverted", False))
            catalog_entry: dict[str, Any] = {"inverted": inverted}
        else:
            cohort_values = impect._cohort_values_for_key(
                cohort_rows,
                "playerScoreId",
                int(metric_id),
                "playerScores",
            )
            catalog_entry = scores_by_id.get(int(metric_id), {})
            inverted = resolve_factor_inverted(factor, catalog_entry)

        if not cohort_values:
            continue

        percentile = impect._cohort_percentile(value, cohort_values)
        if percentile is None:
            continue
        if inverted:
            percentile = round(100.0 - percentile, 1)

        resolved_factors.append(
            {
                "weight": float(factor.get("weight") or 0.0),
                "percentile": float(percentile),
            }
        )

    if not resolved_factors:
        return None

    total_weight = sum(item["weight"] for item in resolved_factors)
    if total_weight <= 0:
        return None

    return round(
        sum(item["percentile"] * item["weight"] for item in resolved_factors) / total_weight,
        1,
    )


def _fetch_kpi_catalog() -> dict[str, dict[str, Any]]:
    impect = _impect()

    def load() -> dict[str, dict[str, Any]]:
        rows = impect._extract_rows(impect._impect_get("/v5/customerapi/kpis")["data"])
        catalog: dict[str, dict[str, Any]] = {}
        for row in rows:
            kpi_id = row.get("id")
            name = str(row.get("name") or "").strip()
            if kpi_id is None or not name:
                continue
            catalog[name.casefold()] = {"id": int(kpi_id), "name": name}
        return catalog

    return impect._cached_catalog("kpis:v1", load)


def _load_monthly_match_rows(
    iteration: dict[str, Any],
    *,
    position: str,
    year: int,
    month: int,
    league_label: str,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    impect = _impect()
    iteration_id = int(iteration["id"])
    competition_name = str(iteration.get("competition_name", ""))
    season_label = str(iteration.get("season", "")).strip()

    all_matches = _fetch_iteration_matches(iteration_id)
    month_matches = _matches_in_calendar_month(all_matches, year=year, month=month)
    if not month_matches:
        return [], 0, []

    warnings: list[str] = []
    match_rows: list[dict[str, Any]] = []

    for index, match in enumerate(month_matches):
        match_id = int(match["id"])
        try:
            players = _fetch_match_position_scores(match_id, position)
            kpi_lookup = _fetch_match_player_kpis(match_id)
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            warnings.append(f"Match {match_id} skipped ({exc.detail}).")
            continue

        for player_row in players:
            player_row["_iterationId"] = iteration_id
            player_row["_competitionName"] = competition_name
            player_row["_seasonLabel"] = season_label
            player_row["_leagueLabel"] = league_label
            squad_id = player_row.get("_squadId")
            player_id = player_row.get("playerId")
            if squad_id is not None and player_id is not None:
                kpis = kpi_lookup.get((int(squad_id), int(player_id)))
                if kpis:
                    player_row["kpis"] = kpis
            match_rows.append(player_row)

        # Only throttle when we actually hit the scores endpoint for this match.
        if index < len(month_matches) - 1:
            time.sleep(MONTHLY_MATCH_PAUSE_SECONDS)

    return match_rows, len(month_matches), warnings


def build_scouting_monthly_list(body: ScoutingMonthlyListRequest) -> dict[str, Any]:
    from app.scouting import (
        SCOUTING_COMPETITION_TO_LEAGUE,
        SCOUTING_LEAGUE_TO_COMPETITION,
        _format_foot,
        _format_height,
        _get_position_shares,
        _get_primary_positions,
        _player_plays_position,
        _profiles_for_position,
        _scouting_iteration_rows,
        _scouting_position_label,
        build_scouting_player_chart_bundle,
    )

    impect = _impect()
    position = body.position.strip()
    if position not in impect.ALLOWED_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported position: {position}")
    if not body.leagues:
        raise HTTPException(status_code=400, detail="Select at least one league.")

    profiles = _profiles_for_position(position)
    if not profiles:
        raise HTTPException(
            status_code=404,
            detail=f"No Port Vale profiles found for {_scouting_position_label(position)}.",
        )

    selected_competitions: list[str] = []
    for league in body.leagues:
        competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
        if competition is None:
            raise HTTPException(status_code=400, detail=f"Unknown league: {league}")
        selected_competitions.append(competition)

    # Calendar months often sit in the previous football season once Impect has
    # published the next season shell (e.g. June 2026 is 25/26 while "current" is 26/27).
    # Load both so the date filter can pick the right matches.
    iteration_rows = _scouting_iteration_rows(
        selected_competitions,
        season_offset=0,
        combine_seasons=True,
    )
    if not iteration_rows:
        raise HTTPException(status_code=404, detail="No season data for the selected leagues.")

    month_label = _month_label(body.year, body.month)
    warnings: list[str] = []
    match_count_total = 0
    raw_match_rows: list[dict[str, Any]] = []
    player_lookup: dict[tuple[int, int], dict[str, Any]] = {}
    squad_names_by_iteration: dict[int, dict[int, str]] = {}
    primary_by_iteration: dict[int, dict[int, str] | None] = {}
    shares_by_iteration: dict[int, dict[int, dict[str, float]] | None] = {}

    for iteration in iteration_rows:
        iteration_id = int(iteration["id"])
        competition_name = str(iteration["competition_name"])
        league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(competition_name, competition_name)
        season_label = str(iteration.get("season", "")).strip()

        try:
            primary_by_iteration[iteration_id] = _get_primary_positions(iteration_id)
            shares_by_iteration[iteration_id] = _get_position_shares(iteration_id)
            squad_names_by_iteration[iteration_id] = impect._fetch_squad_names(iteration_id)

            league_rows, match_count, league_warnings = _load_monthly_match_rows(
                iteration,
                position=position,
                year=body.year,
                month=body.month,
                league_label=league_label,
            )
            match_count_total += match_count
            raw_match_rows.extend(league_rows)
            warnings.extend(league_warnings)

            for player in impect._fetch_players_for_iteration(iteration_id):
                player_id = player.get("id")
                if player_id is not None:
                    player_lookup[(iteration_id, int(player_id))] = player
        except HTTPException as exc:
            if exc.status_code == 429:
                raise
            # Skip seasons the account cannot access yet (common for newly published shells).
            warnings.append(
                f"{league_label} {season_label}: skipped ({exc.detail})."
            )
            continue

    if match_count_total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No matches found in {month_label} for the selected leagues.",
        )

    aggregated_rows = _aggregate_monthly_rows(raw_match_rows)
    if not aggregated_rows:
        raise HTTPException(
            status_code=404,
            detail=f"No { _scouting_position_label(position)} minutes recorded in {month_label}.",
        )

    eligible_rows: list[dict[str, Any]] = []
    cohort_by_league: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in aggregated_rows:
        iteration_id = int(row["_iterationId"])
        primary_positions = primary_by_iteration.get(iteration_id)
        position_shares = shares_by_iteration.get(iteration_id)
        player_id = int(row["playerId"])
        minutes = float(row.get("playDuration") or 0.0)

        if position_shares is not None:
            if not _player_plays_position(position_shares, player_id, position):
                continue
        elif primary_positions is not None:
            if primary_positions.get(player_id) != position:
                continue

        league_label = str(row.get("_leagueLabel") or "")
        row["_combinedMinutes"] = minutes
        cohort_by_league[league_label].append(row)
        if minutes >= body.min_minutes:
            eligible_rows.append(row)

    if not eligible_rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {_scouting_position_label(position)} players with "
                f"{body.min_minutes:.0f}+ minutes in {month_label}."
            ),
        )

    benchmark_by_league: dict[str, list[dict[str, Any]]] = {
        league: [row for row in rows if float(row.get("_combinedMinutes") or 0) >= MONTHLY_BENCHMARK_MINUTES]
        for league, rows in cohort_by_league.items()
    }

    players_payload: list[dict[str, Any]] = []
    for row in eligible_rows:
        iteration_id = int(row["_iterationId"])
        player_id = int(row["playerId"])
        squad_id = row.get("_squadId")
        league_label = str(row.get("_leagueLabel") or "")
        league_cohort = benchmark_by_league.get(league_label, [])

        profile_scores: dict[str, float | None] = {}
        for profile_name in profiles:
            profile_scores[profile_name] = _profile_score_percentile_from_row(
                profile_name,
                row,
                league_cohort,
            )

        if not any(value is not None for value in profile_scores.values()):
            continue

        catalog_player = player_lookup.get((iteration_id, player_id), {})
        name = impect._extract_player_name(catalog_player) or f"Player {player_id}"
        club = ""
        if squad_id is not None:
            club = squad_names_by_iteration.get(iteration_id, {}).get(int(squad_id), "")

        chart_bundle = build_scouting_player_chart_bundle(
            name=name,
            player_id=player_id,
            iteration_id=iteration_id,
            squad_id=int(squad_id) if squad_id is not None else None,
            position=position,
            profiles=profiles,
        )

        players_payload.append(
            {
                "id": f"{iteration_id}:{player_id}",
                "name": name,
                "age": impect._player_age(catalog_player),
                "height": _format_height(catalog_player),
                "foot": _format_foot(catalog_player.get("leg")),
                "league": league_label,
                "club": club,
                "season": str(row.get("_seasonLabel", "")),
                "minutes": int(round(float(row.get("_combinedMinutes") or 0))),
                "matchCount": int(row.get("_matchCount") or 0),
                "profileScores": profile_scores,
                **chart_bundle,
            }
        )

    if not players_payload:
        raise HTTPException(
            status_code=404,
            detail=f"No profile scores could be computed for {month_label}.",
        )

    scoring_note = (
        f"Calendar month only ({month_label}). Profile scores are minutes-weighted across "
        f"match appearances, then ranked vs others in the same league with "
        f"{MONTHLY_BENCHMARK_MINUTES:.0f}+ minutes that month (primary role)."
    )

    return {
        "position": position,
        "positionLabel": _scouting_position_label(position),
        "profiles": [
            {"apiName": name, "label": humanize_profile_name(name)} for name in profiles
        ],
        "players": players_payload,
        "playerCount": len(players_payload),
        "primaryFilterReady": all(value is not None for value in primary_by_iteration.values()),
        "reportMode": "monthly",
        "monthLabel": month_label,
        "year": body.year,
        "month": body.month,
        "matchCount": match_count_total,
        "seasonMode": "monthly",
        "seasonModeLabel": f"Monthly highlights — {month_label}",
        "scoring": {
            "method": "monthly_league_relative_percentile",
            "benchmarkMinutes": MONTHLY_BENCHMARK_MINUTES,
            "note": scoring_note,
            "leagueCohortSizes": {
                league: len(rows) for league, rows in benchmark_by_league.items()
            },
        },
        "seasons": [
            {
                "league": SCOUTING_COMPETITION_TO_LEAGUE.get(
                    str(row["competition_name"]), row["competition_name"]
                ),
                "season": row.get("season"),
                "iterationId": row["id"],
            }
            for row in iteration_rows
        ],
        "minMinutes": body.min_minutes,
        "warnings": warnings,
    }


def monthly_meta_defaults() -> dict[str, Any]:
    year, month = _default_previous_month()
    return {
        "default_year": year,
        "default_month": month,
        "default_min_minutes": MONTHLY_DEFAULT_MIN_MINUTES,
        "benchmark_minutes": MONTHLY_BENCHMARK_MINUTES,
    }
