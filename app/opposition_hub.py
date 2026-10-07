"""Opposition Hub — everything the coaches need on an opponent, on one page.

Reads only the analysis data lake that Attacking Threat, Interventions, Set
Plays, xG Chance Analysis and Pre-Match already fill during the hub refresh:

* ``sp-base``          season matches, club and player names
* ``at-match``         per-match event threat for both squads (progression, threat created / conceded)
* ``iv-league-match``  per-match ball wins, interventions and duels for both squads
* ``xg-league-match``  per-match shot quality for both squads
* ``sp-pack``          per-match set-play records
* ``pre-match``        squad, minutes, line-ups and style radar (one report per opponent)
* ``xg-events``        raw match events, for threat chains and progressive actions

Opening the page never calls Impect. The only Impect path is the "Rebuild
squad data" button, which queues the existing Pre-Match background build.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.paths import STANDALONE_DIR

logger = logging.getLogger(__name__)

ALLOWED_SEASONS = ("26/27", "25/26")
MEMO_TTL_SECONDS = 600
STRONG_RANK = 6
LOG_MATCHES = 8

LONG_ACTIONS = {"HIGH_PASS", "DIAGONAL_PASS", "CHIPPED_PASS", "GOAL_KICK"}
LEFT_ZONES = {"FBL", "WL", "IBWL"}
RIGHT_ZONES = {"FBR", "WR", "IBWR"}
DEEP_ZONES = {"FBL", "CB", "FBR"}
BOX_ZONES = {"IB", "IBWL", "IBWR"}
TRACKED_PHASES = ("IN_POSSESSION", "ATTACKING_TRANSITION", "SET_PIECE", "SECOND_BALL")
TRACKED_FAMILIES = ("cross", "pass", "dribble", "shot", "setPiece", "regain")
IV_FIELDS = ("bw", "oi", "di", "bwd", "gw", "gl", "aw", "al", "threat")
XG_FIELDS = ("count", "goals", "xg", "penCount", "penGoals", "penXg")

_memo: dict[tuple, tuple[float, Any]] = {}
_memo_lock = threading.Lock()


# ---------------------------------------------------------------- lake helpers


def _read(kind: str, key: str) -> dict | None:
    from app.analysis_cache import click_json

    payload = click_json(kind, key)
    return payload if isinstance(payload, dict) else None


def _season_key(season: str | None) -> str:
    return str(season or ALLOWED_SEASONS[0]).replace("/", "-")


def _memoized(key: tuple, build):
    now = time.time()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < MEMO_TTL_SECONDS:
            return hit[1]
    value = build()
    with _memo_lock:
        _memo[key] = (now, value)
    return value


def _memo_peek(key: tuple):
    with _memo_lock:
        hit = _memo.get(key)
    return hit[1] if hit and time.time() - hit[0] < MEMO_TTL_SECONDS else None


def clear_memo() -> None:
    with _memo_lock:
        _memo.clear()


def season_base(season: str | None) -> dict | None:
    base = _read("sp-base", _season_key(season))
    if not base or not base.get("matches"):
        return None
    return base


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _per(value: float, games: int, digits: int = 2) -> float | None:
    return round(float(value) / games, digits) if games else None


def _pct(won: float, lost: float) -> float | None:
    total = float(won) + float(lost)
    return round(100.0 * float(won) / total, 1) if total > 0 else None


def _ordinal(n: int | None) -> str:
    if not n:
        return "—"
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _badge(squad_id: int, name: str = "") -> str:
    """Saved crest on this server if there is one, else the FotMob crest (same as other reports)."""
    from app.handout_badges import hydrate_team_badge

    url = hydrate_team_badge({"id": int(squad_id), "name": name}).get("badge_url")
    return url or f"/api/team-badge/{int(squad_id)}"


def _club(base: dict, squad_id: int) -> str:
    return str((base.get("names") or {}).get(str(int(squad_id))) or f"Squad {squad_id}")


# ---------------------------------------------------------------- fixtures and results


def team_fixtures(base: dict, squad_id: int) -> list[dict[str, Any]]:
    """Every completed league match for one club, oldest first, from that club's side."""
    rows = []
    for match in base.get("matches") or []:
        home_id, away_id = int(match["home"]), int(match["away"])
        if squad_id not in (home_id, away_id):
            continue
        home = home_id == squad_id
        opponent = away_id if home else home_id
        gf, ga = (int(match["hg"]), int(match["ag"])) if home else (int(match["ag"]), int(match["hg"]))
        rows.append({
            "matchId": int(match["matchId"]),
            "date": str(match.get("date") or ""),
            "opponentId": opponent,
            "opponent": _club(base, opponent),
            "badge": _badge(opponent, _club(base, opponent)),
            "home": home,
            "gf": gf,
            "ga": ga,
            "score": f"{gf}-{ga}",
            "result": "W" if gf > ga else "L" if gf < ga else "D",
        })
    rows.sort(key=lambda row: row["date"])
    return rows


def select_window(fixtures: list[dict], window: str) -> list[dict]:
    if window == "last6":
        return fixtures[-6:]
    return list(fixtures)


def _points(result: str) -> int:
    return 3 if result == "W" else 1 if result == "D" else 0


def record(fixtures: list[dict]) -> dict[str, Any]:
    played = len(fixtures)
    won = sum(1 for row in fixtures if row["result"] == "W")
    drawn = sum(1 for row in fixtures if row["result"] == "D")
    lost = played - won - drawn
    gf = sum(row["gf"] for row in fixtures)
    ga = sum(row["ga"] for row in fixtures)
    pts = 3 * won + drawn
    return {
        "played": played, "w": won, "d": drawn, "l": lost, "gf": gf, "ga": ga, "gd": gf - ga, "pts": pts,
        "ppg": _per(pts, played),
        "gfPg": _per(gf, played),
        "gaPg": _per(ga, played),
        "cleanSheets": sum(1 for row in fixtures if row["ga"] == 0),
        "failedToScore": sum(1 for row in fixtures if row["gf"] == 0),
        "form": [row["result"] for row in fixtures[-6:]],
    }


def league_table(base: dict) -> list[dict[str, Any]]:
    clubs: dict[int, list[dict]] = defaultdict(list)
    for match in base.get("matches") or []:
        for squad_id in (int(match["home"]), int(match["away"])):
            clubs[squad_id]
    for squad_id in list(clubs):
        clubs[squad_id] = team_fixtures(base, squad_id)
    rows = []
    for squad_id, fixtures in clubs.items():
        rec = record(fixtures)
        rows.append({
            "squadId": squad_id, "club": _club(base, squad_id), "badge": _badge(squad_id, _club(base, squad_id)),
            **{key: rec[key] for key in ("played", "w", "d", "l", "gf", "ga", "gd", "pts", "ppg", "form")},
        })
    rows.sort(key=lambda row: (-row["pts"], -row["gd"], -row["gf"], row["club"]))
    for index, row in enumerate(rows, start=1):
        row["position"] = index
    return rows


def head_to_head(squad_id: int, vale_id: int) -> list[dict[str, Any]]:
    """Every league meeting with Port Vale across the stored seasons, newest first."""
    rows = []
    for season in ALLOWED_SEASONS:
        base = season_base(season)
        if not base:
            continue
        for row in team_fixtures(base, int(vale_id)):
            if int(row["opponentId"]) != int(squad_id):
                continue
            rows.append({**row, "season": base.get("season") or season})
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows


# ---------------------------------------------------------------- league metric tables


def _rank(values: dict[int, float], higher: bool) -> dict[int, int]:
    ordered = sorted(values.items(), key=lambda item: (-item[1] if higher else item[1], item[0]))
    return {squad_id: index for index, (squad_id, _value) in enumerate(ordered, start=1)}


def metric_row(
    metric_id: str,
    label: str,
    values: dict[int, float],
    squad_id: int,
    *,
    higher: bool = True,
    digits: int = 2,
    pct: bool = False,
) -> dict[str, Any]:
    """One opponent value with its league rank (1 = best for the club that owns the number)."""
    clean = {int(k): float(v) for k, v in values.items() if v is not None}
    ranks = _rank(clean, higher)
    value = clean.get(int(squad_id))
    avg = sum(clean.values()) / len(clean) if clean else None
    return {
        "id": metric_id,
        "label": label,
        "value": round(value, digits) if value is not None else None,
        "rank": ranks.get(int(squad_id)),
        "of": len(clean),
        "avg": round(avg, digits) if avg is not None else None,
        "better": "high" if higher else "low",
        "digits": digits,
        "pct": pct,
    }


def _other(match: dict, squad_id: int) -> int:
    return int(match["away"]) if int(match["home"]) == int(squad_id) else int(match["home"])


def _threat_summaries(base: dict) -> dict[int, dict]:
    out = {}
    for match in base.get("matches") or []:
        summary = _read("at-match", str(int(match["matchId"])))
        if summary and isinstance(summary.get("squads"), dict):
            out[int(match["matchId"])] = summary
    return out


def threat_league(base: dict) -> dict[str, Any]:
    """Per-club threat created and conceded per game, by phase, family, flank and zone."""
    from app.attacking_threat import action_family

    summaries = _threat_summaries(base)
    totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[int, int] = defaultdict(int)
    actions: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    phases: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for match in base.get("matches") or []:
        summary = summaries.get(int(match["matchId"]))
        if not summary:
            continue
        squads = summary["squads"]
        for squad_id in (int(match["home"]), int(match["away"])):
            ours = squads.get(str(squad_id)) or {}
            theirs = squads.get(str(_other(match, squad_id))) or {}
            games[squad_id] += 1
            row = totals[squad_id]
            row["for"] += _num(ours.get("total"))
            row["against"] += _num(theirs.get("total"))
            for phase, value in (ours.get("phases") or {}).items():
                row[f"phaseFor:{phase}"] += _num(value)
                phases[squad_id][phase] += _num(value)
            for phase, value in (theirs.get("phases") or {}).items():
                row[f"phaseAgainst:{phase}"] += _num(value)
            for action, value in (ours.get("actions") or {}).items():
                family = action_family(str(action))
                row[f"famFor:{family}"] += _num(value)
                actions[squad_id][str(action)] += _num(value)
                if family == "pass" or str(action).upper() in LONG_ACTIONS:
                    row["passAll"] += _num(value)
                    if str(action).upper() in LONG_ACTIONS:
                        row["passLong"] += _num(value)
            for action, value in (theirs.get("actions") or {}).items():
                row[f"famAgainst:{action_family(str(action))}"] += _num(value)
            for zone, value in (ours.get("zonesStart") or {}).items():
                row["startAll"] += _num(value)
                if zone in LEFT_ZONES:
                    row["startLeft"] += _num(value)
                elif zone in RIGHT_ZONES:
                    row["startRight"] += _num(value)
                if zone in DEEP_ZONES:
                    row["startDeep"] += _num(value)
            for zone, value in (theirs.get("zonesEnd") or {}).items():
                row["concededEndAll"] += _num(value)
                if zone in LEFT_ZONES:
                    row["concededLeft"] += _num(value)
                elif zone in RIGHT_ZONES:
                    row["concededRight"] += _num(value)
    return {"summaries": summaries, "totals": totals, "games": dict(games), "actions": actions, "phases": phases}


