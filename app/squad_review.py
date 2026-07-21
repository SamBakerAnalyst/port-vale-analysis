from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.label_utils import humanize_profile_name
from app.squad_photos import resolve_squad_photo_url
from app.squad_review_pdf import build_squad_review_pdf
from app.scouting import (
    SCOUTING_DIR,
    _cohort_values_by_profile,
    _league_benchmark_rows,
    _load_iteration_bundle,
    _normalize_profile_key,
    _profile_value_map,
    _profiles_for_position,
    _scouting_iteration_rows,
    _scouting_position_label,
)

_squad_minutes_cache: dict[tuple[int, int], dict[int, float]] = {}
_port_vale_iteration_cache: dict[str, dict[str, Any]] = {}
_port_vale_seasons_cache: list[dict[str, Any]] | None = None

PORT_VALE_COMPETITIONS = ("League One", "League Two")
PORT_VALE_SQUAD_TOKENS = ("port vale",)

POSITION_SHORT_LABELS: dict[str, str] = {
    "GOALKEEPER": "GK",
    "LEFT_WINGBACK_DEFENDER": "LB",
    "RIGHT_WINGBACK_DEFENDER": "RB",
    "CENTRAL_DEFENDER": "CB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "CF",
}

MIDFIELD_COMPARISON_POSITIONS = (
    "CENTRAL_MIDFIELD",
    "DEFENSE_MIDFIELD",
    "ATTACKING_MIDFIELD",
)

PROFILE_KEY_CREATOR = "pv - creator (cm)"
PROFILE_KEY_RUNNING = "pv - running threat (cm)"
PROFILE_KEY_GOAL = "pv - goal threat - (cm)"
PROFILE_KEY_WINNER = "pv - ball winner (cm)"
PROFILE_KEY_PROGRESSOR = "pv - ball progressor - (10)"


class SquadReviewRequest(BaseModel):
    position: str
    min_minutes: float = 0
    player_ids: list[int] = Field(default_factory=list)
    season: str | None = None


class SquadReviewExportAllRequest(BaseModel):
    min_minutes: float = 0
    max_players: int = Field(default=5, ge=2, le=5)
    selections: dict[str, list[int]] = Field(default_factory=dict)
    season: str | None = None


def _impect():
    from app import main as impect_main

    return impect_main


def _is_port_vale_squad(name: str) -> bool:
    lowered = str(name or "").casefold().replace(".", "")
    return any(token in lowered for token in PORT_VALE_SQUAD_TOKENS)


def _resolve_port_vale_squad_id(squad_names: dict[int, str]) -> int | None:
    for squad_id, name in squad_names.items():
        if _is_port_vale_squad(name):
            return int(squad_id)
    return None


def _iteration_competition(iteration: dict[str, Any]) -> str:
    return str(iteration.get("competition_name", "League One")).strip()


def _iteration_has_port_vale_scores(
    iteration: dict[str, Any],
    port_vale_squad_id: int,
    *,
    quick: bool = False,
) -> bool:
    impect = _impect()
    positions = (["CENTRAL_MIDFIELD"], impect.ALLOWED_POSITIONS)[0 if quick else 1]
    for position in positions:
        bundle = _load_iteration_bundle(iteration, position, 0)
        for row in bundle["score_rows"]:
            squad_id = row.get("_squadId") or row.get("squadId")
            if squad_id is not None and int(squad_id) == port_vale_squad_id:
                return True
    return False


def _port_vale_has_score_data(iteration: dict[str, Any], port_vale_squad_id: int) -> bool:
    return _iteration_has_port_vale_scores(iteration, port_vale_squad_id, quick=False)


def _normalize_season_token(season: str) -> str:
    token = str(season or "").strip()
    if not token:
        return ""
    if "/" in token:
        return token
    digits = "".join(ch for ch in token if ch.isdigit())
    if len(digits) == 4:
        return f"{digits[:2]}/{digits[2:]}"
    return token


