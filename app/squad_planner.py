from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.main import ALLOWED_POSITIONS
from app.label_utils import humanize_profile_name
from app.scouting import (
    SCOUTING_DIR,
    SCOUTING_COMPETITION_TO_LEAGUE,
    _cohort_values_from_combined_rows,
    _load_iteration_bundle,
    _normalize_profile_key,
    _profile_value_map,
    _profiles_for_position,
    _row_passes_position_filter,
    _scouting_position_label,
)

SQUAD_PLANNER_POSITIONS: tuple[tuple[str, str, str], ...] = (
    ("GOALKEEPER", "GK", "Goalkeeper"),
    ("RIGHT_WINGBACK_DEFENDER", "RB", "Right back"),
    ("LEFT_WINGBACK_DEFENDER", "LB", "Left back"),
    ("CENTRAL_DEFENDER", "CB", "Centre back"),
    ("DEFENSE_MIDFIELD", "DM", "Defensive mid"),
    ("CENTRAL_MIDFIELD", "CM", "Centre mid"),
    ("ATTACKING_MIDFIELD", "AM", "Attacking mid"),
    ("LEFT_WINGER", "LW", "Left wing"),
    ("RIGHT_WINGER", "RW", "Right wing"),
    ("CENTER_FORWARD", "ST", "Striker"),
)

SQUAD_PLANNER_POSITION_LABELS: dict[str, tuple[str, str]] = {
    position: (short_label, label)
    for position, short_label, label in SQUAD_PLANNER_POSITIONS
}

SQUAD_PLANNER_FORMATIONS: dict[str, tuple[str, ...]] = {
    "4-3-3": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "CENTRAL_MIDFIELD",
        "LEFT_WINGER",
        "CENTER_FORWARD",
        "RIGHT_WINGER",
    ),
    "4-4-2": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "LEFT_WINGER",
        "CENTRAL_MIDFIELD",
        "RIGHT_WINGER",
        "CENTER_FORWARD",
    ),
    "4-2-3-1": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "LEFT_WINGER",
        "ATTACKING_MIDFIELD",
        "RIGHT_WINGER",
        "CENTER_FORWARD",
    ),
    "5-3-2": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "CENTRAL_MIDFIELD",
        "CENTER_FORWARD",
    ),
    "3-5-2": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "CENTRAL_MIDFIELD",
        "CENTER_FORWARD",
    ),
    "5-2-2-1": (
        "GOALKEEPER",
        "LEFT_WINGBACK_DEFENDER",
        "CENTRAL_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "CENTRAL_MIDFIELD",
        "CENTER_FORWARD",
    ),
}

SQUAD_PLANNER_PLAYER_LABELS: tuple[str, ...] = (
    "young player",
    "potential asset",
    "prime player",
    "experienced player",
    "in on loan",
)

SQUAD_PLANNER_POSITION_IDS = {position for position, _, _ in SQUAD_PLANNER_POSITIONS}
COMBINED_SEASON_COUNT = 2


class SquadPlannerPlayerRequest(BaseModel):
    position: str
    player_key: str
    iteration_id: int
    impect_player_id: int
    squad_id: int | None = None
    name: str = ""
    iteration_ids: list[int] = Field(default_factory=list)


class SquadBalanceExportPlayer(BaseModel):
    id: str = ""
    name: str
    club: str = ""
    league: str = ""
    season: str = ""
    minutes: int = 0
    profileScores: dict[str, float | None] = Field(default_factory=dict)
    photoDataUrl: str | None = None


class SquadBalanceExportPosition(BaseModel):
    id: str
    shortLabel: str
    label: str
    profiles: list[dict[str, str]] = Field(default_factory=list)
    players: list[SquadBalanceExportPlayer] = Field(default_factory=list)


class SquadBalanceExportRequest(BaseModel):
    title: str = "Squad Balance"
    subtitle: str = "4-3-3 recruitment plan · last 2 seasons combined at role"
    positions: list[SquadBalanceExportPosition] = Field(default_factory=list)


def _impect():
    from app import main as impect_main

    return impect_main


def _iteration_by_id(iteration_id: int) -> dict[str, Any]:
    impect = _impect()
    for item in impect._fetch_iterations():
        if int(item.get("id", 0)) == iteration_id:
            return item
    raise HTTPException(status_code=404, detail=f"Season iteration {iteration_id} not found.")


