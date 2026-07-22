from __future__ import annotations

import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.label_utils import humanize_profile_name
from app.paths import STANDALONE_DIR
from app.scouting_monthly import ScoutingMonthlyListRequest
from app.scouting_monthly_report import ScoutingMonthlyReportRequest

SCOUTING_DIR = STANDALONE_DIR
STRATEGY_REPORTS_DIR = Path("/Users/AnalysisMac1/strategy-reports")
SCOUTING_CACHE_TTL_SECONDS = 3600
SCOUTING_DISK_CACHE_DIR = Path.home() / ".cache" / "impect-scouting"
MIN_POSITION_MATCH_SHARE = 5.0
# A player is counted at a position if at least this fraction of their own
# playing time (by Impect match share) was spent there. Lets fringe / low-minute
# players appear in every position they meaningfully played, not just their main one.
POSITION_SHARE_THRESHOLD = 0.25
PRIMARY_CACHE_VERSION = 2

_scouting_primary_cache: dict[int, tuple[float, dict[int, str]]] = {}
_scouting_shares_cache: dict[int, tuple[float, dict[int, dict[str, float]]]] = {}
_scouting_warm_lock = threading.Lock()
_scouting_warm_started = False
_export_all_prefetch: dict[int, dict[str, Any]] = {}
_export_all_prefetch_lock = threading.Lock()
EXPORT_ALL_ITERATION_PAUSE_SECONDS = 1.5


SCOUTING_LEAGUE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("National League", "National League"),
    ("League One", "League One"),
    ("League Two", "League Two"),
    ("PL2", "Premier League 2"),
    ("Scottish Prem", "Scottish Premiership"),
    ("Irish Prem", "Irish Premier Division"),
)

SCOUTING_LEAGUE_TO_COMPETITION = dict(SCOUTING_LEAGUE_OPTIONS)
SCOUTING_COMPETITION_TO_LEAGUE = {api: ui for ui, api in SCOUTING_LEAGUE_OPTIONS}

SCOUTING_POSITION_LABELS: dict[str, str] = {
    "LEFT_WINGBACK_DEFENDER": "Left back",
    "RIGHT_WINGBACK_DEFENDER": "Right back",
}


def _scouting_position_label(position: str) -> str:
    if position in SCOUTING_POSITION_LABELS:
        return SCOUTING_POSITION_LABELS[position]
    impect = _impect()
    return impect.POSITION_LABELS.get(position, position)


SCOUTING_SEASON_MODES: dict[str, tuple[int, bool]] = {
    "current": (0, False),
    "previous": (1, False),
    "combined": (0, True),
}


class ScoutingLongListRequest(BaseModel):
    position: str
    leagues: list[str] = Field(default_factory=list)
    min_minutes: float = 450
    season_mode: str = "current"


class ScoutingExportProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_name: str = Field(alias="apiName")
    label: str = ""
    weight: float = 0


class ScoutingExportPlayer(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rank: int
    name: str
    age: int | None = None
    minutes: float | None = None
    height: str = ""
    foot: str = ""
    league: str = ""
    club: str = ""
    overall: float | None = None
    profile_scores: dict[str, float | None] = Field(default_factory=dict, alias="profileScores")


class ScoutingExportPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    image_data: str = Field(default="", alias="imageData")


class ScoutingListExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filename: str = "scouting-long-list.pdf"
    generated_at: str = ""
    position_label: str = ""
    leagues: list[str] = Field(default_factory=list)
    min_minutes: float = 450
    season_mode: str = "current"
    season_mode_label: str = Field(default="", alias="seasonModeLabel")
    scoring_note: str = ""
    profiles: list[ScoutingExportProfile] = Field(default_factory=list)
    players: list[ScoutingExportPlayer] = Field(default_factory=list)
    pages: list[ScoutingExportPage] = Field(default_factory=list)


class ScoutingExcelAllExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filename: str = "scouting-all-positions.xlsx"
    generated_at: str = ""
    leagues: list[str] = Field(default_factory=list)
    min_minutes: float = 450
    season_mode: str = "current"
    season_mode_label: str = Field(default="", alias="seasonModeLabel")


# Backwards-compatible alias
ScoutingSlidesExportRequest = ScoutingListExportRequest


def _impect():
    from app import main as impect_main

    return impect_main


def _primary_cache_path(iteration_id: int) -> Path:
    return SCOUTING_DISK_CACHE_DIR / f"primary-{iteration_id}.json"


def _load_primary_from_disk(
    iteration_id: int,
) -> tuple[dict[int, str], dict[int, dict[str, float]]] | None:
    path = _primary_cache_path(iteration_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("version", 1)) != PRIMARY_CACHE_VERSION:
            return None
        cached_at = float(payload.get("cached_at", 0))
        if time.time() - cached_at > SCOUTING_CACHE_TTL_SECONDS:
            return None
        raw = payload.get("primary", {})
        primary = {int(player_id): str(pos) for player_id, pos in raw.items()}
        raw_shares = payload.get("shares", {})
        shares = {
            int(player_id): {str(pos): float(value) for pos, value in pos_map.items()}
            for player_id, pos_map in raw_shares.items()
        }
        return primary, shares
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _save_primary_to_disk(
    iteration_id: int,
    primary_positions: dict[int, str],
    position_shares: dict[int, dict[str, float]],
) -> None:
    try:
        SCOUTING_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": PRIMARY_CACHE_VERSION,
            "iteration_id": iteration_id,
            "cached_at": time.time(),
            "primary": {str(player_id): pos for player_id, pos in primary_positions.items()},
            "shares": {
                str(player_id): {pos: value for pos, value in pos_map.items()}
                for player_id, pos_map in position_shares.items()
            },
        }
        _primary_cache_path(iteration_id).write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
    except OSError:
        return