def threat_metrics(league: dict, squad_id: int) -> dict[str, dict[str, Any]]:
    totals, games = league["totals"], league["games"]
    if not games:
        return {}

    def per_game(key: str) -> dict[int, float]:
        return {sid: totals[sid].get(key, 0.0) / played for sid, played in games.items() if played}

    def share(part: str, whole: str) -> dict[int, float]:
        return {
            sid: 100.0 * totals[sid].get(part, 0.0) / totals[sid][whole]
            for sid in games if totals[sid].get(whole)
        }

    rows = {
        "threatFor": metric_row("threatFor", "Threat created / game", per_game("for"), squad_id, digits=3),
        "threatAgainst": metric_row("threatAgainst", "Threat conceded / game", per_game("against"), squad_id, higher=False, digits=3),
        "longShare": metric_row("longShare", "Passing threat from long balls", share("passLong", "passAll"), squad_id, digits=0, pct=True),
        "leftShare": metric_row("leftShare", "Threat started down the left", share("startLeft", "startAll"), squad_id, digits=0, pct=True),
        "rightShare": metric_row("rightShare", "Threat started down the right", share("startRight", "startAll"), squad_id, digits=0, pct=True),
        "deepShare": metric_row("deepShare", "Threat started from their back line", share("startDeep", "startAll"), squad_id, digits=0, pct=True),
        "concededLeft": metric_row("concededLeft", "Threat conceded arriving on their left", share("concededLeft", "concededEndAll"), squad_id, higher=False, digits=0, pct=True),
        "concededRight": metric_row("concededRight", "Threat conceded arriving on their right", share("concededRight", "concededEndAll"), squad_id, higher=False, digits=0, pct=True),
    }
    labels = {
        "IN_POSSESSION": "build-up / possession",
        "ATTACKING_TRANSITION": "transition",
        "SET_PIECE": "set pieces",
        "SECOND_BALL": "second balls",
    }
    for phase in TRACKED_PHASES:
        rows[f"phaseFor:{phase}"] = metric_row(
            f"phaseFor:{phase}", f"Threat from {labels[phase]} / game", per_game(f"phaseFor:{phase}"), squad_id, digits=3,
        )
        rows[f"phaseAgainst:{phase}"] = metric_row(
            f"phaseAgainst:{phase}", f"Threat conceded from {labels[phase]} / game", per_game(f"phaseAgainst:{phase}"),
            squad_id, higher=False, digits=3,
        )
    fam_labels = {"cross": "crosses", "pass": "passes", "dribble": "dribbles", "shot": "shots", "setPiece": "set-piece deliveries", "regain": "ball wins"}
    for family in TRACKED_FAMILIES:
        rows[f"famFor:{family}"] = metric_row(
            f"famFor:{family}", f"Threat from {fam_labels[family]} / game", per_game(f"famFor:{family}"), squad_id, digits=3,
        )
        rows[f"famAgainst:{family}"] = metric_row(
            f"famAgainst:{family}", f"Threat conceded from {fam_labels[family]} / game", per_game(f"famAgainst:{family}"),
            squad_id, higher=False, digits=3,
        )
    return rows


def iv_league(base: dict) -> dict[str, Any]:
    """Per-club ball wins, interventions and duels, for and against, plus one observation per match."""
    totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[int, int] = defaultdict(int)
    per_match: dict[int, dict[str, dict[str, float]]] = {}
    for match in base.get("matches") or []:
        cached = _read("iv-league-match", str(int(match["matchId"])))
        squads = (cached or {}).get("squads") or {}
        home, away = str(int(match["home"])), str(int(match["away"]))
        if home not in squads or away not in squads:
            continue
        per_match[int(match["matchId"])] = squads
        for squad_id, other in ((home, away), (away, home)):
            sid = int(squad_id)
            games[sid] += 1
            for field in IV_FIELDS:
                totals[sid][field] += _num(squads[squad_id].get(field))
                totals[sid][f"opp:{field}"] += _num(squads[other].get(field))
    return {"totals": totals, "games": dict(games), "perMatch": per_match}


def iv_metrics(league: dict, squad_id: int) -> dict[str, dict[str, Any]]:
    totals, games = league["totals"], league["games"]
    if not games:
        return {}

    def per_game(key: str) -> dict[int, float]:
        return {sid: totals[sid].get(key, 0.0) / played for sid, played in games.items() if played}

    def rate(won: str, lost: str) -> dict[int, float]:
        out = {}
        for sid in games:
            value = _pct(totals[sid].get(won, 0.0), totals[sid].get(lost, 0.0))
            if value is not None:
                out[sid] = value
        return out

    duel = {}
    for sid in games:
        value = _pct(totals[sid]["gw"] + totals[sid]["aw"], totals[sid]["gl"] + totals[sid]["al"])
        if value is not None:
            duel[sid] = value
    return {
        "bw": metric_row("bw", "Ball wins / game", per_game("bw"), squad_id, digits=1),
        "bwd": metric_row("bwd", "Ball wins vs defenders / game", per_game("bwd"), squad_id, digits=2),
        "oi": metric_row("oi", "Offensive interventions / game", per_game("oi"), squad_id, digits=1),
        "di": metric_row("di", "Defensive interventions / game", per_game("di"), squad_id, higher=False, digits=1),
        "bwThreat": metric_row("bwThreat", "Threat from ball wins / game", per_game("threat"), squad_id, digits=3),
        "duelPct": metric_row("duelPct", "Duels won", duel, squad_id, digits=1, pct=True),
        "aerialPct": metric_row("aerialPct", "Aerial duels won", rate("aw", "al"), squad_id, digits=1, pct=True),
        "groundPct": metric_row("groundPct", "Ground duels won", rate("gw", "gl"), squad_id, digits=1, pct=True),
        "bwAgainst": metric_row("bwAgainst", "Times opponents win the ball off them / game", per_game("opp:bw"), squad_id, higher=False, digits=1),
        "bwdAgainst": metric_row("bwdAgainst", "Ball wins against their defenders / game", per_game("opp:bwd"), squad_id, higher=False, digits=2),
        "aerialDuels": metric_row("aerialDuels", "Aerial duels contested / game", {
            sid: (totals[sid]["aw"] + totals[sid]["al"]) / played for sid, played in games.items() if played
        }, squad_id, digits=1),
    }


def iv_battles(league: dict, fixtures: list[dict], squad_id: int) -> dict[str, Any]:
    """Which intervention battles decide this club's results, plus a match-by-match trend."""
    from app.interventions import battle_table, headline_stats

    observations, trend = [], []
    for fixture in fixtures:
        squads = league["perMatch"].get(int(fixture["matchId"]))
        if not squads:
            continue
        ours = squads.get(str(squad_id)) or {}
        theirs = squads.get(str(fixture["opponentId"])) or {}
        observations.append({"stats": ours, "opp": theirs, "pts": _points(fixture["result"])})
        us, them = headline_stats(ours, 1), headline_stats(theirs, 1)
        trend.append({
            "matchId": fixture["matchId"], "date": fixture["date"], "opponent": fixture["opponent"],
            "badge": fixture["badge"], "home": fixture["home"], "score": fixture["score"], "result": fixture["result"],
            "bw": us.get("bw"), "bwd": us.get("bwd"), "duelPct": us.get("duelPct"), "aerialPct": us.get("aerialPct"),
            "oppBw": them.get("bw"), "oppBwd": them.get("bwd"),
        })
    battles = battle_table(observations)
    return {"battles": battles, "trend": trend}


def xg_league(base: dict) -> dict[str, Any]:
    """Shot quality per club, created and conceded, from the xG Chance Analysis packs."""
    from app.xg_chance_analysis import CHANCE_BUCKETS

    bucket_ids = [bucket["id"] for bucket in CHANCE_BUCKETS]
    created: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: {b: defaultdict(float) for b in bucket_ids})
    conceded: dict[int, dict[str, dict[str, float]]] = defaultdict(lambda: {b: defaultdict(float) for b in bucket_ids})
    games: dict[int, int] = defaultdict(int)
    per_match: dict[int, dict] = {}
    for match in base.get("matches") or []:
        summary = _read("xg-league-match", str(int(match["matchId"])))
        squads = (summary or {}).get("squads") or {}
        home, away = str(int(match["home"])), str(int(match["away"]))
        if home not in squads or away not in squads:
            continue
        per_match[int(match["matchId"])] = squads
        for squad_id, other in ((home, away), (away, home)):
            sid = int(squad_id)
            games[sid] += 1
            for bucket in bucket_ids:
                for field in XG_FIELDS:
                    created[sid][bucket][field] += _num(((squads[squad_id] or {}).get(bucket) or {}).get(field))
                    conceded[sid][bucket][field] += _num(((squads[other] or {}).get(bucket) or {}).get(field))
    return {"created": created, "conceded": conceded, "games": dict(games), "perMatch": per_match, "buckets": CHANCE_BUCKETS}