def _iteration_candidates(body: SquadPlannerPlayerRequest) -> list[dict[str, Any]]:
    """Only use iterations the player actually appears in (from catalog), newest first."""
    impect = _impect()
    by_id = {int(item.get("id", 0)): item for item in impect._fetch_iterations()}
    seed_ids = list(body.iteration_ids or [])
    if body.iteration_id and body.iteration_id not in seed_ids:
        seed_ids.insert(0, body.iteration_id)

    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    for iteration_id in seed_ids:
        iid = int(iteration_id)
        if iid in seen:
            continue
        iteration = by_id.get(iid)
        if iteration is None:
            continue
        seen.add(iid)
        candidates.append(iteration)

    return sorted(
        candidates,
        key=lambda row: impect._season_sort_key(str(row.get("season", ""))),
        reverse=True,
    )


def _single_season_player_row(
    bundle: dict[str, Any],
    position: str,
    impect_player_id: int,
) -> dict[str, Any] | None:
    impect = _impect()
    iteration_id = int(bundle["iteration_id"])
    primary_positions = bundle["primary_positions"]
    position_shares = bundle.get("position_shares")

    for row in bundle["score_rows"]:
        player_id = row.get("playerId")
        if player_id is None or int(player_id) != impect_player_id:
            continue
        if _row_passes_position_filter(
            row,
            position,
            primary_positions,
            0,
            check_minutes=False,
            position_shares=position_shares,
        ):
            return row

    scan = impect._scan_single_position_for_player(
        iteration_id,
        impect_player_id,
        None,
        "",
        {},
        "profiles",
        position,
        0,
    )
    if scan is None:
        return None

    row = dict(scan["row"])
    row["_iterationId"] = iteration_id
    row["_seasonLabel"] = str(bundle["iteration"].get("season", "")).strip()
    row["_competitionName"] = str(bundle["iteration"].get("competition_name", "")).strip()
    return row


def _position_minutes_for_row(
    row: dict[str, Any],
    *,
    position: str,
    bundle: dict[str, Any],
) -> float:
    """Minutes from the position-specific Impect score row (already at this role)."""
    impect = _impect()
    return float(impect._play_duration_minutes(row) or 0.0)


def _merge_combined_player_row(
    rows: list[dict[str, Any]],
    *,
    position_minutes: list[float],
) -> dict[str, Any]:
    """Minutes-weight profile scores using position-attributed minutes."""
    impect = _impect()
    if not rows:
        raise ValueError("No rows to merge")

    newest = rows[0]
    total_minutes = 0.0
    weighted: dict[str, float] = {}
    weight_total: dict[str, float] = {}
    season_labels: list[str] = []
    competition_labels: list[str] = []

    for row, minutes in zip(rows, position_minutes):
        minutes = float(minutes or 0)
        if minutes <= 0:
            minutes = impect._play_duration_minutes(row) or 0.0
        total_minutes += minutes
        season_label = str(row.get("_seasonLabel", "")).strip()
        if season_label and season_label not in season_labels:
            season_labels.append(season_label)
        competition = str(row.get("_competitionName", "")).strip()
        if competition and competition not in competition_labels:
            competition_labels.append(competition)
        for key, value in _profile_value_map(row).items():
            weighted[key] = weighted.get(key, 0.0) + value * minutes
            weight_total[key] = weight_total.get(key, 0.0) + minutes

    combined_values = {
        key: weighted[key] / weight_total[key]
        for key in weighted
        if weight_total.get(key, 0) > 0
    }

    merged = dict(newest)
    merged["_combinedMinutes"] = total_minutes
    merged["_combinedProfileValues"] = combined_values
    merged["_seasonLabel"] = "+".join(season_labels) if season_labels else ""
    merged["_competitionNames"] = competition_labels
    return merged