def _get_primary_positions(iteration_id: int) -> dict[int, str] | None:
    cached = _scouting_primary_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < SCOUTING_CACHE_TTL_SECONDS:
        return cached[1]

    disk = _load_primary_from_disk(iteration_id)
    if disk is not None:
        primary, shares = disk
        _scouting_primary_cache[iteration_id] = (now, primary)
        _scouting_shares_cache[iteration_id] = (now, shares)
        return primary

    return None


def _get_position_shares(iteration_id: int) -> dict[int, dict[str, float]] | None:
    cached = _scouting_shares_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < SCOUTING_CACHE_TTL_SECONDS:
        return cached[1]

    disk = _load_primary_from_disk(iteration_id)
    if disk is not None:
        primary, shares = disk
        _scouting_primary_cache[iteration_id] = (now, primary)
        _scouting_shares_cache[iteration_id] = (now, shares)
        return shares

    return None


def _player_plays_position(
    position_shares: dict[int, dict[str, float]],
    player_id: int,
    position: str,
    threshold: float = POSITION_SHARE_THRESHOLD,
) -> bool:
    shares = position_shares.get(player_id)
    if not shares:
        return False
    total = sum(shares.values())
    if total <= 0:
        return False
    return (shares.get(position, 0.0) / total) >= threshold


def _build_primary_positions(iteration_id: int) -> dict[int, str]:
    impect = _impect()
    best_by_player: dict[int, tuple[float, str]] = {}
    shares_by_player: dict[int, dict[str, float]] = {}

    def fetch_position(position: str) -> tuple[str, list[dict[str, Any]]]:
        rows = impect._fetch_iteration_profile_scores(iteration_id, [position], 0)
        return position, rows

    max_workers = min(8, len(impect.ALLOWED_POSITIONS))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_position, position)
            for position in impect.ALLOWED_POSITIONS
        ]
        for future in as_completed(futures):
            position, rows = future.result()
            for row in rows:
                player_id = row.get("playerId")
                if player_id is None:
                    continue
                player_key = int(player_id)
                match_share = float(row.get("matchShare") or 0)
                if match_share > 0:
                    shares_by_player.setdefault(player_key, {})[position] = match_share
                current = best_by_player.get(player_key)
                if current is None or match_share > current[0]:
                    best_by_player[player_key] = (match_share, position)

    primary_positions = {
        player_id: pos for player_id, (_, pos) in best_by_player.items()
    }
    now = time.time()
    _scouting_primary_cache[iteration_id] = (now, primary_positions)
    _scouting_shares_cache[iteration_id] = (now, shares_by_player)
    _save_primary_to_disk(iteration_id, primary_positions, shares_by_player)
    return primary_positions


def _profiles_for_position(position: str) -> list[str]:
    impect = _impect()
    if position not in impect.ALLOWED_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported position: {position}")

    definitions = impect._fetch_player_profile_definitions()
    profiles = [
        name
        for name, definition in definitions.items()
        if impect._is_pv_profile(name) and position in definition.get("positions", [])
    ]
    return sorted(profiles, key=lambda name: humanize_profile_name(name).casefold())


def _latest_iteration_by_competition() -> dict[str, dict[str, Any]]:
    impect = _impect()
    iterations = impect._fetch_iterations()
    by_competition: dict[str, list[dict[str, Any]]] = {}
    for item in iterations:
        competition_name = str(item.get("competition_name", "")).strip()
        if competition_name not in impect.ALLOWED_COMPETITIONS:
            continue
        by_competition.setdefault(competition_name, []).append(item)

    latest: dict[str, dict[str, Any]] = {}
    for competition_name, items in by_competition.items():
        items.sort(
            key=lambda row: impect._season_sort_key(str(row.get("season", ""))),
            reverse=True,
        )
        if items:
            latest[competition_name] = items[0]
    return latest


def _resolve_scouting_season_mode(season_mode: str) -> tuple[int, bool]:
    key = str(season_mode or "current").strip().casefold()
    if key not in SCOUTING_SEASON_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown season mode: {season_mode}. Use current, previous, or combined.",
        )
    return SCOUTING_SEASON_MODES[key]


