"""Shadow Teams — what made Lincoln, Stockport and Bradford successful, and how Port Vale compares.

Data: data/shadow-teams.json, built offline by scripts/build_shadow_teams.py from Impect.
Context: app/shadow_teams_context.py (ownership, structure, coaches, sourced).
Staff notes: DATA_ROOT/shadow-teams-notes.json.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.paths import DATA_ROOT, HUB_ROOT, STANDALONE_DIR
from app.shadow_teams_context import PLAYOFF_OUTCOMES, SHADOW_CONTEXT, TEMPLATE_INTRO

DATA_NAME = "shadow-teams.json"
DATA_CANDIDATES = (HUB_ROOT / "data" / DATA_NAME, DATA_ROOT / DATA_NAME)
NOTES_PATH = DATA_ROOT / "shadow-teams-notes.json"
VALE_BADGE = "/standalone/port-vale-badge.png?v=2"

SQUAD_TEMPLATE_KEYS = (
    ("avg_age", "Minutes-weighted age", "yrs", 1),
    ("avg_height", "Outfield height (weighted)", "m", 2),
    ("players_used", "Players used", "", 0),
    ("core_players", "Players with 2,000+ minutes", "", 0),
    ("top11_share", "Minutes taken by top 11", "%", 1),
    ("u23_share", "Minutes to U23s", "%", 1),
    ("over30_share", "Minutes to 30+", "%", 1),
    ("left_foot_pct", "Left-footed outfield minutes", "%", 1),
    ("top3_goal_share", "Goals from top 3 scorers", "%", 1),
)
RECRUIT_TEMPLATE_KEYS = (
    ("retained_share_prev", "Last season's minutes kept", "%", 1),
    ("new_minutes_share", "Minutes to new signings", "%", 1),
    ("arrivals_count", "Players arriving (used)", "", 0),
    ("arrivals_core", "Arrivals who became core (2,000+ min)", "", 0),
    ("hit_rate", "Arrivals reaching 900+ min", "%", 0),
    ("avg_age_used_arrivals", "Age of arrivals who played", "yrs", 1),
)

_cache: dict[str, Any] = {"mtime": None, "payload": None}
_cache_lock = threading.Lock()
_notes_lock = threading.Lock()


def _data_path() -> Path | None:
    return next((p for p in DATA_CANDIDATES if p.is_file()), None)


def _load_raw() -> dict[str, Any]:
    path = _data_path()
    if path is None:
        raise FileNotFoundError("Shadow Teams data has not been built yet.")
    mtime = path.stat().st_mtime
    with _cache_lock:
        if _cache["mtime"] != mtime:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _cache["payload"] = build_payload(raw)
            _cache["mtime"] = mtime
        return _cache["payload"]


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 2) if vals else None


def _season_by(club: dict[str, Any], season: str) -> dict[str, Any] | None:
    return next((s for s in club.get("seasons") or [] if s.get("season") == season), None)


def _apply_outcomes(key: str, club: dict[str, Any], leagues: dict[str, Any]) -> None:
    for cs in club.get("seasons") or []:
        table = cs.setdefault("table", {})
        league = leagues.get(str(cs.get("iteration_id"))) or {}
        full = (int(cs.get("teams") or 24) - 1) * 2
        played = [r.get("played", 0) for r in league.get("table") or []]
        # Impect is missing whole matches in some early seasons; the computed table is then wrong.
        cs["partial"] = bool(not cs.get("current") and played and min(played) < full - 2)
        label = PLAYOFF_OUTCOMES.get((key, cs.get("season")))
        if label and not cs.get("current"):
            table["final_outcome"] = label
        elif cs["partial"]:
            table["final_outcome"] = "Impect cover incomplete"


def build_template(clubs: dict[str, dict[str, Any]], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """Average percentile across every success season of the three clubs.

    A trait is "shared" when every success season sits on the same side of the league
    (all ≥ 60th percentile or all ≤ 40th), which is what we want Port Vale to copy.
    """
    seasons: list[tuple[str, dict[str, Any]]] = []
    for key, club in clubs.items():
        for season in club.get("success_seasons") or []:
            cs = _season_by(club, season)
            if cs:
                seasons.append((key, cs))

    style: dict[str, Any] = {}
    for spec in metrics:
        k = spec["key"]
        cells = [(club, cs, cs["style"][k]) for club, cs in seasons if cs.get("style", {}).get(k)]
        if not cells:
            continue
        pcts = [c["pct_high"] for _, _, c in cells]
        high = all(p >= 60 for p in pcts)
        low = all(p <= 40 for p in pcts)
        style[k] = {
            "pct": round(statistics.fmean(pcts)),
            "min_pct": min(pcts),
            "max_pct": max(pcts),
            "shared": "high" if high else ("low" if low else None),
            "by_season": [
                {"club": club, "season": cs["season"], "competition": cs["competition"], "pct": c["pct_high"],
                 "value": c["value"], "rank": c["rank_high"]}
                for club, cs, c in cells
            ],
        }

    squad = {}
    for key, label, unit, digits in SQUAD_TEMPLATE_KEYS:
        vals = [cs["squad"]["summary"].get(key) for _, cs in seasons]
        squad[key] = {"label": label, "unit": unit, "digits": digits, "value": _mean(vals),
                      "by_season": [{"club": c, "season": cs["season"], "value": cs["squad"]["summary"].get(key)}
                                    for c, cs in seasons]}
    recruitment = {}
    for key, label, unit, digits in RECRUIT_TEMPLATE_KEYS:
        rows = [(c, cs) for c, cs in seasons if (cs.get("recruitment") or {}).get("covered")]
        vals = [cs["recruitment"].get(key) for _, cs in rows]
        recruitment[key] = {"label": label, "unit": unit, "digits": digits, "value": _mean(vals),
                            "by_season": [{"club": c, "season": cs["season"], "value": cs["recruitment"].get(key)}
                                          for c, cs in rows]}

    patterns = {}
    for key, label in (("home_ppg", "Home points a game"), ("away_ppg", "Away points a game"),
                       ("clean_sheet_rate", "Clean sheets %"), ("points_from_behind_rate", "Points per game when behind at HT"),
                       ("win_when_leading_rate", "Win % when ahead at HT"), ("top7_ppg", "Points a game vs top 7")):
        vals = [_pattern_value(cs, key) for _, cs in seasons]
        patterns[key] = {"label": label, "value": _mean(vals),
                         "by_season": [{"club": c, "season": cs["season"], "value": _pattern_value(cs, key)}
                                       for c, cs in seasons]}

    xppg = _mean([cs["table"].get("xppg") for _, cs in seasons])
    return {
        "goals": build_goal_template(seasons),
        "intro": TEMPLATE_INTRO,
        "seasons": [{"club": c, "season": cs["season"], "competition": cs["competition"],
                     "position": cs["table"]["position"], "points": cs["table"]["points"],
                     "outcome": cs["table"].get("final_outcome") or cs["table"].get("outcome")}
                    for c, cs in seasons],
        "style": style,
        "squad": squad,
        "recruitment": recruitment,
        "patterns": patterns,
        "xppg": xppg,
    }


def goal_mix(cs: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Share of goals (%) by phase, action and scorer group, plus conceded by phase."""
    g = cs.get("goals") or {}
    if not g.get("total"):
        return {}

    def shares(counts: dict[str, float]) -> dict[str, float]:
        total = sum(counts.values())
        return {k: round(100.0 * v / total, 1) for k, v in counts.items()} if total else {}

    against = g.get("against") or {}
    return {
        "phases": shares({k: v.get("goals", 0) for k, v in (g.get("phases") or {}).items()}),
        "actions": shares({k: v.get("goals", 0) for k, v in (g.get("actions") or {}).items()}),
        "groups": shares({k: v.get("goals", 0) for k, v in (g.get("groups") or {}).items()}),
        "against_phases": shares(against.get("phases") or {}),
    }