def _port_vale_candidate_iterations(impect: Any | None = None) -> list[dict[str, Any]]:
    impect = impect or _impect()
    iterations = impect._fetch_iterations()
    candidates = [
        item
        for item in iterations
        if str(item.get("competition_name", "")).strip() in PORT_VALE_COMPETITIONS
    ]
    candidates.sort(
        key=lambda row: impect._season_sort_key(str(row.get("season", ""))),
        reverse=True,
    )
    return candidates


def _resolve_port_vale_iteration(season: str | None = None) -> dict[str, Any]:
    """Resolve the Impect iteration for Port Vale, optionally pinned to a season."""
    cache_key = _normalize_season_token(season) if season else "__auto__"
    cached = _port_vale_iteration_cache.get(cache_key)
    if cached is not None:
        return cached

    impect = _impect()
    candidates = _port_vale_candidate_iterations(impect)

    if season:
        target = _normalize_season_token(season)
        season_iterations = [
            item
            for item in candidates
            if str(item.get("season", "")).strip() == target
        ]
        if not season_iterations:
            raise HTTPException(
                status_code=404,
                detail=f"No Port Vale squad found for season {target}.",
            )
        for iteration in season_iterations:
            squad_names = impect._fetch_squad_names(int(iteration["id"]))
            port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
            if port_vale_squad_id is None:
                continue
            if _port_vale_has_score_data(iteration, port_vale_squad_id):
                _port_vale_iteration_cache[cache_key] = iteration
                return iteration
        for iteration in season_iterations:
            squad_names = impect._fetch_squad_names(int(iteration["id"]))
            if _resolve_port_vale_squad_id(squad_names) is not None:
                _port_vale_iteration_cache[cache_key] = iteration
                return iteration
        raise HTTPException(
            status_code=404,
            detail=f"No Port Vale squad found for season {target}.",
        )

    for iteration in candidates:
        squad_names = impect._fetch_squad_names(int(iteration["id"]))
        port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
        if port_vale_squad_id is None:
            continue
        if _port_vale_has_score_data(iteration, port_vale_squad_id):
            _port_vale_iteration_cache[cache_key] = iteration
            return iteration

    raise HTTPException(
        status_code=404,
        detail=(
            "Port Vale were found in Impect but no profile scores are available yet "
            "for the current season. Try again once Impect has loaded 26/27 data."
        ),
    )


def _available_port_vale_seasons() -> list[dict[str, Any]]:
    global _port_vale_seasons_cache
    if _port_vale_seasons_cache is not None:
        return _port_vale_seasons_cache

    impect = _impect()
    by_season: dict[str, list[dict[str, Any]]] = {}
    for iteration in _port_vale_candidate_iterations(impect):
        season_label = str(iteration.get("season", "")).strip()
        if season_label:
            by_season.setdefault(season_label, []).append(iteration)

    seasons: list[dict[str, Any]] = []
    for season_label, iterations in by_season.items():
        chosen: dict[str, Any] | None = None
        has_data = False
        for iteration in iterations:
            squad_names = impect._fetch_squad_names(int(iteration["id"]))
            port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
            if port_vale_squad_id is None:
                continue
            if _iteration_has_port_vale_scores(iteration, port_vale_squad_id, quick=True):
                chosen = iteration
                has_data = True
                break
            if chosen is None:
                chosen = iteration
        if chosen is None:
            continue
        seasons.append(
            {
                "value": season_label,
                "label": season_label,
                "competition": _iteration_competition(chosen),
                "hasData": has_data,
            }
        )

    seasons.sort(
        key=lambda row: impect._season_sort_key(str(row.get("value", ""))),
        reverse=True,
    )
    _port_vale_seasons_cache = seasons
    return seasons


def _default_port_vale_season() -> str:
    seasons = _available_port_vale_seasons()
    if not seasons:
        return ""
    for season in seasons:
        if season.get("hasData"):
            return str(season["value"])
    return str(seasons[0]["value"])


def _current_port_vale_iteration(season: str | None = None) -> dict[str, Any]:
    return _resolve_port_vale_iteration(season)


def _current_league_one_iteration(season: str | None = None) -> dict[str, Any]:
    return _resolve_port_vale_iteration(season)