def _scouting_iteration_rows(
    selected_competitions: list[str],
    *,
    season_offset: int,
    combine_seasons: bool,
) -> list[dict[str, Any]]:
    impect = _impect()
    all_iterations = impect._fetch_iterations()
    by_competition: dict[str, list[dict[str, Any]]] = {}
    for item in all_iterations:
        competition_name = str(item.get("competition_name", "")).strip()
        if competition_name not in selected_competitions:
            continue
        by_competition.setdefault(competition_name, []).append(item)

    iteration_rows: list[dict[str, Any]] = []
    for competition in selected_competitions:
        items = by_competition.get(competition, [])
        items.sort(
            key=lambda row: impect._season_sort_key(str(row.get("season", ""))),
            reverse=True,
        )
        if season_offset >= len(items):
            continue
        indices = [season_offset]
        if combine_seasons and season_offset + 1 < len(items):
            indices.append(season_offset + 1)
        for idx in indices:
            iteration_rows.append(items[idx])
    return iteration_rows


def _scouting_season_titles() -> tuple[str, str]:
    """Return (current, previous) season titles from Impect iterations, e.g. ('26/27', '25/26')."""
    impect = _impect()
    seasons: list[str] = []
    seen: set[str] = set()
    for item in impect._fetch_iterations():
        season = str(item.get("season", "")).strip()
        # Prefer football season codes (26/27) over calendar-year leagues (e.g. Irish Prem 2026).
        if not season or "/" not in season or season in seen:
            continue
        competition_name = str(item.get("competition_name", "")).strip()
        if competition_name and competition_name not in impect.ALLOWED_COMPETITIONS:
            continue
        seen.add(season)
        seasons.append(season)
    seasons.sort(key=impect._season_sort_key, reverse=True)
    current = seasons[0] if seasons else "Current season"
    previous = seasons[1] if len(seasons) > 1 else "Previous season"
    return current, previous


def _season_mode_label(season_mode: str, *, combine_seasons: bool) -> str:
    current, previous = _scouting_season_titles()
    if combine_seasons:
        return f"{current} + {previous} (combined minutes)"
    if season_mode == "previous":
        return previous
    return current


def _scouting_season_mode_options() -> list[dict[str, str]]:
    current, previous = _scouting_season_titles()
    return [
        {"value": "current", "label": current},
        {"value": "previous", "label": previous},
        {
            "value": "combined",
            "label": f"{current} + {previous} (combined minutes)",
        },
    ]


