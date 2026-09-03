"""Standalone match dashboards — For/Against + combine games.

Reuses post-match builders (shots, crosses, progression, duels, match story)
without the slide-deck PDF pipeline.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.paths import STANDALONE_DIR
from app.post_match.config import (
    DEFAULT_ITERATION_ID,
    DEFAULT_SEASON_LABEL,
    PORT_VALE_SQUAD_ID,
    POST_MATCH_COMPETITIONS,
)
from app.post_match.ball_progression import build_ball_progression
from app.post_match.crosses import build_crosses
from app.post_match.duels import build_duels
from app.post_match.momentum_blocks import build_momentum_blocks
from app.post_match.season_matches import build_combined_season_matches
from app.post_match.shots import build_shots
from app.post_match.xg_race import build_xg_race
from app.xg_chance_analysis import build_xg_chance_report

VIEWS = ("story", "progression", "crosses", "shots", "duels")
SIDES = ("for", "against")


def _available_matches() -> list[dict[str, Any]]:
    payload = build_combined_season_matches(
        PORT_VALE_SQUAD_ID,
        competitions=POST_MATCH_COMPETITIONS,
        include_upcoming=False,
    )
    matches = [
        m
        for m in (payload.get("matches") or [])
        if m.get("available") is not False and m.get("matchId")
    ]
    matches.sort(key=lambda item: item.get("scheduledDate") or "", reverse=True)
    return matches


def _match_by_id(match_id: int, matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    pool = matches if matches is not None else _available_matches()
    for row in pool:
        if int(row.get("matchId") or 0) == int(match_id):
            return row
    raise HTTPException(status_code=404, detail=f"Match {match_id} not found.")


def _side_context(match: dict[str, Any], side: str) -> dict[str, Any]:
    home = match.get("home") or {}
    away = match.get("away") or {}
    opponent = match.get("opponent") or {}
    home_id = int(home.get("squadId") or 0)
    away_id = int(away.get("squadId") or 0)
    opp_id = int(opponent.get("squadId") or 0)
    vale_is_home = bool(match.get("isHome"))
    if side == "against":
        focus_id = opp_id or (away_id if vale_is_home else home_id)
        focus_name = opponent.get("name") or "Opponent"
        opponent_name = "Port Vale"
        opponent_id = PORT_VALE_SQUAD_ID
        defensive = True
    else:
        focus_id = PORT_VALE_SQUAD_ID
        focus_name = "Port Vale"
        opponent_name = opponent.get("name") or "Opponent"
        opponent_id = opp_id
        defensive = False
    return {
        "matchId": int(match["matchId"]),
        "iterationId": int(match.get("iterationId") or DEFAULT_ITERATION_ID),
        "homeId": home_id,
        "awayId": away_id,
        "homeName": home.get("name"),
        "awayName": away.get("name"),
        "focusId": focus_id,
        "focusName": focus_name,
        "opponentId": opponent_id,
        "opponentName": opponent_name,
        "defensive": defensive,
        "label": _match_label(match),
    }


def _match_label(match: dict[str, Any]) -> str:
    opponent = (match.get("opponent") or {}).get("name") or "Opponent"
    venue = "H" if match.get("isHome") else "A"
    score = match.get("scoreLabel") or match.get("result") or ""
    short = match.get("competitionShort") or ""
    date = str(match.get("scheduledDate") or "")[:10]
    bits = [f"{venue} {opponent}"]
    if score:
        bits.append(str(score))
    if short:
        bits.append(str(short))
    if date:
        bits.append(date)
    return " · ".join(bits)


def _build_one(view: str, ctx: dict[str, Any]) -> dict[str, Any]:
    match_id = ctx["matchId"]
    iteration_id = ctx["iterationId"]
    focus_id = ctx["focusId"]
    opp_name = ctx["opponentName"]
    opp_id = ctx["opponentId"]
    defensive = ctx["defensive"]

    if view == "story":
        story_focus = PORT_VALE_SQUAD_ID if not defensive else ctx["focusId"]
        momentum = build_momentum_blocks(
            match_id,
            ctx["homeId"],
            ctx["awayId"],
            story_focus,
            home_name=ctx["homeName"],
            away_name=ctx["awayName"],
        )
        race = build_xg_race(
            match_id,
            ctx["homeId"],
            ctx["awayId"],
            home_name=ctx["homeName"],
            away_name=ctx["awayName"],
        )
        return {"momentum": momentum, "xgRace": race}

    if view == "progression":
        return build_ball_progression(
            match_id,
            focus_id,
            iteration_id,
            opponent_name=opp_name,
        )

    if view == "crosses":
        title = (
            "Out of Possession — Crosses"
            if defensive
            else "In-Possession — Crosses"
        )
        return build_crosses(
            match_id,
            PORT_VALE_SQUAD_ID,
            iteration_id,
            opponent_squad_id=opp_id if defensive else None,
            title=title,
            defensive=defensive,
        )

    if view == "shots":
        title = (
            "Out of Possession — Shots & xG"
            if defensive
            else "In-Possession — Shots & xG"
        )
        payload = build_shots(
            match_id,
            PORT_VALE_SQUAD_ID,
            iteration_id,
            opponent_name=opp_name,
            opponent_squad_id=opp_id if defensive else None,
            title=title,
            defensive=defensive,
        )
        payload["xgChance"] = None
        return payload

    if view == "duels":
        payload = build_duels(
            match_id,
            focus_id,
            iteration_id,
            opponent_name=opp_name,
        )
        if defensive:
            payload["title"] = "In Possession — Duels and Pressing (against)"
        return payload

    raise HTTPException(status_code=400, detail=f"Unknown view {view}")


def _avg(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _merge_team_metrics(reports: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    if not reports:
        return []
    first = reports[0].get("teamMetrics") or []
    merged: list[dict[str, Any]] = []
    for idx, spec in enumerate(first):
        values = []
        for report in reports:
            rows = report.get("teamMetrics") or []
            if idx < len(rows):
                values.append(rows[idx].get("matchValue"))
        match_value = _avg(values)
        row = dict(spec)
        row["matchValue"] = match_value
        display = spec.get("matchDisplay")
        if isinstance(display, str) and display.endswith("%") and match_value is not None:
            row["matchDisplay"] = f"{round(match_value * 100, 1)}%" if match_value <= 1 else f"{round(match_value, 1)}%"
        elif match_value is not None and isinstance(display, str) and "." in display:
            row["matchDisplay"] = f"{round(match_value, 2)}"
        elif match_value is not None:
            row["matchDisplay"] = str(int(round(match_value)))
        row["combinedGames"] = n
        merged.append(row)
    return merged


def _merge_players_sum(reports: list[dict[str, Any]], sum_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for report in reports:
        for row in report.get("players") or []:
            pid = int(row.get("playerId") or 0)
            if not pid:
                continue
            current = by_id.get(pid)
            if current is None:
                by_id[pid] = dict(row)
                continue
            for key in sum_keys:
                current[key] = (current.get(key) or 0) + (row.get(key) or 0)
            if "minutes" in row:
                current["minutes"] = round(float(current.get("minutes") or 0) + float(row.get("minutes") or 0), 1)
    rows = list(by_id.values())
    rows.sort(key=lambda item: item.get("playerName") or "")
    return rows


def _combine_story(parts: list[dict[str, Any]], n: int) -> dict[str, Any]:
    first = parts[0]["momentum"]
    blocks = first.get("blocks") or []
    combined_blocks = []
    for idx, block in enumerate(blocks):
        same = []
        for part in parts:
            bs = (part.get("momentum") or {}).get("blocks") or []
            if idx < len(bs):
                same.append(bs[idx])
        if not same:
            continue
        combined_blocks.append(
            {
                **block,
                "focusSharePercent": round(_avg([b.get("focusSharePercent") for b in same]) or 0, 1),
                "opponentSharePercent": round(_avg([b.get("opponentSharePercent") for b in same]) or 0, 1),
                "focusPressCount": int(round(_avg([b.get("focusPressCount") or 0 for b in same]) or 0)),
                "focusMeanPressure": _avg([b.get("focusMeanPressure") for b in same]),
                "focusRegains": int(round(_avg([b.get("focusRegains") or 0 for b in same]) or 0)),
                "focusDuelWinPct": _avg([b.get("focusDuelWinPct") for b in same]),
                "focusXg": round(_avg([b.get("focusXg") or 0 for b in same]) or 0, 2),
                "opponentXg": round(_avg([b.get("opponentXg") or 0 for b in same]) or 0, 2),
                "focusShots": int(round(_avg([b.get("focusShots") or 0 for b in same]) or 0)),
                "opponentShots": int(round(_avg([b.get("opponentShots") or 0 for b in same]) or 0)),
                "goals": [g for b in same for g in (b.get("goals") or [])],
            }
        )
    summaries = [(p.get("momentum") or {}).get("summary") or {} for p in parts]
    summary = dict(first.get("summary") or {})
    summary["matchPressCount"] = int(round(_avg([s.get("matchPressCount") or 0 for s in summaries]) or 0))
    summary["matchRegains"] = int(round(_avg([s.get("matchRegains") or 0 for s in summaries]) or 0))
    summary["matchFocusXg"] = round(_avg([s.get("matchFocusXg") or 0 for s in summaries]) or 0, 2)
    summary["matchOpponentXg"] = round(_avg([s.get("matchOpponentXg") or 0 for s in summaries]) or 0, 2)
    summary["combinedGames"] = n
    momentum = dict(first)
    momentum["blocks"] = combined_blocks
    momentum["summary"] = summary
    momentum["goals"] = [g for p in parts for g in ((p.get("momentum") or {}).get("goals") or [])]
    return {"momentum": momentum, "xgRace": parts[0].get("xgRace"), "combined": True, "gameCount": n}


def _combine_shots(parts: list[dict[str, Any]], n: int) -> dict[str, Any]:
    first = dict(parts[0])
    first["shotPoints"] = [pt for p in parts for pt in (p.get("shotPoints") or [])]
    first["teamMetrics"] = _merge_team_metrics(parts, n)
    players: dict[int, dict[str, Any]] = {}
    phases: dict[str, dict[str, Any]] = {}
    total_shots = 0
    total_xg = 0.0
    goals = 0
    on_target = 0
    for part in parts:
        summary = part.get("summary") or {}
        total_shots += int(summary.get("totalShots") or 0)
        total_xg += float(summary.get("totalXg") or 0)
        goals += int(summary.get("goals") or 0)
        on_target += int(summary.get("onTarget") or 0)
        for row in part.get("players") or []:
            pid = int(row.get("playerId") or 0)
            if not pid:
                continue
            cur = players.get(pid)
            if cur is None:
                players[pid] = dict(row)
            else:
                cur["shots"] = (cur.get("shots") or 0) + (row.get("shots") or 0)
                cur["xg"] = round(float(cur.get("xg") or 0) + float(row.get("xg") or 0), 4)
        for row in part.get("phases") or []:
            key = str(row.get("phase") or row.get("label") or "")
            cur = phases.get(key)
            if cur is None:
                phases[key] = dict(row)
            else:
                cur["shots"] = (cur.get("shots") or 0) + (row.get("shots") or 0)
                cur["xg"] = round(float(cur.get("xg") or 0) + float(row.get("xg") or 0), 4)
    first["players"] = sorted(players.values(), key=lambda r: (-float(r.get("xg") or 0), r.get("playerName") or ""))
    first["phases"] = list(phases.values())
    first["summary"] = {
        **(first.get("summary") or {}),
        "totalShots": total_shots,
        "totalXg": round(total_xg, 2),
        "totalXgDisplay": f"{total_xg:.2f}",
        "goals": goals,
        "onTarget": on_target,
    }
    first["combined"] = True
    first["gameCount"] = n
    return first


def _combine_crosses(parts: list[dict[str, Any]], n: int) -> dict[str, Any]:
    first = dict(parts[0])
    first["crossPoints"] = [pt for p in parts for pt in (p.get("crossPoints") or [])]
    summaries = [p.get("summary") or {} for p in parts]
    first["summary"] = {
        **(first.get("summary") or {}),
        "total": sum(int(s.get("total") or 0) for s in summaries),
        "highCross": sum(int(s.get("highCross") or 0) for s in summaries),
        "lowCross": sum(int(s.get("lowCross") or 0) for s in summaries),
        "successful": sum(int(s.get("successful") or 0) for s in summaries),
        "failed": sum(int(s.get("failed") or 0) for s in summaries),
        "alteredThreat": round(_avg([s.get("alteredThreat") for s in summaries]) or 0, 2),
    }
    first["totalCrosses"] = first["summary"]["total"]
    lane_acc: dict[str, int] = {}
    for part in parts:
        for lane in part.get("lanes") or []:
            lane_acc[lane["id"]] = lane_acc.get(lane["id"], 0) + int(lane.get("value") or 0)
    lanes = []
    for lane in first.get("lanes") or []:
        value = lane_acc.get(lane["id"], 0)
        lanes.append({**lane, "value": value})
    first["lanes"] = lanes
    first["maxLaneValue"] = max((ln["value"] for ln in lanes), default=1) or 1
    players: dict[int, dict[str, Any]] = {}
    for part in parts:
        for row in part.get("players") or []:
            pid = int(row.get("playerId") or 0)
            if not pid:
                continue
            cur = players.get(pid)
            if cur is None:
                players[pid] = dict(row)
            else:
                cur["crosses"] = (cur.get("crosses") or 0) + (row.get("crosses") or 0)
                cur["successful"] = (cur.get("successful") or 0) + (row.get("successful") or 0)
                cur["alteredThreat"] = round(float(cur.get("alteredThreat") or 0) + float(row.get("alteredThreat") or 0), 2)
    first["players"] = sorted(players.values(), key=lambda r: (-float(r.get("alteredThreat") or 0), r.get("playerName") or ""))
    first["combined"] = True
    first["gameCount"] = n
    return first


def _combine_progression(parts: list[dict[str, Any]], n: int) -> dict[str, Any]:
    first = dict(parts[0])
    first["teamMetrics"] = _merge_team_metrics(parts, n)
    first["players"] = _merge_players_sum(
        parts,
        ("breakingOpponentDefence", "ballProgression", "defensiveBallControl"),
    )
    first["combined"] = True
    first["gameCount"] = n
    return first


def _combine_duels(parts: list[dict[str, Any]], n: int) -> dict[str, Any]:
    first = dict(parts[0])
    first["teamMetrics"] = _merge_team_metrics(parts, n)
    first["duelMetrics"] = [row for row in first["teamMetrics"] if row.get("section") == "duels"]
    first["pressingMetrics"] = [row for row in first["teamMetrics"] if row.get("section") == "pressing"]
    first["players"] = _merge_players_sum(
        parts,
        (
            "offensiveInterventions",
            "defensiveInterventions",
            "ballWinsFromOppositionDefenders",
        ),
    )
    first["combined"] = True
    first["gameCount"] = n
    return first


def _attach_xg_chance(payload: dict[str, Any], match_ids: list[int], season: str | None) -> dict[str, Any]:
    try:
        if len(match_ids) == 1:
            payload["xgChance"] = build_xg_chance_report(
                season=season or DEFAULT_SEASON_LABEL,
                match_id=match_ids[0],
                scope="match",
            )
        else:
            payload["xgChance"] = build_xg_chance_report(
                season=season or DEFAULT_SEASON_LABEL,
                match_ids=match_ids,
            )
    except Exception as exc:
        payload["xgChance"] = None
        payload["xgChanceError"] = str(exc)
    return payload


def build_dashboard_report(view: str, side: str, match_ids: list[int]) -> dict[str, Any]:
    if view not in VIEWS:
        raise HTTPException(status_code=400, detail="Invalid view")
    if side not in SIDES:
        raise HTTPException(status_code=400, detail="side must be for or against")
    if not match_ids:
        raise HTTPException(status_code=400, detail="Select at least one match")

    matches = _available_matches()
    contexts = [_side_context(_match_by_id(mid, matches), side) for mid in match_ids]

    parts: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(6, len(contexts))) as pool:
        futures = {pool.submit(_build_one, view, ctx): ctx for ctx in contexts}
        for fut in as_completed(futures):
            ctx = futures[fut]
            try:
                parts.append({"_ctx": ctx, **fut.result()} if view == "story" else {"_ctx": ctx, "payload": fut.result()})
            except Exception as exc:
                errors.append(f"{ctx['label']}: {exc}")

    if not parts:
        raise HTTPException(status_code=502, detail="; ".join(errors) or "No data")

    by_id = {
        int((part.get("_ctx") or {}).get("matchId") or 0): part
        for part in parts
    }
    parts = [by_id[ctx["matchId"]] for ctx in contexts if ctx["matchId"] in by_id] or parts

    if view == "story":
        payloads = [{"momentum": p["momentum"], "xgRace": p["xgRace"]} for p in parts]
        data = payloads[0] if len(payloads) == 1 else _combine_story(payloads, len(payloads))
    else:
        payloads = [p["payload"] for p in parts]
        if len(payloads) == 1:
            data = payloads[0]
        elif view == "shots":
            data = _combine_shots(payloads, len(payloads))
        elif view == "crosses":
            data = _combine_crosses(payloads, len(payloads))
        elif view == "progression":
            data = _combine_progression(payloads, len(payloads))
        else:
            data = _combine_duels(payloads, len(payloads))

    labels = [ctx["label"] for ctx in contexts]
    season = next((m.get("seasonLabel") for m in matches if m.get("seasonLabel")), DEFAULT_SEASON_LABEL)
    if view == "shots":
        data = _attach_xg_chance(data, match_ids, season)
    return {
        "view": view,
        "side": side,
        "matchIds": match_ids,
        "matchLabels": labels,
        "combined": len(match_ids) > 1,
        "gameCount": len(match_ids),
        "errors": errors,
        "data": data,
    }


def register_match_dashboards_routes(app: FastAPI) -> None:
    @app.get("/match-dashboards", response_class=HTMLResponse)
    @app.get("/match-dashboards/", response_class=HTMLResponse)
    def match_dashboards_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "match-dashboards.html"
        if not html_path.is_file():
            raise HTTPException(status_code=503, detail="Match dashboards page not found.")
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/api/match-dashboards/meta")
    def match_dashboards_meta() -> dict[str, Any]:
        matches = _available_matches()
        return {
            "portValeSquadId": PORT_VALE_SQUAD_ID,
            "seasonLabel": DEFAULT_SEASON_LABEL,
            "defaultIterationId": DEFAULT_ITERATION_ID,
            "views": [
                {"id": "story", "title": "Match story", "blurb": "15-minute blocks, presses & xG race"},
                {"id": "progression", "title": "Ball progression", "blurb": "Team KPIs and player packing"},
                {"id": "crosses", "title": "Crosses", "blurb": "Origins, flanks and threat"},
                {"id": "shots", "title": "Shots & xG", "blurb": "Map, chance ratings, game state and player xG"},
                {"id": "duels", "title": "Duels & pressing", "blurb": "Team duels, press height, player rows"},
            ],
            "defaultMatchId": matches[0]["matchId"] if matches else None,
        }

    @app.get("/api/match-dashboards/fixtures")
    def match_dashboards_fixtures() -> dict[str, Any]:
        matches = _available_matches()
        return {"matches": matches, "defaultMatchId": matches[0]["matchId"] if matches else None}

    @app.get("/api/match-dashboards/report")
    def match_dashboards_report(
        view: str = Query("shots"),
        side: str = Query("for"),
        match_ids: str | None = Query(None, alias="matchIds"),
        match_id: int | None = Query(None, alias="matchId"),
    ) -> JSONResponse:
        ids: list[int] = []
        if match_ids:
            for part in match_ids.split(","):
                part = part.strip()
                if part:
                    ids.append(int(part))
        elif match_id:
            ids = [int(match_id)]
        else:
            matches = _available_matches()
            if matches:
                ids = [int(matches[0]["matchId"])]
        payload = build_dashboard_report(view, side, ids)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/match-dashboards/export-pdf")
    def match_dashboards_export_pdf(
        view: str = Query("shots"),
        side: str = Query("for"),
        match_ids: str | None = Query(None, alias="matchIds"),
    ) -> Response:
        from app.xg_chance_analysis_pdf import build_xg_chance_analysis_pdf

        ids: list[int] = []
        if match_ids:
            for part in match_ids.split(","):
                part = part.strip()
                if part:
                    ids.append(int(part))
        if not ids:
            raise HTTPException(status_code=400, detail="Select at least one match")
        payload = build_dashboard_report(view or "shots", side, ids)
        data = payload.get("data") or {}
        xg = data.get("xgChance") or {}
        pdf_scope = "match" if len(ids) <= 1 else "last6"
        try:
            pdf_bytes = build_xg_chance_analysis_pdf(
                xg,
                scope=pdf_scope,
                shots_payload=data if view == "shots" else None,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc
        filename = "shots-xg-chance.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