def _related_positions_for_scoring(position: str) -> list[str]:
    if position == "CENTRAL_MIDFIELD":
        return list(MIDFIELD_COMPARISON_POSITIONS)
    return [position]


def _player_rows_by_position(
    iteration: dict[str, Any],
    player_id: int,
    related_positions: list[str],
    bundles_by_position: dict[str, dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], float]]:
    impect = _impect()
    rows: dict[str, tuple[dict[str, Any], float]] = {}

    for related_position in related_positions:
        bundle = bundles_by_position.get(related_position)
        if bundle is None:
            continue
        for row in bundle["score_rows"]:
            if int(row["playerId"]) != player_id:
                continue
            minutes = impect._play_duration_minutes(row) or 0.0
            if minutes <= 0:
                continue
            existing = rows.get(related_position)
            if existing is None or minutes > existing[1]:
                rows[related_position] = (row, minutes)
            break

    return rows


def _impect_ui_display_score(
    profile_key: str,
    position: str,
    comparison_row: dict[str, Any],
    rows_by_position: dict[str, tuple[dict[str, Any], float]],
    cross_cohort: dict[str, list[float]],
) -> tuple[float | None, str]:
    impect = _impect()
    comparison_values = _profile_value_map(comparison_row)

    if position == "CENTRAL_MIDFIELD":
        if profile_key in (PROFILE_KEY_CREATOR, PROFILE_KEY_RUNNING):
            raw_value = comparison_values.get(profile_key)
            cohort_values = cross_cohort.get(profile_key, [])
            score = (
                impect._cohort_percentile(raw_value, cohort_values)
                if raw_value is not None and cohort_values
                else None
            )
            return score, "cross_league_percentile"

        if profile_key == PROFILE_KEY_GOAL:
            raw_value = comparison_values.get(profile_key)
            if raw_value is None:
                return None, "raw_score"
            return round(max(0.0, min(100.0, raw_value * 100.0)), 1), "raw_score"

        if profile_key == PROFILE_KEY_WINNER:
            total_minutes = sum(minutes for _, minutes in rows_by_position.values())
            if total_minutes <= 0:
                return None, "minutes_blend_raw"
            numerator = sum(
                _profile_value_map(row).get(profile_key, 0.0) * minutes
                for row, minutes in rows_by_position.values()
                if _profile_value_map(row).get(profile_key) is not None
            )
            return (
                round(max(0.0, min(100.0, numerator / total_minutes * 100.0)), 1),
                "minutes_blend_raw",
            )

        if profile_key == PROFILE_KEY_PROGRESSOR:
            best_raw: float | None = None
            best_minutes = -1.0
            for row, minutes in rows_by_position.values():
                raw_value = _profile_value_map(row).get(profile_key)
                if raw_value is None:
                    continue
                if minutes > best_minutes:
                    best_minutes = minutes
                    best_raw = raw_value
            cohort_values = cross_cohort.get(profile_key, [])
            score = (
                impect._cohort_percentile(best_raw, cohort_values)
                if best_raw is not None and cohort_values
                else None
            )
            return score, "max_minutes_cross_percentile"

    raw_value = comparison_values.get(profile_key)
    cohort_values = cross_cohort.get(profile_key, [])
    score = (
        impect._cohort_percentile(raw_value, cohort_values)
        if raw_value is not None and cohort_values
        else None
    )
    return score, "cross_league_percentile"


