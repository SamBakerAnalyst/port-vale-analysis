from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.post_match.impect_client import impect_get, v5_path
from app.post_match.phase_analysis import _parse_scheduled_date

# Cache loaded season player rows so Ball Progression + Expected Threat share work.
_SEASON_CACHE: dict[tuple[int, int | None], tuple[float, list[dict[str, Any]]]] = {}
_SEASON_CACHE_TTL_SECONDS = 30 * 60


def position_group(position: Any) -> str:
    text = str(position or "").upper().replace("-", "_").strip()
    if not text:
        return "OTHER"
    if "GOAL" in text:
        return "GK"
    if "CENTRAL_DEFENDER" in text or text in {"CB", "CENTRE_BACK", "CENTER_BACK"}:
        return "CB"
    if "WINGBACK" in text or "FULL_BACK" in text or "FULLBACK" in text or text in {
        "LB",
        "RB",
        "LWB",
        "RWB",
        "LEFT_BACK",
        "RIGHT_BACK",
    }:
        return "FB"
    if "DEFENSE_MID" in text or "DEFENSIVE_MID" in text or text in {"DM", "CDM"}:
        return "DM"
    if "ATTACKING_MID" in text or text in {"AM", "CAM"}:
        return "AM"
    if "WINGER" in text or text in {"LW", "RW", "LM", "RM"}:
        return "W"
    if "FORWARD" in text or "STRIKER" in text or text in {"ST", "CF"}:
        return "ST"
    if "MIDFIELD" in text or text in {"CM", "CENTRAL_MIDFIELD"}:
        return "CM"
    return "OTHER"


def season_iteration_match_ids(
    iteration_id: int,
    *,
    before_match_id: int | None = None,
) -> list[int]:
    """All available league fixtures this iteration before a given match."""
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    from app.post_match.impect_client import extract_rows

    rows = extract_rows(raw["data"])
    cutoff = None
    if before_match_id is not None:
        for row in rows:
            if int(row.get("id") or 0) == before_match_id:
                cutoff = _parse_scheduled_date(row.get("scheduledDate"))
                break

    candidates: list[tuple[Any, int]] = []
    for row in rows:
        if row.get("available") is False:
            continue
        match_id = int(row.get("id") or 0)
        if not match_id:
            continue
        if before_match_id is not None and match_id == before_match_id:
            continue
        scheduled = _parse_scheduled_date(row.get("scheduledDate"))
        if scheduled is None:
            continue
        if cutoff is not None and scheduled >= cutoff:
            continue
        candidates.append((scheduled, match_id))

    candidates.sort(key=lambda item: item[0])
    return [match_id for _, match_id in candidates]


def season_squad_match_ids(
    iteration_id: int,
    squad_id: int,
    *,
    before_match_id: int | None = None,
) -> list[int]:
    """All available matches for a squad this iteration before a given match."""
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    from app.post_match.impect_client import extract_rows

    rows = extract_rows(raw["data"])
    cutoff = None
    if before_match_id is not None:
        for row in rows:
            if int(row.get("id") or 0) == before_match_id:
                cutoff = _parse_scheduled_date(row.get("scheduledDate"))
                break

    candidates: list[tuple[Any, int]] = []
    for row in rows:
        if row.get("available") is False:
            continue
        match_id = int(row.get("id") or 0)
        if not match_id:
            continue
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        if squad_id not in (home_id, away_id):
            continue
        if before_match_id is not None and match_id == before_match_id:
            continue
        scheduled = _parse_scheduled_date(row.get("scheduledDate"))
        if scheduled is None:
            continue
        if cutoff is not None and scheduled >= cutoff:
            continue
        candidates.append((scheduled, match_id))

    candidates.sort(key=lambda item: item[0])
    return [match_id for _, match_id in candidates]


