"""Scoutable Teams — league → club Monday boards linked to Player Pipelines."""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.home_dashboard import STANDOUTS_LEAGUES, _overall_from_profile_scores
from app.label_utils import humanize_profile_name
from app.opponent_photos import opponent_photo_api_url
from app.paths import STANDALONE_DIR
from app.player_pipelines import (
    POSITIONS,
    STAGES,
    pipeline_index_by_player_id,
    remove_pipeline_by_player_id,
    upsert_pipeline_from_scout,
)
from app.scouting import (
    POSITION_SHARE_THRESHOLD,
    SCOUTING_COMPETITION_TO_LEAGUE,
    SCOUTING_LEAGUE_TO_COMPETITION,
    _ensure_position_shares,
    _format_foot,
    _format_height,
    _impect_profile_score,
    _normalize_profile_key,
    _profile_value_map,
    _profiles_for_position,
    _scouting_iteration_rows,
    _scouting_position_label,
)

from app.season_defaults import CURRENT_SEASON

_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SQUAD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_BOARD_TTL = 30 * 60
_SQUAD_TTL = 6 * 3600
_MIN_MINUTES = 90.0
_CACHE_VERSION = 3  # bump: force 26/27 boards after season switch

LEAGUE_COLORS: dict[str, str] = {
    "League One": "#3d8bfd",
    "League Two": "#22c55e",
    "National League": "#a78bfa",
    "Scottish Prem": "#f59e0b",
    "PL2": "#06b6d4",
    "Irish Prem": "#f472b6",
}

POSITION_ORDER = [code for code, _ in POSITIONS]
POSITION_SHORT = {code: short for code, short in POSITIONS}


class SetStatusBody(BaseModel):
    player_id: int
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    # Empty / "none" = not on Player Pipelines.
    stage: str = ""
    reason: str = ""


def _club_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())


def _photo_url(name: str, club: str = "") -> str:
    url = opponent_photo_api_url(name, club_name=club or None)
    if url:
        return url
    from urllib.parse import quote

    if name:
        return f"/api/pre-match/player-photo?name={quote(name)}"
    return ""


def _pick_iteration_for_competition(competition: str) -> dict[str, Any] | None:
    from app import main as impect

    with_squads: list[tuple[dict[str, Any], dict[int, str]]] = []
    for offset in (0, 1, 2):
        rows = _scouting_iteration_rows(
            [competition], season_offset=offset, combine_seasons=False
        )
        if not rows:
            continue
        iteration = rows[0]
        try:
            names = impect._fetch_squad_names(int(iteration["id"]))
        except HTTPException:
            continue
        if names:
            with_squads.append((iteration, names))

    if not with_squads:
        return None
    for iteration, names in with_squads:
        if str(iteration.get("season") or "").strip() == CURRENT_SEASON:
            return {"iteration": iteration, "squads": names}
    iteration, names = with_squads[0]
    return {"iteration": iteration, "squads": names}


def build_leagues_board() -> dict[str, Any]:
    cache_key = f"board:v{_CACHE_VERSION}"
    cached = _BOARD_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _BOARD_TTL:
        payload = dict(cached[1])
        return _attach_pipeline_counts(payload)

    leagues: list[dict[str, Any]] = []
    for league in STANDOUTS_LEAGUES:
        competition = SCOUTING_LEAGUE_TO_COMPETITION.get(league)
        if not competition:
            continue
        picked = _pick_iteration_for_competition(competition)
        if not picked:
            leagues.append(
                {
                    "id": league,
                    "title": league,
                    "color": LEAGUE_COLORS.get(league, "#3d8bfd"),
                    "season": "",
                    "clubs": [],
                }
            )
            continue
        iteration = picked["iteration"]
        clubs = [
            {
                "id": int(squad_id),
                "name": name,
                "iteration_id": int(iteration["id"]),
                "league": league,
            }
            for squad_id, name in sorted(
                picked["squads"].items(), key=lambda item: str(item[1]).casefold()
            )
        ]
        leagues.append(
            {
                "id": league,
                "title": league,
                "color": LEAGUE_COLORS.get(league, "#3d8bfd"),
                "season": str(iteration.get("season") or ""),
                "clubs": clubs,
            }
        )

    payload = {
        "stages": list(STAGES),
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "leagues": leagues,
    }
    _BOARD_CACHE[cache_key] = (now, payload)
    return _attach_pipeline_counts(dict(payload))