def _player_review_scores(
    row: dict[str, Any],
    profiles: list[str],
    league_cohort: dict[str, list[float]],
    *,
    position: str,
    rows_by_position: dict[str, tuple[dict[str, Any], float]],
    cross_cohort: dict[str, list[float]],
) -> tuple[
    dict[str, float | None],
    dict[str, float | None],
    dict[str, float | None],
    dict[str, float | None],
    dict[str, str],
]:
    impect = _impect()
    profile_values = _profile_value_map(row)
    profile_keys = {_normalize_profile_key(name): name for name in profiles}

    profile_scores: dict[str, float | None] = {}
    league_percentiles: dict[str, float | None] = {}
    cross_percentiles: dict[str, float | None] = {}
    raw_values: dict[str, float | None] = {}
    display_methods: dict[str, str] = {}

    for profile_key, profile_name in profile_keys.items():
        raw_value = profile_values.get(profile_key)
        if raw_value is None:
            profile_scores[profile_name] = None
            league_percentiles[profile_name] = None
            cross_percentiles[profile_name] = None
            raw_values[profile_name] = None
            continue

        raw_values[profile_name] = round(raw_value, 6)
        league_cohort_values = league_cohort.get(profile_key, [])
        cross_cohort_values = cross_cohort.get(profile_key, [])
        league_percentiles[profile_name] = (
            impect._cohort_percentile(raw_value, league_cohort_values)
            if league_cohort_values
            else None
        )
        cross_percentiles[profile_name] = (
            impect._cohort_percentile(raw_value, cross_cohort_values)
            if cross_cohort_values
            else None
        )

        display_score, display_method = _impect_ui_display_score(
            profile_key,
            position,
            row,
            rows_by_position,
            cross_cohort,
        )
        profile_scores[profile_name] = display_score
        display_methods[profile_name] = display_method

    return profile_scores, league_percentiles, cross_percentiles, raw_values, display_methods


def _squad_total_minutes_by_player(
    iteration: dict[str, Any],
    port_vale_squad_id: int,
) -> dict[int, float]:
    impect = _impect()
    iteration_id = int(iteration["id"])
    cache_key = (iteration_id, port_vale_squad_id)
    cached = _squad_minutes_cache.get(cache_key)
    if cached is not None:
        return cached

    totals: dict[int, float] = {}
    for related_position in impect.ALLOWED_POSITIONS:
        related_bundle = _load_iteration_bundle(iteration, related_position, 0)
        for related_row in related_bundle["score_rows"]:
            squad_id = related_row.get("_squadId") or related_row.get("squadId")
            if squad_id is None or int(squad_id) != port_vale_squad_id:
                continue
            player_key = int(related_row["playerId"])
            row_minutes = impect._play_duration_minutes(related_row) or 0.0
            totals[player_key] = max(totals.get(player_key, 0.0), row_minutes)

    _squad_minutes_cache[cache_key] = totals
    return totals


def _position_attributed_minutes(
    player_id: int,
    position: str,
    *,
    position_shares: dict[int, dict[str, float]] | None,
    total_minutes_by_player: dict[int, float],
    row_fallback_minutes: float = 0.0,
) -> int:
    total_minutes = total_minutes_by_player.get(player_id)
    if total_minutes is None or total_minutes <= 0:
        total_minutes = row_fallback_minutes
    if not position_shares:
        return int(round(row_fallback_minutes))

    shares = position_shares.get(player_id, {})
    position_share = shares.get(position, 0.0)
    total_share = sum(shares.values())
    if total_share <= 0 or position_share <= 0:
        return 0
    return int(round(total_minutes * position_share / total_share))

def _squad_review_row_eligible(
    row: dict[str, Any],
    min_minutes: float,
    *,
    position: str,
    position_shares: dict[int, dict[str, float]] | None,
    total_minutes_by_player: dict[int, float],
) -> bool:
    """Include squad players with meaningful minutes in this position row."""
    impect = _impect()
    player_id = int(row["playerId"])
    row_minutes = impect._play_duration_minutes(row) or 0.0
    attributed_minutes = _position_attributed_minutes(
        player_id,
        position,
        position_shares=position_shares,
        total_minutes_by_player=total_minutes_by_player,
        row_fallback_minutes=row_minutes,
    )
    if attributed_minutes < min_minutes:
        return False
    profile_values = _profile_value_map(row)
    return any(value is not None for value in profile_values.values())