def _merge_player_season_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge profile scores (minutes-weighted) and sum minutes — newest row first."""
    impect = _impect()
    newest = rows[0]
    total_minutes = 0.0
    weighted: dict[str, float] = {}
    weight_total: dict[str, float] = {}
    season_labels: list[str] = []

    for row in rows:
        minutes = impect._play_duration_minutes(row) or 0.0
        total_minutes += minutes
        season_label = str(row.get("_seasonLabel", "")).strip()
        if season_label and season_label not in season_labels:
            season_labels.append(season_label)
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
    if len(season_labels) > 1:
        merged["_seasonLabel"] = "+".join(season_labels)
    elif season_labels:
        merged["_seasonLabel"] = season_labels[0]
    return merged


def _cohort_values_from_combined_rows(
    merged_rows: list[dict[str, Any]],
    profiles: list[str],
) -> dict[str, list[float]]:
    cohort: dict[str, list[float]] = {}
    for profile_name in profiles:
        profile_key = _normalize_profile_key(profile_name)
        values: list[float] = []
        for row in merged_rows:
            combined = row.get("_combinedProfileValues") or {}
            value = combined.get(profile_key)
            if value is not None:
                values.append(float(value))
        cohort[profile_key] = values
    return cohort


def _normalize_profile_key(name: str) -> str:
    return _impect()._normalize_profile_name(name).casefold()


def _profile_value_map(row: dict[str, Any]) -> dict[str, float]:
    impect = _impect()
    values: dict[str, float] = {}
    for score in row.get("profileScores", []):
        if not isinstance(score, dict):
            continue
        profile_name = impect._normalize_profile_name(score.get("profileName"))
        if not profile_name or not impect._is_pv_profile(profile_name):
            continue
        value = score.get("value")
        if value is None:
            continue
        values[_normalize_profile_key(profile_name)] = float(value)
    return values


def _format_foot(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text == "LEFT":
        return "L"
    if text == "RIGHT":
        return "R"
    if text == "BOTH":
        return "Both"
    return "—"


def _format_height(player: dict[str, Any]) -> str | None:
    for key in ("heightCm", "height", "bodyHeight"):
        raw = player.get(key)
        if raw is None or raw == "":
            continue
        try:
            cm = int(float(raw))
        except (TypeError, ValueError):
            continue
        if cm <= 0:
            continue
        feet = int(cm // 30.48)
        inches = int(round((cm / 2.54) % 12))
        return f"{feet}'{inches}\" ({cm}cm)"
    return None


def build_scouting_player_chart_bundle(
    *,
    name: str,
    player_id: int,
    iteration_id: int,
    squad_id: int | None,
    position: str,
    profiles: list[str],
) -> dict[str, Any]:
    """Build player chart identifiers and a /api/charts request payload."""
    impect = _impect()
    player_key = impect._player_key(name, player_id)
    iteration_str = str(iteration_id)
    catalog_entry: dict[str, Any] = {
        "name": name,
        "ids_by_iteration": {iteration_str: player_id},
    }
    if squad_id is not None:
        catalog_entry["squad_ids_by_iteration"] = {iteration_str: int(squad_id)}

    return {
        "playerKey": player_key,
        "playerId": player_id,
        "iterationId": iteration_id,
        "squadId": squad_id,
        "chartRequest": {
            "iteration_ids": [iteration_id],
            "player_keys": [player_key],
            "player_catalog": {player_key: catalog_entry},
            "player_seasons": {player_key: [iteration_id]},
            "player_positions": {player_key: [position]},
            "positions": [position],
            "profiles": profiles,
            "chart_source": "profiles",
        },
    }


def _scouting_export_positions() -> list[str]:
    impect = _impect()
    return list(impect.ALLOWED_POSITIONS)


def _clear_export_all_prefetch() -> None:
    with _export_all_prefetch_lock:
        _export_all_prefetch.clear()


def _prefetch_export_all_iterations(
    iteration_rows: list[dict[str, Any]],
    positions: list[str],
) -> None:
    """Load each iteration once for all positions — avoids 9× API traffic on export-all."""
    impect = _impect()
    for index, iteration in enumerate(iteration_rows):
        iteration_id = int(iteration["id"])
        with _export_all_prefetch_lock:
            if iteration_id in _export_all_prefetch:
                continue

        primary_positions, position_shares = _ensure_position_shares(iteration_id)
        score_rows = impect._fetch_iteration_profile_scores(iteration_id, positions, 0)
        season_label = str(iteration.get("season", "")).strip()
        competition_name = str(iteration["competition_name"])
        for row in score_rows:
            row["_iterationId"] = iteration_id
            row["_competitionName"] = competition_name
            row["_seasonLabel"] = season_label

        players = impect._fetch_players_for_iteration(iteration_id)
        player_lookup: dict[tuple[int, int], dict[str, Any]] = {}
        for player in players:
            player_id = player.get("id")
            if player_id is None:
                continue
            player_lookup[(iteration_id, int(player_id))] = player

        bundle = {
            "iteration": iteration,
            "iteration_id": iteration_id,
            "league_label": SCOUTING_COMPETITION_TO_LEAGUE.get(
                competition_name,
                competition_name,
            ),
            "primary_ready": position_shares is not None,
            "score_rows": score_rows,
            "player_lookup": player_lookup,
            "squad_names": impect._fetch_squad_names(iteration_id),
            "primary_positions": primary_positions,
            "position_shares": position_shares,
        }
        with _export_all_prefetch_lock:
            _export_all_prefetch[iteration_id] = bundle

        if index < len(iteration_rows) - 1:
            time.sleep(EXPORT_ALL_ITERATION_PAUSE_SECONDS)


def _fetch_position_rows(iteration_id: int, position: str) -> list[dict[str, Any]]:
    impect = _impect()
    return impect._fetch_iteration_profile_scores(iteration_id, [position], 0)


def _row_passes_position_filter(
    row: dict[str, Any],
    position: str,
    primary_positions: dict[int, str] | None,
    min_minutes: float,
    *,
    check_minutes: bool = True,
    position_shares: dict[int, dict[str, float]] | None = None,
) -> bool:
    impect = _impect()
    if check_minutes and (impect._play_duration_minutes(row) or 0) < min_minutes:
        return False
    player_id = row.get("playerId")
    if player_id is None:
        return False

    player_key = int(player_id)
    # Preferred: a player qualifies for any position where they spent a
    # meaningful share of their own minutes (so low-minute players still show).
    if position_shares is not None:
        return _player_plays_position(position_shares, player_key, position)
    if primary_positions is not None:
        return primary_positions.get(player_key) == position

    match_share = float(row.get("matchShare") or 0)
    return match_share >= MIN_POSITION_MATCH_SHARE


def _cohort_values_by_profile(
    cohort_rows: list[dict[str, Any]],
    profiles: list[str],
) -> dict[str, list[float]]:
    impect = _impect()
    cohort: dict[str, list[float]] = {}
    for profile_name in profiles:
        cohort[_normalize_profile_key(profile_name)] = impect._cohort_values_for_key(
            cohort_rows,
            "profileName",
            profile_name,
            "profileScores",
        )
    return cohort


def _league_benchmark_rows(
    score_rows: list[dict[str, Any]],
    position: str,
    primary_positions: dict[int, str] | None,
    benchmark_minutes: float,
    position_shares: dict[int, dict[str, float]] | None = None,
) -> list[dict[str, Any]]:
    return [
        row
        for row in score_rows
        if _row_passes_position_filter(
            row,
            position,
            primary_positions,
            benchmark_minutes,
            position_shares=position_shares,
        )
    ]


def _ensure_position_shares(
    iteration_id: int,
) -> tuple[dict[int, str] | None, dict[int, dict[str, float]] | None]:
    primary_positions = _get_primary_positions(iteration_id)
    position_shares = _get_position_shares(iteration_id)
    if position_shares is not None:
        return primary_positions, position_shares
    _build_primary_positions(iteration_id)
    return _get_primary_positions(iteration_id), _get_position_shares(iteration_id)


def _load_iteration_bundle(
    iteration: dict[str, Any],
    position: str,
    min_minutes: float,
) -> dict[str, Any]:
    impect = _impect()
    iteration_id = int(iteration["id"])
    primary_positions, position_shares = _ensure_position_shares(iteration_id)
    with _export_all_prefetch_lock:
        cached = _export_all_prefetch.get(iteration_id)
    if cached is not None:
        if cached.get("position_shares") is None and position_shares is not None:
            cached["position_shares"] = position_shares
            cached["primary_positions"] = primary_positions
            cached["primary_ready"] = True
        return cached

    competition_name = str(iteration["competition_name"])
    league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(competition_name, competition_name)

    score_rows = _fetch_position_rows(iteration_id, position)
    season_label = str(iteration.get("season", "")).strip()
    for row in score_rows:
        row["_iterationId"] = iteration_id
        row["_competitionName"] = competition_name
        row["_seasonLabel"] = season_label

    players = impect._fetch_players_for_iteration(iteration_id)
    player_lookup: dict[tuple[int, int], dict[str, Any]] = {}
    for player in players:
        player_id = player.get("id")
        if player_id is None:
            continue
        player_lookup[(iteration_id, int(player_id))] = player

    return {
        "iteration": iteration,
        "iteration_id": iteration_id,
        "league_label": league_label,
        "primary_ready": position_shares is not None,
        "score_rows": score_rows,
        "player_lookup": player_lookup,
        "squad_names": impect._fetch_squad_names(iteration_id),
        "primary_positions": primary_positions,
        "position_shares": position_shares,
    }


def scouting_meta() -> dict[str, Any]:
    from app.scouting_monthly import monthly_meta_defaults

    impect = _impect()
    _ensure_scouting_warmup()
    return {
        "positions": [
            {"value": position, "label": _scouting_position_label(position)}
            for position in impect.ALLOWED_POSITIONS
        ],
        "leagues": [ui for ui, _ in SCOUTING_LEAGUE_OPTIONS],
        "default_min_minutes": 450,
        "season_modes": _scouting_season_mode_options(),
        "default_season_mode": "current",
        "report_modes": [
            {"value": "season", "label": "Season long list"},
            {"value": "monthly", "label": "Monthly highlights"},
        ],
        "default_report_mode": "season",
        "monthly": monthly_meta_defaults(),
    }


def build_scouting_long_list(body: ScoutingLongListRequest) -> dict[str, Any]:
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

    profile_keys = {_normalize_profile_key(name): name for name in profiles}
    season_offset, combine_seasons = _resolve_scouting_season_mode(body.season_mode)
    season_mode_key = str(body.season_mode or "current").strip().casefold()

    selected_competitions: list[str] = []
    for league in body.leagues:
        competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
        if competition is None:
            raise HTTPException(status_code=400, detail=f"Unknown league: {league}")
        selected_competitions.append(competition)

    iteration_rows = _scouting_iteration_rows(
        selected_competitions,
        season_offset=season_offset,
        combine_seasons=combine_seasons,
    )
    if not iteration_rows:
        detail = "No season data for the selected leagues."
        if season_mode_key == "previous":
            detail = "No previous-season data for the selected leagues."
        raise HTTPException(status_code=404, detail=detail)

    load_minutes = 0.0 if combine_seasons else body.min_minutes
    iteration_rank = {
        int(row["id"]): index
        for index, row in enumerate(
            sorted(
                iteration_rows,
                key=lambda item: impect._season_sort_key(str(item.get("season", ""))),
                reverse=True,
            )
        )
    }

    player_lookup: dict[tuple[int, int], dict[str, Any]] = {}
    squad_names_by_iteration: dict[int, dict[int, str]] = {}
    primary_by_iteration: dict[int, dict[int, str] | None] = {}
    shares_by_iteration: dict[int, dict[int, dict[str, float]] | None] = {}
    league_cohort_sizes: dict[str, int] = {}
    warnings: list[str] = []
    primary_ready = True
    benchmark_minutes = float(impect.BENCHMARK_MIN_MINUTES)

    iteration_bundles: list[dict[str, Any]] = []
    max_workers = min(6, max(len(iteration_rows), 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_load_iteration_bundle, iteration, position, load_minutes)
            for iteration in iteration_rows
        ]
        for future in as_completed(futures):
            iteration_bundles.append(future.result())

    for bundle in iteration_bundles:
        iteration_id = bundle["iteration_id"]
        if not bundle["primary_ready"]:
            primary_ready = False
        primary_by_iteration[iteration_id] = bundle["primary_positions"]
        shares_by_iteration[iteration_id] = bundle.get("position_shares")
        player_lookup.update(bundle["player_lookup"])
        squad_names_by_iteration[iteration_id] = bundle["squad_names"]

    if not primary_ready:
        warnings.insert(
            0,
            "Position filter still warming up — using fast match-share filter for now. "
            "Reload in a minute for full results.",
        )
        _ensure_scouting_warmup()

    cohort_by_league: dict[str, dict[str, list[float]]] = {}
    eligible_rows: list[dict[str, Any]] = []

    if combine_seasons:
        rows_by_competition_player: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for bundle in iteration_bundles:
            competition_name = str(bundle["iteration"]["competition_name"])
            for row in bundle["score_rows"]:
                player_id = row.get("playerId")
                if player_id is None:
                    continue
                key = (competition_name, int(player_id))
                rows_by_competition_player.setdefault(key, []).append(row)

        merged_by_league: dict[str, list[dict[str, Any]]] = {}
        for (competition_name, _player_id), group in rows_by_competition_player.items():
            group.sort(
                key=lambda row: iteration_rank.get(int(row.get("_iterationId") or 0), 0),
                reverse=True,
            )
            newest = group[0]
            newest_iteration_id = int(newest.get("_iterationId") or 0)
            primary_positions = primary_by_iteration.get(newest_iteration_id)
            position_shares = shares_by_iteration.get(newest_iteration_id)
            if not _row_passes_position_filter(
                newest,
                position,
                primary_positions,
                0,
                check_minutes=False,
                position_shares=position_shares,
            ):
                continue

            merged = (
                _merge_player_season_rows(group)
                if len(group) > 1
                else {
                    **newest,
                    "_combinedMinutes": impect._play_duration_minutes(newest) or 0.0,
                    "_combinedProfileValues": _profile_value_map(newest),
                }
            )
            league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(
                competition_name,
                competition_name,
            )
            merged["_leagueLabel"] = league_label
            merged_by_league.setdefault(league_label, []).append(merged)

        for league_label, merged_rows in merged_by_league.items():
            benchmark_rows = [
                row
                for row in merged_rows
                if float(row.get("_combinedMinutes") or 0) >= benchmark_minutes
            ]
            cohort_by_league[league_label] = _cohort_values_from_combined_rows(
                benchmark_rows,
                profiles,
            )
            league_cohort_sizes[league_label] = len(benchmark_rows)

            filtered_rows = [
                row
                for row in merged_rows
                if float(row.get("_combinedMinutes") or 0) >= body.min_minutes
            ]
            eligible_rows.extend(filtered_rows)
            if not filtered_rows:
                warnings.append(
                    f"No {_scouting_position_label(position)} players met the "
                    f"{body.min_minutes:.0f}+ combined-minute filter in {league_label}."
                )
    else:
        for bundle in iteration_bundles:
            iteration_id = bundle["iteration_id"]
            league_label = bundle["league_label"]
            primary_positions = bundle["primary_positions"]
            position_shares = bundle.get("position_shares")
            league_cohort_rows = _league_benchmark_rows(
                bundle["score_rows"],
                position,
                primary_positions,
                benchmark_minutes,
                position_shares=position_shares,
            )
            cohort_by_league[league_label] = _cohort_values_by_profile(
                league_cohort_rows,
                profiles,
            )
            league_cohort_sizes[league_label] = len(league_cohort_rows)

            filtered_rows = [
                row
                for row in bundle["score_rows"]
                if _row_passes_position_filter(
                    row,
                    position,
                    primary_positions,
                    body.min_minutes,
                    position_shares=position_shares,
                )
            ]
            for row in filtered_rows:
                row["_combinedMinutes"] = impect._play_duration_minutes(row) or 0.0
                row["_combinedProfileValues"] = _profile_value_map(row)
                row["_seasonLabel"] = str(row.get("_seasonLabel", ""))
                row["_leagueLabel"] = league_label
            eligible_rows.extend(filtered_rows)
            if not filtered_rows:
                warnings.append(
                    f"No {_scouting_position_label(position)} players met the "
                    f"{body.min_minutes:.0f}+ minute filter in {league_label}."
                )

    if not eligible_rows:
        minute_label = "combined minutes" if combine_seasons else "minutes"
        raise HTTPException(
            status_code=404,
            detail=(
                f"No {_scouting_position_label(position)} players found "
                f"with {body.min_minutes:.0f}+ {minute_label} in the selected leagues."
            ),
        )

    players_payload: list[dict[str, Any]] = []
    for row in eligible_rows:
        player_id = row.get("playerId")
        squad_id = row.get("_squadId")
        iteration_id = row.get("_iterationId")
        if player_id is None or iteration_id is None:
            continue

        iteration_id = int(iteration_id)
        league_label = str(row.get("_leagueLabel", ""))
        league_cohort = cohort_by_league.get(league_label, {})
        combined_values = row.get("_combinedProfileValues") or {}

        catalog_player = player_lookup.get((iteration_id, int(player_id)), {})
        name = impect._extract_player_name(catalog_player) or f"Player {player_id}"
        age = impect._player_age(catalog_player)
        foot = _format_foot(catalog_player.get("leg"))
        height = _format_height(catalog_player)
        club = ""
        if squad_id is not None:
            club = squad_names_by_iteration.get(iteration_id, {}).get(int(squad_id), "")

        chart_bundle = build_scouting_player_chart_bundle(
            name=name,
            player_id=int(player_id),
            iteration_id=iteration_id,
            squad_id=int(squad_id) if squad_id is not None else None,
            position=position,
            profiles=profiles,
        )

        profile_scores: dict[str, float | None] = {}
        for profile_key, profile_name in profile_keys.items():
            raw_value = combined_values.get(profile_key)
            cohort_values = league_cohort.get(profile_key, [])
            if raw_value is None or not cohort_values:
                profile_scores[profile_name] = None
                continue
            percentile = impect._cohort_percentile(raw_value, cohort_values)
            profile_scores[profile_name] = percentile

        if not any(value is not None for value in profile_scores.values()):
            continue

        players_payload.append(
            {
                "id": f"{iteration_id}:{player_id}",
                "name": name,
                "age": age,
                "height": height,
                "foot": foot,
                "league": league_label,
                "club": club,
                "season": str(row.get("_seasonLabel", "")),
                "minutes": int(round(float(row.get("_combinedMinutes") or 0))),
                "profileScores": profile_scores,
                **chart_bundle,
            }
        )

    display_profiles = [
        {"apiName": name, "label": humanize_profile_name(name)}
        for name in profiles
    ]

    season_mode_label = _season_mode_label(season_mode_key, combine_seasons=combine_seasons)
    current_title, previous_title = _scouting_season_titles()

    scoring_note = (
        f"{season_mode_label}. Scores compare each player to others in the same league only "
        f"({benchmark_minutes:.0f}+ min, primary role)."
    )
    if combine_seasons:
        scoring_note = (
            f"Combined minutes from {current_title} + {previous_title}. Profile scores are "
            "minutes-weighted across both seasons, then ranked vs the same league "
            f"({benchmark_minutes:.0f}+ combined min, primary role in latest season)."
        )
    elif season_mode_key == "previous":
        scoring_note = (
            f"{previous_title} only. Scores compare each player to others in the same "
            f"league ({benchmark_minutes:.0f}+ min, primary role)."
        )

    return {
        "position": position,
        "positionLabel": _scouting_position_label(position),
        "profiles": display_profiles,
        "players": players_payload,
        "playerCount": len(players_payload),
        "primaryFilterReady": primary_ready,
        "seasonMode": season_mode_key,
        "seasonModeLabel": season_mode_label,
        "scoring": {
            "method": "league_relative_percentile",
            "benchmarkMinutes": benchmark_minutes,
            "note": scoring_note,
            "leagueCohortSizes": league_cohort_sizes,
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


def _warm_scouting_cache() -> None:
    try:
        latest = _latest_iteration_by_competition()
        iteration_ids = [int(item["id"]) for item in latest.values()]
        max_workers = min(3, max(len(iteration_ids), 1))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_build_primary_positions, iteration_id)
                for iteration_id in iteration_ids
                if _get_position_shares(iteration_id) is None
            ]
            for future in as_completed(futures):
                future.result()
    except Exception:
        return


def _ensure_scouting_warmup() -> None:
    global _scouting_warm_started
    with _scouting_warm_lock:
        if _scouting_warm_started:
            return
        _scouting_warm_started = True

        def delayed_warm() -> None:
            time.sleep(90)
            _warm_scouting_cache()

        threading.Thread(target=delayed_warm, daemon=True).start()


def register_scouting_routes(app: FastAPI) -> None:
    app.mount("/standalone", StaticFiles(directory=SCOUTING_DIR), name="scouting-standalone")

    @app.get("/strategy", response_class=HTMLResponse)
    @app.get("/strategy/", response_class=HTMLResponse)
    def strategy_report_home() -> HTMLResponse:
        html_path = STRATEGY_REPORTS_DIR / "index.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Strategy report not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    if STRATEGY_REPORTS_DIR.is_dir():
        app.mount(
            "/strategy/assets",
            StaticFiles(directory=STRATEGY_REPORTS_DIR),
            name="strategy-reports-static",
        )

    @app.on_event("startup")
    def start_scouting_cache_warmup() -> None:
        _ensure_scouting_warmup()

    @app.get("/scouting", response_class=HTMLResponse)
    def scouting_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "index.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scouting UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/scouting/player", response_class=HTMLResponse)
    def scouting_player_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "player.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scouting player charts UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/scouting/compare", response_class=HTMLResponse)
    def scouting_compare_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "compare.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scouting comparison charts UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/scouting/meta")
    def scouting_meta_route() -> dict[str, Any]:
        return scouting_meta()

    @app.post("/api/scouting/long-list")
    def scouting_long_list(body: ScoutingLongListRequest) -> dict[str, Any]:
        return build_scouting_long_list(body)

    @app.post("/api/scouting/monthly-list")
    def scouting_monthly_list(body: ScoutingMonthlyListRequest) -> dict[str, Any]:
        from app.scouting_monthly import build_scouting_monthly_list

        return build_scouting_monthly_list(body)

    @app.post("/api/scouting/export-pdf")
    def scouting_export_pdf(body: ScoutingListExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop
        from app.scouting_export_pdf import build_scouting_export_pdf

        try:
            pdf_bytes = build_scouting_export_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        filename = _safe_export_filename(body.filename, default_ext=".pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    @app.post("/api/scouting/export-excel")
    def scouting_export_excel(body: ScoutingListExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop
        from app.scouting_export_xlsx import build_scouting_export_xlsx

        try:
            xlsx_bytes = build_scouting_export_xlsx(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        filename = _safe_export_filename(body.filename, default_ext=".xlsx")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(xlsx_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    @app.post("/api/scouting/export-excel-all")
    def scouting_export_excel_all(body: ScoutingExcelAllExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop
        from app.scouting_export_xlsx import build_scouting_all_positions_xlsx

        if not body.leagues:
            raise HTTPException(status_code=400, detail="Select at least one league.")

        positions = _scouting_export_positions()
        season_mode_key = str(body.season_mode or "current").strip().casefold()
        season_offset, combine_seasons = _resolve_scouting_season_mode(body.season_mode)
        season_mode_label = (
            str(body.season_mode_label or "").strip()
            or _season_mode_label(season_mode_key, combine_seasons=combine_seasons)
        )

        selected_competitions: list[str] = []
        for league in body.leagues:
            competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
            if competition is None:
                raise HTTPException(status_code=400, detail=f"Unknown league: {league}")
            selected_competitions.append(competition)

        iteration_rows = _scouting_iteration_rows(
            selected_competitions,
            season_offset=season_offset,
            combine_seasons=combine_seasons,
        )
        if not iteration_rows:
            raise HTTPException(
                status_code=404,
                detail="No season data for the selected leagues.",
            )

        sheets: list[dict[str, Any]] = []
        errors: list[str] = []

        try:
            _prefetch_export_all_iterations(iteration_rows, positions)
            for position in positions:
                try:
                    sheet_data = build_scouting_long_list(
                        ScoutingLongListRequest(
                            position=position,
                            leagues=body.leagues,
                            min_minutes=body.min_minutes,
                            season_mode=body.season_mode,
                        )
                    )
                except HTTPException as exc:
                    if exc.status_code == 404:
                        errors.append(f"{_scouting_position_label(position)}: {exc.detail}")
                        continue
                    if exc.status_code == 429:
                        raise HTTPException(
                            status_code=429,
                            detail=(
                                "Impect API rate limit reached while building the workbook. "
                                "Wait 2–3 minutes, narrow leagues if you can, then try again."
                            ),
                        ) from exc
                    raise
                if sheet_data.get("players"):
                    sheets.append(sheet_data)
        finally:
            _clear_export_all_prefetch()

        if not sheets:
            detail = "No players found for any position with the current filters."
            if errors:
                detail = f"{detail} ({errors[0]})"
            raise HTTPException(status_code=404, detail=detail)

        scoring_note = str(sheets[0].get("scoring", {}).get("note", ""))
        try:
            xlsx_bytes = build_scouting_all_positions_xlsx(
                sheets=sheets,
                generated_at=body.generated_at,
                leagues=body.leagues,
                min_minutes=body.min_minutes,
                season_mode_label=season_mode_label,
                scoring_note=scoring_note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        filename = _safe_export_filename(body.filename, default_ext=".xlsx")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(xlsx_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
        )

    @app.post("/api/scouting/monthly-report-pdf")
    def scouting_monthly_report_pdf(body: ScoutingMonthlyReportRequest) -> Response:
        """Player of the Month pack: top 10 overall + profile strengths per position."""
        from app.main import _safe_export_filename, _save_export_to_desktop
        from app.scouting_monthly_report import build_monthly_report_pdf

        try:
            pdf_bytes = build_monthly_report_pdf(body)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Player of the Month report failed: {exc}",
            ) from exc

        month_slug = f"{body.year}-{body.month:02d}"
        filename = _safe_export_filename(
            f"player-of-the-month-{month_slug}.pdf",
            default_ext=".pdf",
        )
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