def _xg_side(buckets: dict[str, dict[str, float]]) -> dict[str, float]:
    shots = sum(row["count"] for row in buckets.values())
    goals = sum(row["goals"] for row in buckets.values())
    xg = sum(row["xg"] for row in buckets.values())
    pen_xg = sum(row["penXg"] for row in buckets.values())
    pen_goals = sum(row["penGoals"] for row in buckets.values())
    pens = sum(row["penCount"] for row in buckets.values())
    big = sum(buckets[b]["count"] - buckets[b]["penCount"] for b in ("excellent", "very_good") if b in buckets)
    return {
        "shots": shots, "goals": goals, "xg": xg, "npxg": xg - pen_xg, "npGoals": goals - pen_goals,
        "npShots": shots - pens, "big": big,
    }


def xg_metrics(league: dict, squad_id: int) -> dict[str, dict[str, Any]]:
    games = league["games"]
    if not games:
        return {}
    made = {sid: _xg_side(league["created"][sid]) for sid in games}
    let = {sid: _xg_side(league["conceded"][sid]) for sid in games}

    def pg(side: dict[int, dict], key: str) -> dict[int, float]:
        return {sid: side[sid][key] / games[sid] for sid in games if games[sid]}

    return {
        "xgFor": metric_row("xgFor", "Non-penalty xG / game", pg(made, "npxg"), squad_id),
        "xgAgainst": metric_row("xgAgainst", "Non-penalty xG conceded / game", pg(let, "npxg"), squad_id, higher=False),
        "shotsFor": metric_row("shotsFor", "Shots / game", pg(made, "shots"), squad_id, digits=1),
        "shotsAgainst": metric_row("shotsAgainst", "Shots conceded / game", pg(let, "shots"), squad_id, higher=False, digits=1),
        "bigFor": metric_row("bigFor", "Big chances / game (xG 0.19+)", pg(made, "big"), squad_id),
        "bigAgainst": metric_row("bigAgainst", "Big chances conceded / game", pg(let, "big"), squad_id, higher=False),
        "xgPerShot": metric_row("xgPerShot", "Non-penalty xG per shot", {
            sid: made[sid]["npxg"] / made[sid]["npShots"] for sid in games if made[sid]["npShots"]
        }, squad_id, digits=3),
        "finishing": metric_row("finishing", "Goals minus xG (no pens)", {
            sid: made[sid]["npGoals"] - made[sid]["npxg"] for sid in games
        }, squad_id, digits=1),
        "keeping": metric_row("keeping", "Goals conceded minus xG (no pens)", {
            sid: let[sid]["npGoals"] - let[sid]["npxg"] for sid in games
        }, squad_id, higher=False, digits=1),
    }


def xg_window(league: dict, fixtures: list[dict], squad_id: int) -> dict[str, Any]:
    """Chance-quality buckets for the selected games, and xG for / against per match."""
    buckets = league["buckets"]
    made = {b["id"]: defaultdict(float) for b in buckets}
    let = {b["id"]: defaultdict(float) for b in buckets}
    trend = []
    for fixture in fixtures:
        squads = league["perMatch"].get(int(fixture["matchId"]))
        if not squads:
            continue
        ours = squads.get(str(squad_id)) or {}
        theirs = squads.get(str(fixture["opponentId"])) or {}
        for b in buckets:
            for field in XG_FIELDS:
                made[b["id"]][field] += _num((ours.get(b["id"]) or {}).get(field))
                let[b["id"]][field] += _num((theirs.get(b["id"]) or {}).get(field))
        side_for = _xg_side({k: v for k, v in ((b["id"], ours.get(b["id"]) or defaultdict(float)) for b in buckets)})
        side_against = _xg_side({k: v for k, v in ((b["id"], theirs.get(b["id"]) or defaultdict(float)) for b in buckets)})
        trend.append({
            "matchId": fixture["matchId"], "date": fixture["date"], "opponent": fixture["opponent"],
            "badge": fixture["badge"], "home": fixture["home"], "score": fixture["score"], "result": fixture["result"],
            "xgFor": round(side_for["xg"], 2), "xgAgainst": round(side_against["xg"], 2),
        })

    def rows(side: dict) -> list[dict]:
        return [{
            "id": b["id"], "label": b["label"], "color": b["color"],
            "count": int(side[b["id"]]["count"]), "goals": int(side[b["id"]]["goals"]),
            "xg": round(side[b["id"]]["xg"], 2),
        } for b in buckets]

    return {
        "for": rows(made), "against": rows(let), "trend": trend,
        "covered": len(trend), "of": len(fixtures),
        "leagueCovered": len(league["perMatch"]),
    }


# ---------------------------------------------------------------- threat window detail