def build_goal_template(seasons: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    mixes = [(club, cs, goal_mix(cs)) for club, cs in seasons]
    mixes = [m for m in mixes if m[2]]
    out: dict[str, Any] = {}
    for part in ("phases", "actions", "groups", "against_phases"):
        keys = sorted({k for _, _, mix in mixes for k in mix.get(part, {})})
        out[part] = {
            k: {
                "share": _mean([mix[part].get(k, 0.0) for _, _, mix in mixes if mix.get(part)]),
                "by_season": [{"club": club, "season": cs["season"], "share": mix[part].get(k, 0.0)}
                              for club, cs, mix in mixes if mix.get(part)],
            }
            for k in keys
        }
    out["per_game"] = _mean([cs["goals"]["total"] / cs["table"]["played"] for _, cs, _ in mixes if cs["table"].get("played")])
    out["conceded_per_game"] = _mean([cs["goals"]["against"]["total"] / cs["goals"]["against"]["matches"]
                                      for _, cs, _ in mixes if (cs["goals"].get("against") or {}).get("matches")])
    return out


def _pattern_value(cs: dict[str, Any], key: str) -> float | None:
    p = cs.get("patterns") or {}
    overall = p.get("overall") or {}
    if key == "home_ppg":
        return (p.get("home") or {}).get("ppg")
    if key == "away_ppg":
        return (p.get("away") or {}).get("ppg")
    if key == "top7_ppg":
        return (p.get("vs_top7") or {}).get("ppg")
    if key == "clean_sheet_rate":
        return round(100.0 * p.get("clean_sheets", 0) / overall["p"], 1) if overall.get("p") else None
    if key == "points_from_behind_rate":
        trailing = (p.get("half_time") or {}).get("trailing") or {}
        return round(p.get("points_from_behind", 0) / trailing["p"], 2) if trailing.get("p") else None
    if key == "win_when_leading_rate":
        leading = (p.get("half_time") or {}).get("leading") or {}
        return round(100.0 * leading.get("w", 0) / leading["p"], 1) if leading.get("p") else None
    return None


def build_payload(raw: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(raw)
    clubs = payload.get("clubs") or {}
    leagues = payload.get("leagues") or {}
    for key, club in clubs.items():
        ctx = SHADOW_CONTEXT.get(key, {})
        club.update({k: v for k, v in ctx.items()})
        _apply_outcomes(key, club, leagues)
        for cs in club.get("seasons") or []:
            cs["pattern_rates"] = {k: _pattern_value(cs, k) for k in (
                "home_ppg", "away_ppg", "top7_ppg", "clean_sheet_rate", "points_from_behind_rate", "win_when_leading_rate")}
            cs["goal_mix"] = goal_mix(cs)
    vale = payload.get("vale") or {}
    vale["badge"] = VALE_BADGE
    _apply_outcomes("vale", vale, leagues)
    for cs in vale.get("seasons") or []:
        cs["pattern_rates"] = {k: _pattern_value(cs, k) for k in (
            "home_ppg", "away_ppg", "top7_ppg", "clean_sheet_rate", "points_from_behind_rate", "win_when_leading_rate")}
        cs["goal_mix"] = goal_mix(cs)
    payload["template"] = build_template(clubs, payload.get("metrics") or [])
    payload["club_order"] = [k for k in ("lincoln", "stockport", "bradford") if k in clubs]
    return payload


# ---------------------------------------------------------------- staff notes


def read_notes() -> list[dict[str, Any]]:
    if not NOTES_PATH.is_file():
        return []
    try:
        data = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write_notes(notes: list[dict[str, Any]]) -> None:
    NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = NOTES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, indent=2), encoding="utf-8")
    tmp.replace(NOTES_PATH)


