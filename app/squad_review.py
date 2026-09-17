from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.label_utils import full_stat_label, humanize_profile_name
from app.paths import SQUAD_REVIEW_CACHE_DIR, ensure_data_dirs
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

logger = logging.getLogger(__name__)

_squad_minutes_cache: dict[tuple[int, int], dict[int, float]] = {}
_port_vale_iteration_cache: dict[str, dict[str, Any]] = {}
_port_vale_seasons_cache: list[dict[str, Any]] | None = None
_comparison_all_memory: dict[str, tuple[float, dict[str, Any]]] = {}
_charts_memory: dict[str, tuple[float, dict[str, Any]]] = {}
_player_scores_memory: dict[str, tuple[float, list[dict[str, Any]]]] = {}

SQUAD_REVIEW_CACHE_VERSION = 1
CHARTS_CACHE_VERSION = 6
SQUAD_REVIEW_CACHE_TTL_SECONDS = 6 * 3600
SQUAD_REVIEW_TOP_FACTORS = 3
PREFERRED_FACTOR_LABELS = ("aerial duel win %",)

PORT_VALE_COMPETITIONS = ("League Two", "League One")
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
    force_refresh: bool = False


class SquadReviewChartsRequest(SquadReviewRequest):
    force_refresh: bool = False


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
    return str(iteration.get("competition_name", "League Two")).strip()


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
    return _iteration_has_port_vale_scores(iteration, port_vale_squad_id, quick=True)


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

    # Prefer 26/27 once Vale are in that iteration (scores first, then squad-only).
    preferred_season = "26/27"
    preferred_with_squad: dict[str, Any] | None = None
    for iteration in candidates:
        squad_names = impect._fetch_squad_names(int(iteration["id"]))
        port_vale_squad_id = _resolve_port_vale_squad_id(squad_names)
        if port_vale_squad_id is None:
            continue
        season_label = str(iteration.get("season") or "").strip()
        has_scores = _port_vale_has_score_data(iteration, port_vale_squad_id)
        if season_label == preferred_season:
            if has_scores:
                _port_vale_iteration_cache[cache_key] = iteration
                return iteration
            if preferred_with_squad is None:
                preferred_with_squad = iteration
            continue
        if has_scores:
            _port_vale_iteration_cache[cache_key] = iteration
            return iteration

    if preferred_with_squad is not None:
        _port_vale_iteration_cache[cache_key] = preferred_with_squad
        return preferred_with_squad

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
    # Current season first — do not stick on 25/26 just because it has more scores.
    for preferred in ("26/27",):
        for season in seasons:
            if str(season.get("value")) == preferred:
                return preferred
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


def _player_review_scores(
    row: dict[str, Any],
    profiles: list[str],
    league_cohort: dict[str, list[float]],
    *,
    cross_cohort: dict[str, list[float]] | None = None,
) -> tuple[
    dict[str, float | None],
    dict[str, float | None],
    dict[str, float | None],
    dict[str, float | None],
    dict[str, str],
]:
    """Slide values are Impect's own 0–100 profile ratings, not cohort ranks."""
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
        cross_cohort_values = (cross_cohort or {}).get(profile_key, [])
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
        profile_scores[profile_name] = impect._impect_score_0_100(raw_value)
        display_methods[profile_name] = "impect_profile"

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
    benchmark_minutes = 0.0

    cohort_rows = _league_benchmark_rows(
        bundle["score_rows"],
        position,
        primary_positions,
        benchmark_minutes,
        position_shares=position_shares,
    )
    league_cohort = _cohort_values_by_profile(cohort_rows, profiles)

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

    try:
        _prefetch_vale_player_scores(
            season_label,
            position,
            iteration_id,
            port_vale_squad_id,
        )
    except HTTPException:
        logger.exception("Could not prefetch player-scores for %s", position)

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
            "method": "impect_profile",
            "displayScale": "Impect platform profile values (0–100)",
            "note": (
                f"Impect profile scores · {_iteration_competition(iteration)} · {season_label}. "
                "Exact Impect ratings (0–100), not league-relative percentiles."
            ),
        },
        "updatedAt": datetime.now(UTC).isoformat(),
    }


def _comparison_export_filename(
    position_label: str,
    *,
    all_positions: bool = False,
    full: bool = False,
) -> str:
    suffix = "-full" if full else ""
    if all_positions:
        return f"port-vale-all-positions-comparison{suffix}.pdf"
    slug = (
        str(position_label or "comparison")
        .lower()
        .replace(" ", "-")
        .replace("'", "")
    )
    slug = "".join(char for char in slug if char.isalnum() or char == "-").strip("-")
    return f"port-vale-{slug or 'comparison'}-comparison{suffix}.pdf"


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


