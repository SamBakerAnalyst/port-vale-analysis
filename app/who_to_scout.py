"""WHO TO SCOUT — recruitment shortlist by league, position, and profile weights."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
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
from app.scouting import (
    SCOUTING_COMPETITION_TO_LEAGUE,
    SCOUTING_DIR,
    SCOUTING_LEAGUE_TO_COMPETITION,
    POSITION_SHARE_THRESHOLD,
    _format_foot,
    _format_height,
    _impect_profile_score,
    _normalize_profile_key,
    _profile_value_map,
    _profiles_for_position,
    _scouting_iteration_rows,
    _scouting_position_label,
)

_squad_sheet_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SQUAD_SHEET_TTL = 6 * 3600


def _club_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())


def _pick_squad(names: dict[int, str], needle: str) -> tuple[int, str] | None:
    key = _club_key(needle)
    if not key:
        return None
    exact = [(sid, name) for sid, name in names.items() if _club_key(name) == key]
    if exact:
        return exact[0]
    contains = [(sid, name) for sid, name in names.items() if key in _club_key(name)]
    if len(contains) == 1:
        return contains[0]
    return None


def _score_row_to_sheet_player(
    *,
    row: dict[str, Any],
    catalog: dict[str, Any],
    player_id: int,
    iteration_id: int,
    club: str,
    league: str,
    season: str,
    position: str,
) -> dict[str, Any] | None:
    from app import main as impect
    from app.home_dashboard import _overall_from_profile_scores

    values = _profile_value_map(row)
    profile_names = _profiles_for_position(position) if position else []
    profile_scores: dict[str, float | None] = {}
    if profile_names:
        for name in profile_names:
            profile_scores[name] = _impect_profile_score(values.get(_normalize_profile_key(name)))
    if not any(value is not None for value in profile_scores.values()):
        for key, raw in values.items():
            profile_scores[key] = _impect_profile_score(raw)
    if not any(value is not None for value in profile_scores.values()):
        return None
    overall = _overall_from_profile_scores(profile_scores)
    if overall is None:
        return None
    name = impect._extract_player_name(catalog) or f"Player {player_id}"
    return {
        "id": f"{iteration_id}:{player_id}:{position or 'squad'}",
        "playerId": player_id,
        "name": name,
        "age": impect._player_age(catalog),
        "height": _format_height(catalog),
        "foot": _format_foot(catalog.get("leg")),
        "club": club,
        "league": league,
        "season": season,
        "minutes": impect._play_duration_minutes(row),
        "position": position,
        "positionLabel": _scouting_position_label(position) if position else "",
        "overall": overall,
        "profileScores": profile_scores,
    }


def build_club_team_sheet(club_query: str) -> dict[str, Any]:
    from app import main as impect

    needle = str(club_query or "").strip()
    if not needle:
        raise HTTPException(status_code=400, detail="club is required")

    cache_key = _club_key(needle)
    cached = _squad_sheet_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _SQUAD_SHEET_TTL:
        return cached[1]

    competitions: list[str] = []
    hint_league = None
    disk = _load_standouts_disk(_standouts_raw_cache_key("season"))
    if disk:
        for row in disk[1].get("players") or []:
            if _club_key(row.get("club") or "") == cache_key:
                hint_league = str(row.get("league") or "").strip()
                break
    for league in (
        hint_league,
        "League Two",
        "League One",
        "National League",
        *STANDOUTS_LEAGUES,
    ):
        if not league or league not in SCOUTING_LEAGUE_TO_COMPETITION:
            continue
        name = SCOUTING_LEAGUE_TO_COMPETITION[league]
        if name not in competitions:
            competitions.append(name)

    chosen: dict[str, Any] | None = None
    score_rows: list[dict[str, Any]] = []
    for offset in (1, 0):
        for competition in competitions:
            for iteration in _scouting_iteration_rows(
                [competition], season_offset=offset, combine_seasons=False
            ):
                iteration_id = int(iteration["id"])
                try:
                    names = impect._fetch_squad_names(iteration_id)
                except HTTPException:
                    continue
                picked = _pick_squad(names, needle)
                if not picked:
                    continue
                squad_id, club_name = picked
                try:
                    rows, _ = impect._fetch_profile_scores(
                        iteration_id, squad_id, list(impect.ALLOWED_POSITIONS), 0
                    )
                except HTTPException:
                    rows = []
                if not rows:
                    continue
                chosen = {
                    "iteration": iteration,
                    "iteration_id": iteration_id,
                    "squad_id": squad_id,
                    "club_name": club_name,
                }
                score_rows = rows
                break
            if chosen and score_rows:
                break
        if chosen and score_rows:
            break

    if not chosen:
        raise HTTPException(status_code=404, detail=f"No Impect squad matching “{needle}”.")

    iteration = chosen["iteration"]
    iteration_id = int(chosen["iteration_id"])
    club_name = str(chosen["club_name"])
    league = str(iteration.get("competition_name") or "")
    league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(league, league)
    season = str(iteration.get("season") or "")

    catalog_by_id: dict[int, dict[str, Any]] = {}
    try:
        for player in impect._fetch_players_for_iteration(iteration_id):
            pid = player.get("id")
            if pid is not None:
                catalog_by_id[int(pid)] = player
    except HTTPException:
        catalog_by_id = {}

    primary, shares = None, None
    try:
        from app.scouting import PRIMARY_CACHE_VERSION, _primary_cache_path

        path = _primary_cache_path(iteration_id)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("version", 1)) == PRIMARY_CACHE_VERSION:
                primary = {int(pid): str(pos) for pid, pos in (payload.get("primary") or {}).items()}
                shares = {
                    int(pid): {str(pos): float(value) for pos, value in pos_map.items()}
                    for pid, pos_map in (payload.get("shares") or {}).items()
                }
    except Exception:  # noqa: BLE001
        primary, shares = None, None
    players: list[dict[str, Any]] = []
    for row in score_rows:
        try:
            player_id = int(row.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id:
            continue
        catalog = catalog_by_id.get(player_id) or {}
        player_shares = (shares or {}).get(player_id) or {}
        total = sum(player_shares.values()) if player_shares else 0.0
        positions: list[str] = []
        if total > 0:
            positions = [
                pos
                for pos, value in player_shares.items()
                if (value / total) >= POSITION_SHARE_THRESHOLD
            ]
        primary_pos = (primary or {}).get(player_id)
        if primary_pos and primary_pos not in positions:
            positions.insert(0, primary_pos)
        if not positions:
            positions = [""]
        for position in positions:
            sheet = _score_row_to_sheet_player(
                row=row,
                catalog=catalog,
                player_id=player_id,
                iteration_id=iteration_id,
                club=club_name,
                league=league_label,
                season=season,
                position=position,
            )
            if sheet:
                players.append(sheet)

    _attach_scout_coverage(players)
    payload = {
        "club": club_name,
        "league": league_label,
        "season": season,
        "player_count": len({row.get("playerId") for row in players}),
        "players": players,
    }
    _squad_sheet_cache[cache_key] = (now, payload)
    return payload


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

    @app.get("/api/who-to-scout/loans")
    def who_to_scout_loans_route(
        club: list[str] = Query(default_factory=list),
        season: str | None = Query(None),
    ) -> dict[str, Any]:
        from app.opponent_photos import transfermarkt_loan_ins

        clubs = [str(name).strip() for name in club if str(name).strip()]
        by_club: dict[str, list[dict[str, str]]] = {}
        for name in clubs:
            loans = transfermarkt_loan_ins(name, season=season)
            by_club[name] = [
                {"name": row["name"], "from": row["on_loan_from"]}
                for row in loans.values()
            ]
        return {"clubs": by_club}

    @app.get("/api/who-to-scout/squad")
    def who_to_scout_squad_route(club: str = Query(...)) -> dict[str, Any]:
        return build_club_team_sheet(club)
