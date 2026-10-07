"""Set Plays — Port Vale's corners, free kicks, throw-ins and penalties, both ends.

Every League Two match is reduced to compact set-play records (``sp-pack``)
in the analysis data lake. Reports for the season, last 6 and each Port Vale
match are built from those packs during the hub's analysis refresh and saved as
``sp-report``. Opening the page only reads the lake — it never calls Impect.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.paths import STANDALONE_DIR
from app.set_plays_engine import (
    BUCKETS,
    FK_AREA_LABELS,
    SUB_LABELS,
    ZONE_LABELS,
    benchmarks,
    bucket_rows,
    extract_match,
    in_bucket,
    league_table,
    points_per_goal,
    record_goals,
    record_xg,
    summarize,
    zone_rows,
)

logger = logging.getLogger(__name__)

ALLOWED_SEASONS = ("26/27", "25/26")
PACK_VERSION = 2
LEVER_MIN_EVENTS = 15
LEVER_PRIOR = 40
MIN_COMPLETE_EVENTS = 1000
WHY = (
    "Set plays decide tight League Two games. A corner, free kick or long throw is "
    "the one moment we can rehearse to the inch — and the one moment a well-drilled "
    "opponent punishes a lapse. This is every one of ours, and every one against us."
)
LAKE_EMPTY = (
    "Set plays are saved in the data lake. This page only reads that saved pack. "
    "Nothing is stored for this view yet — use Refresh data on the hub, then come back."
)


def _cache_read(kind: str, key: str) -> dict | None:
    from app.analysis_cache import click_json

    payload = click_json(kind, key)
    return payload if isinstance(payload, dict) else None


def _cache_write(kind: str, key: str, data: dict) -> None:
    from app.analysis_cache import write_json

    write_json(kind, key, data)


def _season_key(season: str | None) -> str:
    return str(season or "default").replace("/", "-")


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _per(value: float, games: int, digits: int = 2) -> float:
    return round(value / games, digits) if games else 0.0


# ---------------------------------------------------------------- packs
def pack_from_events(events: list, event_kpis: list, match_id: int) -> dict:
    pack = extract_match(events, event_kpis, match_id)
    pack["version"] = PACK_VERSION
    return pack


def read_pack(match_id: int) -> dict | None:
    pack = _cache_read("sp-pack", str(int(match_id)))
    if pack and int(pack.get("version") or 0) == PACK_VERSION:
        return pack
    return None


def match_pack(match_id: int) -> dict:
    """Impect read for one match. Only the data-lake refresh calls this."""
    cached = read_pack(match_id)
    if cached:
        return cached
    from app.set_plays_impect import fetch_event_kpis, fetch_events

    events = fetch_events(int(match_id))
    event_kpis = fetch_event_kpis(int(match_id))
    pack = pack_from_events(events, event_kpis, int(match_id))
    # Impect can post the final score before the event feed is complete; a
    # partial pack saved now would never be re-fetched.
    if len(events) >= MIN_COMPLETE_EVENTS and event_kpis:
        _cache_write("sp-pack", str(int(match_id)), pack)
    return pack


def load_packs(match_ids: list[int], *, fetch: bool) -> dict[int, dict]:
    loaded: dict[int, dict] = {}
    pending = []
    for match_id in match_ids:
        pack = read_pack(match_id)
        if pack:
            loaded[int(match_id)] = pack
        elif fetch:
            pending.append(int(match_id))
    if pending:
        with ThreadPoolExecutor(max_workers=min(2, len(pending))) as pool:
            futures = {pool.submit(match_pack, match_id): match_id for match_id in pending}
            for future in as_completed(futures):
                try:
                    loaded[futures[future]] = future.result()
                except Exception:
                    logger.exception("Set plays pack %s failed", futures[future])
    return loaded


# ---------------------------------------------------------------- season base
def _score(match: dict) -> tuple[int, int] | None:
    goals = match.get("goals") or {}
    home = (goals.get("home") or {}).get("fullTime")
    away = (goals.get("away") or {}).get("fullTime")
    if home is None or away is None:
        return None
    return int(home), int(away)


def base_from_rows(
    season: str,
    iteration_id: int,
    competition: str,
    vale_id: int,
    names: dict[int, str],
    matches: list[dict],
    players: dict[int, str],
) -> dict:
    """Everything a report needs about the season, without any event data."""
    completed = []
    for match in matches:
        score = _score(match)
        if score is None or match.get("id") is None:
            continue
        completed.append({
            "matchId": int(match["id"]),
            "date": str(match.get("scheduledDate") or ""),
            "home": int(match.get("homeSquadId") or 0),
            "away": int(match.get("awaySquadId") or 0),
            "hg": score[0],
            "ag": score[1],
        })
    completed.sort(key=lambda row: row["date"])
    return {
        "season": season,
        "iterationId": int(iteration_id),
        "competition": competition,
        "valeId": int(vale_id),
        "names": {str(k): re.sub(r"^FC\s+", "", str(v).strip()) for k, v in names.items()},
        "players": {str(k): str(v) for k, v in players.items()},
        "matches": completed,
    }


def season_base(season: str) -> dict:
    """One Impect read of the season context. Refresh only."""
    from app import set_plays_impect as impect

    ctx = impect.resolve_season(season)
    matches = impect.iteration_matches(ctx["iterationId"])
    players = impect.player_names(ctx["iterationId"])
    base = base_from_rows(
        ctx["season"], ctx["iterationId"], ctx["competition"], ctx["valeId"],
        ctx["names"], matches, players,
    )
    _cache_write("sp-base", _season_key(base["season"]), base)
    return base


def _fixtures(base: dict) -> list[dict]:
    vale = int(base["valeId"])
    names = base.get("names") or {}
    rows = []
    for match in base.get("matches") or []:
        if vale not in {match["home"], match["away"]}:
            continue
        home = match["home"] == vale
        opponent = match["away"] if home else match["home"]
        gf, ga = (match["hg"], match["ag"]) if home else (match["ag"], match["hg"])
        rows.append({
            "matchId": match["matchId"],
            "date": match["date"],
            "opponent": names.get(str(opponent)) or f"Squad {opponent}",
            "opponentId": opponent,
            "home": home,
            "score": f"{match['hg']}-{match['ag']}",
            "gf": gf,
            "ga": ga,
            "result": "W" if gf > ga else "L" if gf < ga else "D",
        })
    return rows


def _select(fixtures: list[dict], scope: str, match_id: int | None) -> list[dict]:
    if scope == "match":
        chosen = match_id or (fixtures[-1]["matchId"] if fixtures else None)
        return [row for row in fixtures if int(row["matchId"]) == int(chosen or 0)]
    if scope == "last6":
        return fixtures[-6:]
    return list(fixtures)


# ---------------------------------------------------------------- report parts
def _name(players: dict, player_id: int) -> str:
    return players.get(str(int(player_id or 0))) or (f"Player {player_id}" if player_id else "Unknown")


def _outcome(record: dict) -> str:
    if record_goals(record):
        return "goal"
    if record.get("shots"):
        return "shot"
    team = (record.get("fc") or {}).get("team")
    if team == "att":
        return "won"
    if team == "def":
        return "lost"
    return "none"


def _map_points(records: list[dict], players: dict, fixtures: dict[int, dict]) -> list[dict]:
    points = []
    for record in records:
        if record.get("type") not in {"corner", "free_kick", "throw_in"} or record.get("dx") is None:
            continue
        if record.get("type") == "throw_in" and record.get("sub") != "long":
            continue
        fixture = fixtures.get(int(record["m"])) or {}
        contact = record.get("fc") or {}
        shots = record.get("shots") or []
        key_shot = max(shots, key=lambda s: (bool(s.get("goal")), _num(s.get("xg"))), default=None)
        points.append({
            "type": record["type"],
            "sub": record["sub"],
            "side": record["side"],
            "swing": record.get("swing"),
            "sx": record["sx"], "sy": record["sy"],
            "dx": record["dx"], "dy": record["dy"],
            "zone": record.get("zone"),
            "outcome": _outcome(record),
            "xg": round(record_xg(record), 3),
            "taker": _name(players, record.get("del") or record.get("taker")),
            "contact": _name(players, contact["pl"]) if contact.get("pl") else None,
            "contactHead": bool(contact.get("head")),
            "contactGk": bool(contact.get("gk")),
            "shooter": _name(players, key_shot["pl"]) if key_shot and key_shot.get("pl") else None,
            "shotHead": bool(key_shot and key_shot.get("head")),
            "minute": record.get("min"),
            "opponent": fixture.get("opponent"),
        })
    return points


def _shot_points(records: list[dict], players: dict, fixtures: dict[int, dict]) -> list[dict]:
    out = []
    for record in records:
        fixture = fixtures.get(int(record["m"])) or {}
        for shot in record.get("shots") or []:
            if shot.get("x") is None:
                continue
            out.append({
                "x": shot["x"], "y": shot["y"], "xg": shot.get("xg"), "goal": bool(shot.get("goal")),
                "head": bool(shot.get("head")), "phase": shot.get("ph"), "type": record["type"],
                "player": _name(players, shot.get("pl")), "minute": record.get("min"),
                "opponent": fixture.get("opponent"),
            })
    return out


def _goal_log(records: list[dict], players: dict, fixtures: dict[int, dict], *, attacking: bool) -> list[dict]:
    rows = []
    for record in records:
        for shot in record.get("shots") or []:
            if not shot.get("goal"):
                continue
            fixture = fixtures.get(int(record["m"])) or {}
            fc = record.get("fc") or {}
            beaten = ""
            if not attacking and fc.get("team") == "att" and fc.get("loser"):
                beaten = _name(players, fc["loser"])
            rows.append({
                "matchId": record["m"],
                "date": fixture.get("date"),
                "opponent": fixture.get("opponent"),
                "home": fixture.get("home"),
                "minute": record.get("min"),
                "type": record["type"],
                "typeLabel": {"corner": "Corner", "free_kick": "Free kick", "throw_in": "Throw-in", "penalty": "Penalty"}[record["type"]],
                "routine": "" if record["type"] == "penalty" else SUB_LABELS.get(record.get("sub") or "", ""),
                "side": record.get("side"),
                "swing": record.get("swing"),
                "zone": ZONE_LABELS.get(record.get("zone") or "", ""),
                "taker": _name(players, record.get("del") or record.get("taker")),
                "scorer": _name(players, shot.get("pl")),
                "xg": round(_num(shot.get("xg")), 3),
                "head": bool(shot.get("head")),
                "phase": "Second ball" if shot.get("ph") == "second" else "First phase",
                "firstContact": "Won by us" if (fc.get("team") == "att") == attacking and fc.get("team") else ("Lost" if fc.get("team") else "—"),
                "beaten": beaten,
            })
    rows.sort(key=lambda row: (str(row.get("date") or ""), row.get("minute") or 0))
    return rows


def _takers(records: list[dict], players: dict) -> list[dict]:
    by: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("type") in {"corner", "free_kick"} and record.get("sub") != "direct_shot":
            by[int(record.get("del") or record.get("taker") or 0)].append(record)
    rows = []
    for player_id, subset in by.items():
        if not player_id:
            continue
        contested = [r for r in subset if (r.get("fc") or {}).get("team")]
        won = sum(1 for r in contested if r["fc"]["team"] == "att")
        swings = defaultdict(int)
        zones = defaultdict(int)
        for r in subset:
            if r.get("swing"):
                swings[r["swing"]] += 1
            zones[r.get("zone") or "outside"] += 1
        top_zone = max(zones.items(), key=lambda kv: kv[1])[0] if zones else "outside"
        xg = sum(record_xg(r) for r in subset)
        feet = defaultdict(int)
        for r in subset:
            if r.get("foot"):
                feet[r["foot"]] += 1
        rows.append({
            "id": player_id,
            "name": _name(players, player_id),
            "deliveries": len(subset),
            "corners": sum(1 for r in subset if r["type"] == "corner"),
            "freeKicks": sum(1 for r in subset if r["type"] == "free_kick"),
            "foot": max(feet.items(), key=lambda kv: kv[1])[0] if feet else "",
            "inswing": swings.get("in", 0),
            "outswing": swings.get("out", 0),
            "intoBoxPct": round(100 * sum(1 for r in subset if r.get("zone") != "outside") / len(subset)),
            "fcWonPct": round(100 * won / len(contested)) if contested else None,
            "shotRate": round(100 * sum(1 for r in subset if r.get("shots")) / len(subset)),
            "xg": round(xg, 3),
            "xgPer": round(xg / len(subset), 4),
            "goals": sum(record_goals(r) for r in subset),
            "topZone": ZONE_LABELS.get(top_zone, top_zone),
        })
    rows.sort(key=lambda row: -row["deliveries"])
    return rows[:10]


def _attack_targets(records: list[dict], players: dict) -> list[dict]:
    rows: dict[int, dict] = {}

    def row(player_id: int) -> dict:
        return rows.setdefault(player_id, {
            "id": player_id, "name": _name(players, player_id), "fcWon": 0, "headers": 0,
            "shots": 0, "headedShots": 0, "xg": 0.0, "goals": 0, "secondGoals": 0,
        })

    for record in records:
        if record.get("type") == "penalty":
            continue
        fc = record.get("fc") or {}
        into_box = record.get("zone") not in (None, "outside")
        if into_box and fc.get("team") == "att" and fc.get("pl") and fc.get("pl") != record.get("del"):
            item = row(int(fc["pl"]))
            item["fcWon"] += 1
            item["headers"] += int(bool(fc.get("head")))
        for shot in record.get("shots") or []:
            if not shot.get("pl"):
                continue
            item = row(int(shot["pl"]))
            item["shots"] += 1
            item["headedShots"] += int(bool(shot.get("head")))
            item["xg"] += _num(shot.get("xg"))
            item["goals"] += int(bool(shot.get("goal")))
            item["secondGoals"] += int(bool(shot.get("goal")) and shot.get("ph") == "second")
    out = [r for r in rows.values() if r["fcWon"] or r["shots"]]
    for item in out:
        item["xg"] = round(item["xg"], 3)
        item["xgPerShot"] = round(item["xg"] / item["shots"], 3) if item["shots"] else None
    out.sort(key=lambda r: (-r["xg"], -r["fcWon"]))
    return out[:14]


def _defenders(records: list[dict], players: dict, vale_id: int) -> list[dict]:
    rows: dict[int, dict] = {}

    def row(player_id: int) -> dict:
        return rows.setdefault(player_id, {
            "id": player_id, "name": _name(players, player_id), "won": 0, "headedClear": 0,
            "lostDuels": 0, "lostOnShot": 0, "lostOnGoal": 0,
        })

    for record in records:
        fc = record.get("fc") or {}
        if not fc.get("team"):
            continue
        if fc["team"] == "def" and fc.get("pl"):
            item = row(int(fc["pl"]))
            item["won"] += 1
            item["headedClear"] += int(bool(fc.get("head")))
        elif fc["team"] == "att" and fc.get("loser"):
            item = row(int(fc["loser"]))
            item["lostDuels"] += 1
            item["lostOnShot"] += int(bool(record.get("shots")))
            item["lostOnGoal"] += int(record_goals(record) > 0)
    out = list(rows.values())
    for item in out:
        total = item["won"] + item["lostDuels"]
        item["involvements"] = total
        item["winPct"] = round(100 * item["won"] / total) if total else None
    out = [r for r in out if r["involvements"] >= 2]
    out.sort(key=lambda r: (-r["involvements"], r["name"]))
    return out[:14]


def _opponent_threats(records: list[dict], players: dict, fixtures: dict[int, dict]) -> list[dict]:
    rows: dict[int, dict] = {}
    for record in records:
        fixture = fixtures.get(int(record["m"])) or {}
        for shot in record.get("shots") or []:
            if not shot.get("pl"):
                continue
            item = rows.setdefault(int(shot["pl"]), {
                "id": int(shot["pl"]), "name": _name(players, shot["pl"]), "team": fixture.get("opponent"),
                "shots": 0, "xg": 0.0, "goals": 0,
            })
            item["shots"] += 1
            item["xg"] += _num(shot.get("xg"))
            item["goals"] += int(bool(shot.get("goal")))
    out = list(rows.values())
    for item in out:
        item["xg"] = round(item["xg"], 3)
    out.sort(key=lambda r: (-r["goals"], -r["xg"]))
    return out[:10]


def _gk_profile(against: list[dict]) -> dict:
    crosses = [r for r in against if r.get("type") in {"corner", "free_kick", "throw_in"} and r.get("zone") != "outside"]
    claims = sum(1 for r in crosses if (r.get("fc") or {}).get("gk"))
    goalmouth = [r for r in crosses if r.get("zone") == "goalmouth"]
    gm_claims = sum(1 for r in goalmouth if (r.get("fc") or {}).get("gk"))
    return {
        "boxDeliveries": len(crosses),
        "claims": claims,
        "claimPct": round(100 * claims / len(crosses)) if crosses else None,
        "goalmouthDeliveries": len(goalmouth),
        "goalmouthClaimPct": round(100 * gm_claims / len(goalmouth)) if goalmouth else None,
    }


def _minute_bins(for_records: list[dict], against_records: list[dict]) -> list[dict]:
    bins = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 200)]
    out = []
    for lo, hi in bins:
        f = [r for r in for_records if lo <= int(r.get("min") or 0) <= hi]
        a = [r for r in against_records if lo <= int(r.get("min") or 0) <= hi]
        out.append({
            "label": f"{lo}–{hi if hi < 200 else '90+'}",
            "xgFor": round(sum(record_xg(r) for r in f), 3),
            "xgAgainst": round(sum(record_xg(r) for r in a), 3),
            "goalsFor": sum(record_goals(r) for r in f),
            "goalsAgainst": sum(record_goals(r) for r in a),
        })
    return out


def _match_log(selected: list[dict], vale_for: list[dict], vale_against: list[dict]) -> list[dict]:
    rows = []
    for fixture in selected:
        mid = int(fixture["matchId"])
        f = [r for r in vale_for if int(r["m"]) == mid and r.get("type") != "penalty"]
        a = [r for r in vale_against if int(r["m"]) == mid and r.get("type") != "penalty"]
        pf = [r for r in vale_for if int(r["m"]) == mid and r.get("type") == "penalty"]
        pa = [r for r in vale_against if int(r["m"]) == mid and r.get("type") == "penalty"]
        rows.append({
            **fixture,
            "nFor": len(f), "nAgainst": len(a),
            "cornersFor": sum(1 for r in f if r["type"] == "corner"),
            "cornersAgainst": sum(1 for r in a if r["type"] == "corner"),
            "xgFor": round(sum(record_xg(r) for r in f), 3),
            "xgAgainst": round(sum(record_xg(r) for r in a), 3),
            "goalsFor": sum(record_goals(r) for r in f) + sum(record_goals(r) for r in pf),
            "goalsAgainst": sum(record_goals(r) for r in a) + sum(record_goals(r) for r in pa),
            "pensFor": len(pf), "pensAgainst": len(pa),
        })
    return rows


def _type_value(records: list[dict], games_total: int) -> list[dict]:
    """What each kind of set play is worth across League Two."""
    rows = []
    for spec in BUCKETS:
        if spec["id"] in {"all"}:
            continue
        subset = [r for r in records if in_bucket(r, spec["id"])]
        if not subset:
            continue
        xg = sum(record_xg(r) for r in subset)
        goals = sum(record_goals(r) for r in subset)
        rows.append({
            "id": spec["id"], "label": spec["label"], "n": len(subset),
            "perTeamGame": round(len(subset) / games_total, 2) if games_total else None,
            "xgPer": round(xg / len(subset), 4), "goalPct": round(100 * goals / len(subset), 2),
            "goals": goals,
        })
    return rows


# ---------------------------------------------------------------- the plan
LEVERS: tuple[dict[str, Any], ...] = (
    {"id": "corner_attack", "end": "attack", "bucket": "corner", "title": "Make our corners count",
     "what": "xG per corner we take"},
    {"id": "fk_attack", "end": "attack", "bucket": "fk_cross", "title": "Free kicks into the box",
     "what": "xG per free kick we cross in"},
    {"id": "throw_attack", "end": "attack", "bucket": "throw_long", "title": "Long throws",
     "what": "xG per throw we put into the box"},
    {"id": "corner_defence", "end": "defence", "bucket": "corner", "title": "Shut down corners against",
     "what": "xG we concede per corner"},
    {"id": "fk_defence", "end": "defence", "bucket": "fk_cross", "title": "Defend wide free kicks",
     "what": "xG we concede per free kick crossed in"},
    {"id": "throw_defence", "end": "defence", "bucket": "throw_long", "title": "Defend long throws",
     "what": "xG we concede per long throw"},
)


LEVER_LABELS = {
    "corner_attack": "Our corners",
    "fk_attack": "Our free kicks into the box",
    "throw_attack": "Our long throws",
    "corner_defence": "Corners against us",
    "fk_defence": "Free kicks into our box",
    "throw_defence": "Long throws against us",
}
LEVER_NOUNS = {
    "corner_attack": "corners we have taken",
    "fk_attack": "free kicks we have crossed in",
    "throw_attack": "long throws we have taken",
    "corner_defence": "corners we have faced",
    "fk_defence": "free kicks crossed into our box",
    "throw_defence": "long throws we have faced",
}


def _squad_bucket_rates(records: list[dict], games: dict[int, int]) -> dict[int, dict[str, dict[str, float]]]:
    """xG per set play for every squad and lever, shrunk towards the league rate by sample size."""
    out: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    by_for: dict[int, list[dict]] = defaultdict(list)
    by_against: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        by_for[int(record.get("sq") or 0)].append(record)
        by_against[int(record.get("opp") or 0)].append(record)
    for lever in LEVERS:
        league = [r for r in records if in_bucket(r, lever["bucket"])]
        league_rate = sum(record_xg(r) for r in league) / len(league) if league else 0.0
        for squad, played in games.items():
            if not played:
                continue
            pool = by_for.get(squad, []) if lever["end"] == "attack" else by_against.get(squad, [])
            subset = [r for r in pool if in_bucket(r, lever["bucket"])]
            xg = sum(record_xg(r) for r in subset)
            own_side = "att" if lever["end"] == "attack" else "def"
            contested = [r for r in subset if (r.get("fc") or {}).get("team")]
            out[squad][lever["id"]] = {
                "n": len(subset),
                "perGame": len(subset) / played,
                "xg": xg,
                "goals": sum(record_goals(r) for r in subset),
                "shots": sum(1 for r in subset if r.get("shots")),
                "contested": len(contested),
                "fcWon": sum(1 for r in contested if r["fc"]["team"] == own_side),
                "raw": xg / len(subset) if subset else 0.0,
                "xgPer": (xg + LEVER_PRIOR * league_rate) / (len(subset) + LEVER_PRIOR),
                "leagueRate": league_rate,
            }
    return out


def _league_fc_pct(records: list[dict], bucket: str, attacking: bool) -> float | None:
    contested = [r for r in records if in_bucket(r, bucket) and (r.get("fc") or {}).get("team")]
    if not contested:
        return None
    att_won = sum(1 for r in contested if r["fc"]["team"] == "att")
    share = att_won / len(contested)
    return round(100 * (share if attacking else 1 - share), 1)


def build_plan(records: list[dict], games: dict[int, int], names: dict, vale_id: int) -> list[dict]:
    """Each set-play type so far this season against what an average League Two side does with the same volume.

    ``vsAvg`` is in xG and always reads "positive = better than average".
    """
    rates = _squad_bucket_rates(records, games)
    vale = rates.get(vale_id) or {}
    plan = []
    for lever in LEVERS:
        mine = vale.get(lever["id"])
        if not mine or mine["n"] < 5:
            continue
        others = [
            (squad, r[lever["id"]]) for squad, r in rates.items()
            if squad != vale_id and r.get(lever["id"], {}).get("n", 0) >= LEVER_MIN_EVENTS
        ]
        if len(others) < 6:
            continue
        attack = lever["end"] == "attack"
        best_squad, best = sorted(others, key=lambda item: item[1]["xgPer"], reverse=attack)[0]
        pool = others + [(vale_id, mine)]
        ordered = sorted(pool, key=lambda item: item[1]["xgPer"], reverse=attack)
        rank = next(i for i, (squad, _) in enumerate(ordered, start=1) if squad == vale_id)
        league_rate = mine["leagueRate"]
        expected = league_rate * mine["n"]
        vs_avg = (mine["xg"] - expected) if attack else (expected - mine["xg"])
        plan.append({
            "id": lever["id"],
            "end": lever["end"],
            "title": lever["title"],
            "count": mine["n"],
            "perGame": round(mine["perGame"], 2),
            "xg": round(mine["xg"], 2),
            "goals": mine["goals"],
            "shots": mine["shots"],
            "fcPct": round(100 * mine["fcWon"] / mine["contested"], 1) if mine["contested"] else None,
            "leagueFcPct": _league_fc_pct(records, lever["bucket"], attack),
            "avgXg": round(expected, 2),
            "vsAvg": round(vs_avg, 2),
            "valeRate": round(mine["raw"], 4),
            "leagueRate": round(league_rate, 4),
            "bestRate": round(best["raw"], 4),
            "bestClub": names.get(str(best_squad)) or f"Squad {best_squad}",
            "rank": rank,
            "of": len(pool),
            "smallSample": mine["n"] < LEVER_MIN_EVENTS,
        })
    plan.sort(key=lambda row: row["vsAvg"])
    return plan


def _ordinal(n: int) -> str:
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fc_def_strong_but_leaking(marks: dict, defence: dict) -> bool:
    mark = marks.get("fcDefence") or {}
    rank = mark.get("rank") or 99
    return rank <= max(1, (mark.get("of") or 24) // 3) and defence.get("goals", 0) > defence.get("xg", 0) + 1


def build_insights(report: dict) -> list[dict]:
    out: list[dict] = []
    h = report.get("headline") or {}
    att = (report.get("attack") or {}).get("summary") or {}
    dfn = (report.get("defence") or {}).get("summary") or {}
    plan = report.get("plan") or []
    marks = {row["id"]: row for row in report.get("benchmarks") or []}

    if plan and plan[0]["vsAvg"] < 0:
        worst = plan[0]
        noun = LEVER_NOUNS.get(worst["id"], "set plays")
        attacking = worst["end"] == "attack"
        out.append({
            "tone": "bad",
            "title": f"Biggest problem: {LEVER_LABELS.get(worst['id'], worst['title']).lower()}",
            "text": (
                f"From the {worst['count']} {noun} so far, an average League Two side would have "
                f"{'created' if attacking else 'conceded'} {worst['avgXg']:.1f} xG. We have "
                f"{'created' if attacking else 'conceded'} {worst['xg']:.1f} — {abs(worst['vsAvg']):.1f} "
                f"{'short' if attacking else 'worse'}. {_ordinal(worst['rank'])} of {worst['of']} in League Two."
            ),
        })
    if plan:
        net = sum(row["vsAvg"] for row in plan)
        out.append({
            "tone": "good" if net >= 0 else "bad",
            "title": f"Set plays so far: {'+' if net >= 0 else '−'}{abs(net):.1f} xG against an average side",
            "text": (
                "Adds up corners, wide free kicks and long throws at both ends, compared with what an average "
                "League Two team would create or concede from the same number. "
                + ("We are ahead overall." if net >= 0 else "Overall they are costing us chances.")
            ),
        })
    if att.get("n"):
        diff = att["goals"] - att["xg"]
        tone = "good" if diff >= 0 else "bad"
        verb = "beating" if diff >= 0 else "under"
        out.append({
            "tone": tone,
            "title": f"Attacking finish: {att['goals']} goals from {att['xg']:.1f} xG (no pens)",
            "text": (
                f"We are {verb}-performing our set-play chances by {abs(diff):.1f} goals. "
                + ("Chance quality is the issue, not finishing — fix the delivery and the runs." if diff >= 0 else
                   "We are creating more than we score — attack the ball with more conviction and test the keeper.")
            ),
        })
    if dfn.get("n"):
        diff = dfn["goals"] - dfn["xg"]
        tone = "bad" if diff > 0 else "good"
        out.append({
            "tone": tone,
            "title": f"Defending: {dfn['goals']} conceded from {dfn['xg']:.1f} xG against (no pens)",
            "text": (
                f"We have conceded {abs(diff):.1f} {'more' if diff > 0 else 'fewer'} set-play goals than the chances deserved. "
                + ("Blocks, goalkeeping and the second ball are leaking — see Defending." if diff > 0 else
                   "Our blocks and keeper are holding up; the volume of chances is the issue.")
            ),
        })
    for key, label, why in (
        ("fcAttack", "First contact attacking", "First contact decides whether a delivery becomes a chance."),
        ("fcDefence", "First contact defending", "Every first contact we lose in our box is a free header for them."),
    ):
        mark = marks.get(key)
        if not mark or mark.get("vale") is None:
            continue
        rank = mark.get("rank") or 99
        best = "Best in the league." if rank == 1 else f"League best is {mark['best']:.0f}% ({mark['bestClub']})."
        out.append({
            "tone": "good" if rank <= 8 else "bad",
            "title": f"{label}: {mark['vale']:.0f}% ({rank} of {mark['of']})",
            "text": f"{best} {why}",
        })
    if fc_def_strong_but_leaking(marks, dfn):
        out.append({
            "tone": "bad",
            "title": "We win the first ball but still concede",
            "text": (
                "Our first-contact rate is top-third, yet the goals keep coming. Look at what happens after the "
                "first header — second balls, blocks on the edge of the box, and who is free at the back post."
            ),
        })
    sec = marks.get("secondXgAgainst")
    if sec and sec.get("rank") and sec["rank"] > (sec["of"] or 24) / 2:
        out.append({
            "tone": "bad",
            "title": "We lose the second ball",
            "text": f"{sec['vale']:.2f} xG a game conceded after the first clearance — {sec['rank']} of {sec['of']}. Edge-of-box screeners and the reset after the first header matter.",
        })
    counter = marks.get("counterXgAgainst")
    if counter and counter.get("rank") and counter["rank"] > (counter["of"] or 24) * 2 / 3:
        out.append({
            "tone": "bad",
            "title": "Caught on the break off our own set plays",
            "text": f"{counter['vale']:.3f} xG a game conceded within 30s of our own set plays — {counter['rank']} of {counter['of']}. Check rest defence numbers on our corners.",
        })
    share = h.get("shareFor")
    if share is not None:
        out.append({
            "tone": "info",
            "title": f"{share:.0f}% of our goals come from set plays",
            "text": f"League average is {h.get('leagueShareFor') or 0:.0f}%. Top sides typically get a quarter to a third of their goals this way.",
        })
    return out[:9]


# ---------------------------------------------------------------- report
def build_report(base: dict, packs: dict[int, dict], scope: str, match_id: int | None = None) -> dict:
    vale = int(base["valeId"])
    players = base.get("players") or {}
    names = base.get("names") or {}
    fixtures = _fixtures(base)
    selected = _select(fixtures, scope, match_id)
    selected = [row for row in selected if int(row["matchId"]) in packs]
    fixture_by_id = {int(row["matchId"]): row for row in fixtures}

    league_records: list[dict] = []
    league_matches = []
    for match in base.get("matches") or []:
        pack = packs.get(int(match["matchId"]))
        if not pack:
            continue
        league_matches.append(match)
        league_records.extend(pack.get("records") or [])
    games = defaultdict(int)
    goals_total: dict[int, int] = defaultdict(int)
    for match in league_matches:
        games[match["home"]] += 1
        games[match["away"]] += 1
        goals_total[match["home"]] += match["hg"]
        goals_total[match["away"]] += match["ag"]
    int_names = {int(k): v for k, v in names.items()}
    table = league_table(league_records, dict(games), int_names, dict(goals_total), vale)
    marks = benchmarks(table, vale)
    ppg = points_per_goal([(m["home"], m["away"], m["hg"], m["ag"]) for m in base.get("matches") or []])
    plan = build_plan(league_records, dict(games), names, vale)

    window_ids = {int(row["matchId"]) for row in selected}
    window_games = len(selected)
    vale_records = [r for r in league_records if int(r["m"]) in window_ids]
    vale_for = [r for r in vale_records if int(r.get("sq") or 0) == vale]
    vale_against = [r for r in vale_records if int(r.get("opp") or 0) == vale]
    open_for = [r for r in vale_for if r.get("type") != "penalty"]
    open_against = [r for r in vale_against if r.get("type") != "penalty"]

    att_summary = summarize(open_for, window_games, attacking=True)
    def_summary = summarize(open_against, window_games, attacking=False)
    pens_for = [r for r in vale_for if r.get("type") == "penalty"]
    pens_against = [r for r in vale_against if r.get("type") == "penalty"]
    goals_for_total = sum(int(row["gf"]) for row in selected)
    goals_against_total = sum(int(row["ga"]) for row in selected)
    sp_for_goals = att_summary["goals"] + sum(record_goals(r) for r in pens_for)
    sp_against_goals = def_summary["goals"] + sum(record_goals(r) for r in pens_against)
    focus_row = next((r for r in table["rows"] if r["focus"]), {})
    league_share = [r["spShareFor"] for r in table["rows"] if r.get("spShareFor") is not None]

    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": base["season"],
        "competition": base.get("competition") or "League Two",
        "scope": scope,
        "matchId": int(selected[-1]["matchId"]) if scope == "match" and selected else None,
        "why": WHY,
        "matchCount": window_games,
        "leagueMatches": len(league_matches),
        "fixtures": selected,
        "pointsPerGoal": ppg,
        "headline": {
            "club": names.get(str(vale)) or "Port Vale",
            "games": window_games,
            "goalsFor": sp_for_goals,
            "goalsAgainst": sp_against_goals,
            "goalDiff": sp_for_goals - sp_against_goals,
            "xgFor": round(att_summary["xg"] + sum(record_xg(r) for r in pens_for), 2),
            "xgAgainst": round(def_summary["xg"] + sum(record_xg(r) for r in pens_against), 2),
            "npxgFor": att_summary["xg"],
            "npxgAgainst": def_summary["xg"],
            "goalsForTotal": goals_for_total,
            "goalsAgainstTotal": goals_against_total,
            "shareFor": round(100 * att_summary["goals"] / goals_for_total) if goals_for_total else None,
            "shareAgainst": round(100 * def_summary["goals"] / goals_against_total) if goals_against_total else None,
            "leagueShareFor": round(sum(league_share) / len(league_share)) if league_share else None,
            "rank": focus_row.get("rank"),
            "of": table.get("of"),
            "pensFor": len(pens_for),
            "pensScored": sum(record_goals(r) for r in pens_for),
            "pensAgainst": len(pens_against),
            "pensConceded": sum(record_goals(r) for r in pens_against),
            "vsAvgAttack": round(sum(row["vsAvg"] for row in plan if row["end"] == "attack"), 2),
            "vsAvgDefence": round(sum(row["vsAvg"] for row in plan if row["end"] == "defence"), 2),
            "vsAvg": round(sum(row["vsAvg"] for row in plan), 2),
        },
        "benchmarks": marks,
        "plan": plan,
        "table": table["rows"],
        "attack": {
            "summary": att_summary,
            "buckets": bucket_rows(vale_for, window_games, attacking=True),
            "zones": zone_rows(open_for, attacking=True),
            "deliveries": _map_points(open_for, players, fixture_by_id),
            "shots": _shot_points(vale_for, players, fixture_by_id),
            "takers": _takers(open_for, players),
            "targets": _attack_targets(open_for, players),
            "goals": _goal_log(vale_for, players, fixture_by_id, attacking=True),
            "fkAreas": _fk_areas(open_for),
        },
        "defence": {
            "summary": def_summary,
            "buckets": bucket_rows(vale_against, window_games, attacking=False),
            "zones": zone_rows(open_against, attacking=False),
            "deliveries": _map_points(open_against, players, fixture_by_id),
            "shots": _shot_points(vale_against, players, fixture_by_id),
            "defenders": _defenders(open_against, players, vale),
            "threats": _opponent_threats(vale_against, players, fixture_by_id),
            "goals": _goal_log(vale_against, players, fixture_by_id, attacking=False),
            "gk": _gk_profile(open_against),
            "fkAreas": _fk_areas(open_against),
        },
        "minutes": _minute_bins(vale_for, vale_against),
        "matches": _match_log(selected, vale_for, vale_against),
        "typeValue": _type_value([r for r in league_records], sum(games.values())),
        "ready": True,
        "fromLake": False,
    }
    report["insights"] = build_insights(report)
    return report


def _fk_areas(records: list[dict]) -> list[dict]:
    rows = []
    for area, label in FK_AREA_LABELS.items():
        subset = [r for r in records if r.get("type") == "free_kick" and r.get("area") == area]
        xg = sum(record_xg(r) for r in subset)
        rows.append({
            "id": area, "label": label, "n": len(subset),
            "crossed": sum(1 for r in subset if r.get("sub") == "cross"),
            "direct": sum(1 for r in subset if r.get("sub") == "direct_shot"),
            "xg": round(xg, 3), "goals": sum(record_goals(r) for r in subset),
        })
    return rows


# ---------------------------------------------------------------- lake storage
def report_key(season: str | None, scope: str, match_id: int | None = None) -> str:
    key = _season_key(season)
    if scope == "match" and match_id:
        return f"{key}-match-{int(match_id)}"
    return f"{key}-{scope}"


def _scope(scope: str | None) -> str:
    normalized = (scope or "season").strip().lower()
    if normalized not in {"match", "last6", "season"}:
        raise ValueError("scope must be match, last6, or season")
    return normalized


def store_views(base: dict, packs: dict[int, dict]) -> dict:
    season = base["season"]
    fixtures = [row for row in _fixtures(base) if int(row["matchId"]) in packs]
    season_report = build_report(base, packs, "season")
    _store(season_report)
    _store(build_report(base, packs, "last6"))
    for row in fixtures:
        _store(build_report(base, packs, "match", int(row["matchId"])))
    _cache_write("sp-fixtures", _season_key(season), {
        "season": season,
        "fixtures": fixtures,
        "defaultMatchId": fixtures[-1]["matchId"] if fixtures else None,
        "ready": True,
    })
    return {"season": season, "fixtures": len(fixtures), "leagueMatches": season_report["leagueMatches"]}


def _store(report: dict) -> None:
    payload = dict(report)
    payload["ready"] = True
    payload["fromLake"] = True
    _cache_write("sp-report", report_key(payload["season"], payload["scope"], payload.get("matchId")), payload)


def meta() -> dict:
    return {
        "seasons": [{"value": value, "label": value} for value in ALLOWED_SEASONS],
        "defaultSeason": ALLOWED_SEASONS[0],
        "why": WHY,
    }


def warm_set_plays(*, include_previous: bool = True) -> dict[str, Any]:
    """Write the Set Plays pack into the data lake. Hub analysis refresh only."""
    payload = meta()
    payload["ready"] = True
    _cache_write("sp-meta", "default", payload)
    seasons = list(ALLOWED_SEASONS if include_previous else ALLOWED_SEASONS[:1])
    result: dict[str, Any] = {"ok": True, "seasons": {}}
    for season in seasons:
        try:
            base = season_base(season)
            ids = [int(m["matchId"]) for m in base["matches"]]
            packs = load_packs(ids, fetch=True)
            result["seasons"][season] = store_views(base, packs)
        except Exception as exc:
            logger.exception("Set plays warm for %s failed", season)
            result["seasons"][season] = {"ok": False, "error": str(exc)}
            if season == ALLOWED_SEASONS[0]:
                result["ok"] = False
    return result


def rebuild_from_lake(season: str | None = None) -> dict[str, Any]:
    """Recompute every stored view from saved packs only. No Impect calls."""
    done: dict[str, Any] = {}
    for item in ([season] if season else list(ALLOWED_SEASONS)):
        base = _cache_read("sp-base", _season_key(item))
        if not base:
            done[item] = "no saved season"
            continue
        ids = [int(m["matchId"]) for m in base["matches"]]
        done[item] = store_views(base, load_packs(ids, fetch=False))
    return done


# ---------------------------------------------------------------- click path
def read_meta() -> dict:
    cached = _cache_read("sp-meta", "default")
    if cached and cached.get("seasons"):
        return {**cached, "fromLake": True}
    return {**meta(), "ready": False, "fromLake": True, "message": LAKE_EMPTY}


def read_fixtures(season: str | None) -> dict:
    cached = _cache_read("sp-fixtures", _season_key(season))
    if cached:
        return {**cached, "fromLake": True}
    return {"season": season or "", "fixtures": [], "defaultMatchId": None, "ready": False, "fromLake": True}


def read_report(season: str | None, scope: str | None, match_id: int | None = None) -> dict:
    normalized = _scope(scope)
    cached = _cache_read("sp-report", report_key(season, normalized, match_id if normalized == "match" else None))
    if not cached:
        return {
            "ready": False, "fromLake": True, "season": season or ALLOWED_SEASONS[0],
            "scope": normalized, "matchId": match_id, "why": WHY, "message": LAKE_EMPTY,
        }
    return {**cached, "table": _with_badges(cached.get("table") or []), "ready": True, "fromLake": True}


def _with_badges(rows: list) -> list:
    """Crest per club from disk or FotMob ids. No Impect."""
    from app.handout_badges import hydrate_team_badge

    out = []
    for row in rows:
        item = dict(row)
        try:
            item["badge"] = hydrate_team_badge({"id": item.get("squadId"), "name": item.get("club")}).get("badge_url")
        except Exception:
            item["badge"] = None
        out.append(item)
    return out


def register_set_plays_routes(app: FastAPI) -> None:
    @app.get("/set-plays")
    def set_plays_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "set-plays.html")

    @app.get("/api/set-plays/meta")
    def set_plays_meta_route() -> dict:
        return read_meta()

    @app.get("/api/set-plays/fixtures")
    def set_plays_fixtures_route(season: str | None = Query(None)) -> dict:
        return read_fixtures(season)

    @app.get("/api/set-plays/report")
    def set_plays_report_route(
        season: str | None = Query(None),
        scope: str | None = Query("season"),
        match_id: int | None = Query(None, alias="matchId"),
    ) -> JSONResponse:
        try:
            payload = read_report(season, scope, match_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