def build_squad_review(body: SquadReviewRequest) -> dict[str, Any]:
    impect = _impect()
    position = body.position.strip()
    if position not in impect.ALLOWED_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported position: {position}")

    profiles = _profiles_for_position(position)
    if not profiles:
        raise HTTPException(
            status_code=404,
            detail=f"No Port Vale profiles found for {_scouting_position_label(position)}.",
        )

    profile_keys = {_normalize_profile_key(name): name for name in profiles}
    iteration = _resolve_port_vale_iteration(body.season)
    iteration_id = int(iteration["id"])
    season_label = str(iteration.get("season", "")).strip()

    bundle = _load_iteration_bundle(iteration, position, 0)
    squad_names = bundle["squad_names"]
    port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
    if port_vale_squad_id is None:
        raise HTTPException(
            status_code=404,
            detail="Port Vale squad not found in the current League One iteration.",
        )

    primary_positions = bundle["primary_positions"]
    position_shares = bundle.get("position_shares")
    benchmark_minutes = float(impect.BENCHMARK_MIN_MINUTES)

    cohort_rows = _league_benchmark_rows(
        bundle["score_rows"],
        position,
        primary_positions,
        benchmark_minutes,
        position_shares=position_shares,
    )
    league_cohort = _cohort_values_by_profile(cohort_rows, profiles)
    related_positions = _related_positions_for_scoring(position)
    related_bundles = {
        related_position: _load_iteration_bundle(iteration, related_position, 0)
        for related_position in related_positions
    }
    cross_cohort_rows, cross_meta = impect._fetch_benchmark_cohort(
        season_label,
        [position],
        "profiles",
    )
    cross_cohort = _cohort_values_by_profile(cross_cohort_rows, profiles)

    total_minutes_by_player = _squad_total_minutes_by_player(iteration, port_vale_squad_id)

    squad_rows: list[dict[str, Any]] = []
    for row in bundle["score_rows"]:
        squad_id = row.get("_squadId") or row.get("squadId")
        if squad_id is None or int(squad_id) != port_vale_squad_id:
            continue
        if not _squad_review_row_eligible(
            row,
            body.min_minutes,
            position=position,
            position_shares=position_shares,
            total_minutes_by_player=total_minutes_by_player,
        ):
            continue
        squad_rows.append(row)

    if not squad_rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No Port Vale {_scouting_position_label(position)} players with "
                f"{body.min_minutes:.0f}+ minutes this season."
            ),
        )

    selected_ids = {int(player_id) for player_id in body.player_ids if player_id}
    players_payload: list[dict[str, Any]] = []

    for row in squad_rows:
        player_id = row.get("playerId")
        if player_id is None:
            continue
        player_id = int(player_id)
        if selected_ids and player_id not in selected_ids:
            continue

        catalog_player = bundle["player_lookup"].get((iteration_id, player_id), {})
        name = impect._extract_player_name(catalog_player) or f"Player {player_id}"
        row_minutes = impect._play_duration_minutes(row) or 0.0
        minutes = _position_attributed_minutes(
            player_id,
            position,
            position_shares=position_shares,
            total_minutes_by_player=total_minutes_by_player,
            row_fallback_minutes=row_minutes,
        )
        rows_by_position = _player_rows_by_position(
            iteration,
            player_id,
            related_positions,
            related_bundles,
        )

        (
            profile_scores,
            league_percentiles,
            cross_percentiles,
            raw_values,
            display_methods,
        ) = _player_review_scores(
            row,
            profiles,
            league_cohort,
            position=position,
            rows_by_position=rows_by_position,
            cross_cohort=cross_cohort,
        )

        if not any(value is not None for value in profile_scores.values()):
            continue

        photo_source = resolve_squad_photo_url(name)
        photo_url = f"/api/squad-review/photo?name={quote(name)}" if photo_source else None

        players_payload.append(
            {
                "id": player_id,
                "name": name,
                "age": impect._player_age(catalog_player),
                "minutes": int(round(minutes)),
                "position": position,
                "positionLabel": _scouting_position_label(position),
                "club": squad_names.get(port_vale_squad_id, "Port Vale FC"),
                "season": season_label,
                "profileScores": profile_scores,
                "leaguePercentiles": league_percentiles,
                "crossLeaguePercentiles": cross_percentiles,
                "rawProfileValues": raw_values,
                "displayMethods": display_methods,
                "photoUrl": photo_url,
            }
        )

    players_payload.sort(key=lambda item: (-(item.get("minutes") or 0), item["name"].casefold()))

    if selected_ids and not players_payload:
        raise HTTPException(
            status_code=404,
            detail="Selected players were not found for this position and season.",
        )

    display_profiles = [
        {"apiName": name, "label": humanize_profile_name(name)}
        for name in profiles
    ]

    return {
        "position": position,
        "positionLabel": _scouting_position_label(position),
        "positionShortLabel": POSITION_SHORT_LABELS.get(position, position),
        "profiles": display_profiles,
        "players": players_payload,
        "playerCount": len(players_payload),
        "season": season_label,
        "competition": _iteration_competition(iteration),
        "iterationId": iteration_id,
        "squadId": port_vale_squad_id,
        "minMinutes": body.min_minutes,
        "scoring": {
            "method": "impect_ui_aligned",
            "displayScale": "Impect platform profile values (0–100)",
            "benchmarkMinutes": benchmark_minutes,
            "note": (
                f"Impect profile scores · {_iteration_competition(iteration)} · {season_label} "
                f"({benchmark_minutes:.0f}+ min benchmark cohort)."
            ),
            "cohortSize": len(cohort_rows),
            "crossLeagueCohort": cross_meta,
        },
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def _comparison_export_filename(position_label: str, *, all_positions: bool = False) -> str:
    if all_positions:
        return "port-vale-all-positions-comparison.pdf"
    slug = (
        str(position_label or "comparison")
        .lower()
        .replace(" ", "-")
        .replace("'", "")
    )
    slug = "".join(char for char in slug if char.isalnum() or char == "-").strip("-")
    return f"port-vale-{slug or 'comparison'}-comparison.pdf"


def build_squad_review_export_pdf(body: SquadReviewRequest) -> tuple[bytes, str]:
    data = build_squad_review(body)
    if len(data.get("players") or []) < 2:
        raise HTTPException(
            status_code=400,
            detail="Select at least two players before exporting a PDF.",
        )
    pdf_bytes = build_squad_review_pdf([data])
    filename = _comparison_export_filename(str(data.get("positionLabel", "")))
    return pdf_bytes, filename


def _resolve_selected_player_ids(
    roster_players: list[dict[str, Any]],
    requested_ids: list[int] | None,
    max_players: int,
) -> list[int]:
    roster_ids = [int(player["id"]) for player in roster_players]
    roster_id_set = set(roster_ids)
    if requested_ids:
        valid = [int(player_id) for player_id in requested_ids if int(player_id) in roster_id_set]
        if len(valid) >= 2:
            return valid[:max_players]
    return roster_ids[:max_players]


def build_squad_review_all_comparisons(
    body: SquadReviewExportAllRequest,
) -> dict[str, Any]:
    impect = _impect()
    iteration = _resolve_port_vale_iteration(body.season)
    season_label = str(iteration.get("season", "")).strip()
    comparisons: list[dict[str, Any]] = []

    for position in impect.ALLOWED_POSITIONS:
        try:
            roster = build_squad_review(
                SquadReviewRequest(
                    position=position,
                    min_minutes=body.min_minutes,
                    player_ids=[],
                    season=body.season,
                )
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise

        roster_players = roster.get("players") or []
        if len(roster_players) < 2:
            continue

        requested_ids = body.selections.get(position) if body.selections else None
        selected_ids = _resolve_selected_player_ids(
            roster_players,
            requested_ids,
            body.max_players,
        )
        comparison = build_squad_review(
            SquadReviewRequest(
                position=position,
                min_minutes=body.min_minutes,
                player_ids=selected_ids,
                season=body.season,
            )
        )
        if len(comparison.get("players") or []) < 2:
            continue

        comparison["roster"] = roster_players
        comparison["selectedPlayerIds"] = selected_ids
        comparisons.append(comparison)

    if not comparisons:
        season_hint = f" for {season_label}" if body.season else ""
        raise HTTPException(
            status_code=404,
            detail=(
                f"No positions had enough Port Vale players to compare{season_hint}. "
                "Impect may not have profile data loaded for this season yet."
            ),
        )

    return {
        "season": season_label,
        "competition": _iteration_competition(iteration),
        "comparisons": comparisons,
        "positionCount": len(comparisons),
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def build_squad_review_all_positions_pdf(body: SquadReviewExportAllRequest) -> tuple[bytes, str]:
    payload = build_squad_review_all_comparisons(body)
    pdf_bytes = build_squad_review_pdf(payload["comparisons"])
    return pdf_bytes, _comparison_export_filename("", all_positions=True)


def squad_review_meta() -> dict[str, Any]:
    impect = _impect()
    seasons = _available_port_vale_seasons()
    default_season = _default_port_vale_season()
    iteration = _resolve_port_vale_iteration(default_season or None)
    return {
        "positions": [
            {
                "value": position,
                "label": impect.POSITION_LABELS.get(position, position),
                "shortLabel": POSITION_SHORT_LABELS.get(position, position),
            }
            for position in impect.ALLOWED_POSITIONS
        ],
        "defaultPosition": "RIGHT_WINGBACK_DEFENDER",
        "defaultMinMinutes": 0,
        "maxComparePlayers": 5,
        "season": str(iteration.get("season", "")).strip(),
        "defaultSeason": default_season,
        "seasons": seasons,
        "competition": _iteration_competition(iteration),
    }


def register_squad_review_routes(app: FastAPI) -> None:
    @app.get("/squad-review", response_class=HTMLResponse)
    def squad_review_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "squad-review.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Squad review UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/squad-review/meta")
    def squad_review_meta_route() -> dict[str, Any]:
        return squad_review_meta()

    @app.post("/api/squad-review/comparison")
    def squad_review_comparison(body: SquadReviewRequest) -> dict[str, Any]:
        return build_squad_review(body)

    @app.post("/api/squad-review/comparison-all")
    def squad_review_comparison_all(body: SquadReviewExportAllRequest) -> dict[str, Any]:
        return build_squad_review_all_comparisons(body)

    @app.post("/api/squad-review/export-pdf")
    def squad_review_export_pdf(body: SquadReviewRequest) -> Response:
        try:
            pdf_bytes, filename = build_squad_review_export_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/squad-review/export-pdf-all")
    def squad_review_export_pdf_all(body: SquadReviewExportAllRequest) -> Response:
        try:
            pdf_bytes, filename = build_squad_review_all_positions_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/squad-review/debug")
    def squad_review_debug(
        name: str = Query(..., min_length=1),
        position: str = Query("CENTRAL_MIDFIELD"),
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        impect = _impect()
        position = position.strip()
        if position not in impect.ALLOWED_POSITIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported position: {position}")

        profiles = _profiles_for_position(position)
        iteration = _resolve_port_vale_iteration(season)
        iteration_id = int(iteration["id"])
        season_label = str(iteration.get("season", "")).strip()
        bundle = _load_iteration_bundle(iteration, position, 0)

        primary_positions = bundle["primary_positions"]
        position_shares = bundle.get("position_shares")
        benchmark_minutes = float(impect.BENCHMARK_MIN_MINUTES)

        cohort_rows = _league_benchmark_rows(
            bundle["score_rows"],
            position,
            primary_positions,
            benchmark_minutes,
            position_shares=position_shares,
        )
        league_cohort = _cohort_values_by_profile(cohort_rows, profiles)

        cross_cohort_rows, cross_meta = impect._fetch_benchmark_cohort(
            season_label,
            [position],
            "profiles",
        )
        cross_cohort = _cohort_values_by_profile(cross_cohort_rows, profiles)
        related_positions = _related_positions_for_scoring(position)
        related_bundles = {
            related_position: _load_iteration_bundle(iteration, related_position, 0)
            for related_position in related_positions
        }
        squad_names = bundle["squad_names"]
        port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
        total_minutes_by_player = (
            _squad_total_minutes_by_player(iteration, port_vale_squad_id)
            if port_vale_squad_id is not None
            else {}
        )

        target = name.strip().casefold()
        matches: list[dict[str, Any]] = []
        for row in bundle["score_rows"]:
            player_id = int(row["playerId"])
            catalog_player = bundle["player_lookup"].get((iteration_id, player_id), {})
            player_name = impect._extract_player_name(catalog_player) or f"Player {player_id}"
            if target not in player_name.casefold():
                continue

            rows_by_position = _player_rows_by_position(
                iteration,
                player_id,
                related_positions,
                related_bundles,
            )
            (
                profile_scores,
                league_percentiles,
                cross_percentiles,
                raw_values,
                display_methods,
            ) = _player_review_scores(
                row,
                profiles,
                league_cohort,
                position=position,
                rows_by_position=rows_by_position,
                cross_cohort=cross_cohort,
            )

            row_minutes = impect._play_duration_minutes(row) or 0.0
            attributed_minutes = _position_attributed_minutes(
                player_id,
                position,
                position_shares=position_shares,
                total_minutes_by_player=total_minutes_by_player,
                row_fallback_minutes=row_minutes,
            )
            player_shares = (position_shares or {}).get(player_id, {})
            total_share = sum(player_shares.values())
            position_share_pct = (
                round(player_shares.get(position, 0.0) / total_share * 100.0, 1)
                if total_share > 0
                else None
            )

            position_rows = [
                {
                    "position": related_position,
                    "minutes": int(round(minutes)),
                    "rawProfileValues": {
                        profile_name: _profile_value_map(position_row).get(
                            _normalize_profile_key(profile_name)
                        )
                        for profile_name in profiles
                        if _profile_value_map(position_row).get(
                            _normalize_profile_key(profile_name)
                        )
                        is not None
                    },
                }
                for related_position, (position_row, minutes) in rows_by_position.items()
            ]

            matches.append(
                {
                    "name": player_name,
                    "playerId": player_id,
                    "squadId": row.get("_squadId"),
                    "minutes": attributed_minutes,
                    "rowMinutes": int(round(row_minutes)),
                    "seasonMinutes": int(round(total_minutes_by_player.get(player_id, row_minutes))),
                    "positionSharePercent": position_share_pct,
                    "primaryPosition": (primary_positions or {}).get(player_id),
                    "matchShare": row.get("matchShare"),
                    "displayScores": profile_scores,
                    "displayMethods": display_methods,
                    "rawProfileValues": raw_values,
                    "leagueOnePrimaryPercentiles": league_percentiles,
                    "crossLeaguePercentiles": cross_percentiles,
                    "positionRows": position_rows,
                }
            )

        if not matches:
            raise HTTPException(status_code=404, detail=f"No player found matching {name!r}.")

        return {
            "player": name,
            "position": position,
            "positionLabel": _scouting_position_label(position),
            "season": season_label,
            "competition": _iteration_competition(iteration),
            "iterationId": iteration_id,
            "displayMethod": "impect_ui_aligned",
            "displayRules": {
                "CENTRAL_MIDFIELD": {
                    "PV - CREATOR (CM)": "cross_league_percentile",
                    "PV - RUNNING THREAT (CM)": "cross_league_percentile",
                    "PV - GOAL THREAT - (CM)": "raw_score",
                    "PV - BALL WINNER (CM)": "minutes_blend_raw",
                    "PV - BALL PROGRESSOR - (10)": "max_minutes_cross_percentile",
                },
                "default": "cross_league_percentile",
            },
            "cohorts": {
                "leagueOnePrimary": {
                    "description": (
                        f"League One players at this position with primary-role filter "
                        f"and {benchmark_minutes:.0f}+ minutes"
                    ),
                    "size": len(cohort_rows),
                },
                "crossLeague": cross_meta,
            },
            "matches": matches,
        }

    @app.get("/api/squad-review/photo")
    def squad_review_photo(name: str = Query(..., min_length=1)) -> Response:
        from app.squad_photos import fetch_photo_bytes, resolve_squad_photo_url

        source_url = resolve_squad_photo_url(name)
        if not source_url:
            raise HTTPException(status_code=404, detail=f"No squad photo found for {name}")

        try:
            image_bytes, content_type = fetch_photo_bytes(source_url)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