def _load_match_player_rows(
    match_id: int,
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    from app.post_match.report import _consolidate_player_match_rows, _flatten_player_kpis

    raw = impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"]
    flat = _flatten_player_kpis(raw, player_names)
    consolidated = _consolidate_player_match_rows(flat)
    out: list[dict[str, Any]] = []
    for row in consolidated:
        minutes = float(row.get("minutes") or 0) / 60.0
        if minutes <= 0:
            continue
        out.append(
            {
                "matchId": match_id,
                "playerId": int(row["playerId"]),
                "squadId": int(row.get("squadId") or 0) or None,
                "position": row.get("position"),
                "positionGroup": position_group(row.get("position")),
                "minutes": minutes,
                "kpis": row.get("kpis") or {},
            }
        )
    return out


def load_season_player_rows(
    iteration_id: int,
    focus_squad_id: int | None = None,
    *,
    before_match_id: int | None,
) -> list[dict[str, Any]]:
    """Player-match rows from every available league fixture this season.

    ``focus_squad_id`` is accepted for call-site compatibility and ignored —
    gold bands need the full league population, and personal (blue) pools are
    filtered later by player + squad.
    """
    del focus_squad_id  # kept in signature for callers; pool is league-wide
    cache_key = (int(iteration_id), before_match_id)
    cached = _SEASON_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _SEASON_CACHE_TTL_SECONDS:
        return cached[1]

    from app.post_match.report import _player_directory

    match_ids = season_iteration_match_ids(
        iteration_id,
        before_match_id=before_match_id,
    )
    if not match_ids:
        _SEASON_CACHE[cache_key] = (now, [])
        return []

    player_names = _player_directory(iteration_id)
    rows: list[dict[str, Any]] = []
    workers = min(24, max(8, len(match_ids)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_load_match_player_rows, match_id, player_names): match_id
            for match_id in match_ids
        }
        for future in as_completed(futures):
            match_id = futures[future]
            try:
                rows.extend(future.result())
            except Exception:
                # Skip broken/unavailable fixtures rather than failing the whole pool.
                continue

    _SEASON_CACHE[cache_key] = (now, rows)
    return rows


def _metric_values(
    season_rows: list[dict[str, Any]],
    *,
    extract: Callable[[dict[str, Any]], float | None],
    player_id: int | None = None,
    position_group_key: str | None = None,
    focus_squad_only: bool = False,
    focus_squad_id: int | None = None,
) -> list[float]:
    values: list[float] = []
    for row in season_rows:
        if player_id is not None and int(row["playerId"]) != int(player_id):
            continue
        if position_group_key is not None and row.get("positionGroup") != position_group_key:
            continue
        if focus_squad_only and focus_squad_id is not None:
            if int(row.get("squadId") or 0) != int(focus_squad_id):
                continue
        value = extract(row)
        if value is None:
            continue
        values.append(float(value))
    return values


def top_fraction_threshold(values: list[float], fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values, reverse=True)
    cutoff_index = max(1, math.ceil(len(ordered) * fraction)) - 1
    return ordered[min(cutoff_index, len(ordered) - 1)]


def is_top_fraction(value: float | None, values: list[float], fraction: float = 0.1) -> bool:
    if value is None or not values:
        return False
    threshold = top_fraction_threshold(values, fraction=fraction)
    if threshold is None:
        return False
    return float(value) >= float(threshold) - 1e-12


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def performance_highlight(
    match_value: float | None,
    *,
    personal_values: list[float],
    position_values: list[float],
    fraction: float = 0.1,
) -> str | None:
    """Return 'gold' (position elite), 'blue' (personal elite), or None.

    Gold wins when both apply.
    """
    if match_value is None:
        return None
    position_elite = is_top_fraction(match_value, position_values, fraction=fraction)
    personal_elite = is_top_fraction(match_value, personal_values, fraction=fraction)
    if position_elite:
        return "gold"
    if personal_elite:
        return "blue"
    return None


LEGEND_BLUE = "Blue = top 10% of that player's own season"
LEGEND_GOLD = "Gold = top 10% for that position across the whole league this season"


def annotate_metric(
    match_value: float | None,
    season_rows: list[dict[str, Any]],
    *,
    player_id: int,
    position_group_key: str | None,
    extract: Callable[[dict[str, Any]], float | None],
    focus_squad_id: int,
    format_avg: Callable[[float | None], str | None],
    fraction: float = 0.1,
) -> dict[str, Any]:
    personal_values = _metric_values(
        season_rows,
        extract=extract,
        player_id=player_id,
        focus_squad_only=True,
        focus_squad_id=focus_squad_id,
    )
    # Position pool: every player-match in that position from all league fixtures.
    position_values = _metric_values(
        season_rows,
        extract=extract,
        position_group_key=position_group_key,
    )
    avg_value = average(personal_values)
    return {
        "avg": None if avg_value is None else round(avg_value, 4),
        "avgDisplay": format_avg(avg_value),
        "highlight": performance_highlight(
            match_value,
            personal_values=personal_values,
            position_values=position_values,
            fraction=fraction,
        ),
    }