def _attach_pipeline_counts(payload: dict[str, Any]) -> dict[str, Any]:
    index = pipeline_index_by_player_id()
    # Counts by club name from pipeline targets — approximate for overview badges.
    by_club: dict[str, int] = {}
    for target in index.values():
        key = _club_key(target.get("club") or "")
        if key:
            by_club[key] = by_club.get(key, 0) + 1
    for league in payload.get("leagues") or []:
        for club in league.get("clubs") or []:
            club["pipeline_count"] = by_club.get(_club_key(club.get("name") or ""), 0)
    return payload


def _score_row_to_player(
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

    values = _profile_value_map(row)
    profile_names = _profiles_for_position(position) if position else []
    profile_scores: dict[str, float | None] = {}
    if profile_names:
        for name in profile_names:
            profile_scores[name] = _impect_profile_score(
                values.get(_normalize_profile_key(name))
            )
    if not any(value is not None for value in profile_scores.values()):
        for key, raw in values.items():
            profile_scores[key] = _impect_profile_score(raw)
    if not any(value is not None for value in profile_scores.values()):
        return None
    overall = _overall_from_profile_scores(profile_scores)
    if overall is None:
        return None
    name = impect._extract_player_name(catalog) or f"Player {player_id}"
    top_profile = ""
    top_score = None
    scored = {k: float(v) for k, v in profile_scores.items() if v is not None}
    if scored:
        top_api = max(scored, key=scored.get)
        top_profile = humanize_profile_name(top_api)
        top_score = round(scored[top_api])
    return {
        "player_id": player_id,
        "name": name,
        "age": impect._player_age(catalog),
        "height": _format_height(catalog),
        "foot": _format_foot(catalog.get("leg")),
        "club": club,
        "league": league,
        "season": season,
        "minutes": int(round(float(impect._play_duration_minutes(row) or 0))),
        "position": position,
        "position_label": POSITION_SHORT.get(position) or _scouting_position_label(position),
        "overall": round(float(overall)),
        "top_profile": top_profile,
        "top_profile_score": top_score,
        "profile_scores": {
            name: (round(float(value)) if value is not None else None)
            for name, value in profile_scores.items()
        },
        "photo_url": _photo_url(name, club),
        "dossier_href": f"/player/{player_id}",
        "iteration_id": iteration_id,
    }


def build_club_board(
    *,
    club: str | None = None,
    squad_id: int | None = None,
    iteration_id: int | None = None,
    league: str | None = None,
) -> dict[str, Any]:
    from app import main as impect

    needle = str(club or "").strip()
    cache_key = (
        f"squad:v{_CACHE_VERSION}:"
        f"{iteration_id or 0}:{squad_id or 0}:{_club_key(needle)}:{league or ''}"
    )
    cached = _SQUAD_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _SQUAD_TTL:
        return _attach_player_pipeline_status(dict(cached[1]))

    chosen: dict[str, Any] | None = None
    score_rows: list[dict[str, Any]] = []

    def _try_club_on_offset(offset: int, competitions: list[str]) -> bool:
        nonlocal chosen, score_rows
        for competition in competitions:
            for iteration in _scouting_iteration_rows(
                [competition], season_offset=offset, combine_seasons=False
            ):
                iid = int(iteration["id"])
                try:
                    names = impect._fetch_squad_names(iid)
                except HTTPException:
                    continue
                match = None
                for sid, squad_name in names.items():
                    if _club_key(squad_name) == _club_key(needle):
                        match = (int(sid), squad_name)
                        break
                if not match:
                    continue
                sid, club_name = match
                try:
                    rows, _ = impect._fetch_profile_scores(
                        iid, sid, list(impect.ALLOWED_POSITIONS), 0
                    )
                except HTTPException:
                    rows = []
                # Current season wins even with empty profile scores — do not
                # silently fall back to last season's full minutes.
                chosen = {
                    "iteration": iteration,
                    "iteration_id": iid,
                    "squad_id": sid,
                    "club_name": club_name,
                }
                score_rows = rows or []
                return True
        return False

    if iteration_id and squad_id:
        try:
            names = impect._fetch_squad_names(int(iteration_id))
            club_name = names.get(int(squad_id), needle or f"Squad {squad_id}")
            rows, _ = impect._fetch_profile_scores(
                int(iteration_id), int(squad_id), list(impect.ALLOWED_POSITIONS), 0
            )
            meta = next(
                (
                    item
                    for item in impect._fetch_iterations()
                    if int(item.get("id") or 0) == int(iteration_id)
                ),
                {},
            )
            chosen = {
                "iteration": meta,
                "iteration_id": int(iteration_id),
                "squad_id": int(squad_id),
                "club_name": club_name,
            }
            score_rows = rows or []
            # If the board still pointed at last season, upgrade to 26/27.
            if str(meta.get("season") or "").strip() != CURRENT_SEASON and needle:
                competitions: list[str] = []
                if league and league in SCOUTING_LEAGUE_TO_COMPETITION:
                    competitions.append(SCOUTING_LEAGUE_TO_COMPETITION[league])
                for name in STANDOUTS_LEAGUES:
                    competition = SCOUTING_LEAGUE_TO_COMPETITION.get(name)
                    if competition and competition not in competitions:
                        competitions.append(competition)
                _try_club_on_offset(0, competitions)
        except HTTPException:
            chosen = None

    if chosen is None:
        if not needle:
            raise HTTPException(status_code=400, detail="club or squad_id is required")
        competitions = []
        if league and league in SCOUTING_LEAGUE_TO_COMPETITION:
            competitions.append(SCOUTING_LEAGUE_TO_COMPETITION[league])
        for name in STANDOUTS_LEAGUES:
            competition = SCOUTING_LEAGUE_TO_COMPETITION.get(name)
            if competition and competition not in competitions:
                competitions.append(competition)
        # Current season first; only then previous — and only if club missing now.
        if not _try_club_on_offset(0, competitions):
            _try_club_on_offset(1, competitions)

    if not chosen:
        raise HTTPException(
            status_code=404,
            detail=f"No Impect squad matching “{needle or squad_id}”.",
        )

    iteration = chosen["iteration"]
    iid = int(chosen["iteration_id"])
    club_name = str(chosen["club_name"])
    competition = str(iteration.get("competition_name") or "")
    league_label = SCOUTING_COMPETITION_TO_LEAGUE.get(competition, competition) or (
        league or ""
    )
    season = str(iteration.get("season") or "")

    catalog_by_id: dict[int, dict[str, Any]] = {}
    try:
        for player in impect._fetch_players_for_iteration(iid):
            pid = player.get("id")
            if pid is not None:
                catalog_by_id[int(pid)] = player
    except HTTPException:
        catalog_by_id = {}

    try:
        primary, shares = _ensure_position_shares(iid)
    except Exception:  # noqa: BLE001
        primary, shares = None, None
    primary = primary or {}
    shares = shares or {}

    players: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in score_rows:
        try:
            player_id = int(row.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if not player_id or player_id in seen:
            continue
        catalog = catalog_by_id.get(player_id) or {}
        player_shares = shares.get(player_id) or {}
        total = sum(player_shares.values()) if player_shares else 0.0
        positions: list[str] = []
        if total > 0:
            ranked = sorted(
                player_shares.items(), key=lambda item: item[1], reverse=True
            )
            positions = [
                pos
                for pos, value in ranked
                if (value / total) >= POSITION_SHARE_THRESHOLD
            ]
        primary_pos = primary.get(player_id)
        if primary_pos:
            if primary_pos in positions:
                positions = [primary_pos] + [p for p in positions if p != primary_pos]
            else:
                positions.insert(0, primary_pos)
        position = positions[0] if positions else ""
        sheet = _score_row_to_player(
            row=row,
            catalog=catalog,
            player_id=player_id,
            iteration_id=iid,
            club=club_name,
            league=league_label,
            season=season,
            position=position,
        )
        if not sheet:
            continue
        if float(sheet.get("minutes") or 0) < (
            0.0 if season == CURRENT_SEASON else _MIN_MINUTES
        ):
            continue
        seen.add(player_id)
        players.append(sheet)

    players.sort(
        key=lambda row: (
            POSITION_ORDER.index(row["position"])
            if row.get("position") in POSITION_ORDER
            else 99,
            -(row.get("overall") or 0),
            str(row.get("name") or "").casefold(),
        )
    )

    profiles_by_position: dict[str, list[dict[str, str]]] = {}
    for code, _short in POSITIONS:
        try:
            names = _profiles_for_position(code) or []
        except Exception:  # noqa: BLE001
            names = []
        profiles_by_position[code] = [
            {"apiName": name, "label": humanize_profile_name(name)} for name in names
        ]

    payload = {
        "club": club_name,
        "league": league_label,
        "season": season,
        "iteration_id": iid,
        "squad_id": int(chosen["squad_id"]),
        "player_count": len(players),
        "stages": list(STAGES),
        "positions": [{"id": code, "label": short} for code, short in POSITIONS],
        "profiles_by_position": profiles_by_position,
        "players": players,
    }
    _SQUAD_CACHE[cache_key] = (now, payload)
    return _attach_player_pipeline_status(dict(payload))


def _attach_player_pipeline_status(payload: dict[str, Any]) -> dict[str, Any]:
    index = pipeline_index_by_player_id()
    for player in payload.get("players") or []:
        target = index.get(int(player.get("player_id") or 0))
        if target:
            player["in_pipeline"] = True
            player["pipeline_stage"] = target.get("stage")
            player["pipeline_stage_title"] = next(
                (
                    stage["title"]
                    for stage in STAGES
                    if stage["id"] == target.get("stage")
                ),
                target.get("stage"),
            )
            player["pipeline_stage_color"] = next(
                (
                    stage["color"]
                    for stage in STAGES
                    if stage["id"] == target.get("stage")
                ),
                "#3d8bfd",
            )
            player["pipeline_target_id"] = target.get("id")
        else:
            player["in_pipeline"] = False
            player["pipeline_stage"] = ""
            player["pipeline_stage_title"] = ""
            player["pipeline_stage_color"] = ""
            player["pipeline_target_id"] = ""
    return payload


def register_scoutable_teams_routes(app: FastAPI) -> None:
    @app.get("/scoutable-teams", response_class=HTMLResponse)
    def scoutable_teams_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "scoutable-teams.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Scoutable Teams UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/scoutable-teams")
    def scoutable_teams_board() -> dict[str, Any]:
        return build_leagues_board()

    @app.get("/api/scoutable-teams/club")
    def scoutable_teams_club(
        club: str | None = Query(None),
        squad_id: int | None = Query(None),
        iteration_id: int | None = Query(None),
        league: str | None = Query(None),
    ) -> dict[str, Any]:
        return build_club_board(
            club=club,
            squad_id=squad_id,
            iteration_id=iteration_id,
            league=league,
        )

    @app.post("/api/scoutable-teams/set-status")
    def scoutable_teams_set_status(
        request: Request, body: SetStatusBody
    ) -> dict[str, Any]:
        stage = str(body.stage or "").strip().lower()
        if stage in ("", "none", "not_in_pipeline", "not-in-pipeline"):
            removed = remove_pipeline_by_player_id(int(body.player_id))
            return {
                "created": False,
                "moved": False,
                "removed": bool(removed.get("removed")),
                "target": None,
            }
        result = upsert_pipeline_from_scout(
            request,
            player_id=body.player_id,
            name=body.name,
            club=body.club,
            league=body.league,
            position=body.position,
            position_label=body.position_label,
            age=body.age,
            stage=body.stage,
            reason=body.reason,
        )
        result["removed"] = False
        return result
