"""WHO TO SCOUT — recruitment shortlist by league, position, and profile weights."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from app.home_dashboard import (
    STANDOUTS_CACHE_TTL,
    STANDOUTS_DEFAULT_MIN_SCORE,
    STANDOUTS_LEAGUES,
    STANDOUTS_PER_LEAGUE_LIMIT,
    _attach_scout_coverage,
    _build_standouts_month_payload,
    _build_standouts_season_payload,
    _load_standouts_disk,
    _normalize_standouts_month,
    _schedule_standouts_refresh,
    _standouts_building_payload,
    _standouts_cache,
    _standouts_month_options,
    _standouts_positions,
    _standouts_raw_cache_key,
)
from app.label_utils import humanize_profile_name
from app.scouting import SCOUTING_DIR, _profiles_for_position


def _profiles_from_players(players: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    by_position: dict[str, dict[str, str]] = {}
    for player in players:
        position = str(player.get("position") or "").strip()
        if not position:
            continue
        bucket = by_position.setdefault(position, {})
        for name in player.get("profileScores") or {}:
            if name not in bucket:
                bucket[name] = humanize_profile_name(name)
    return {
        position: [
            {"apiName": api_name, "label": label}
            for api_name, label in sorted(bucket.items(), key=lambda item: item[1].casefold())
        ]
        for position, bucket in by_position.items()
    }


def _profiles_meta_for_position(position: str) -> list[dict[str, str]]:
    try:
        return [
            {"apiName": name, "label": humanize_profile_name(name)}
            for name in _profiles_for_position(position)
        ]
    except Exception:  # noqa: BLE001
        return []


def _profiles_meta_from_disk() -> dict[str, list[dict[str, str]]]:
    disk = _load_standouts_disk(_standouts_raw_cache_key("season"))
    if disk is None:
        return {}
    players = disk[1].get("players") or []
    derived = _profiles_from_players(players)
    if derived:
        return derived
    from app import main as impect

    return {
        position: _profiles_meta_for_position(position)
        for position in impect.ALLOWED_POSITIONS
    }


def _who_to_scout_player(row: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "id",
        "playerId",
        "name",
        "age",
        "height",
        "foot",
        "club",
        "league",
        "season",
        "minutes",
        "matchCount",
        "position",
        "positionLabel",
        "overall",
        "bestProfile",
        "bestProfileScore",
        "profileScores",
        "scout",
        "scout_total",
    )
    return {key: row[key] for key in keep if key in row}


def _load_standouts_raw_payload(
    *,
    period: str,
    year: int | None = None,
    month: int | None = None,
    force_refresh: bool = False,
    _from_background: bool = False,
) -> dict[str, Any]:
    period_key = "month" if period == "month" else "season"
    month_year: int | None = None
    month_num: int | None = None
    month_label: str | None = None
    if period_key == "month":
        month_year, month_num, month_label = _normalize_standouts_month(year, month)

    now = time.time()
    cache_key = _standouts_raw_cache_key(period_key, year=month_year, month=month_num)
    cached = _standouts_cache.get(cache_key)

    raw_payload: dict[str, Any] | None = None
    if not force_refresh and cached and now - cached[0] < STANDOUTS_CACHE_TTL:
        raw_payload = cached[1]
    elif not force_refresh:
        disk = _load_standouts_disk(cache_key)
        if disk is not None:
            saved_at, payload = disk
            _standouts_cache[cache_key] = (saved_at, payload)
            raw_payload = payload

    if raw_payload is None:
        month_extra: dict[str, Any] = {}
        if period_key == "month":
            month_extra = {
                "year": month_year,
                "month": month_num,
                "month_label": month_label,
                "month_options": _standouts_month_options(),
            }
        if not _from_background and not force_refresh:
            _schedule_standouts_refresh(period_key, year=month_year, month=month_num)
            return _standouts_building_payload(
                period=period_key,
                position="ALL",
                min_score=STANDOUTS_DEFAULT_MIN_SCORE,
                extra={"positions": _standouts_positions(), **month_extra},
            )
        raw_payload = (
            _build_standouts_month_payload(year=month_year, month=month_num)
            if period_key == "month"
            else _build_standouts_season_payload()
        )
        _standouts_cache[cache_key] = (time.time(), raw_payload)
        from app.home_dashboard import _save_standouts_disk

        _save_standouts_disk(cache_key, raw_payload)

    return raw_payload


def build_who_to_scout_data(
    *,
    period: str = "season",
    year: int | None = None,
    month: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    period_key = "month" if str(period).strip().casefold() in {"month", "monthly", "m"} else "season"
    raw_payload = _load_standouts_raw_payload(
        period=period_key,
        year=year,
        month=month,
        force_refresh=force_refresh,
    )
    if raw_payload.get("building"):
        return {
            **raw_payload,
            "leagues": list(STANDOUTS_LEAGUES),
            "profiles_by_position": _profiles_meta_from_disk(),
            "per_league_limit": STANDOUTS_PER_LEAGUE_LIMIT,
        }

    players = [_who_to_scout_player(row) for row in raw_payload.get("players") or []]
    _attach_scout_coverage(players)
    profiles_by_position = _profiles_from_players(players) or _profiles_meta_from_disk()

    result = {
        **{k: v for k, v in raw_payload.items() if k not in {"players", "player_count", "highest_overall"}},
        "building": False,
        "period": period_key,
        "players": players,
        "player_count": len(players),
        "leagues": list(STANDOUTS_LEAGUES),
        "positions": raw_payload.get("positions") or _standouts_positions(),
        "profiles_by_position": profiles_by_position,
        "per_league_limit": STANDOUTS_PER_LEAGUE_LIMIT,
        "scoring": {
            **(raw_payload.get("scoring") or {}),
            "note": (
                "Overall = weighted profile average (adjust sliders below). "
                f"Top {STANDOUTS_PER_LEAGUE_LIMIT} per league by overall after filters. "
                "Live / Video / Reports from Fixture Planner."
            ),
        },
    }
    if period_key == "month":
        result["month_options"] = _standouts_month_options()
    return result


def who_to_scout_meta() -> dict[str, Any]:
    from app import main as impect
    from app.scouting import _scouting_position_label

    return {
        "positions": [
            {"value": position, "label": _scouting_position_label(position)}
            for position in impect.ALLOWED_POSITIONS
        ],
        "leagues": list(STANDOUTS_LEAGUES),
        "profiles_by_position": _profiles_meta_from_disk(),
        "per_league_limit": STANDOUTS_PER_LEAGUE_LIMIT,
        "default_min_score": STANDOUTS_DEFAULT_MIN_SCORE,
        "default_min_minutes": 0,
    }


def register_who_to_scout_routes(app: FastAPI) -> None:
    page_path = SCOUTING_DIR / "who-to-scout.html"

    @app.get("/who-to-scout", response_class=HTMLResponse)
    def who_to_scout_page() -> HTMLResponse:
        if not page_path.is_file():
            raise RuntimeError(f"Missing page: {page_path}")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/who-to-scout/meta")
    def who_to_scout_meta_route() -> dict[str, Any]:
        return who_to_scout_meta()

    @app.get("/api/who-to-scout/data")
    def who_to_scout_data_route(
        period: str = Query("season"),
        year: int | None = Query(None),
        month: int | None = Query(None, ge=1, le=12),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        period_key = "month" if str(period).strip().casefold() in {"month", "monthly", "m"} else "season"
        if refresh:
            _schedule_standouts_refresh(period_key, year=year, month=month)
        return build_who_to_scout_data(
            period=period_key,
            year=year,
            month=month,
            force_refresh=False,
        )