def _comparison_cache_key(season: str | None, min_minutes: float) -> str:
    token = _normalize_season_token(season or "") or "auto"
    safe = token.replace("/", "-").replace(" ", "")
    return f"{safe}-{int(round(float(min_minutes or 0)))}"


def _player_scores_cache_key(season: str | None, position: str) -> str:
    token = _normalize_season_token(season or "") or "auto"
    safe = token.replace("/", "-").replace(" ", "")
    return f"{safe}-{position}"


def _player_scores_cache_path(cache_key: str) -> Path:
    return SQUAD_REVIEW_CACHE_DIR / f"player-scores-{cache_key}.json"


def _load_player_scores_cache(cache_key: str) -> list[dict[str, Any]] | None:
    cached = _player_scores_memory.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < SQUAD_REVIEW_CACHE_TTL_SECONDS:
        return json.loads(json.dumps(cached[1]))
    path = _player_scores_cache_path(cache_key)
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != SQUAD_REVIEW_CACHE_VERSION:
            return None
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        _player_scores_memory[cache_key] = (now, rows)
        return json.loads(json.dumps(rows))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_player_scores_cache(cache_key: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    try:
        ensure_data_dirs()
        payload = {
            "version": SQUAD_REVIEW_CACHE_VERSION,
            "cached_at": time.time(),
            "data": rows,
        }
        path = _player_scores_cache_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        _player_scores_memory[cache_key] = (time.time(), rows)
    except OSError:
        logger.exception("Failed to write squad comparison player-scores cache")


def _prefetch_vale_player_scores(
    season: str | None,
    position: str,
    iteration_id: int,
    squad_id: int,
) -> list[dict[str, Any]]:
    cache_key = _player_scores_cache_key(season, position)
    cached = _load_player_scores_cache(cache_key)
    if cached is not None:
        return cached
    impect = _impect()
    rows, _ = impect._fetch_player_scores(int(iteration_id), int(squad_id), [position], 0)
    _save_player_scores_cache(cache_key, rows)
    return rows


def _vale_player_score_rows(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    position = str(comparison.get("position") or "")
    season = comparison.get("season")
    iteration_id = comparison.get("iterationId")
    squad_id = comparison.get("squadId")
    if iteration_id is None or squad_id is None:
        iteration = _resolve_port_vale_iteration(str(season) if season else None)
        iteration_id = int(iteration["id"])
        if squad_id is None:
            names = _impect()._fetch_squad_names(iteration_id)
            squad_id = _resolve_port_vale_squad_id(names)
    if squad_id is None:
        return []
    return _prefetch_vale_player_scores(
        season,
        position,
        int(iteration_id),
        int(squad_id),
    )


def _comparison_cache_path(cache_key: str) -> Path:
    return SQUAD_REVIEW_CACHE_DIR / f"comparison-all-{cache_key}.json"


def _load_comparison_all_cache(cache_key: str, *, allow_stale: bool) -> dict[str, Any] | None:
    cached = _comparison_all_memory.get(cache_key)
    now = time.time()
    if cached and (allow_stale or now - cached[0] < SQUAD_REVIEW_CACHE_TTL_SECONDS):
        return json.loads(json.dumps(cached[1]))

    path = _comparison_cache_path(cache_key)
    try:
        if not path.exists():
            return None
        age = now - path.stat().st_mtime
        if not allow_stale and age > SQUAD_REVIEW_CACHE_TTL_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != SQUAD_REVIEW_CACHE_VERSION:
            return None
        body = payload.get("data")
        if not isinstance(body, dict) or not (body.get("comparisons") or []):
            return None
        _comparison_all_memory[cache_key] = (now, body)
        return json.loads(json.dumps(body))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_comparison_all_cache(cache_key: str, data: dict[str, Any]) -> None:
    if not (data.get("comparisons") or []):
        return
    try:
        ensure_data_dirs()
        payload = {
            "version": SQUAD_REVIEW_CACHE_VERSION,
            "cached_at": time.time(),
            "data": data,
        }
        path = _comparison_cache_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        _comparison_all_memory[cache_key] = (time.time(), data)
    except OSError:
        logger.exception("Failed to write squad comparison cache")


def _charts_cache_key(
    season: str | None,
    position: str,
    min_minutes: float,
    player_ids: list[int] | None = None,
    *,
    version: int | None = None,
) -> str:
    token = f"{_comparison_cache_key(season, min_minutes)}-{position}"
    if player_ids:
        ids = "-".join(str(int(player_id)) for player_id in sorted(player_ids))
        token = f"{token}-{ids}"
    ver = CHARTS_CACHE_VERSION if version is None else version
    if ver <= 1:
        return token
    return f"v{ver}-{token}"


def _filter_charts_to_comparison(
    payload: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    wanted = {
        str(player.get("name") or "").strip().casefold()
        for player in comparison.get("players") or []
        if str(player.get("name") or "").strip()
    }
    if not wanted:
        return payload
    filtered = dict(payload)
    drilldowns: list[dict[str, Any]] = []
    for entry in payload.get("profile_drilldowns") or []:
        copy = dict(entry)
        copy["players"] = [
            player
            for player in entry.get("players") or []
            if str(player.get("player") or player.get("name") or "").strip().casefold()
            in wanted
        ]
        if len(copy["players"]) >= 2:
            drilldowns.append(copy)
    filtered["profile_drilldowns"] = drilldowns
    filtered["players"] = [
        player
        for player in payload.get("players") or []
        if str(player.get("player") or player.get("name") or "").strip().casefold()
        in wanted
    ]
    return filtered


def _drilldowns_are_placeholder_standing(payload: dict[str, Any]) -> bool:
    """True when bars are 50s or 17/33/67 steps from a 3-player cohort."""
    values: list[float] = []
    for entry in payload.get("profile_drilldowns") or []:
        for player in entry.get("players") or []:
            series = player.get("bar_radar_values") or player.get("radar_values") or []
            for value in series:
                if value is None:
                    continue
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
    if len(values) < 6:
        return False
    if all(abs(value - 50.0) < 0.51 for value in values):
        return True
    unique = {round(value) for value in values}
    return len(unique) <= 5


def _peek_charts_cache(
    season: str | None,
    position: str,
    min_minutes: float,
    player_ids: list[int],
) -> dict[str, Any] | None:
    keys: list[str] = []
    minutes_options = [min_minutes, 0.0, 600.0]
    seen_minutes: set[int] = set()
    for minutes in minutes_options:
        rounded = int(round(float(minutes or 0)))
        if rounded in seen_minutes:
            continue
        seen_minutes.add(rounded)
        for version in range(CHARTS_CACHE_VERSION, 0, -1):
            keys.append(
                _charts_cache_key(season, position, minutes, version=version)
            )
            keys.append(
                _charts_cache_key(
                    season, position, minutes, player_ids, version=version
                )
            )
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        cached = _load_charts_cache(key, allow_stale=True)
        if cached is not None:
            return cached
    return _peek_charts_cache_by_position(position)


def _peek_charts_cache_by_position(position: str) -> dict[str, Any] | None:
    needle = f"-{position}"
    try:
        matches = sorted(
            SQUAD_REVIEW_CACHE_DIR.glob("charts-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for path in matches:
        stem = path.stem.removeprefix("charts-")
        if needle not in stem:
            continue
        cached = _load_charts_cache(stem, allow_stale=True)
        if cached is not None:
            return cached
    return None


def _charts_cache_path(cache_key: str) -> Path:
    return SQUAD_REVIEW_CACHE_DIR / f"charts-{cache_key}.json"


def _load_charts_cache(cache_key: str, *, allow_stale: bool = False) -> dict[str, Any] | None:
    cached = _charts_memory.get(cache_key)
    now = time.time()
    if cached and (allow_stale or now - cached[0] < SQUAD_REVIEW_CACHE_TTL_SECONDS):
        return json.loads(json.dumps(cached[1]))
    path = _charts_cache_path(cache_key)
    try:
        if not path.exists():
            return None
        age = now - path.stat().st_mtime
        if not allow_stale and age > SQUAD_REVIEW_CACHE_TTL_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != SQUAD_REVIEW_CACHE_VERSION:
            return None
        body = payload.get("data")
        if not isinstance(body, dict) or not (body.get("profile_drilldowns") or []):
            return None
        _charts_memory[cache_key] = (now, body)
        return json.loads(json.dumps(body))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_charts_cache(cache_key: str, data: dict[str, Any]) -> None:
    if not (data.get("profile_drilldowns") or []):
        return
    try:
        ensure_data_dirs()
        payload = {
            "version": SQUAD_REVIEW_CACHE_VERSION,
            "cached_at": time.time(),
            "data": data,
        }
        path = _charts_cache_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        _charts_memory[cache_key] = (time.time(), data)
    except OSError:
        logger.exception("Failed to write squad comparison charts cache")


def _clear_charts_cache() -> None:
    _charts_memory.clear()
    try:
        for path in SQUAD_REVIEW_CACHE_DIR.glob("charts-*.json"):
            path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to clear squad comparison charts cache")


def _peek_comparison_all_cache(
    season: str | None, min_minutes: float
) -> dict[str, Any] | None:
    keys: list[str] = []
    if season:
        keys.append(_comparison_cache_key(season, min_minutes))
    keys.append(_comparison_cache_key("", min_minutes))
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        cached = _load_comparison_all_cache(key, allow_stale=True)
        if cached is not None:
            return cached
    try:
        matches = sorted(
            SQUAD_REVIEW_CACHE_DIR.glob("comparison-all-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for path in matches:
        stem = path.stem.removeprefix("comparison-all-")
        if stem in seen:
            continue
        cached = _load_comparison_all_cache(stem, allow_stale=True)
        if cached is not None:
            return cached
    return None


def _meta_cache_path() -> Path:
    return SQUAD_REVIEW_CACHE_DIR / "meta.json"


def _load_meta_cache() -> dict[str, Any] | None:
    path = _meta_cache_path()
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 0)) != SQUAD_REVIEW_CACHE_VERSION:
            return None
        body = payload.get("data")
        return body if isinstance(body, dict) and body.get("positions") else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_meta_cache(data: dict[str, Any]) -> None:
    if not data.get("positions"):
        return
    try:
        ensure_data_dirs()
        path = _meta_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SQUAD_REVIEW_CACHE_VERSION,
            "cached_at": time.time(),
            "data": data,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.exception("Failed to write squad comparison meta cache")


def _positions_meta() -> list[dict[str, Any]]:
    impect = _impect()
    return [
        {
            "value": position,
            "label": impect.POSITION_LABELS.get(position, position),
            "shortLabel": POSITION_SHORT_LABELS.get(position, position),
        }
        for position in impect.ALLOWED_POSITIONS
    ]


def _meta_from_cached_deck(deck: dict[str, Any]) -> dict[str, Any]:
    season = str(deck.get("season") or "").strip()
    competition = str(deck.get("competition") or "League Two").strip()
    seasons = (
        [
            {
                "value": season,
                "label": season,
                "competition": competition,
                "hasData": True,
            }
        ]
        if season
        else []
    )
    return {
        "positions": _positions_meta(),
        "defaultPosition": "RIGHT_WINGBACK_DEFENDER",
        "defaultMinMinutes": 0,
        "maxComparePlayers": 5,
        "season": season,
        "defaultSeason": season or "26/27",
        "seasons": seasons,
        "competition": competition,
        "source": "disk_cache",
    }


def _apply_selections_to_payload(
    payload: dict[str, Any],
    selections: dict[str, list[int]] | None,
    max_players: int,
) -> dict[str, Any]:
    applied = dict(payload)
    comparisons: list[dict[str, Any]] = []
    for comparison in payload.get("comparisons") or []:
        page = dict(comparison)
        roster = list(page.get("roster") or page.get("players") or [])
        if len(roster) < 2:
            continue
        position = str(page.get("position") or "")
        requested = (selections or {}).get(position)
        selected_ids = _resolve_selected_player_ids(roster, requested, max_players)
        selected_set = set(selected_ids)
        page["roster"] = roster
        page["selectedPlayerIds"] = selected_ids
        page["players"] = [player for player in roster if int(player["id"]) in selected_set]
        if len(page["players"]) < 2:
            continue
        profiles = []
        for profile in page.get("profiles") or []:
            item = dict(profile)
            api_name = str(item.get("apiName") or "").strip()
            if api_name:
                item["label"] = humanize_profile_name(api_name)
            profiles.append(item)
        if profiles:
            page["profiles"] = profiles
        comparisons.append(page)
    applied["comparisons"] = comparisons
    applied["positionCount"] = len(comparisons)
    return applied


def _build_all_comparisons_from_impect(
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

        comparison = dict(roster)
        comparison["roster"] = roster_players
        comparison["players"] = roster_players
        comparison["selectedPlayerIds"] = [int(player["id"]) for player in roster_players]
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
        "source": "impect",
    }


def build_squad_review_all_comparisons(
    body: SquadReviewExportAllRequest,
) -> dict[str, Any]:
    if not body.force_refresh:
        cached = _peek_comparison_all_cache(body.season, body.min_minutes)
        if cached is not None:
            cached["source"] = "disk_cache"
            return _apply_selections_to_payload(cached, body.selections, body.max_players)

    if body.force_refresh:
        _clear_charts_cache()

    iteration = _resolve_port_vale_iteration(body.season)
    season_label = str(iteration.get("season", "")).strip()
    cache_key = _comparison_cache_key(season_label or body.season, body.min_minutes)

    try:
        payload = _build_all_comparisons_from_impect(body)
    except HTTPException:
        cached = _peek_comparison_all_cache(body.season, body.min_minutes)
        if cached is not None:
            logger.warning("Squad comparison Impect pull failed; serving disk cache")
            cached["source"] = "disk_cache"
            return _apply_selections_to_payload(cached, body.selections, body.max_players)
        raise

    _save_comparison_all_cache(cache_key, payload)
    _save_meta_cache(_meta_from_cached_deck(payload))
    return _apply_selections_to_payload(payload, body.selections, body.max_players)


def _factor_label_key(label: str) -> str:
    return str(label or "").strip().casefold()


def _values_for_factor_labels(
    labels: list[str],
    source_labels: list[str],
    values: list[Any],
) -> list[float | None]:
    by_label: dict[str, float | None] = {}
    for label, value in zip(source_labels, values):
        key = _factor_label_key(str(label))
        if not key:
            continue
        try:
            by_label[key] = float(value) if value is not None else None
        except (TypeError, ValueError):
            by_label[key] = None
    return [by_label.get(_factor_label_key(label)) for label in labels]


def _player_score_rows_by_id(bundle: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in bundle.get("score_rows") or []:
        player_id = row.get("playerId")
        if player_id is None:
            continue
        rows[int(player_id)] = row
    return rows


def _comparison_profile_breakdowns(comparison: dict[str, Any]) -> list[dict[str, Any]]:
    """Player Comparison factor breakdowns for the players on this slide."""
    players = comparison.get("players") or []
    profiles = comparison.get("profiles") or []
    profile_names = [str(profile.get("apiName") or "").strip() for profile in profiles]
    profile_names = [name for name in profile_names if name]
    if len(players) < 2 or not profile_names:
        return []

    impect = _impect()
    position = str(comparison.get("position") or "").strip()
    season = comparison.get("season")
    iteration = _resolve_port_vale_iteration(str(season) if season else None)
    bundle = _load_iteration_bundle(iteration, position, 0)
    rows_by_id = _player_score_rows_by_id(bundle)
    cohort_rows = impect._metrics_cohort_rows(int(iteration["id"]), [position])

    player_drilldowns: list[dict[str, dict[str, Any]]] = []
    for player in players:
        row = rows_by_id.get(int(player["id"]))
        drilldowns = (
            impect._build_profile_drilldowns(profile_names, row, cohort_rows)
            if row is not None
            else []
        )
        by_profile = {
            impect._normalize_profile_name(item.get("profile")): item
            for item in drilldowns
            if item.get("profile")
        }
        player_drilldowns.append(by_profile)

    breakdowns: list[dict[str, Any]] = []
    for profile in profiles:
        api_name = str(profile.get("apiName") or "").strip()
        if not api_name:
            continue
        profile_key = impect._normalize_profile_name(api_name)
        matched = [by_profile.get(profile_key) for by_profile in player_drilldowns]
        reference = max(
            (item for item in matched if item),
            key=lambda item: len(item.get("labels") or []),
            default=None,
        )
        if reference is None:
            continue
        labels = [str(label) for label in (reference.get("labels") or []) if str(label).strip()]
        if not labels:
            continue

        factors: list[dict[str, Any]] = []
        for label in labels:
            scores: list[float | None] = []
            standings: list[float | None] = []
            for drilldown in matched:
                if not drilldown:
                    scores.append(None)
                    standings.append(None)
                    continue
                aligned_scores = _values_for_factor_labels(
                    [label],
                    list(drilldown.get("labels") or []),
                    list(drilldown.get("raw_values") or []),
                )
                aligned_standings = _values_for_factor_labels(
                    [label],
                    list(drilldown.get("labels") or []),
                    list(drilldown.get("radar_values") or []),
                )
                scores.append(aligned_scores[0] if aligned_scores else None)
                standings.append(aligned_standings[0] if aligned_standings else None)
            if all(value is None for value in scores):
                continue
            factors.append(
                {
                    "label": label,
                    "scores": scores,
                    "standings": standings,
                }
            )

        if not factors:
            continue
        breakdowns.append(
            {
                "profile": api_name,
                "label": profile.get("label") or humanize_profile_name(api_name),
                "factors": factors,
            }
        )
    return breakdowns


def _charts_payload_from_breakdowns(
    comparison: dict[str, Any],
    breakdowns: list[dict[str, Any]],
) -> dict[str, Any]:
    players = comparison.get("players") or []
    drilldowns: list[dict[str, Any]] = []
    for breakdown in breakdowns:
        factors = breakdown.get("factors") or []
        labels = [str(factor.get("label") or "").strip() for factor in factors]
        labels = [label for label in labels if label]
        if not labels:
            continue
        label_set = set(labels)
        aligned = [
            factor
            for factor in factors
            if str(factor.get("label") or "").strip() in label_set
        ]
        entry_players: list[dict[str, Any]] = []
        for index, player in enumerate(players):
            standings = []
            scores = []
            for factor in aligned:
                player_standings = factor.get("standings") or []
                player_scores = factor.get("scores") or []
                standing = player_standings[index] if index < len(player_standings) else None
                score = player_scores[index] if index < len(player_scores) else None
                standings.append(standing)
                scores.append(score)
            entry_players.append(
                {
                    "player": player.get("name"),
                    "photo_url": player.get("photoUrl"),
                    "play_duration_minutes": player.get("minutes"),
                    "radar_values": standings,
                    "bar_radar_values": standings,
                    "bar_raw_values": scores,
                }
            )
        drilldowns.append(
            {
                "profile": breakdown.get("profile"),
                "labels": labels,
                "bar_labels": labels,
                "players": entry_players,
            }
        )
    return {
        "profile_drilldowns": drilldowns,
        "players": [
            {
                "player": player.get("name"),
                "photo_url": player.get("photoUrl"),
                "play_duration_minutes": player.get("minutes"),
            }
            for player in players
        ],
    }


def _charts_payload_from_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    breakdowns = comparison.get("profileBreakdowns")
    if not isinstance(breakdowns, list) or not breakdowns:
        breakdowns = _comparison_profile_breakdowns(comparison)
    return _charts_payload_from_breakdowns(comparison, breakdowns)


def _merge_player_drilldowns_into_charts(
    comparison: dict[str, Any],
    per_player: list[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    players = comparison.get("players") or []
    drilldowns: list[dict[str, Any]] = []
    for profile in comparison.get("profiles") or []:
        api_name = str(profile.get("apiName") or "").strip()
        if not api_name:
            continue
        profile_key = _normalize_profile_key(api_name)
        matched = [by_profile.get(profile_key) for by_profile in per_player]
        reference = max(
            (item for item in matched if item),
            key=lambda item: len(item.get("bar_labels") or item.get("labels") or []),
            default=None,
        )
        if reference is None:
            continue
        labels = [
            str(label)
            for label in (reference.get("bar_labels") or reference.get("labels") or [])
            if str(label).strip()
        ]
        if not labels:
            continue
        weights = list(reference.get("bar_weights") or [])
        entry_players: list[dict[str, Any]] = []
        for player, by_profile in zip(players, per_player):
            item = by_profile.get(profile_key) or {}
            source_labels = [
                str(label)
                for label in (item.get("bar_labels") or item.get("labels") or [])
            ]
            raw = _values_for_factor_labels(
                labels,
                source_labels,
                list(item.get("bar_raw_values") or item.get("raw_values") or []),
            )
            metric = _values_for_factor_labels(
                labels,
                source_labels,
                list(
                    item.get("bar_metric_values")
                    or item.get("metric_values")
                    or item.get("bar_raw_values")
                    or item.get("raw_values")
                    or []
                ),
            )
            radar = _values_for_factor_labels(
                labels,
                source_labels,
                list(item.get("bar_radar_values") or item.get("radar_values") or []),
            )
            entry_players.append(
                {
                    "player": player.get("name"),
                    "photo_url": player.get("photoUrl"),
                    "play_duration_minutes": player.get("minutes"),
                    "radar_values": radar,
                    "bar_radar_values": radar,
                    "bar_raw_values": raw,
                    "bar_metric_values": metric,
                }
            )
        drilldowns.append(
            {
                "profile": api_name,
                "labels": labels,
                "bar_labels": labels,
                "bar_weights": weights,
                "players": entry_players,
            }
        )
    return {
        "profile_drilldowns": drilldowns,
        "players": [
            {
                "player": player.get("name"),
                "photo_url": player.get("photoUrl"),
                "play_duration_minutes": player.get("minutes"),
            }
            for player in players
        ],
        "source": "player_scores",
    }


def _charts_payload_from_player_scores(comparison: dict[str, Any]) -> dict[str, Any]:
    impect = _impect()
    rows = _vale_player_score_rows(comparison)
    rows_by_id = {
        int(row["playerId"]): row
        for row in rows
        if row.get("playerId") is not None
    }
    profiles = [
        str(profile.get("apiName") or "").strip()
        for profile in comparison.get("profiles") or []
        if str(profile.get("apiName") or "").strip()
    ]
    per_player: list[dict[str, dict[str, Any]]] = []
    for player in comparison.get("players") or []:
        row = rows_by_id.get(int(player["id"]))
        items = (
            impect._build_profile_drilldowns(profiles, row, None) if row is not None else []
        )
        per_player.append(
            {
                _normalize_profile_key(str(item.get("profile") or "")): item
                for item in items
                if item.get("profile")
            }
        )
    return _merge_player_drilldowns_into_charts(comparison, per_player)


def _comparison_for_charts(body: SquadReviewChartsRequest) -> dict[str, Any]:
    deck = _peek_comparison_all_cache(body.season, body.min_minutes)
    if deck is not None:
        match = next(
            (
                comparison
                for comparison in deck.get("comparisons") or []
                if comparison.get("position") == body.position
            ),
            None,
        )
        if match is not None:
            max_players = max(2, min(5, len(body.player_ids) or 5))
            applied = _apply_selections_to_payload(
                {"comparisons": [match]},
                {body.position: list(body.player_ids)} if body.player_ids else {},
                max_players,
            )
            pages = applied.get("comparisons") or []
            if pages:
                return pages[0]
    raise HTTPException(
        status_code=404,
        detail="Squad comparison cache is empty. Refresh the page to reload scores.",
    )


def _player_chart_key(name: str, player_id: int) -> str:
    return f"{str(name or '').lower().strip()}|{int(player_id)}"


def _chart_request_from_comparison(comparison: dict[str, Any]):
    impect = _impect()
    iteration_id = int(comparison["iterationId"])
    squad_id = comparison.get("squadId")
    position = str(comparison.get("position") or "")
    players = comparison.get("players") or []
    profiles = [
        str(profile.get("apiName") or "").strip()
        for profile in comparison.get("profiles") or []
        if str(profile.get("apiName") or "").strip()
    ]
    player_keys: list[str] = []
    player_catalog: dict[str, dict[str, Any]] = {}
    player_seasons: dict[str, list[int]] = {}
    player_positions: dict[str, list[str]] = {}
    for player in players:
        player_id = int(player["id"])
        key = _player_chart_key(str(player.get("name") or ""), player_id)
        player_keys.append(key)
        catalog: dict[str, Any] = {
            "name": player.get("name"),
            "ids_by_iteration": {str(iteration_id): player_id},
        }
        if squad_id is not None:
            catalog["squad_ids_by_iteration"] = {str(iteration_id): int(squad_id)}
        player_catalog[key] = catalog
        player_seasons[key] = [iteration_id]
        player_positions[key] = [position]
    return impect.ChartRequest(
        iteration_ids=[iteration_id],
        competition_name=comparison.get("competition") or None,
        player_keys=player_keys,
        player_catalog=player_catalog,
        player_seasons=player_seasons,
        player_positions=player_positions,
        positions=[position],
        profiles=profiles,
        chart_source="profiles",
        include_drilldowns=True,
        min_games=0,
    )


def _is_preferred_factor(label: str) -> bool:
    lowered = str(label or "").casefold()
    return any(preferred in lowered for preferred in PREFERRED_FACTOR_LABELS)


def _limit_drilldown_to_top_weighted(
    entry: dict[str, Any],
    count: int = SQUAD_REVIEW_TOP_FACTORS,
) -> dict[str, Any]:
    labels = [str(label) for label in (entry.get("bar_labels") or []) if str(label).strip()]
    weights = list(entry.get("bar_weights") or [])
    if not labels:
        labels = [str(label) for label in (entry.get("labels") or []) if str(label).strip()]
    ranked = list(range(len(labels)))
    ranked.sort(
        key=lambda index: (
            -(float(weights[index]) if index < len(weights) else 0.0),
            0 if _is_preferred_factor(labels[index]) else 1,
            index,
        )
    )
    order = ranked[:count]
    labels = [full_stat_label(labels[index]) for index in order]
    weights = [
        float(weights[index]) if index < len(weights) else 0.0 for index in order
    ]
    players: list[dict[str, Any]] = []
    for player in entry.get("players") or []:
        standings = list(player.get("bar_radar_values") or player.get("radar_values") or [])
        raw_values = list(player.get("bar_raw_values") or player.get("raw_values") or [])
        metric_values = list(
            player.get("bar_metric_values") or player.get("metric_values") or raw_values
        )
        copy = dict(player)
        copy["labels"] = labels
        copy["bar_labels"] = labels
        copy["radar_values"] = [
            standings[index] if index < len(standings) else None for index in order
        ]
        copy["bar_radar_values"] = copy["radar_values"]
        copy["raw_values"] = [
            raw_values[index] if index < len(raw_values) else None for index in order
        ]
        copy["bar_raw_values"] = copy["raw_values"]
        copy["metric_values"] = [
            metric_values[index] if index < len(metric_values) else None for index in order
        ]
        copy["bar_metric_values"] = copy["metric_values"]
        players.append(copy)
    limited = dict(entry)
    limited["labels"] = labels
    limited["bar_labels"] = labels
    limited["bar_weights"] = weights
    limited["players"] = players
    return limited


def build_squad_review_charts(body: SquadReviewChartsRequest) -> dict[str, Any]:
    comparison = _comparison_for_charts(body)
    payload = _charts_payload_from_player_scores(comparison)
    result = {
        "profile_drilldowns": [
            _limit_drilldown_to_top_weighted(entry)
            for entry in payload.get("profile_drilldowns") or []
        ],
        "players": payload.get("players") or [],
        "source": "player_scores",
    }
    if not result["profile_drilldowns"]:
        raise HTTPException(
            status_code=404,
            detail="No player-scores on disk for this position. Refresh the comparison to pull them.",
        )
    return _filter_charts_to_comparison(result, comparison)


def _enrich_comparisons_with_breakdowns(
    comparisons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for comparison in comparisons:
        page = dict(comparison)
        page["profileBreakdowns"] = _comparison_profile_breakdowns(comparison)
        enriched.append(page)
    return enriched


def build_squad_review_all_positions_pdf(body: SquadReviewExportAllRequest) -> tuple[bytes, str]:
    payload = build_squad_review_all_comparisons(body)
    pdf_bytes = build_squad_review_pdf(payload["comparisons"])
    return pdf_bytes, _comparison_export_filename("", all_positions=True)


def build_squad_review_full_export(body: SquadReviewRequest) -> tuple[bytes, str]:
    data = build_squad_review(body)
    if len(data.get("players") or []) < 2:
        raise HTTPException(
            status_code=400,
            detail="Select at least two players before exporting a PDF.",
        )
    pages = _enrich_comparisons_with_breakdowns([data])
    from app.squad_review_pdf import build_squad_review_full_pdf

    pdf_bytes = build_squad_review_full_pdf(pages)
    filename = _comparison_export_filename(str(data.get("positionLabel", "")), full=True)
    return pdf_bytes, filename


def squad_review_meta() -> dict[str, Any]:
    cached = _load_meta_cache()
    if cached is not None:
        cached["source"] = "disk_cache"
        return cached

    deck = _peek_comparison_all_cache("26/27", 0) or _peek_comparison_all_cache(None, 0)
    if deck is not None:
        payload = _meta_from_cached_deck(deck)
        _save_meta_cache(payload)
        return payload

    impect = _impect()
    seasons = _available_port_vale_seasons()
    default_season = _default_port_vale_season()
    iteration = _resolve_port_vale_iteration(default_season or None)
    payload = {
        "positions": _positions_meta(),
        "defaultPosition": "RIGHT_WINGBACK_DEFENDER",
        "defaultMinMinutes": 0,
        "maxComparePlayers": 5,
        "season": str(iteration.get("season", "")).strip(),
        "defaultSeason": default_season,
        "seasons": seasons,
        "competition": _iteration_competition(iteration),
        "source": "impect",
    }
    _save_meta_cache(payload)
    return payload


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

    @app.post("/api/squad-review/charts")
    def squad_review_charts(body: SquadReviewChartsRequest) -> dict[str, Any]:
        return build_squad_review_charts(body)

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

    @app.post("/api/squad-review/export-full-pdf")
    def squad_review_export_full_pdf(body: SquadReviewRequest) -> Response:
        try:
            pdf_bytes, filename = build_squad_review_full_export(body)
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
        benchmark_minutes = 0.0

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
            "displayMethod": "impect_profile",
            "displayRules": {
                "default": "impect_profile",
            },
            "cohorts": {
                "leagueOnePrimary": {
                    "description": (
                        "League players at this position. Ratings are Impect profile scores "
                        "(0–100), not a minutes-filtered percentile."
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