def threat_window(league: dict, fixtures: list[dict], squad_id: int, players: dict[str, str]) -> dict[str, Any]:
    from app import attacking_threat as at

    parts, conceded = [], []
    for fixture in fixtures:
        summary = league["summaries"].get(int(fixture["matchId"]))
        if not summary:
            continue
        squads = summary["squads"]
        ours = squads.get(str(squad_id))
        theirs = squads.get(str(fixture["opponentId"]))
        if ours:
            parts.append(ours)
        if theirs:
            conceded.append(theirs)
    games = len([f for f in fixtures if int(f["matchId"]) in league["summaries"]])
    if not games:
        return {"games": 0}
    merged = at.merge_summaries(parts, keep_passes=True)
    against = at.merge_summaries(conceded, keep_passes=True)
    action_ranks = at.league_slice_ranks(league["actions"], league["games"], squad_id)
    phase_ranks = at.league_slice_ranks(league["phases"], league["games"], squad_id)
    opponent_by_match = {int(f["matchId"]): f["opponent"] for f in fixtures}

    def tidy_passes(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            item = {k: row.get(k) for k in ("action", "label", "family", "color", "pxt", "x1", "y1", "x2", "y2", "player", "playerId", "phase")}
            name = players.get(str(row.get("playerId") or ""))
            if name:
                item["player"] = name
            item["opponent"] = opponent_by_match.get(int(row.get("matchId") or 0))
            out.append(item)
        return out

    player_rows = at._player_rows(merged, games)
    for row in player_rows:
        row["name"] = players.get(str(row["id"])) or row["name"]
    return {
        "games": games,
        "total": round(merged["total"], 3),
        "perGame": _per(merged["total"], games, 3),
        "conceded": round(against["total"], 3),
        "concededPerGame": _per(against["total"], games, 3),
        "actions": at._action_rows(merged, games, action_ranks)[:12],
        "phases": at._phase_rows(merged, games, phase_ranks),
        "zones": {
            "start": at._zone_rows(merged.get("zonesStart") or {}, games),
            "end": at._zone_rows(merged.get("zonesEnd") or {}, games),
        },
        "players": player_rows,
        "passes": tidy_passes(merged.get("passes") or []),
        "against": {
            "actions": at._action_rows(against, games)[:10],
            "phases": at._phase_rows(against, games),
            "zonesEnd": at._zone_rows(against.get("zonesEnd") or {}, games),
            "passes": tidy_passes(against.get("passes") or []),
        },
    }


# ---------------------------------------------------------------- progression

PROG_PASS_METRES = 10.0
PROG_CARRY_METRES = 8.0
FINAL_THIRD_X = 17.5
WIDE_Y = 13.84
PROG_METHODS = (("short", "Short passes"), ("long", "Long balls"), ("carry", "Carries"), ("cross", "Crosses"))
PROG_MIN_MINUTES = 270


def _match_pack(match_id: int, summary: dict | None) -> list[dict]:
    """Compact events for one match from the saved xG events, threat from the saved at-match summary."""
    from app.analysis_cache import click_list
    from app.attacking_threat_chains import SHOT_XG_KPI_ID, compact_events

    events = click_list("xg-events", str(int(match_id))) or []
    if not events:
        return []
    kpis = []
    for squad in ((summary or {}).get("squads") or {}).values():
        for row in squad.get("passes") or []:
            if row.get("id"):
                kpis.append({"eventId": row["id"], "kpiId": 1404, "value": row.get("pxt")})
    for event_id, xg in (_read("xg-ekpi", str(int(match_id))) or {}).items():
        kpis.append({"eventId": event_id, "kpiId": SHOT_XG_KPI_ID, "value": xg})
    return compact_events([e for e in events if isinstance(e, dict)], kpis)


def _prog_method(step: dict) -> str | None:
    """Short pass / long ball / carry / cross if this step moved the ball forward enough, else None."""
    if step.get("res") != "SUCCESS" or "x1" not in step or "x2" not in step:
        return None
    dx = _num(step["x2"]) - _num(step["x1"])
    if step.get("at") == "DRIBBLE":
        return "carry" if dx >= PROG_CARRY_METRES else None
    if step.get("at") != "PASS":
        return None
    action = str(step.get("a") or "")
    if "CROSS" in action:
        return "cross" if _num(step["x1"]) >= FINAL_THIRD_X - 5 else None
    if dx < PROG_PASS_METRES or _num(step["x2"]) <= -FINAL_THIRD_X:
        return None
    length = ((_num(step["x2"]) - _num(step["x1"])) ** 2 + (_num(step["y2"]) - _num(step["y1"])) ** 2) ** 0.5
    return "long" if length >= 30 or action in LONG_ACTIONS else "short"


def _lane(y: Any) -> str:
    value = _num(y)
    return "left" if value > WIDE_Y else "right" if value < -WIDE_Y else "centre"


def season_packs(league: dict, fixtures: list[dict]) -> dict[int, list[dict]]:
    summaries = league["threat"]["summaries"]
    return {int(f["matchId"]): _match_pack(int(f["matchId"]), summaries.get(int(f["matchId"]))) for f in fixtures}


def progression_view(
    packs: dict[int, list[dict]],
    window_fixtures: list[dict],
    season_fixtures: list[dict],
    squad_id: int,
    names: dict[str, str],
    squad_players: list[dict],
) -> dict[str, Any]:
    """Threat chains (window) and who moves the ball forward (season), from saved events only."""
    from app.attacking_threat import FAMILY_COLORS, action_family, action_label
    from app.attacking_threat_chains import analyse_chains, chain_record, possessions, receiver_of

    window_ids = {int(f["matchId"]) for f in window_fixtures}
    int_names = {int(k): v for k, v in names.items() if str(k).isdigit()}
    chains, window_games, season_games = [], 0, 0
    players: dict[int, dict] = {}
    team = {"prog": 0, "finalThird": 0, "box": 0, "methods": defaultdict(int), "lanes": defaultdict(int)}

    for fixture in season_fixtures:
        match_id = int(fixture["matchId"])
        pack = packs.get(match_id)
        if not pack:
            continue
        season_games += 1
        squad_possessions = possessions(pack, int(squad_id), match_id)
        if match_id in window_ids:
            window_games += 1
            chains.extend(chain_record(item, action_label, action_family) for item in squad_possessions)
        for possession in squad_possessions:
            steps = possession["steps"]
            for index, step in enumerate(steps):
                method = _prog_method(step)
                if not method or not step.get("pl"):
                    continue
                row = players.setdefault(int(step["pl"]), {
                    "prog": 0, "passes": 0, "carries": 0, "finalThird": 0, "box": 0, "threat": 0.0,
                    "methods": defaultdict(int), "lanes": defaultdict(int), "to": defaultdict(int),
                })
                into_final = _num(step["x1"]) < FINAL_THIRD_X <= _num(step["x2"])
                into_box = _num(step["x2"]) >= 36 and abs(_num(step["y2"])) <= 20.16
                row["prog"] += 1
                row["carries" if method == "carry" else "passes"] += 1
                row["finalThird"] += 1 if into_final else 0
                row["box"] += 1 if into_box else 0
                row["threat"] += _num(step.get("v"))
                row["methods"][method] += 1
                row["lanes"][_lane(step["y1"])] += 1
                receiver = receiver_of(steps, index) if method != "carry" else 0
                if receiver:
                    row["to"][receiver] += 1
                team["prog"] += 1
                team["finalThird"] += 1 if into_final else 0
                team["box"] += 1 if into_box else 0
                team["methods"][method] += 1
                team["lanes"][_lane(step["y1"])] += 1

    if not season_games:
        return {"ready": False}

    fixtures_by_id = {int(f["matchId"]): f for f in season_fixtures}
    chain_view = analyse_chains(chains, window_games, int_names, fixtures_by_id,
                                labeler=action_label, familier=action_family, colors=FAMILY_COLORS) if chains else None
    for chain in (chain_view or {}).get("top") or []:
        for step in chain.get("steps") or []:
            if step.get("family") == "shot" and not step.get("shot"):
                step["family"], step["color"] = "pass", FAMILY_COLORS["pass"]

    minutes = {int(p["id"]): _num(p.get("minutes")) for p in squad_players if p.get("id")}
    meta = {int(p["id"]): p for p in squad_players if p.get("id")}
    method_labels = dict(PROG_METHODS)
    rows = []
    for player_id, row in players.items():
        mins = minutes.get(player_id, 0.0)
        if mins < PROG_MIN_MINUTES or row["prog"] < 5 or (meta.get(player_id) or {}).get("band") == "gk":
            continue
        p90 = 90.0 / mins
        methods = sorted(row["methods"].items(), key=lambda item: item[1], reverse=True)
        lanes = sorted(row["lanes"].items(), key=lambda item: item[1], reverse=True)
        targets = sorted(row["to"].items(), key=lambda item: item[1], reverse=True)[:2]
        rows.append({
            "id": player_id,
            "name": int_names.get(player_id) or (meta.get(player_id) or {}).get("name") or f"Player {player_id}",
            "position": (meta.get(player_id) or {}).get("position"),
            "shirt": (meta.get(player_id) or {}).get("shirt"),
            "minutes": int(mins),
            "prog90": round(row["prog"] * p90, 2),
            "passes90": round(row["passes"] * p90, 2),
            "carries90": round(row["carries"] * p90, 2),
            "finalThird90": round(row["finalThird"] * p90, 2),
            "box90": round(row["box"] * p90, 2),
            "threat90": round(row["threat"] * p90, 3),
            "methods": [{"id": key, "label": method_labels[key], "share": round(100 * count / row["prog"])} for key, count in methods],
            "lane": lanes[0][0] if lanes else None,
            "laneShare": round(100 * lanes[0][1] / row["prog"]) if lanes else None,
            "targets": [{"name": int_names.get(pid) or f"Player {pid}", "count": count} for pid, count in targets],
        })
    rows.sort(key=lambda item: item["prog90"], reverse=True)

    total = team["prog"] or 1
    return {
        "ready": True,
        "games": season_games,
        "windowGames": window_games,
        "chains": chain_view,
        "team": {
            "progPerGame": round(team["prog"] / season_games, 1),
            "finalThirdPerGame": round(team["finalThird"] / season_games, 1),
            "boxPerGame": round(team["box"] / season_games, 1),
            "methods": [{"id": key, "label": label, "share": round(100 * team["methods"].get(key, 0) / total),
                         "perGame": round(team["methods"].get(key, 0) / season_games, 1)} for key, label in PROG_METHODS],
            "lanes": {lane: round(100 * team["lanes"].get(lane, 0) / total) for lane in ("left", "centre", "right")},
        },
        "players": rows[:14],
    }


# ---------------------------------------------------------------- trends & timings

BANDS = ("1–15", "16–30", "31–45+", "46–60", "61–75", "76–90+")


def _clock(event: dict) -> tuple[int, int, str]:
    """(minute, stoppage, label) from Impect's "MM:SS.f (+MM:SS.f)" game clock."""
    text = str((event.get("gameTime") or {}).get("gameTime") or "")
    main, _, extra = text.partition("(+")
    try:
        minute = int(main.strip().split(":")[0])
    except ValueError:
        return 0, 0, ""
    if extra:
        try:
            added = int(extra.split(":")[0]) + 1
        except ValueError:
            added = 1
        return minute, added, f"{minute}+{added}"
    return minute, 0, str(minute + 1)


def _band(period: int, minute: int, stoppage: int) -> int | None:
    if period == 1:
        return 2 if stoppage else min(2, minute // 15)
    if period == 2:
        return 5 if stoppage else max(3, min(5, minute // 15))
    return None


def match_goals(match: dict, names: dict[str, str]) -> list[dict] | None:
    """Goals in time order from saved events. None if the events don't add up to the final score."""
    from app.analysis_cache import click_list

    events = click_list("xg-events", str(int(match["matchId"]))) or []
    if not events:
        return None
    home, away = int(match["home"]), int(match["away"])
    goals = []
    for event in events:
        if not isinstance(event, dict):
            continue
        action_type = event.get("actionType")
        own = action_type == "OWN_GOAL"
        if not own and not (action_type == "SHOT" and event.get("result") == "SUCCESS"):
            continue
        squad = int(event.get("squadId") or 0)
        if own:
            squad = away if squad == home else home
        period = int(event.get("periodId") or 0)
        minute, stoppage, label = _clock(event)
        band = _band(period, minute, stoppage)
        if band is None:
            continue
        player_id = str((event.get("player") or {}).get("id") or "")
        goals.append({
            "squad": squad, "period": period, "minute": minute + stoppage / 100, "label": label, "band": band,
            "player": names.get(player_id) or "", "own": own, "pen": str(event.get("action") or "") == "PENALTY_KICK",
        })
    goals.sort(key=lambda g: (g["period"], g["minute"]))
    if sum(1 for g in goals if g["squad"] == home) != int(match["hg"]) or sum(1 for g in goals if g["squad"] == away) != int(match["ag"]):
        return None
    return goals


def _league_goals(base: dict) -> dict[int, list[dict]]:
    names = {str(k): v for k, v in (base.get("players") or {}).items()}

    def build() -> dict[int, list[dict]]:
        out = {}
        for match in base.get("matches") or []:
            goals = match_goals(match, names)
            if goals is not None:
                out[int(match["matchId"])] = goals
        return out

    return _memoized(("goals", base.get("season"), len(base.get("matches") or [])), build)


def _game_state(fixture: dict, goals: list[dict], squad_id: int) -> dict:
    us = them = 0
    led = trailed = False
    first = None
    ht = (0, 0)
    for goal in goals:
        mine = goal["squad"] == squad_id
        if first is None:
            first = "us" if mine else "them"
        if goal["period"] == 1:
            ht = (ht[0] + (1 if mine else 0), ht[1] + (0 if mine else 1))
        us += 1 if mine else 0
        them += 0 if mine else 1
        led = led or us > them
        trailed = trailed or them > us
    return {"first": first, "ht": ht, "led": led, "trailed": trailed, "points": _points(fixture["result"])}


def _timing_stats(fixtures: list[dict], goals_by_match: dict[int, list[dict]], squad_id: int) -> dict | None:
    rows = [(f, goals_by_match[f["matchId"]]) for f in fixtures if f["matchId"] in goals_by_match]
    if not rows:
        return None
    games = len(rows)
    bands_for, bands_against = [0] * 6, [0] * 6
    states = []
    first_minutes = []
    for fixture, goals in rows:
        for goal in goals:
            (bands_for if goal["squad"] == squad_id else bands_against)[goal["band"]] += 1
        mine = [g for g in goals if g["squad"] == squad_id]
        if mine:
            first_minutes.append(int(mine[0]["minute"]) + 1)
        states.append((fixture, _game_state(fixture, goals, squad_id)))
    scored_first = [s for _, s in states if s["first"] == "us"]
    conceded_first = [s for _, s in states if s["first"] == "them"]
    trailed = [s for _, s in states if s["trailed"]]
    led = [s for _, s in states if s["led"]]
    return {
        "games": games,
        "bandsFor": bands_for,
        "bandsAgainst": bands_against,
        "scoredFirst": len(scored_first),
        "concededFirst": len(conceded_first),
        "goalless": games - len(scored_first) - len(conceded_first),
        "scoredFirstPct": round(100 * len(scored_first) / games),
        "ptsAfterScoringFirst": sum(s["points"] for s in scored_first),
        "ptsAfterConcedingFirst": sum(s["points"] for s in conceded_first),
        "recordScoringFirst": [sum(1 for s in scored_first if s["points"] == p) for p in (3, 1, 0)],
        "recordConcedingFirst": [sum(1 for s in conceded_first if s["points"] == p) for p in (3, 1, 0)],
        "ptsFromBehind": sum(s["points"] for s in trailed),
        "gamesBehind": len(trailed),
        "ptsDropped": sum(3 - s["points"] for s in led),
        "gamesAhead": len(led),
        "avgFirstGoal": round(sum(first_minutes) / len(first_minutes)) if first_minutes else None,
        "states": states,
    }


def _ht_ft(states: list[tuple[dict, dict]]) -> list[dict]:
    out = []
    for key, label in (("ahead", "Leading at half-time"), ("level", "Level at half-time"), ("behind", "Behind at half-time")):
        picked = [
            s for _, s in states
            if (s["ht"][0] > s["ht"][1] and key == "ahead") or (s["ht"][0] == s["ht"][1] and key == "level") or (s["ht"][0] < s["ht"][1] and key == "behind")
        ]
        out.append({"key": key, "label": label, "games": len(picked),
                    "w": sum(1 for s in picked if s["points"] == 3), "d": sum(1 for s in picked if s["points"] == 1),
                    "l": sum(1 for s in picked if s["points"] == 0)})
    return out


def _threat_bands(packs: dict[int, list[dict]], fixtures: list[dict], squad_id: int) -> dict | None:
    created, conceded = [0.0] * 6, [0.0] * 6
    games = 0
    for fixture in fixtures:
        pack = packs.get(int(fixture["matchId"]))
        if not pack:
            continue
        games += 1
        for event in pack:
            value = _num(event.get("v"))
            if value <= 0:
                continue
            seconds = _num(event.get("t"))
            period = int(event.get("p") or 0)
            if period == 1:
                minute = (seconds % 10000) / 60
                band = min(2, int(minute // 15))
            elif period == 2:
                minute = (seconds - 10000) / 60 if seconds >= 10000 else seconds / 60 - 45
                band = 3 + min(2, max(0, int(minute // 15)))
            else:
                continue
            (created if event.get("sq") == squad_id else conceded)[band] += value
    if not games:
        return None
    return {"games": games, "for": [round(v / games, 3) for v in created], "against": [round(v / games, 3) for v in conceded]}


def trends_view(base: dict, packs: dict[int, list[dict]], season_fixtures: list[dict], squad_id: int) -> dict[str, Any]:
    """When goals and threat happen, game states and the game-by-game goal timeline. Season only."""
    goals_by_match = _league_goals(base)
    mine = _timing_stats(season_fixtures, goals_by_match, squad_id)
    if not mine:
        return {"ready": False}

    league_rows: dict[int, dict] = {}
    for match in base.get("matches") or []:
        for sid in (int(match["home"]), int(match["away"])):
            if sid not in league_rows:
                stats = _timing_stats(team_fixtures(base, sid), goals_by_match, sid)
                if stats:
                    league_rows[sid] = stats

    def per_game(fn) -> dict[int, float]:
        return {sid: fn(s) / s["games"] for sid, s in league_rows.items() if s["games"]}

    metrics = [
        metric_row("lateFor", "Goals scored 76'+ a game", per_game(lambda s: s["bandsFor"][5]), squad_id),
        metric_row("lateAgainst", "Goals conceded 76'+ a game", per_game(lambda s: s["bandsAgainst"][5]), squad_id, higher=False),
        metric_row("earlyAgainst", "Goals conceded in the first 15' a game", per_game(lambda s: s["bandsAgainst"][0]), squad_id, higher=False),
        metric_row("secondHalfFor", "Second-half goals a game", per_game(lambda s: sum(s["bandsFor"][3:])), squad_id),
        metric_row("scoredFirst", "Score first", {sid: s["scoredFirstPct"] for sid, s in league_rows.items()}, squad_id, digits=0, pct=True),
        metric_row("fromBehind", "Points won from losing positions", {sid: s["ptsFromBehind"] for sid, s in league_rows.items()}, squad_id, digits=0),
        metric_row("dropped", "Points dropped from winning positions", {sid: s["ptsDropped"] for sid, s in league_rows.items()}, squad_id, higher=False, digits=0),
    ]
    timeline = []
    for fixture, state in reversed(mine["states"]):
        goals = goals_by_match.get(fixture["matchId"]) or []
        timeline.append({
            "matchId": fixture["matchId"], "date": fixture["date"], "opponent": fixture["opponent"], "badge": fixture["badge"],
            "home": fixture["home"], "score": fixture["score"], "result": fixture["result"],
            "ht": f"{state['ht'][0]}-{state['ht'][1]}",
            "goals": [{"us": g["squad"] == squad_id, "label": g["label"], "period": g["period"], "minute": g["minute"],
                       "player": g["player"], "own": g["own"], "pen": g["pen"]} for g in goals],
        })
    missing = len(season_fixtures) - mine["games"]
    return {
        "ready": True,
        "games": mine["games"],
        "missing": missing,
        "bands": [{"label": label, "for": mine["bandsFor"][i], "against": mine["bandsAgainst"][i]} for i, label in enumerate(BANDS)],
        "threatBands": _threat_bands(packs, season_fixtures, squad_id),
        "metrics": {row["id"]: row for row in metrics},
        "states": {key: mine[key] for key in (
            "scoredFirst", "concededFirst", "goalless", "scoredFirstPct", "ptsAfterScoringFirst", "ptsAfterConcedingFirst",
            "recordScoringFirst", "recordConcedingFirst", "ptsFromBehind", "gamesBehind", "ptsDropped", "gamesAhead", "avgFirstGoal",
        )},
        "htft": _ht_ft(mine["states"]),
        "timeline": timeline,
    }


# ---------------------------------------------------------------- set plays


def set_play_view(base: dict, squad_id: int, window: str) -> dict[str, Any] | None:
    """Set Plays report with the opponent as the focus club. Reads saved packs only."""
    from app import set_plays as sp

    ids = [int(m["matchId"]) for m in base.get("matches") or []]
    packs = _memoized(("sp-packs", base.get("season"), len(ids)), lambda: sp.load_packs(ids, fetch=False))
    if not packs:
        return None
    focus_base = dict(base, valeId=int(squad_id))
    report = sp.build_report(focus_base, packs, "last6" if window == "last6" else "season")
    if not report.get("matchCount"):
        return None
    attack, defence = report.get("attack") or {}, report.get("defence") or {}
    return {
        "games": report["matchCount"],
        "headline": report.get("headline") or {},
        "benchmarks": report.get("benchmarks") or [],
        "plan": report.get("plan") or [],
        "table": report.get("table") or [],
        "minutes": report.get("minutes") or [],
        "attack": {k: attack.get(k) for k in ("summary", "buckets", "zones", "deliveries", "takers", "targets", "goals", "fkAreas")},
        "defence": {k: defence.get(k) for k in ("summary", "buckets", "zones", "deliveries", "defenders", "goals", "gk")},
    }


# ---------------------------------------------------------------- squad (Pre-Match report)


def _vale_fixture_rows(iteration_id: int) -> list[dict]:
    cached = _read("pre-match-fixtures", f"fixtures_{int(iteration_id)}") or {}
    rows = cached.get("fixtures")
    if isinstance(rows, list) and rows:
        return [row for row in rows if isinstance(row, dict)]
    from app.analysis_cache import all_json

    for body in all_json("pre-match-fixtures"):
        if isinstance(body.get("fixtures"), list) and body["fixtures"]:
            return [row for row in body["fixtures"] if isinstance(row, dict)]
    return []


def _parse_dt(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def vale_fixture_for(iteration_id: int, squad_id: int, *, now: datetime | None = None) -> dict | None:
    """The next Port Vale fixture against this club, else the most recent one."""
    now = now or datetime.now(UTC)
    rows = [row for row in _vale_fixture_rows(iteration_id) if int((row.get("opponent") or {}).get("id") or 0) == int(squad_id)]
    rows.sort(key=lambda row: str(row.get("scheduled_date") or ""))
    upcoming = [row for row in rows if (_parse_dt(row.get("scheduled_date")) or now) >= now and not row.get("played")]
    if upcoming:
        return upcoming[0]
    return rows[-1] if rows else None


def next_opponent(iteration_id: int, *, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(UTC)
    rows = sorted(_vale_fixture_rows(iteration_id), key=lambda row: str(row.get("scheduled_date") or ""))
    for row in rows:
        when = _parse_dt(row.get("scheduled_date"))
        if row.get("played") or (when and when < now):
            continue
        opponent = row.get("opponent") or {}
        if opponent.get("id"):
            return {
                "squadId": int(opponent["id"]),
                "name": opponent.get("name"),
                "matchId": row.get("match_id"),
                "date": row.get("scheduled_date"),
                "home": bool(row.get("is_home")),
            }
    return None


def _squad_cache_key(iteration_id: int, squad_id: int, match_id: int | None) -> str:
    return f"report_{int(iteration_id)}_{int(squad_id)}_{int(match_id or 0)}"


def _build_state(cache_key: str) -> dict | None:
    from app import pre_match

    with pre_match._background_builds_lock:
        state = pre_match._background_builds.get(cache_key)
        return dict(state) if state else None


LEADER_LABELS = {
    "pxt": "Threat /90",
    "ball_progression": "Progression",
    "bypassed_defenders": "Line-breaker",
    "regains_vs_defenders": "Wins it high",
    "offensive_interventions": "Interventions",
    "presses": "Presser",
    "duel_rate": "Duels",
}


def squad_view(
    base: dict,
    squad_id: int,
    fixtures: list[dict],
    threat_players: dict[str, dict],
    set_play: dict | None,
) -> dict[str, Any]:
    from app import pre_match

    iteration_id = int(base.get("iterationId") or 0)
    vale_fixture = vale_fixture_for(iteration_id, squad_id)
    match_id = int(vale_fixture["match_id"]) if vale_fixture and vale_fixture.get("match_id") else None
    cache_key = _squad_cache_key(iteration_id, squad_id, match_id)
    report = pre_match._pre_match_report_from_disk(iteration_id, squad_id, match_id)
    state = _build_state(cache_key)
    if not report:
        return {"ready": False, "build": state, "fixture": vale_fixture}

    form_dates = [str(row.get("date") or "") for row in report.get("form") or []]
    covered_to = max(form_dates) if form_dates else ""
    games_since = sum(1 for row in fixtures if row["date"] > covered_to) if covered_to else 0
    covered = [row for row in fixtures if not covered_to or row["date"] <= covered_to]
    log_fixtures = covered[-LOG_MATCHES:]
    games_available = len(covered)
    # Pre-Match squad totals can include cup games, so never divide by fewer games than a player has played.
    share_games = max([games_available] + [int(row.get("appearances") or 0) for row in report.get("squad") or []])
    # Minutes include stoppage time, so a 90-minute game is often logged as 95+.
    share_minutes = max([share_games * 90] + [int(row.get("minutes") or 0) for row in report.get("squad") or []])

    sp_attack = (set_play or {}).get("attack") or {}
    taker_rows = sorted(sp_attack.get("takers") or [], key=lambda row: -int(row.get("deliveries") or 0))
    takers = {int(row["id"]): row for row in taker_rows[:3] if int(row.get("deliveries") or 0) >= 6}
    target_rows = [row for row in sp_attack.get("targets") or [] if int(row.get("fcWon") or 0) >= 3 or int(row.get("goals") or 0)]
    target_rows.sort(key=lambda row: (-int(row.get("goals") or 0), -_num(row.get("xg")), -int(row.get("fcWon") or 0)))
    targets = {int(row["id"]): row for row in target_rows[:4]}
    all_takers = {int(row["id"]): row for row in sp_attack.get("takers") or [] if row.get("id")}
    all_targets = {int(row["id"]): row for row in sp_attack.get("targets") or [] if row.get("id")}
    defenders = {int(row["id"]): row for row in ((set_play or {}).get("defence") or {}).get("defenders") or [] if row.get("id")}
    danger = [pid for pid, _ in sorted(threat_players.items(), key=lambda kv: -_num(kv[1].get("pxt")))[:3]]
    leaders: dict[int, list[dict]] = {}
    rankings_raw = report.get("player_rankings") or {}
    for side in ("in_possession", "out_of_possession"):
        for group in rankings_raw.get(side) or []:
            label = LEADER_LABELS.get(str(group.get("key")))
            if not label:
                continue
            for rank, entry in enumerate(group.get("players") or [], start=1):
                if entry.get("id") is not None and rank == 1:
                    leaders.setdefault(int(entry["id"]), []).append({
                        "label": label, "rank": rank, "value": entry.get("value_label"), "side": side,
                    })
    players = []
    for row in report.get("squad") or []:
        player_id = int(row.get("id") or 0)
        log = {int(entry["m"]): entry for entry in row.get("match_log") or [] if entry.get("m") is not None}
        threat = threat_players.get(str(player_id)) or {}
        minutes = int(row.get("minutes") or 0)
        recent = [log.get(int(f["matchId"])) for f in log_fixtures]
        recent_minutes = sum(int(entry["min"]) for entry in recent if entry)
        tags = []
        if share_games and row.get("starts", 0) >= max(1, share_games - 1):
            tags.append("Ever-present")
        if log and log_fixtures and all(not entry or not entry.get("min") for entry in recent[-3:]) and minutes >= 270:
            tags.append("Not played lately")
        if log and len([e for e in recent[-3:] if e and e.get("s")]) == 3 and row.get("starts", 0) <= 4:
            tags.append("Recently in the XI")
        if str(player_id) in danger:
            tags.append("Danger man")
        if player_id in takers:
            tags.append("Set-piece taker")
        if player_id in targets:
            tags.append("Set-piece target")
        taker = all_takers.get(player_id)
        target = all_targets.get(player_id)
        defender = defenders.get(player_id)
        set_plays = {}
        if taker and int(taker.get("deliveries") or 0) >= 3:
            set_plays["taker"] = {
                "deliveries": int(taker.get("deliveries") or 0), "corners": int(taker.get("corners") or 0),
                "freeKicks": int(taker.get("freeKicks") or 0), "foot": taker.get("foot"),
                "inswing": int(taker.get("inswing") or 0), "outswing": int(taker.get("outswing") or 0),
                "topZone": taker.get("topZone"), "goals": int(taker.get("goals") or 0),
            }
        if target and (int(target.get("fcWon") or 0) >= 2 or int(target.get("goals") or 0)):
            set_plays["target"] = {
                "fcWon": int(target.get("fcWon") or 0), "shots": int(target.get("shots") or 0),
                "goals": int(target.get("goals") or 0), "xg": round(_num(target.get("xg")), 2),
            }
        if defender and int(defender.get("involvements") or 0) >= 3:
            set_plays["defending"] = {
                "won": int(defender.get("won") or 0), "lost": int(defender.get("lostDuels") or 0),
                "lostOnShot": int(defender.get("lostOnShot") or 0), "lostOnGoal": int(defender.get("lostOnGoal") or 0),
                "winPct": defender.get("winPct"),
            }
        goal_inv = int(row.get("goals") or 0) + int(row.get("assists") or 0)
        players.append({
            "id": player_id,
            "name": row.get("name"),
            "shirt": row.get("shirt_number"),
            "position": row.get("position"),
            "positionCode": row.get("position_code"),
            "band": row.get("band"),
            "age": row.get("age"),
            "foot": row.get("foot"),
            "apps": int(row.get("appearances") or 0),
            "starts": int(row.get("starts") or 0),
            "minutes": minutes,
            "minutesShare": round(100.0 * minutes / share_minutes, 0) if share_minutes else None,
            "goals": int(row.get("goals") or 0),
            "assists": int(row.get("assists") or 0),
            "current": bool(row.get("current")),
            "threat": round(_num(threat.get("pxt")), 3) if threat else None,
            "threat90": round(_num(threat.get("pxt")) * 90.0 / minutes, 3) if threat and minutes >= 90 else None,
            "threatShare": round(_num(threat.get("share")), 1) if threat and threat.get("share") is not None else None,
            "ga90": round(goal_inv * 90.0 / minutes, 2) if minutes >= 270 else None,
            "setPlays": set_plays,
            "leaders": leaders.get(player_id, []),
            "recentMinutes": recent_minutes if log else None,
            "log": [
                {"min": int(entry["min"]), "start": bool(entry.get("s")), "g": int(entry.get("g") or 0), "a": int(entry.get("a") or 0)}
                if entry else None
                for entry in recent
            ] if log else None,
            "tags": tags,
            "photo": "/api/pre-match/player-photo?" + urlencode({
                "name": row.get("name") or "", "club": _club(base, squad_id), "season": base.get("season") or "",
                **({"shirt": row["shirt_number"]} if row.get("shirt_number") is not None else {}),
            }),
        })

    squad_list = report.get("squad_list") or {}
    formation = squad_list.get("formation_analysis") or {}
    xis = []
    for xi in report.get("previous_xis") or []:
        xis.append({
            "date": xi.get("date"), "opponent": xi.get("opponent"), "venue": xi.get("venue"),
            "result": xi.get("result"), "score": xi.get("score"), "formation": xi.get("formation"),
            "players": [{
                "name": p.get("name"), "short": p.get("short_name"), "shirt": p.get("shirt_number"),
                "position": p.get("position"), "x": p.get("x_pct"), "y": p.get("y_pct"),
            } for p in xi.get("pitch_players") or []],
        })
    goals = report.get("goals_analysis") or {}
    rankings = report.get("player_rankings") or {}

    def trim_rankings(groups: list[dict]) -> list[dict]:
        return [{
            "key": g.get("key"), "label": g.get("label"), "subtitle": g.get("subtitle"),
            "players": [{
                "name": p.get("name"), "shirt": p.get("shirt_number"), "value": p.get("value_label") or p.get("value"),
                "minutes": p.get("minutes"),
            } for p in (g.get("players") or [])[:5]],
        } for g in groups or [] if g.get("players")]

    return {
        "ready": True,
        "build": state,
        "fixture": vale_fixture,
        "builtAt": report.get("generated_at"),
        "coveredTo": covered_to,
        "gamesSince": games_since,
        "gamesAvailable": games_available,
        "manager": (report.get("overview") or {}).get("manager") or squad_list.get("manager"),
        "formations": (report.get("overview") or {}).get("formations") or [],
        "formationUsage": formation.get("usage") or [],
        "resultsByShape": formation.get("results_by_shape") or [],
        "vsShapes": formation.get("vs_opponent") or [],
        "players": players,
        "logFixtures": [{k: f[k] for k in ("matchId", "date", "opponent", "badge", "home", "score", "result")} for f in log_fixtures],
        "hasLog": any(p["log"] for p in players),
        "xis": xis,
        "style": (report.get("team_style") or {}).get("radar") or [],
        "styleSummary": (report.get("team_style") or {}).get("summary") or [],
        "archetype": (report.get("team_style") or {}).get("archetype"),
        "teamMetrics": report.get("team_metrics") or {},
        "keyStats": squad_list.get("key_stats") or {},
        "goals": {
            "summary": goals.get("summary") or {},
            "for": {k: (goals.get("for") or {}).get(k) for k in ("total", "phases", "types")},
            "against": {k: (goals.get("against") or {}).get(k) for k in ("total", "phases", "types")},
        },
        "rankings": {
            "inPossession": trim_rankings(rankings.get("in_possession") or []),
            "outOfPossession": trim_rankings(rankings.get("out_of_possession") or []),
        },
    }


def queue_squad_build(season: str | None, squad_id: int) -> dict[str, Any]:
    """The one Impect path: queue the Pre-Match background build for this opponent."""
    from app import pre_match
    from app.brand import is_demo

    if is_demo():
        return {"status": "unavailable", "detail": "Blank demo hub — no club data."}
    base = season_base(season)
    if not base:
        raise ValueError("No saved season for that choice yet.")
    iteration_id = int(base["iterationId"])
    fixture = vale_fixture_for(iteration_id, squad_id)
    match_id = int(fixture["match_id"]) if fixture and fixture.get("match_id") else None
    body = pre_match.PreMatchReportRequest(iteration_id=iteration_id, squad_id=int(squad_id), match_id=match_id, refresh=True)
    clear_memo()
    return pre_match._queue_background_build(_squad_cache_key(iteration_id, squad_id, match_id), body)


# ---------------------------------------------------------------- matchup and game plan


MATCHUPS: tuple[dict[str, Any], ...] = (
    # Their attack against our defence.
    {"side": "theirAttack", "label": "Chance creation (npxG)", "them": "xgFor", "us": "xgAgainst"},
    {"side": "theirAttack", "label": "Big chances", "them": "bigFor", "us": "bigAgainst"},
    {"side": "theirAttack", "label": "Attacking threat", "them": "threatFor", "us": "threatAgainst"},
    {"side": "theirAttack", "label": "Transitions", "them": "phaseFor:ATTACKING_TRANSITION", "us": "phaseAgainst:ATTACKING_TRANSITION"},
    {"side": "theirAttack", "label": "Crosses", "them": "famFor:cross", "us": "famAgainst:cross"},
    {"side": "theirAttack", "label": "Set-play xG", "them": "sp:xgFor", "us": "sp:xgAgainst"},
    {"side": "theirAttack", "label": "Ball wins off defenders", "them": "bwd", "us": "bwdAgainst"},
    # Our attack against their defence.
    {"side": "ourAttack", "label": "Chance creation (npxG)", "them": "xgAgainst", "us": "xgFor"},
    {"side": "ourAttack", "label": "Big chances", "them": "bigAgainst", "us": "bigFor"},
    {"side": "ourAttack", "label": "Attacking threat", "them": "threatAgainst", "us": "threatFor"},
    {"side": "ourAttack", "label": "Transitions", "them": "phaseAgainst:ATTACKING_TRANSITION", "us": "phaseFor:ATTACKING_TRANSITION"},
    {"side": "ourAttack", "label": "Crosses", "them": "famAgainst:cross", "us": "famFor:cross"},
    {"side": "ourAttack", "label": "Set-play xG", "them": "sp:xgAgainst", "us": "sp:xgFor"},
    {"side": "ourAttack", "label": "Ball wins off defenders", "them": "bwdAgainst", "us": "bwd"},
    # Head to head in the duels.
    {"side": "battle", "label": "Aerial duels won", "them": "aerialPct", "us": "aerialPct"},
    {"side": "battle", "label": "Ground duels won", "them": "groundPct", "us": "groundPct"},
    {"side": "battle", "label": "Duels won", "them": "duelPct", "us": "duelPct"},
    {"side": "battle", "label": "Ball wins", "them": "bw", "us": "bw"},
)


def set_play_metrics(table: list[dict], squad_id: int) -> dict[str, dict[str, Any]]:
    rows = [row for row in table or [] if row.get("squadId") is not None]
    if not rows:
        return {}

    def values(key: str) -> dict[int, float]:
        return {int(r["squadId"]): float(r[key]) for r in rows if r.get(key) is not None}

    return {
        "sp:xgFor": metric_row("sp:xgFor", "Set-play xG / game", values("xgFor"), squad_id),
        "sp:xgAgainst": metric_row("sp:xgAgainst", "Set-play xG conceded / game", values("xgAgainst"), squad_id, higher=False),
        "sp:goalsFor": metric_row("sp:goalsFor", "Set-play goals / game (no pens)", values("goalsFor"), squad_id),
        "sp:goalsAgainst": metric_row("sp:goalsAgainst", "Set-play goals conceded / game", values("goalsAgainst"), squad_id, higher=False),
        "sp:fcAttack": metric_row("sp:fcAttack", "First contacts won attacking set plays", values("fcAttack"), squad_id, digits=0, pct=True),
        "sp:fcDefence": metric_row("sp:fcDefence", "First contacts won defending set plays", values("fcDefence"), squad_id, digits=0, pct=True),
        "sp:cornersFor": metric_row("sp:cornersFor", "Corners won / game", values("cornersFor"), squad_id, digits=1),
    }


def matchup(them: dict[str, dict], us: dict[str, dict]) -> list[dict[str, Any]]:
    rows = []
    for spec in MATCHUPS:
        a, b = them.get(spec["them"]), us.get(spec["us"])
        if not a or not b or a.get("rank") is None or b.get("rank") is None:
            continue
        edge = "vale" if b["rank"] < a["rank"] else "them" if a["rank"] < b["rank"] else "even"
        rows.append({
            "side": spec["side"], "label": spec["label"],
            "them": {k: a[k] for k in ("value", "rank", "of", "label", "digits", "pct")},
            "us": {k: b[k] for k in ("value", "rank", "of", "label", "digits", "pct")},
            "edge": edge,
            "gap": abs(int(a["rank"]) - int(b["rank"])),
        })
    return rows


# id, strength text, weakness text — {v} value, {r} ordinal rank, {of} league size.
PLAN_TEXT: tuple[tuple[str, str, str], ...] = (
    ("xgFor", "They create good chances — {v} npxG a game ({r} of {of}). Protect the box and limit clean shots.",
     "They struggle to create — {v} npxG a game ({r} of {of}). Make them break a set block down."),
    ("xgAgainst", "Hard to create against — {v} npxG conceded a game ({r} of {of}). Expect few clear chances; be patient.",
     "They leak chances — {v} npxG conceded a game ({r} of {of}). We will get opportunities; be clinical."),
    ("bigAgainst", "They rarely give up big chances ({r} of {of}).",
     "They concede big chances — {v} a game ({r} of {of}). Get runners into the six-yard box."),
    ("phaseFor:ATTACKING_TRANSITION", "Dangerous on the break — {v} threat a game from transitions ({r} of {of}). Keep rest-defence numbers behind the ball.",
     "Little threat in transition ({r} of {of}). We can commit numbers forward."),
    ("phaseAgainst:ATTACKING_TRANSITION", "Well set when they lose it ({r} of {of}) — counter-pressing won't come easy.",
     "Vulnerable when they lose the ball — {v} transition threat conceded a game ({r} of {of}). Win it and go."),
    ("famFor:cross", "Crossing is a main weapon — {v} threat a game from crosses ({r} of {of}). Stop the delivery and win first contact.",
     "Rarely dangerous from crosses ({r} of {of})."),
    ("famAgainst:cross", "Defend crosses well ({r} of {of}) — vary the attack.",
     "Concede from crosses — {v} threat a game ({r} of {of}). Get wide and deliver early."),
    ("phaseFor:SET_PIECE", "Big set-piece threat ({r} of {of}). Prepare blocks and markers — see Set plays.",
     "Little threat from their own set pieces ({r} of {of})."),
    ("sp:xgAgainst", "Defend set plays well — {v} set-play xG conceded a game ({r} of {of}).",
     "Weak defending set plays — {v} xG conceded a game ({r} of {of}). Win corners and free kicks in the final third."),
    ("aerialPct", "Dominant in the air — {v}% of aerials won ({r} of {of}). Keep the ball on the floor.",
     "Weak in the air — only {v}% of aerials won ({r} of {of}). Go direct and attack the box."),
    ("groundPct", "Strong in ground duels — {v}% won ({r} of {of}).",
     "Lose ground duels — {v}% won ({r} of {of}). Be aggressive in 1v1s and take players on."),
    ("bwd", "Win it high off defenders — {v} ball wins vs defenders a game ({r} of {of}). Be secure building out from the back.",
     "Don't win it high often ({r} of {of}). We can build out with confidence."),
    ("bwdAgainst", "Secure in their own build-up ({r} of {of}).",
     "Lose the ball in their back line — {v} a game ({r} of {of}). Press their centre-backs."),
    ("longShare", "Direct side — {v}% of their passing threat comes from long balls ({r} of {of}). Win the first and second ball.",
     "Play through on the floor — only {v}% of passing threat from long balls ({r} of {of}). Press their midfield and cut central passes."),
    ("finishing", "Clinical — {v} goals above xG ({r} of {of}). Don't give up half-chances.",
     "Wasteful — {v} goals vs xG ({r} of {of}). They miss chances they should score."),
)


def game_plan(
    metrics: dict[str, dict],
    battles: list[dict],
    threat: dict,
    set_play: dict | None,
    squad: dict,
    club: str,
    venue_record: dict | None,
    vale_home: bool | None,
) -> dict[str, list[dict[str, str]]]:
    strengths, weaknesses, notes = [], [], []
    for metric_id, strong, weak in PLAN_TEXT:
        row = metrics.get(metric_id)
        if not row or row.get("rank") is None or row.get("value") is None:
            continue
        of = int(row.get("of") or 24)
        cut = max(1, min(STRONG_RANK, of // 4))
        value = row["value"]
        text_value = f"{value:.0f}" if row.get("pct") else (f"{value:+.1f}" if metric_id == "finishing" else f"{value}")
        fields = {"v": text_value, "r": _ordinal(row["rank"]), "of": of}
        if row["rank"] <= cut:
            strengths.append({"metric": metric_id, "rank": row["rank"], "text": strong.format(**fields), "label": row["label"]})
        elif row["rank"] > of - cut:
            weaknesses.append({"metric": metric_id, "rank": row["rank"], "text": weak.format(**fields), "label": row["label"]})
    strengths.sort(key=lambda item: item["rank"])
    weaknesses.sort(key=lambda item: -item["rank"])

    decisive = [b for b in battles if b.get("ppgGap") is not None and b["won"]["games"] >= 2 and b["lost"]["games"] >= 2 and b["id"] != "di"]
    if decisive:
        top = decisive[0]
        notes.append({
            "tone": "info",
            "title": f"Beat them in the {top['label'].lower()} battle",
            "text": (
                f"When {club} win it they take {top['won']['ppg']:.2f} points a game "
                f"({top['won']['w']}W {top['won']['d']}D {top['won']['l']}L). When they lose it: "
                f"{top['lost']['ppg']:.2f} ({top['lost']['w']}W {top['lost']['d']}D {top['lost']['l']}L)."
            ),
        })
    danger = (threat.get("players") or [])[:3]
    if danger:
        names = ", ".join(f"{p['name']} ({p['perGame']:.2f} a game)" for p in danger)
        notes.append({"tone": "bad", "title": "Danger men — most attacking threat", "text": names + "."})
    if set_play:
        takers = (set_play.get("attack") or {}).get("takers") or []
        targets = (set_play.get("attack") or {}).get("targets") or []
        bits = []
        if takers:
            t = takers[0]
            swing = "inswing" if t.get("inswing", 0) > t.get("outswing", 0) else "outswing" if t.get("outswing", 0) else ""
            bits.append(f"{t['name']} takes most ({t['deliveries']} deliveries{', ' + t['foot'].lower() + ' foot' if t.get('foot') else ''}{', mostly ' + swing if swing else ''}, aimed at the {str(t.get('topZone') or '').lower()})")
        if targets:
            bits.append(f"main target {targets[0]['name']} ({targets[0]['fcWon']} first contacts, {targets[0]['goals']} goals)")
        if bits:
            notes.append({"tone": "info", "title": "Set plays: who to watch", "text": "; ".join(bits) + "."})
    usage = squad.get("formationUsage") or []
    if usage:
        main = usage[0]
        notes.append({
            "tone": "info",
            "title": f"Shape: {main.get('formation')} ({main.get('time_pct', 0):.0f}% of minutes)",
            "text": "Other shapes: " + (", ".join(f"{u.get('formation')} {u.get('time_pct', 0):.0f}%" for u in usage[1:3]) or "none") + ".",
        })
    if venue_record and venue_record.get("played") and vale_home is not None:
        where = "away" if vale_home else "at home"
        notes.append({
            "tone": "good" if (venue_record.get("ppg") or 0) < 1.2 else "bad" if (venue_record.get("ppg") or 0) >= 1.8 else "info",
            "title": f"{club} {where}: {venue_record['w']}W {venue_record['d']}D {venue_record['l']}L",
            "text": f"{venue_record['ppg']:.2f} points a game, {venue_record['gf']} scored and {venue_record['ga']} conceded {where}.",
        })
    return {"strengths": strengths[:6], "weaknesses": weaknesses[:6], "notes": notes}


# ---------------------------------------------------------------- report


def _league_pack(base: dict) -> dict[str, Any]:
    key = ("league", base.get("season"), len(base.get("matches") or []))

    def build() -> dict[str, Any]:
        return {
            "threat": threat_league(base),
            "iv": iv_league(base),
            "xg": xg_league(base),
            "table": league_table(base),
        }

    return _memoized(key, build)


def _all_metrics(league: dict, set_play: dict | None, squad_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    out.update(threat_metrics(league["threat"], squad_id))
    out.update(iv_metrics(league["iv"], squad_id))
    out.update(xg_metrics(league["xg"], squad_id))
    out.update(set_play_metrics((set_play or {}).get("table") or [], squad_id))
    return out


def _window(window: str | None) -> str:
    value = (window or "season").strip().lower()
    if value not in {"season", "last6"}:
        raise ValueError("window must be season or last6")
    return value


def vale_fixture_strip(base: dict, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every Port Vale league fixture this season, oldest first, with results where played."""
    now = now or datetime.now(UTC)
    vale_id = int(base["valeId"])
    results = {row["matchId"]: row for row in team_fixtures(base, vale_id)}
    strip = []
    for row in sorted(_vale_fixture_rows(int(base["iterationId"])), key=lambda r: str(r.get("scheduled_date") or "")):
        opponent = row.get("opponent") or {}
        if not opponent.get("id") or not row.get("match_id"):
            continue
        match_id = int(row["match_id"])
        squad_id = int(opponent["id"])
        result = results.get(match_id)
        when = _parse_dt(row.get("scheduled_date"))
        strip.append({
            "matchId": match_id,
            "squadId": squad_id,
            "name": opponent.get("name") or _club(base, squad_id),
            "badge": _badge(squad_id, _club(base, squad_id) or opponent.get("name") or ""),
            "date": row.get("scheduled_date"),
            "home": bool(row.get("is_home")),
            "played": bool(result) or bool(row.get("played")) or bool(when and when < now - timedelta(hours=3)),
            "score": result["score"] if result else None,
            "result": result["result"] if result else None,
        })
    return strip


def read_meta() -> dict[str, Any]:
    seasons = []
    for season in ALLOWED_SEASONS:
        base = season_base(season)
        if base:
            seasons.append({"value": base.get("season") or season, "label": base.get("season") or season})
    default = seasons[0]["value"] if seasons else ALLOWED_SEASONS[0]
    base = season_base(default)
    teams, upcoming, strip = [], None, []
    if base:
        strip = vale_fixture_strip(base)
        vale_id = int(base["valeId"])
        squad_ids = {int(m["home"]) for m in base["matches"]} | {int(m["away"]) for m in base["matches"]}
        teams = sorted(
            ({"id": sid, "name": _club(base, sid), "badge": _badge(sid, _club(base, sid))} for sid in squad_ids if sid != vale_id),
            key=lambda row: row["name"].casefold(),
        )
        upcoming = next_opponent(int(base["iterationId"]))
    return {
        "seasons": seasons,
        "defaultSeason": default,
        "teams": teams,
        "next": upcoming,
        "fixtures": strip,
        "ready": bool(base),
        "message": None if base else "The data lake has no saved season yet. Use Refresh data on the hub, then come back.",
    }


def build_report(season: str | None, squad_id: int, window: str | None = "season") -> dict[str, Any]:
    normalized = _window(window)
    base = season_base(season)
    if not base:
        return {"ready": False, "message": "The data lake has no saved season yet. Use Refresh data on the hub, then come back."}
    squad_id = int(squad_id)
    vale_id = int(base["valeId"])
    all_fixtures = team_fixtures(base, squad_id)
    if not all_fixtures:
        return {"ready": False, "message": f"No completed league games for {_club(base, squad_id)} in {base.get('season')}."}
    selected = select_window(all_fixtures, normalized)
    league = _league_pack(base)
    players = base.get("players") or {}
    club = _club(base, squad_id)

    set_play = _memoized(("sp", base.get("season"), squad_id, normalized, len(base["matches"])),
                         lambda: set_play_view(base, squad_id, normalized))
    vale_set_play = _memoized(("sp", base.get("season"), vale_id, "season", len(base["matches"])),
                              lambda: set_play_view(base, vale_id, "season"))
    season_set_play = set_play if normalized == "season" else _memoized(
        ("sp", base.get("season"), squad_id, "season", len(base["matches"])),
        lambda: set_play_view(base, squad_id, "season"),
    )
    metrics = _all_metrics(league, season_set_play, squad_id)
    vale_metrics = _all_metrics(league, vale_set_play, vale_id)

    threat = threat_window(league["threat"], selected, squad_id, players)
    season_threat = threat if normalized == "season" else threat_window(league["threat"], all_fixtures, squad_id, players)
    threat_players = {
        str(p["id"]): {"pxt": p["total"], "share": p.get("share"), "count": p.get("count")}
        for p in season_threat.get("players") or []
    }
    squad = squad_view(base, squad_id, all_fixtures, threat_players, season_set_play)
    events_key = (base.get("season"), squad_id, len(base["matches"]))
    progression = _memo_peek(("prog", *events_key, normalized))
    trends = _memo_peek(("trends", *events_key))
    if progression is None or trends is None:
        packs = season_packs(league, all_fixtures)
        progression = _memoized(
            ("prog", *events_key, normalized),
            lambda: progression_view(packs, selected, all_fixtures, squad_id, players, squad.get("players") or []),
        )
        trends = _memoized(("trends", *events_key), lambda: trends_view(base, packs, all_fixtures, squad_id))
    battles = iv_battles(league["iv"], selected, squad_id)
    xg = xg_window(league["xg"], selected, squad_id)

    table = league["table"]
    position = next((row for row in table if row["squadId"] == squad_id), None)
    upcoming = squad.get("fixture") or vale_fixture_for(int(base["iterationId"]), squad_id)
    vale_home = bool(upcoming.get("is_home")) if upcoming else None
    home_rec = record([f for f in all_fixtures if f["home"]])
    away_rec = record([f for f in all_fixtures if not f["home"]])
    venue_record = (away_rec if vale_home else home_rec) if vale_home is not None else None

    plan = game_plan(metrics, battles["battles"], season_threat, season_set_play, squad, club, venue_record, vale_home)

    return {
        "ready": True,
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": base.get("season"),
        "window": normalized,
        "club": {"id": squad_id, "name": club, "badge": _badge(squad_id, club)},
        "vale": {"id": vale_id, "name": _club(base, vale_id), "badge": "/standalone/port-vale-badge.png?v=2"},
        "fixture": {
            "matchId": upcoming.get("match_id"),
            "date": upcoming.get("scheduled_date"),
            "valeHome": vale_home,
            "played": bool(upcoming.get("played")),
            "label": upcoming.get("kickoff_label"),
        } if upcoming else None,
        "games": len(selected),
        "seasonGames": len(all_fixtures),
        "position": position,
        "leagueTable": table,
        "record": record(selected),
        "home": home_rec,
        "away": away_rec,
        "fixtures": list(reversed(selected)),
        "h2h": head_to_head(squad_id, vale_id),
        "metrics": metrics,
        "valeMetrics": vale_metrics,
        "matchup": matchup(metrics, vale_metrics),
        "plan": plan,
        "threat": threat,
        "xg": xg,
        "interventions": battles,
        "setPlays": set_play,
        "squad": squad,
        "progression": progression,
        "trends": trends,
    }


def read_report(season: str | None, squad_id: int, window: str | None = "season") -> dict[str, Any]:
    normalized = _window(window)
    key = ("report", _season_key(season), int(squad_id), normalized)
    with _memo_lock:
        hit = _memo.get(key)
        if hit and time.time() - hit[0] < MEMO_TTL_SECONDS:
            return hit[1]
    report = build_report(season, squad_id, normalized)
    squad = report.get("squad") or {}
    building = (squad.get("build") or {}).get("status") == "running"
    if report.get("ready") and squad.get("ready") and not building:
        with _memo_lock:
            _memo[key] = (time.time(), report)
    return report


# ---------------------------------------------------------------- routes


def register_opposition_hub_routes(app: FastAPI) -> None:
    @app.get("/opposition-hub")
    def opposition_hub_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "opposition-hub.html")

    @app.get("/api/opposition-hub/meta")
    def opposition_hub_meta() -> JSONResponse:
        return JSONResponse(read_meta(), headers={"Cache-Control": "no-store"})

    @app.get("/api/opposition-hub/report")
    def opposition_hub_report(
        squad_id: int = Query(..., alias="squadId"),
        season: str | None = Query(None),
        window: str | None = Query("season"),
    ) -> JSONResponse:
        try:
            payload = read_report(season, squad_id, window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.post("/api/opposition-hub/squad-build")
    def opposition_hub_squad_build(
        squad_id: int = Query(..., alias="squadId"),
        season: str | None = Query(None),
    ) -> JSONResponse:
        try:
            state = queue_squad_build(season, squad_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(state, headers={"Cache-Control": "no-store"})