def _build_combined_league_cohort(
    season_hits: list[dict[str, Any]],
    position: str,
    profiles: list[str],
    benchmark_minutes: float,
) -> dict[str, list[float]]:
    """Build cohort from the same season iterations used for the player."""
    rows_by_player: dict[int, list[tuple[dict[str, Any], float]]] = {}

    for hit in season_hits:
        bundle = hit["bundle"]
        primary_positions = bundle["primary_positions"]
        position_shares = bundle.get("position_shares")
        for row in bundle["score_rows"]:
            player_id = row.get("playerId")
            if player_id is None:
                continue
            if not _row_passes_position_filter(
                row,
                position,
                primary_positions,
                0,
                check_minutes=False,
                position_shares=position_shares,
            ):
                continue
            minutes = _position_minutes_for_row(row, position=position, bundle=bundle)
            rows_by_player.setdefault(int(player_id), []).append((row, minutes))

    merged_rows: list[dict[str, Any]] = []
    for group in rows_by_player.values():
        group.sort(key=lambda item: int(item[0].get("_iterationId") or 0), reverse=True)
        # Keep at most one row per season label
        by_season: dict[str, tuple[dict[str, Any], float]] = {}
        for row, minutes in group:
            season = str(row.get("_seasonLabel", "")).strip() or str(row.get("_iterationId"))
            if season not in by_season:
                by_season[season] = (row, minutes)
        chosen = list(by_season.values())[:COMBINED_SEASON_COUNT]
        rows = [item[0] for item in chosen]
        minutes_list = [item[1] for item in chosen]
        merged_rows.append(_merge_combined_player_row(rows, position_minutes=minutes_list))

    benchmark_rows = [
        row
        for row in merged_rows
        if float(row.get("_combinedMinutes") or 0) >= benchmark_minutes
    ]
    return _cohort_values_from_combined_rows(benchmark_rows, profiles)


def _formation_position_meta(position_id: str) -> dict[str, str]:
    short_label, label = SQUAD_PLANNER_POSITION_LABELS.get(
        position_id, (position_id[:2].upper(), position_id.replace("_", " ").title())
    )
    return {
        "id": position_id,
        "shortLabel": short_label,
        "label": label,
    }


def squad_planner_meta() -> dict[str, Any]:
    positions: list[dict[str, Any]] = []
    for position_id, short_label, label in SQUAD_PLANNER_POSITIONS:
        if position_id not in ALLOWED_POSITIONS:
            continue
        profiles = _profiles_for_position(position_id)
        positions.append(
            {
                "id": position_id,
                "shortLabel": short_label,
                "label": label,
                "profiles": [
                    {"apiName": name, "label": humanize_profile_name(name)}
                    for name in profiles
                ],
            }
        )

    formations: list[dict[str, Any]] = []
    for formation_id, position_ids in SQUAD_PLANNER_FORMATIONS.items():
        formations.append(
            {
                "id": formation_id,
                "label": formation_id,
                "positions": [
                    _formation_position_meta(position_id) for position_id in position_ids
                ],
            }
        )

    impect = _impect()
    benchmark_minutes = float(impect.BENCHMARK_MIN_MINUTES)
    return {
        "formation": "4-3-3",
        "defaultFormation": "4-3-3",
        "formations": formations,
        "playerLabels": list(SQUAD_PLANNER_PLAYER_LABELS),
        "maxPlayersPerPosition": 15,
        "positions": positions,
        "scoring": {
            "method": "league_relative_percentile",
            "benchmarkMinutes": benchmark_minutes,
            "seasonWindow": COMBINED_SEASON_COUNT,
            "note": (
                f"Position-specific minutes and minutes-weighted profiles from the last "
                f"{COMBINED_SEASON_COUNT} seasons with data at the selected role. "
                f"Percentiles vs the same-league cohort ({benchmark_minutes:.0f}+ combined min)."
            ),
        },
    }