def add_note(club: str, text: str, author: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Write a note first.")
    if club not in (*SHADOW_CONTEXT.keys(), "template"):
        raise ValueError("Unknown club.")
    note = {"id": uuid.uuid4().hex[:12], "club": club, "text": text[:4000], "author": author,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _notes_lock:
        notes = read_notes()
        notes.append(note)
        _write_notes(notes)
    return note


def delete_note(note_id: str) -> bool:
    with _notes_lock:
        notes = read_notes()
        kept = [n for n in notes if n.get("id") != note_id]
        if len(kept) == len(notes):
            return False
        _write_notes(kept)
    return True


def _username(request: Request) -> str:
    try:
        from app.auth import current_user_payload

        user = current_user_payload(request)
        return str(user.get("display_name") or user.get("username") or "staff")
    except Exception:
        return "staff"


# ---------------------------------------------------------------- routes


def register_shadow_teams_routes(app: FastAPI) -> None:
    @app.get("/shadow-teams")
    @app.get("/shadow-teams/")
    def shadow_teams_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "shadow-teams.html")

    @app.get("/api/shadow-teams/data")
    def shadow_teams_data() -> JSONResponse:
        try:
            payload = _load_raw()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/shadow-teams/notes")
    def shadow_teams_notes() -> dict:
        return {"notes": read_notes()}

    @app.post("/api/shadow-teams/notes")
    def shadow_teams_add_note(request: Request, body: dict = Body(...)) -> dict:
        try:
            note = add_note(str(body.get("club") or ""), str(body.get("text") or ""), _username(request))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"note": note}

    @app.delete("/api/shadow-teams/notes/{note_id}")
    def shadow_teams_delete_note(note_id: str) -> dict:
        if not delete_note(note_id):
            raise HTTPException(status_code=404, detail="Note not found.")
        return {"ok": True}
