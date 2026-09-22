"""Player Reports — watch a fixture with both team sheets and a shared player file.

Notes written here land on Scoutable Teams, Who to Scout, and the player page.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.auth import current_user_payload
from app.fixture_planner import DEFAULT_SEASON
from app.games_to_watch import (
    build_fixture_sheet,
    cached_games_to_watch_payload,
)
from app.label_utils import humanize_profile_name
from app.opponent_photos import (
    opponent_photo_api_url,
    squad_entry_for_player,
    squad_meta_for_club,
)
from app.paths import STANDALONE_DIR
from app.pre_match import assign_lineup_formation_slots
from app.player_dossier import (
    PlayerNoteCreate,
    _notes_for_player,
    _normalize_entry_kind,
    create_player_note,
)
from app.player_pipelines import STAGES, pipeline_index_by_player_id, upsert_pipeline_from_scout
from app.player_reports import (
    DetailedReportBody,
    GeneralReportBody,
    MatchConditionsBody,
    PlayerCmsBody,
    match_conditions_for_fixture,
    report_file_for_player,
    save_cms,
    save_detailed_report,
    save_general_report,
    save_match_conditions,
)
from app.scoutable_teams import (
    attach_scout_notes_to_players,
    save_scout_notes,
    scout_notes_for_player,
)


class VideoWatchNoteBody(BaseModel):
    player_id: int
    kind: str = "comment"
    text: str = ""
    title: str = ""
    match_minute: int | None = None
    fixture_id: str = ""
    fixture_label: str = ""
    name: str = ""
    club: str = ""
    league: str = ""
    position: str = ""
    position_label: str = ""
    age: int | None = None
    current_ability: float | None = None
    potential_ability: float | None = None
    scout_scores: dict[str, int | None] = Field(default_factory=dict)


def _staff_name(request: Request) -> str:
    payload = current_user_payload(request)
    return str(payload.get("display_name") or payload.get("username") or "Staff").strip() or "Staff"


POSITION_SHORT = {
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
    "Goalkeeper": "GK",
    "Left back": "LB",
    "Right back": "RB",
    "Left wing-back": "LB",
    "Right wing-back": "RB",
    "Centre-back": "CB",
    "Defensive midfield": "DM",
    "Central midfield": "CM",
    "Attacking midfield": "AM",
    "Left winger": "LW",
    "Right winger": "RW",
    "Centre-forward": "CF",
}


def _position_short(player: dict[str, Any]) -> str:
    for key in (player.get("position_short"), player.get("position"), player.get("position_label")):
        short = POSITION_SHORT.get(str(key or "").strip())
        if short:
            return short
    label = str(player.get("position_label") or player.get("position") or "").strip()
    if not label:
        return ""
    parts = [part[0] for part in label.replace("-", " ").split() if part]
    return "".join(parts)[:3].upper()


def _photo_url(name: str, club: str = "", shirt: str | int | None = None) -> str:
    url = opponent_photo_api_url(name, club_name=club or None, shirt_number=shirt)
    if url:
        return url
    from urllib.parse import quote

    if name:
        params = [f"name={quote(name)}"]
        if club:
            params.append(f"club={quote(club)}")
        if shirt is not None and str(shirt).strip() != "":
            params.append(f"shirt={quote(str(shirt))}")
        return "/api/pre-match/player-photo?" + "&".join(params)
    return ""


def _attach_squad_shirts(players: list[dict[str, Any]], club: str) -> None:
    if not club or not players:
        return
    try:
        entries = squad_meta_for_club(club)
    except Exception:
        return
    if not entries:
        return
    for player in players:
        if player.get("shirt_number") not in (None, ""):
            continue
        entry = squad_entry_for_player(str(player.get("name") or ""), entries)
        if entry and entry.get("shirt_number"):
            player["shirt_number"] = entry["shirt_number"]


def _profile_rows(player: dict[str, Any]) -> list[dict[str, Any]]:
    scores = player.get("profile_scores") or player.get("profileScores") or {}
    if not isinstance(scores, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, value in scores.items():
        if value is None or value == "":
            continue
        try:
            score = round(float(value))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "key": str(key),
                "label": humanize_profile_name(str(key)),
                "score": score,
            }
        )
    rows.sort(key=lambda row: (-int(row["score"]), str(row["label"]).casefold()))
    return rows


WATCH_FORMATIONS = ("4-3-3", "4-2-3-1", "4-4-2", "5-3-2")


def infer_watch_formation(players: list[dict[str, Any]]) -> str:
    ranked = sorted(
        players,
        key=lambda row: (
            -float(row.get("minutes") or 0),
            -float(row.get("overall") or 0),
        ),
    )[:14]
    shorts = [_position_short(row) for row in ranked]
    cbs = shorts.count("CB")
    cfs = sum(1 for short in shorts if short in {"CF", "ST"})
    wingers = shorts.count("LW") + shorts.count("RW")
    if cbs >= 3:
        return "5-3-2"
    if shorts.count("AM") >= 1 and shorts.count("DM") >= 2:
        return "4-2-3-1"
    if cfs >= 2 and wingers >= 2:
        return "4-4-2"
    return "4-3-3"


def _players_with_ids(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player in players:
        try:
            player_id = int(player.get("player_id"))
        except (TypeError, ValueError):
            continue
        rows.append({**player, "player_id": player_id})
    return rows


def attach_watch_formation(
    team: dict[str, Any],
    formation: str | None = None,
) -> dict[str, Any]:
    players = _players_with_ids(list(team.get("players") or []))
    starters = [row for row in players if row.get("started")]
    subs = [row for row in players if row.get("subbed_on")]
    if starters or subs:
        key = str(formation or team.get("formation") or infer_watch_formation(starters)).strip()
        team["formation"] = key or infer_watch_formation(starters)
        team["formations"] = list(WATCH_FORMATIONS)
        team["xi"] = starters
        team["bench"] = subs
        team["lineup_source"] = "match"
        return team
    key = str(formation or team.get("formation") or infer_watch_formation(players)).strip()
    if key not in WATCH_FORMATIONS:
        key = infer_watch_formation(players)
    xi = assign_lineup_formation_slots(players, key)[:11] if players else []
    used = {int(row["player_id"]) for row in xi if row.get("player_id") is not None}
    bench = [row for row in players if int(row["player_id"]) not in used]
    team["formation"] = key
    team["formations"] = list(WATCH_FORMATIONS)
    team["xi"] = xi
    team["bench"] = bench
    return team


def _decorate_sheet_player(player: dict[str, Any], *, club: str = "") -> dict[str, Any]:
    name = str(player.get("name") or "")
    club_name = str(player.get("club") or club or "")
    player["position_short"] = _position_short(player)
    shirt = player.get("shirt_number")
    player["photo_url"] = player.get("photo_url") or _photo_url(name, club_name, shirt)
    player["profiles"] = _profile_rows(player)
    if not player.get("dossier_href") and player.get("player_id"):
        player["dossier_href"] = f"/player/{int(player['player_id'])}"
    return player


def _decorate_fixture_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    for side in ("home", "away"):
        team = sheet.get(side) if isinstance(sheet.get(side), dict) else {}
        club = str(team.get("name") or "")
        players = list(team.get("players") or [])
        attach_scout_notes_to_players(players)
        _attach_squad_shirts(players, club)
        decorated_players = []
        for row in players:
            player = _decorate_sheet_player(row, club=club)
            player["sheet_side"] = side
            decorated_players.append(player)
        decorated = {
            **team,
            "players": decorated_players,
        }
        sheet[side] = attach_watch_formation(decorated)
    fixture_id = str(sheet.get("fixture_id") or "")
    home_name = str((sheet.get("home") or {}).get("name") or "")
    away_name = str((sheet.get("away") or {}).get("name") or "")
    label = f"{home_name} vs {away_name}" if home_name or away_name else ""
    sheet["match_conditions"] = match_conditions_for_fixture(
        fixture_id, fixture_label=label
    )
    return sheet


def _pipeline_for_player(player_id: int) -> dict[str, Any] | None:
    target = pipeline_index_by_player_id().get(int(player_id))
    if not target:
        return None
    stage = str(target.get("stage") or "")
    meta = next((row for row in STAGES if row["id"] == stage), None)
    return {
        "id": target.get("id") or "",
        "stage": stage,
        "stage_title": (meta or {}).get("title") or stage,
        "stage_color": (meta or {}).get("color") or "#eab308",
    }


def _real_activity(player_id: int, name: str) -> dict[str, Any]:
    rows = [row for row in _notes_for_player(player_id) if not row.get("example")]
    notes = [row for row in rows if _normalize_entry_kind(row.get("kind")) == "note"]
    reports = [row for row in rows if _normalize_entry_kind(row.get("kind")) != "note"]
    return {
        "notes": notes,
        "reports": reports,
        "ability": None,
    }


def build_watch_player(
    *,
    player_id: int,
    sheet_player: dict[str, Any] | None = None,
    fixture_id: str = "",
    fixture_label: str = "",
    home_name: str = "",
    away_name: str = "",
    sheet_side: str = "",
) -> dict[str, Any]:
    base = dict(sheet_player or {})
    name = str(base.get("name") or f"Player {player_id}")
    club = str(base.get("club") or base.get("team_name") or "")
    _decorate_sheet_player(base, club=club)
    shared = scout_notes_for_player(player_id)
    activity = _real_activity(player_id, name)
    pipeline = _pipeline_for_player(player_id)
    report_file = report_file_for_player(
        player_id=int(player_id),
        club=club,
        name=name,
        fixture_id=fixture_id,
        fixture_label=fixture_label,
        home_name=home_name,
        away_name=away_name,
        sheet_side=sheet_side or str(base.get("sheet_side") or ""),
        position=str(base.get("position") or ""),
        player_profiles=list(base.get("profiles") or []),
    )
    return {
        **base,
        "player_id": int(player_id),
        "name": name,
        "club": club,
        "photo_url": base.get("photo_url") or _photo_url(name, club),
        "scout_comment": shared.get("scout_comment") or "",
        "scout_scores": shared.get("scout_scores") or {},
        "has_scout_note": bool(shared.get("scout_comment")),
        "notes": activity["notes"],
        "reports": activity["reports"],
        "ability": activity.get("ability"),
        "pipeline": pipeline,
        "dossier_href": f"/player/{int(player_id)}",
        "scoutable_href": f"/scoutable-teams?club={club}" if club else "/scoutable-teams",
        "who_to_scout_href": "/who-to-scout",
        **report_file,
    }


def _note_title(*, kind: str, title: str, fixture_label: str, match_minute: int | None) -> str:
    cleaned = str(title or "").strip()
    if cleaned:
        return cleaned
    parts = ["Video"]
    if fixture_label:
        parts.append(fixture_label)
    if match_minute is not None:
        parts.append(f"{int(match_minute)}'")
    if kind == "report":
        parts[0] = "Video report"
    return " · ".join(parts)


def save_video_watch_entry(
    *,
    player_id: int,
    kind: str,
    text: str,
    title: str = "",
    match_minute: int | None = None,
    fixture_label: str = "",
    staff: str = "Staff",
    name: str = "",
    club: str = "",
    league: str = "",
    position: str = "",
    position_label: str = "",
    age: int | None = None,
    current_ability: float | None = None,
    potential_ability: float | None = None,
    scout_scores: dict[str, int | None] | None = None,
    fixture_id: str = "",
    home_name: str = "",
    away_name: str = "",
    sheet_side: str = "",
) -> dict[str, Any]:
    if not player_id:
        raise HTTPException(status_code=400, detail="player_id is required")
    summary = str(text or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Add a comment, note, or report first.")

    entry_kind = str(kind or "comment").strip().casefold()
    if entry_kind not in {"comment", "note", "report"}:
        entry_kind = "comment"
    dossier_kind = "report" if entry_kind == "report" else "note"
    existing = scout_notes_for_player(player_id)
    shared = save_scout_notes(
        player_id=player_id,
        scout_scores=scout_scores if scout_scores is not None else existing.get("scout_scores"),
        scout_comment=summary,
        staff=staff,
    )
    note = create_player_note(
        player_id,
        PlayerNoteCreate(
            kind=dossier_kind,
            summary=summary,
            title=_note_title(
                kind=entry_kind,
                title=title,
                fixture_label=fixture_label,
                match_minute=match_minute,
            ),
            staff=staff,
            position=position_label or position,
            current_ability=current_ability if dossier_kind == "report" else None,
            potential_ability=potential_ability if dossier_kind == "report" else None,
        ),
        player_name=name,
    )
    player = build_watch_player(
        player_id=player_id,
        sheet_player={
            "name": name,
            "club": club,
            "league": league,
            "position": position,
            "position_label": position_label,
            "age": age,
            "sheet_side": sheet_side,
        },
        fixture_id=fixture_id,
        fixture_label=fixture_label,
        home_name=home_name,
        away_name=away_name,
        sheet_side=sheet_side,
    )
    return {
        "ok": True,
        "player_id": int(player_id),
        "scout_comment": shared.get("scout_comment") or "",
        "scout_scores": shared.get("scout_scores") or {},
        "note": note,
        "player": player,
    }


def register_video_watch_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "video-watch.html"

    @app.get("/player-reports", response_class=HTMLResponse)
    def player_reports_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="Player Reports UI not found.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/video-watch")
    def video_watch_legacy(request: Request) -> RedirectResponse:
        dest = "/player-reports"
        if request.url.query:
            dest = f"{dest}?{request.url.query}"
        return RedirectResponse(url=dest, status_code=307)

    @app.get("/api/video-watch/games")
    def video_watch_games(season: str = Query(DEFAULT_SEASON)) -> dict[str, Any]:
        return cached_games_to_watch_payload(season=season)

    @app.get("/api/video-watch/fixture")
    def video_watch_fixture(
        fixture_id: str = Query(...),
        season: str = Query(DEFAULT_SEASON),
    ) -> dict[str, Any]:
        return _decorate_fixture_sheet(
            build_fixture_sheet(season=season, fixture_id=fixture_id)
        )

    @app.get("/api/video-watch/player")
    def video_watch_player(
        player_id: int = Query(...),
        name: str | None = Query(None),
        club: str | None = Query(None),
        league: str | None = Query(None),
        position: str | None = Query(None),
        position_label: str | None = Query(None),
        age: int | None = Query(None),
        fixture_id: str | None = Query(None),
        fixture_label: str | None = Query(None),
        home_name: str | None = Query(None),
        away_name: str | None = Query(None),
        sheet_side: str | None = Query(None),
    ) -> dict[str, Any]:
        if not player_id:
            raise HTTPException(status_code=400, detail="player_id is required")
        sheet_player = {
            "name": name or "",
            "club": club or "",
            "league": league or "",
            "position": position or "",
            "position_label": position_label or "",
            "age": age,
            "sheet_side": sheet_side or "",
        }
        return {
            "player": build_watch_player(
                player_id=player_id,
                sheet_player=sheet_player,
                fixture_id=fixture_id or "",
                fixture_label=fixture_label or "",
                home_name=home_name or "",
                away_name=away_name or "",
                sheet_side=sheet_side or "",
            )
        }

    @app.post("/api/video-watch/notes")
    def video_watch_save_note(request: Request, body: VideoWatchNoteBody) -> dict[str, Any]:
        return save_video_watch_entry(
            player_id=body.player_id,
            kind=body.kind,
            text=body.text,
            title=body.title,
            match_minute=body.match_minute,
            fixture_label=body.fixture_label,
            staff=_staff_name(request),
            name=body.name,
            club=body.club,
            league=body.league,
            position=body.position,
            position_label=body.position_label,
            age=body.age,
            current_ability=body.current_ability,
            potential_ability=body.potential_ability,
            scout_scores=body.scout_scores,
            fixture_id=body.fixture_id,
        )

    def _player_after_report_save(
        *,
        player_id: int,
        name: str = "",
        club: str = "",
        fixture_id: str = "",
        fixture_label: str = "",
        home_name: str = "",
        away_name: str = "",
        sheet_side: str = "",
        position: str = "",
        position_label: str = "",
    ) -> dict[str, Any]:
        return build_watch_player(
            player_id=player_id,
            sheet_player={
                "name": name,
                "club": club,
                "sheet_side": sheet_side,
                "position": position,
                "position_label": position_label,
            },
            fixture_id=fixture_id,
            fixture_label=fixture_label,
            home_name=home_name,
            away_name=away_name,
            sheet_side=sheet_side,
        )

    @app.post("/api/video-watch/match-conditions")
    def video_watch_save_match_conditions(
        request: Request, body: MatchConditionsBody
    ) -> dict[str, Any]:
        conditions = save_match_conditions(
            fixture_id=body.fixture_id,
            fixture_label=body.fixture_label,
            weather=body.weather,
            weather_note=body.weather_note,
            pitch=body.pitch,
            pitch_note=body.pitch_note,
            staff=_staff_name(request),
        )
        return {"ok": True, "match_conditions": conditions}

    @app.post("/api/video-watch/general-report")
    def video_watch_save_general_report(
        request: Request, body: GeneralReportBody
    ) -> dict[str, Any]:
        staff = _staff_name(request)
        conditions = save_match_conditions(
            fixture_id=body.fixture_id,
            fixture_label=body.fixture_label,
            weather=body.weather,
            weather_note=body.weather_note,
            pitch=body.pitch,
            pitch_note=body.pitch_note,
            staff=staff,
        )
        general = save_general_report(
            player_id=body.player_id,
            fixture_id=body.fixture_id,
            notes=body.notes,
            position_in_game=body.position_in_game,
            physical=body.physical,
            profiles=body.profiles,
            next_steps=body.next_steps,
            match_rating=body.match_rating,
            pvfc_level=body.pvfc_level,
            add_to_pipeline=body.add_to_pipeline,
            pipeline_stage=body.pipeline_stage,
            next_action=body.next_action,
            name=body.name,
            club=body.club,
            league=body.league,
            fixture_label=body.fixture_label,
            position=body.position or body.position_in_game,
            position_label=body.position_label,
            age=body.age,
            staff=staff,
        )
        pipeline = None
        pipeline_error = ""
        if body.add_to_pipeline or general.get("add_to_pipeline"):
            stage = general.get("pipeline_stage") or "video_scouted"
            reason = (
                general.get("next_steps")
                or general.get("notes")
                or "Not to standard off this look."
            )
            try:
                pipeline = upsert_pipeline_from_scout(
                    request,
                    player_id=body.player_id,
                    name=body.name,
                    club=body.club,
                    league=body.league,
                    position=body.position_in_game or body.position,
                    position_label=body.position_label,
                    age=body.age,
                    stage=stage,
                    reason=reason,
                )
            except HTTPException as exc:
                pipeline_error = str(exc.detail or "Could not add to pipeline.")
        player = _player_after_report_save(
            player_id=body.player_id,
            name=body.name,
            club=body.club,
            fixture_id=body.fixture_id,
            fixture_label=body.fixture_label,
            home_name=body.home_name,
            away_name=body.away_name,
            sheet_side=body.sheet_side,
            position=body.position_in_game or body.position,
            position_label=body.position_label,
        )
        return {
            "ok": True,
            "match_conditions": conditions,
            "general_report": general,
            "pipeline": pipeline,
            "pipeline_error": pipeline_error,
            "player": player,
        }

    @app.post("/api/video-watch/detailed-report")
    def video_watch_save_detailed_report(
        request: Request, body: DetailedReportBody
    ) -> dict[str, Any]:
        staff = _staff_name(request)
        detailed = save_detailed_report(
            player_id=body.player_id,
            fixture_id=body.fixture_id,
            position_in_game=body.position_in_game,
            physical=body.physical,
            profiles=body.profiles,
            psychology=body.psychology,
            write_up=body.write_up,
            next_steps=body.next_steps,
            match_rating=body.match_rating,
            pvfc_level=body.pvfc_level,
            add_to_pipeline=body.add_to_pipeline,
            pipeline_stage=body.pipeline_stage,
            next_action=body.next_action,
            name=body.name,
            club=body.club,
            league=body.league,
            fixture_label=body.fixture_label,
            position=body.position or body.position_in_game,
            position_label=body.position_label,
            age=body.age,
            staff=staff,
        )
        pipeline = None
        pipeline_error = ""
        if body.add_to_pipeline:
            stage = detailed.get("pipeline_stage") or "video_scouted"
            reason = (
                detailed.get("write_up")
                or detailed.get("next_steps")
                or "Not to standard off this look."
            )
            try:
                pipeline = upsert_pipeline_from_scout(
                    request,
                    player_id=body.player_id,
                    name=body.name,
                    club=body.club,
                    league=body.league,
                    position=body.position_in_game or body.position,
                    position_label=body.position_label,
                    age=body.age,
                    stage=stage,
                    reason=reason,
                )
            except HTTPException as exc:
                pipeline_error = str(exc.detail or "Could not add to pipeline.")
        player = _player_after_report_save(
            player_id=body.player_id,
            name=body.name,
            club=body.club,
            fixture_id=body.fixture_id,
            fixture_label=body.fixture_label,
            home_name=body.home_name,
            away_name=body.away_name,
            sheet_side=body.sheet_side,
            position=body.position_in_game or body.position,
            position_label=body.position_label,
        )
        return {
            "ok": True,
            "detailed_report": detailed,
            "pipeline": pipeline,
            "pipeline_error": pipeline_error,
            "player": player,
        }

    @app.post("/api/video-watch/cms")
    def video_watch_save_cms(request: Request, body: PlayerCmsBody) -> dict[str, Any]:
        cms = save_cms(
            player_id=body.player_id,
            agent_name=body.agent_name,
            agent_notes=body.agent_notes,
            contract_expires=body.contract_expires,
            contract_notes=body.contract_notes,
            wages_notes=body.wages_notes,
            other_notes=body.other_notes,
            staff=_staff_name(request),
            name=body.name,
            club=body.club,
        )
        return {"ok": True, "cms": cms}