def build_squad_planner_player(body: SquadPlannerPlayerRequest) -> dict[str, Any]:
    position = body.position.strip()
    if position not in SQUAD_PLANNER_POSITION_IDS:
        raise HTTPException(status_code=400, detail=f"Unsupported position: {position}")

    profiles = _profiles_for_position(position)
    if not profiles:
        raise HTTPException(
            status_code=404,
            detail=f"No Port Vale profiles found for {_scouting_position_label(position)}.",
        )

    profile_keys = {_normalize_profile_key(name): name for name in profiles}
    impect = _impect()
    candidates = _iteration_candidates(body)

    hits: list[dict[str, Any]] = []
    for iteration in candidates:
        bundle = _load_iteration_bundle(iteration, position, 0)
        row = _single_season_player_row(bundle, position, body.impect_player_id)
        if row is None:
            continue
        minutes = _position_minutes_for_row(row, position=position, bundle=bundle)
        if minutes <= 0:
            continue
        hits.append(
            {
                "iteration": iteration,
                "bundle": bundle,
                "row": row,
                "minutes": minutes,
                "season": str(iteration.get("season", "")).strip(),
                "competition": str(iteration.get("competition_name", "")).strip(),
            }
        )

    if not hits:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No profile data for {body.name or 'player'} at "
                f"{_scouting_position_label(position)} across recent seasons."
            ),
        )

    # Keep the last N distinct season labels that actually have data
    # (skips empty 26/27 stubs; allows L1 25/26 + L2 24/25).
    selected: list[dict[str, Any]] = []
    seen_seasons: set[str] = set()
    for hit in hits:
        season = hit["season"]
        if season in seen_seasons:
            continue
        selected.append(hit)
        seen_seasons.add(season)
        if len(selected) >= COMBINED_SEASON_COUNT:
            break

    player_rows = [hit["row"] for hit in selected]
    position_minutes = [hit["minutes"] for hit in selected]
    player_merged = _merge_combined_player_row(player_rows, position_minutes=position_minutes)

    newest_competition = selected[0]["competition"]
    # Build percentiles from the same iterations we used for the player
    benchmark_minutes = float(impect.BENCHMARK_MIN_MINUTES)
    league_cohort = _build_combined_league_cohort(
        selected,
        position,
        profiles,
        benchmark_minutes,
    )
    combined_values = player_merged.get("_combinedProfileValues") or {}

    newest = selected[0]
    newest_iteration_id = int(newest["bundle"]["iteration_id"])
    catalog_player = newest["bundle"]["player_lookup"].get(
        (newest_iteration_id, body.impect_player_id),
        {},
    )
    squad_id = newest["row"].get("_squadId") or newest["row"].get("squadId")
    club = ""
    if squad_id is not None:
        club = newest["bundle"]["squad_names"].get(int(squad_id), "")

    name = (
        body.name.strip()
        or impect._extract_player_name(catalog_player)
        or f"Player {body.impect_player_id}"
    )
    league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(
        newest_competition,
        newest_competition,
    )
    competitions_used = [hit["competition"] for hit in selected]

    profile_scores: dict[str, float | None] = {}
    for profile_key, profile_name in profile_keys.items():
        raw_value = combined_values.get(profile_key)
        cohort_values = league_cohort.get(profile_key, [])
        if raw_value is None or not cohort_values:
            profile_scores[profile_name] = None
            continue
        profile_scores[profile_name] = impect._cohort_percentile(raw_value, cohort_values)

    if not any(value is not None for value in profile_scores.values()):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No usable profile scores for {name} at "
                f"{_scouting_position_label(position)} across recent seasons."
            ),
        )

    minutes = int(round(float(player_merged.get("_combinedMinutes") or 0)))
    season = str(player_merged.get("_seasonLabel", "")).strip()
    season_parts = " + ".join(
        f"{hit['season']} {SCOUTING_COMPETITION_TO_LEAGUE.get(hit['competition'], hit['competition'])}"
        for hit in selected
    )

    return {
        "id": f"{newest_iteration_id}:{body.impect_player_id}",
        "playerKey": body.player_key,
        "name": name,
        "club": club,
        "league": league_label,
        "season": season,
        "minutes": minutes,
        "position": position,
        "positionLabel": _scouting_position_label(position),
        "iterationId": newest_iteration_id,
        "impectPlayerId": body.impect_player_id,
        "profileScores": profile_scores,
        "profiles": [
            {"apiName": name, "label": humanize_profile_name(name)}
            for name in profiles
        ],
        "scoring": {
            "seasonWindow": COMBINED_SEASON_COUNT,
            "combinedMinutes": minutes,
            "positionMinutes": [
                {
                    "season": hit["season"],
                    "competition": hit["competition"],
                    "minutes": int(round(hit["minutes"])),
                }
                for hit in selected
            ],
            "note": (
                f"{minutes}′ at {_scouting_position_label(position)} "
                f"across {season_parts}."
            ),
        },
        "competitions": competitions_used,
    }


def register_squad_planner_routes(app: FastAPI) -> None:
    @app.get("/squad-planner", response_class=HTMLResponse)
    def squad_planner_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "squad-planner.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Squad planner UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/squad-planner/meta")
    def squad_planner_meta_route() -> dict[str, Any]:
        return squad_planner_meta()

    @app.post("/api/squad-planner/player")
    def squad_planner_player_route(body: SquadPlannerPlayerRequest) -> dict[str, Any]:
        return build_squad_planner_player(body)
