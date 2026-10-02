"""Interventions — where, how and by whom Port Vale win the ball, and whether it wins games.

Impect definitions (same KPIs as Post-Match and Blocks Analysis):

* Ball wins (KPI 27) — every regain Impect counts.
* Offensive interventions (KPI 24) — opponents taken out of the game when we win the ball.
* Defensive interventions (KPI 23) — our team-mates put back behind the ball when we win it.
* Ball wins vs defenders (KPI 25) — opposition defenders removed by the regain.
* Duels — ground (94/95) and aerial (96/97) won / lost.

Every ball-win event carries those values, so summing the event rows gives the
official match totals while keeping the location and the player. Coordinates
are Impect ``adjCoordinates``: the acting team always attacks towards +x.

The page only reads the analysis lake. ``warm_interventions`` (hub analysis
refresh) is the only path that calls Impect.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.paths import STANDALONE_DIR

logger = logging.getLogger(__name__)

KPI_DI = 23
KPI_OI = 24
KPI_BWD = 25
KPI_BALL_WINS = 27
KPI_GROUND_WON = 94
KPI_GROUND_LOST = 95
KPI_AERIAL_WON = 96
KPI_AERIAL_LOST = 97
KPI_PXT_BALL_WIN = 1409
BALL_WIN_KPIS = {KPI_BALL_WINS, KPI_DI, KPI_OI, KPI_BWD}
DUEL_KPIS = {KPI_GROUND_WON: "gw", KPI_GROUND_LOST: "gl", KPI_AERIAL_WON: "aw", KPI_AERIAL_LOST: "al"}
EVENT_KPIS = BALL_WIN_KPIS | set(DUEL_KPIS) | {KPI_PXT_BALL_WIN}

ALLOWED_SEASONS = ("26/27", "25/26")
PITCH_HALF_LENGTH = 52.5
THIRD_EDGE = 17.5
LANE_WING = 20.16
LANE_HALF_SPACE = 9.16
MAX_POINTS = 24000

THIRDS = (("D", "Defensive third"), ("M", "Middle third"), ("F", "Final third"))
LANES = (
    ("L", "Left wing"),
    ("LH", "Left half-space"),
    ("C", "Centre"),
    ("RH", "Right half-space"),
    ("R", "Right wing"),
)
ZONE_IDS = tuple(f"{third}-{lane}" for third, _ in THIRDS for lane, _ in LANES)
THIRD_LABELS = dict(THIRDS)
LANE_LABELS = dict(LANES)

UNIT_LABELS = {"DEF": "Defenders", "MID": "Midfielders", "ATT": "Forwards", "GK": "Goalkeeper"}
UNIT_ORDER = ("DEF", "MID", "ATT", "GK")
TYPE_LABELS = {
    "LOOSE_BALL_REGAIN": "Loose-ball regain",
    "INTERCEPTION": "Interception",
    "GROUND_DUEL": "Ground duel",
    "AERIAL_DUEL": "Aerial duel",
    "HEADER": "Header",
    "BLOCK": "Block",
    "CLEARANCE": "Clearance",
    "GK_CATCH": "Keeper catch",
    "GK_SAVE": "Keeper save",
}
TYPE_COLORS = {
    "LOOSE_BALL_REGAIN": "#fbbf24",
    "INTERCEPTION": "#34d399",
    "GROUND_DUEL": "#f97316",
    "AERIAL_DUEL": "#38bdf8",
    "HEADER": "#60a5fa",
    "BLOCK": "#c084fc",
    "CLEARANCE": "#94a3b8",
    "GK_CATCH": "#64748b",
    "GK_SAVE": "#64748b",
}

# Battles: who out-did the other side in a match, and what that did to the result.
BATTLES: tuple[dict[str, Any], ...] = (
    {"id": "bw", "label": "Ball wins", "hint": "More regains than the opponent", "higher": True},
    {"id": "bwd", "label": "Ball wins vs defenders", "hint": "Regains that take their defenders out", "higher": True},
    {"id": "high", "label": "Final-third regains", "hint": "Ball wins in their third", "higher": True, "events": True},
    {"id": "duelPct", "label": "Duel win %", "hint": "Ground + aerial", "higher": True},
    {"id": "aerialPct", "label": "Aerial win %", "hint": "Aerial duels", "higher": True},
    {"id": "groundPct", "label": "Ground duel %", "hint": "Ground duels", "higher": True},
    {"id": "oi", "label": "Offensive interventions", "hint": "Opponents removed on ball wins", "higher": True},
    {"id": "threat", "label": "Ball-win threat", "hint": "Impect threat added by the regain", "higher": True},
    {"id": "di", "label": "Defensive interventions", "hint": "Team-mates put back behind the ball", "higher": False},
)

WHY = (
    "Interventions are how we get the ball back. League Two history says the detail matters more "
    "than the volume: winning duels, winning the air and winning it high off their defenders all "
    "track winning games. Piling up defensive interventions does not — that usually means we are "
    "living without the ball."
)
LAKE_EMPTY = (
    "Interventions are saved in the data lake. This page only reads that saved pack. "
    "Nothing is stored for this view yet — use Refresh data on the hub, then come back."
)
FALLBACK_EVIDENCE = (
    {"key": "aerial_pct", "label": "Aerial win %", "r": 0.416},
    {"key": "duel_pct", "label": "Duel win %", "r": 0.412},
    {"key": "ball_wins_defenders", "label": "Ball wins vs defenders", "r": 0.400},
    {"key": "defensive_interventions", "label": "Defensive interventions", "r": -0.341},
)


def _impect():
    from app import main as impect_main

    return impect_main


# ---------------------------------------------------------------- pitch helpers


def _coords(event: dict[str, Any]) -> tuple[float, float] | None:
    start = event.get("start") if isinstance(event.get("start"), dict) else {}
    coords = start.get("adjCoordinates") or start.get("coordinates") or {}
    try:
        return float(coords["x"]), float(coords["y"])
    except (KeyError, TypeError, ValueError):
        return None


def third_of(x: float) -> str:
    if x < -THIRD_EDGE:
        return "D"
    if x > THIRD_EDGE:
        return "F"
    return "M"


def lane_of(y: float) -> str:
    if y > LANE_WING:
        return "L"
    if y > LANE_HALF_SPACE:
        return "LH"
    if y < -LANE_WING:
        return "R"
    if y < -LANE_HALF_SPACE:
        return "RH"
    return "C"


def zone_of(x: float, y: float) -> str:
    return f"{third_of(x)}-{lane_of(y)}"


def zone_label(zone_id: str) -> str:
    third, _, lane = str(zone_id).partition("-")
    return f"{THIRD_LABELS.get(third, third)} · {LANE_LABELS.get(lane, lane).lower()}"


def unit_of(position: str | None) -> str:
    key = str(position or "").upper()
    if "GOALKEEPER" in key:
        return "GK"
    if "DEFENDER" in key or key == "CENTRAL_DEFENDER":
        return "DEF"
    if "WINGER" in key or "FORWARD" in key or "STRIKER" in key:
        return "ATT"
    if "MIDFIELD" in key:
        return "MID"
    return "MID"


def regain_type(event: dict[str, Any]) -> str:
    duel = event.get("duel") if isinstance(event.get("duel"), dict) else None
    if duel and duel.get("duelType"):
        return str(duel["duelType"]).upper()
    action_type = str(event.get("actionType") or "").upper()
    if action_type == "LOOSE_BALL_REGAIN" and str(event.get("action") or "").upper() == "HEADER":
        return "HEADER"
    return action_type or "OTHER"


def type_label(key: str) -> str:
    if key in TYPE_LABELS:
        return TYPE_LABELS[key]
    text = str(key or "other").replace("_", " ").lower()
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------- match summary


def _blank_stats() -> dict[str, float]:
    return {
        "bw": 0, "oi": 0.0, "di": 0.0, "bwd": 0.0, "bwdCount": 0, "threat": 0.0,
        "high": 0, "mid": 0, "deep": 0, "gw": 0, "gl": 0, "aw": 0, "al": 0,
    }


def _blank_squad() -> dict[str, Any]:
    return {
        **_blank_stats(),
        "types": {},
        "zones": {},
        "units": {},
        "periods": {},
        "players": {},
    }


def _add(into: dict[str, Any], key: str, value: float) -> None:
    into[key] = float(into.get(key) or 0) + float(value)


def _period_bucket(event: dict[str, Any]) -> str:
    game_time = event.get("gameTime") if isinstance(event.get("gameTime"), dict) else {}
    try:
        seconds = float(game_time.get("gameTimeInSec") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    period = int(event.get("periodId") or 1)
    labels = ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90")
    if period <= 1:
        return labels[min(2, max(0, int(seconds // 900)))]
    # Impect restarts the second-half clock at 10,000 seconds.
    if seconds >= 10000:
        seconds -= 10000
    elif seconds >= 2700:
        seconds -= 2700
    return labels[3 + min(2, max(0, int(seconds // 900)))]


def summarize_match(events: list[dict[str, Any]], event_kpis: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-squad ball wins, interventions and duels, by zone, unit, player and type."""
    by_id: dict[int, dict[str, Any]] = {}
    player_squad: dict[int, int] = {}
    squad_ids: set[int] = set()
    for event in events:
        try:
            event_id = int(event.get("id") or 0)
            squad_id = int(event.get("squadId") or 0)
        except (TypeError, ValueError):
            continue
        if event_id <= 0 or squad_id <= 0:
            continue
        by_id[event_id] = event
        squad_ids.add(squad_id)
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        try:
            player_id = int(player.get("id") or 0)
        except (TypeError, ValueError):
            player_id = 0
        if player_id:
            player_squad.setdefault(player_id, squad_id)

    appeared: dict[int, set[int]] = defaultdict(set)
    for player_id, squad_id in player_squad.items():
        appeared[squad_id].add(player_id)

    ball_wins: dict[int, dict[int, float]] = defaultdict(dict)
    duel_rows: list[tuple[int, int, str, str]] = []
    for row in event_kpis:
        try:
            kpi_id = int(row.get("kpiId") if row.get("kpiId") is not None else -1)
            event_id = int(row.get("eventId") or 0)
            value = float(row.get("value") or 0)
            player_id = int(row.get("playerId") or 0)
        except (TypeError, ValueError):
            continue
        if kpi_id not in EVENT_KPIS or event_id not in by_id:
            continue
        if kpi_id in DUEL_KPIS:
            if value > 0:
                duel_rows.append((event_id, player_id, DUEL_KPIS[kpi_id], str(row.get("position") or "")))
            continue
        ball_wins[event_id][kpi_id] = ball_wins[event_id].get(kpi_id, 0.0) + value

    squads: dict[str, dict[str, Any]] = {}
    points: list[dict[str, Any]] = []

    def squad_bucket(squad_id: int) -> dict[str, Any]:
        return squads.setdefault(str(squad_id), _blank_squad())

    def player_bucket(squad: dict[str, Any], player_id: int, position: str) -> dict[str, Any]:
        row = squad["players"].setdefault(
            str(player_id),
            {"id": player_id, "position": position, "unit": unit_of(position), **_blank_stats(), "zones": {}},
        )
        if position and not row.get("position"):
            row["position"] = position
            row["unit"] = unit_of(position)
        return row

    for event_id, kpis in ball_wins.items():
        if float(kpis.get(KPI_BALL_WINS) or 0) <= 0 and KPI_DI not in kpis and KPI_OI not in kpis:
            continue
        event = by_id[event_id]
        squad_id = int(event.get("squadId") or 0)
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        try:
            player_id = int(player.get("id") or 0)
        except (TypeError, ValueError):
            player_id = 0
        position = str(player.get("position") or "")
        unit = unit_of(position)
        xy = _coords(event)
        zone = zone_of(*xy) if xy else ""
        third = zone[:1] if zone else ""
        kind = regain_type(event)
        oi = float(kpis.get(KPI_OI) or 0)
        di = float(kpis.get(KPI_DI) or 0)
        bwd = float(kpis.get(KPI_BWD) or 0)
        threat = max(0.0, float(kpis.get(KPI_PXT_BALL_WIN) or 0))
        squad = squad_bucket(squad_id)
        targets = [squad]
        if player_id:
            targets.append(player_bucket(squad, player_id, position))
        unit_row = squad["units"].setdefault(unit, _blank_stats())
        targets.append(unit_row)
        for target in targets:
            target["bw"] += 1
            target["oi"] += oi
            target["di"] += di
            target["bwd"] += bwd
            target["bwdCount"] += 1 if bwd > 0 else 0
            target["threat"] += threat
            if third == "F":
                target["high"] += 1
            elif third == "M":
                target["mid"] += 1
            elif third == "D":
                target["deep"] += 1
        _add(squad["types"], kind, 1)
        _add(squad["periods"], _period_bucket(event), 1)
        if zone:
            zone_row = squad["zones"].setdefault(zone, _blank_stats())
            zone_row["bw"] += 1
            zone_row["oi"] += oi
            zone_row["di"] += di
            zone_row["bwd"] += bwd
            zone_row["threat"] += threat
            if player_id:
                _add(squad["players"][str(player_id)]["zones"], zone, 1)
        if xy:
            points.append({
                "s": squad_id, "k": "bw", "t": kind, "p": player_id,
                "x": round(xy[0], 1), "y": round(xy[1], 1),
                "oi": round(oi, 2), "di": round(di, 2), "bwd": round(bwd, 2),
            })

    for event_id, player_id, kind, position in duel_rows:
        event = by_id[event_id]
        event_squad = int(event.get("squadId") or 0)
        winner = kind in {"gw", "aw"}
        squad_id = player_squad.get(player_id)
        if squad_id is None:
            others = [sid for sid in squad_ids if sid != event_squad]
            squad_id = event_squad if winner else (others[0] if others else 0)
        if not squad_id:
            continue
        squad = squad_bucket(squad_id)
        squad[kind] += 1
        unit = unit_of(position)
        squad["units"].setdefault(unit, _blank_stats())[kind] += 1
        if player_id:
            player_bucket(squad, player_id, position)[kind] += 1
        xy = _coords(event)
        if xy:
            x, y = xy if squad_id == event_squad else (-xy[0], -xy[1])
            zone = zone_of(x, y)
            squad["zones"].setdefault(zone, _blank_stats())[kind] += 1
            points.append({"s": squad_id, "k": kind, "p": player_id, "x": round(x, 1), "y": round(y, 1)})

    for squad_id, players in appeared.items():
        squad_bucket(squad_id)["appeared"] = sorted(players)
    for squad in squads.values():
        _round_stats(squad)
        for key in ("zones", "units"):
            for row in squad[key].values():
                _round_stats(row)
        for row in squad["players"].values():
            _round_stats(row)
    return {"squads": squads, "points": points}


def _round_stats(row: dict[str, Any]) -> None:
    for key in ("oi", "di", "bwd", "threat"):
        if key in row:
            row[key] = round(float(row[key]), 4)


# ---------------------------------------------------------------- merging


def _merge_stats(into: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in (extra or {}).items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            into[key] = float(into.get(key) or 0) + float(value)


def merge_squads(parts: list[dict[str, Any]]) -> dict[str, Any]:
    merged = _blank_squad()
    merged["games"] = {}
    for part in parts:
        if not part:
            continue
        _merge_stats(merged, {k: v for k, v in part.items() if k in _blank_stats()})
        for key in ("types", "periods"):
            for name, value in (part.get(key) or {}).items():
                _add(merged[key], name, value)
        for key in ("zones", "units"):
            for name, row in (part.get(key) or {}).items():
                _merge_stats(merged[key].setdefault(name, _blank_stats()), row)
        appeared = {str(pid) for pid in part.get("appeared") or []}
        for player_id in appeared:
            merged["games"][player_id] = int(merged["games"].get(player_id) or 0) + 1
        for player_id, row in (part.get("players") or {}).items():
            current = merged["players"].setdefault(
                str(player_id),
                {"id": int(row.get("id") or player_id), "position": row.get("position") or "",
                 "unit": row.get("unit") or "MID", **_blank_stats(), "zones": {}},
            )
            _merge_stats(current, {k: v for k, v in row.items() if k in _blank_stats()})
            if str(player_id) not in appeared:
                merged["games"][str(player_id)] = int(merged["games"].get(str(player_id)) or 0) + 1
            if row.get("position"):
                current["position"] = row["position"]
                current["unit"] = row.get("unit") or unit_of(row["position"])
            for zone, value in (row.get("zones") or {}).items():
                _add(current["zones"], zone, value)
    return merged


# ---------------------------------------------------------------- derived figures


def _pct(won: float, lost: float) -> float | None:
    total = float(won) + float(lost)
    return round(100.0 * float(won) / total, 1) if total > 0 else None


def _per_game(value: float, games: int, digits: int = 2) -> float:
    return round(float(value) / games, digits) if games > 0 else 0.0


def headline_stats(squad: dict[str, Any], games: int) -> dict[str, Any]:
    bw = float(squad.get("bw") or 0)
    duels_won = float(squad.get("gw") or 0) + float(squad.get("aw") or 0)
    duels_lost = float(squad.get("gl") or 0) + float(squad.get("al") or 0)
    return {
        "games": games,
        "bw": _per_game(bw, games, 1),
        "oi": _per_game(squad.get("oi") or 0, games, 1),
        "di": _per_game(squad.get("di") or 0, games, 1),
        "bwd": _per_game(squad.get("bwd") or 0, games, 2),
        "bwdCount": _per_game(squad.get("bwdCount") or 0, games, 1),
        "threat": _per_game(squad.get("threat") or 0, games, 3),
        "high": _per_game(squad.get("high") or 0, games, 1),
        "mid": _per_game(squad.get("mid") or 0, games, 1),
        "deep": _per_game(squad.get("deep") or 0, games, 1),
        "highShare": round(100.0 * float(squad.get("high") or 0) / bw, 1) if bw else None,
        "deepShare": round(100.0 * float(squad.get("deep") or 0) / bw, 1) if bw else None,
        "oiPerWin": round(float(squad.get("oi") or 0) / bw, 2) if bw else None,
        "duelPct": _pct(duels_won, duels_lost),
        "groundPct": _pct(squad.get("gw") or 0, squad.get("gl") or 0),
        "aerialPct": _pct(squad.get("aw") or 0, squad.get("al") or 0),
        "duelsWon": _per_game(duels_won, games, 1),
        "duelsLost": _per_game(duels_lost, games, 1),
        "aerialWon": _per_game(squad.get("aw") or 0, games, 1),
        "groundWon": _per_game(squad.get("gw") or 0, games, 1),
    }


def zone_rows(squad: dict[str, Any], games: int) -> list[dict[str, Any]]:
    zones = squad.get("zones") or {}
    total_bw = sum(float((zones.get(z) or {}).get("bw") or 0) for z in ZONE_IDS) or 0.0
    rows = []
    for zone_id in ZONE_IDS:
        row = zones.get(zone_id) or {}
        bw = float(row.get("bw") or 0)
        rows.append({
            "id": zone_id,
            "third": zone_id.split("-")[0],
            "lane": zone_id.split("-")[1],
            "label": zone_label(zone_id),
            "bw": _per_game(bw, games, 2),
            "bwTotal": int(bw),
            "share": round(100.0 * bw / total_bw, 1) if total_bw else 0.0,
            "oi": _per_game(row.get("oi") or 0, games, 2),
            "di": _per_game(row.get("di") or 0, games, 2),
            "bwd": _per_game(row.get("bwd") or 0, games, 2),
            "threat": _per_game(row.get("threat") or 0, games, 3),
            "duelsWon": _per_game(float(row.get("gw") or 0) + float(row.get("aw") or 0), games, 2),
            "duelsLost": _per_game(float(row.get("gl") or 0) + float(row.get("al") or 0), games, 2),
            "duelPct": _pct(float(row.get("gw") or 0) + float(row.get("aw") or 0),
                            float(row.get("gl") or 0) + float(row.get("al") or 0)),
        })
    return rows


def unit_rows(squad: dict[str, Any], games: int) -> list[dict[str, Any]]:
    units = squad.get("units") or {}
    total_bw = sum(float((row or {}).get("bw") or 0) for row in units.values()) or 0.0
    rows = []
    for unit in UNIT_ORDER:
        row = units.get(unit)
        if not row:
            continue
        stats = headline_stats(row, games)
        stats.update({
            "id": unit,
            "label": UNIT_LABELS[unit],
            "share": round(100.0 * float(row.get("bw") or 0) / total_bw, 1) if total_bw else 0.0,
        })
        rows.append(stats)
    return rows


def type_rows(squad: dict[str, Any], games: int) -> list[dict[str, Any]]:
    types = squad.get("types") or {}
    total = sum(float(v) for v in types.values()) or 0.0
    rows = [{
        "id": key,
        "label": type_label(key),
        "color": TYPE_COLORS.get(key, "#94a3b8"),
        "count": int(value),
        "perGame": _per_game(value, games, 1),
        "share": round(100.0 * float(value) / total, 1) if total else 0.0,
    } for key, value in types.items()]
    rows.sort(key=lambda row: -row["count"])
    return rows


def period_rows(squad: dict[str, Any], games: int) -> list[dict[str, Any]]:
    periods = squad.get("periods") or {}
    return [
        {"id": key, "perGame": _per_game(periods.get(key) or 0, games, 1)}
        for key in ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90")
    ]


def player_rows(squad: dict[str, Any], names: dict[int, str]) -> list[dict[str, Any]]:
    rows = []
    games_by_player = squad.get("games") or {}
    for row in (squad.get("players") or {}).values():
        player_id = int(row.get("id") or 0)
        games = max(1, int(games_by_player.get(str(player_id)) or 1))
        bw = float(row.get("bw") or 0)
        duels = float(row.get("gw") or 0) + float(row.get("gl") or 0) + float(row.get("aw") or 0) + float(row.get("al") or 0)
        if bw <= 0 and duels <= 0:
            continue
        zones = row.get("zones") or {}
        top_zone = max(zones.items(), key=lambda item: float(item[1]))[0] if zones else None
        stats = headline_stats(row, games)
        stats.update({
            "id": player_id,
            "name": names.get(player_id) or f"Player {player_id}",
            "position": row.get("position") or "",
            "unit": row.get("unit") or unit_of(row.get("position")),
            "unitLabel": UNIT_LABELS.get(row.get("unit") or "MID", "Midfielders"),
            "bwTotal": int(bw),
            "oiTotal": round(float(row.get("oi") or 0), 1),
            "diTotal": round(float(row.get("di") or 0), 1),
            "bwdTotal": round(float(row.get("bwd") or 0), 1),
            "highTotal": int(row.get("high") or 0),
            "duelsTotal": int(duels),
            "topZone": top_zone,
            "topZoneLabel": zone_label(top_zone) if top_zone else None,
            "zones": {key: int(value) for key, value in zones.items()},
        })
        rows.append(stats)
    rows.sort(key=lambda item: (-item["bwTotal"], -item["duelsTotal"], item["name"]))
    return rows


# ---------------------------------------------------------------- battles (does it win games?)


def _battle_value(stats: dict[str, Any], battle_id: str) -> float | None:
    if battle_id == "duelPct":
        return _pct(float(stats.get("gw") or 0) + float(stats.get("aw") or 0),
                    float(stats.get("gl") or 0) + float(stats.get("al") or 0))
    if battle_id == "aerialPct":
        return _pct(stats.get("aw") or 0, stats.get("al") or 0)
    if battle_id == "groundPct":
        return _pct(stats.get("gw") or 0, stats.get("gl") or 0)
    value = stats.get(battle_id)
    return float(value) if value is not None else None


def _points(goals_for: int, goals_against: int) -> int:
    return 3 if goals_for > goals_against else 1 if goals_for == goals_against else 0


def _record(rows: list[dict[str, Any]]) -> dict[str, Any]:
    won = sum(1 for row in rows if row["pts"] == 3)
    drawn = sum(1 for row in rows if row["pts"] == 1)
    lost = sum(1 for row in rows if row["pts"] == 0)
    games = len(rows)
    return {
        "games": games, "w": won, "d": drawn, "l": lost,
        "ppg": round(sum(row["pts"] for row in rows) / games, 2) if games else None,
        "winPct": round(100.0 * won / games, 1) if games else None,
    }


def battle_table(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """observations: one row per team per match: {'stats', 'opp', 'pts'}.

    For each battle, the record of the side that won it vs the side that lost it.
    """
    out = []
    for spec in BATTLES:
        won_rows, lost_rows, level_rows = [], [], []
        for obs in observations:
            ours = _battle_value(obs["stats"], spec["id"])
            theirs = _battle_value(obs["opp"], spec["id"])
            if ours is None or theirs is None:
                continue
            if abs(ours - theirs) < 1e-9:
                level_rows.append(obs)
                continue
            better = ours > theirs if spec["higher"] else ours < theirs
            (won_rows if better else lost_rows).append(obs)
        won, lost = _record(won_rows), _record(lost_rows)
        gap = None
        if won["ppg"] is not None and lost["ppg"] is not None:
            gap = round(won["ppg"] - lost["ppg"], 2)
        out.append({
            "id": spec["id"], "label": spec["label"], "hint": spec["hint"], "higher": spec["higher"],
            "won": won, "lost": lost, "level": len(level_rows), "ppgGap": gap,
        })
    out.sort(key=lambda row: -(row["ppgGap"] if row["ppgGap"] is not None else -99))
    return out


def _score_for(fixture: dict[str, Any]) -> tuple[int, int] | None:
    try:
        home_goals, away_goals = (int(part) for part in str(fixture.get("score") or "").split("-"))
    except ValueError:
        return None
    return (home_goals, away_goals) if fixture.get("home") else (away_goals, home_goals)


def match_trend(selected: list[dict[str, Any]], loaded: dict[int, dict[str, Any]], vale_id: int) -> list[dict[str, Any]]:
    rows = []
    for fixture in selected:
        summary = loaded.get(int(fixture["matchId"])) or {}
        squads = summary.get("squads") or {}
        ours = squads.get(str(vale_id))
        theirs = squads.get(str(fixture.get("opponentId")))
        if not ours or not theirs:
            continue
        score = _score_for(fixture)
        us = headline_stats(ours, 1)
        them = headline_stats(theirs, 1)
        rows.append({
            "matchId": int(fixture["matchId"]),
            "date": fixture.get("date"),
            "opponent": fixture.get("opponent"),
            "opponentId": fixture.get("opponentId"),
            "home": bool(fixture.get("home")),
            "goalsFor": score[0] if score else None,
            "goalsAgainst": score[1] if score else None,
            "result": ("W" if score[0] > score[1] else "D" if score[0] == score[1] else "L") if score else None,
            "us": us,
            "them": them,
        })
    return rows


def vale_observations(trend: list[dict[str, Any]], loaded: dict[int, dict[str, Any]], vale_id: int) -> list[dict[str, Any]]:
    obs = []
    for row in trend:
        if row.get("goalsFor") is None:
            continue
        squads = (loaded.get(int(row["matchId"])) or {}).get("squads") or {}
        obs.append({
            "stats": squads.get(str(vale_id)) or {},
            "opp": squads.get(str(row.get("opponentId"))) or {},
            "pts": _points(int(row["goalsFor"]), int(row["goalsAgainst"])),
        })
    return obs


def results_split(trend: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Average Vale numbers in wins, draws and defeats."""
    keys = ("bw", "oi", "di", "bwd", "high", "duelPct", "aerialPct", "groundPct", "threat")
    out = []
    for result, label in (("W", "Wins"), ("D", "Draws"), ("L", "Defeats")):
        rows = [row for row in trend if row.get("result") == result]
        item: dict[str, Any] = {"id": result, "label": label, "games": len(rows)}
        for key in keys:
            values = [float(row["us"][key]) for row in rows if row["us"].get(key) is not None]
            item[key] = round(sum(values) / len(values), 2) if values else None
        out.append(item)
    return out


# ---------------------------------------------------------------- League Two (match squad KPIs)


def league_observation_pair(match: dict[str, Any], squads: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    from app.analysis_cache import goals_full_time

    score = goals_full_time(match)
    try:
        home_id = str(int(match.get("homeSquadId") or 0))
        away_id = str(int(match.get("awaySquadId") or 0))
    except (TypeError, ValueError):
        return []
    home, away = squads.get(home_id), squads.get(away_id)
    if not score or not home or not away:
        return []
    return [
        {"stats": home, "opp": away, "pts": _points(score[0], score[1]), "squadId": int(home_id)},
        {"stats": away, "opp": home, "pts": _points(score[1], score[0]), "squadId": int(away_id)},
    ]


def _compact_match_squads(raw: dict[Any, Any]) -> dict[str, dict[str, float]]:
    keys = {KPI_BALL_WINS: "bw", KPI_DI: "di", KPI_OI: "oi", KPI_BWD: "bwd", KPI_GROUND_WON: "gw", KPI_GROUND_LOST: "gl",
            KPI_AERIAL_WON: "aw", KPI_AERIAL_LOST: "al", KPI_PXT_BALL_WIN: "threat"}
    out = {}
    for squad_id, stats in (raw or {}).items():
        stats = {int(k): float(v) for k, v in (stats or {}).items() if v is not None}
        out[str(int(squad_id))] = {name: stats.get(kpi, 0.0) for kpi, name in keys.items()}
    return out


def league_match_squads(match_id: int, *, lake_only: bool = False) -> dict[str, dict[str, float]] | None:
    """Both squads' intervention KPIs for one league match. Played matches never change."""
    cached = _cache_read("iv-league-match", str(int(match_id)))
    if cached and cached.get("squads"):
        return cached["squads"]
    raw = None
    try:
        from app import win_drivers

        disk = win_drivers._read_json(win_drivers._match_raw_path(int(match_id)))
        if disk and disk.get("squads"):
            raw = disk["squads"]
    except Exception:
        logger.debug("Win drivers match cache unreadable for %s", match_id, exc_info=True)
    if raw is None:
        if lake_only:
            return None
        from app.post_match.impect_client import impect_get, v5_path
        from app.post_match.report import _flatten_squad_kpis

        raw = _flatten_squad_kpis(impect_get(v5_path(f"/matches/{int(match_id)}/squad-kpis"))["data"])
    squads = _compact_match_squads(raw)
    if squads:
        _cache_write("iv-league-match", str(int(match_id)), {"matchId": int(match_id), "squads": squads})
    return squads or None


def build_league_battles(matches: list[dict[str, Any]], *, lake_only: bool = False) -> dict[str, Any]:
    loaded: dict[int, dict[str, dict[str, float]]] = {}
    pending = []
    for match in matches:
        match_id = int(match["id"])
        cached = _cache_read("iv-league-match", str(match_id))
        if cached and cached.get("squads"):
            loaded[match_id] = cached["squads"]
        elif not lake_only:
            pending.append(match_id)
    if pending:
        with ThreadPoolExecutor(max_workers=min(2, len(pending))) as pool:
            futures = {pool.submit(league_match_squads, mid): mid for mid in pending}
            for future in as_completed(futures):
                try:
                    squads = future.result()
                    if squads:
                        loaded[futures[future]] = squads
                except Exception:
                    logger.exception("Interventions league match %s failed", futures[future])
    observations = []
    for match in matches:
        squads = loaded.get(int(match["id"]))
        if squads:
            observations.extend(league_observation_pair(match, squads))
    return {
        "matches": len(observations) // 2,
        "expected": len(matches),
        "battles": battle_table(observations),
    }


# ---------------------------------------------------------------- season table (squad KPIs, per game)


def build_league_table(kpi_table: dict[int, dict[int, float]], played: dict[int, int], names: dict[int, str], focus: int) -> dict[str, Any]:
    from app.attacking_threat import _rank_desc

    rows = []
    for squad_id, stats in kpi_table.items():
        games = int(played.get(int(squad_id)) or 0)
        if games <= 0:
            continue
        gw, gl = stats.get(KPI_GROUND_WON) or 0, stats.get(KPI_GROUND_LOST) or 0
        aw, al = stats.get(KPI_AERIAL_WON) or 0, stats.get(KPI_AERIAL_LOST) or 0
        rows.append({
            "squadId": int(squad_id),
            "club": names.get(int(squad_id)) or f"Squad {squad_id}",
            "focus": int(squad_id) == int(focus),
            "played": games,
            "bw": round(float(stats.get(KPI_BALL_WINS) or 0), 1),
            "oi": round(float(stats.get(KPI_OI) or 0), 1),
            "di": round(float(stats.get(KPI_DI) or 0), 1),
            "bwd": round(float(stats.get(KPI_BWD) or 0), 2),
            "threat": round(float(stats.get(KPI_PXT_BALL_WIN) or 0), 3),
            "duelPct": _pct(gw + aw, gl + al),
            "groundPct": _pct(gw, gl),
            "aerialPct": _pct(aw, al),
            "duelsWon": round(float(gw + aw), 1),
        })
    metrics = {"bw": True, "oi": True, "di": False, "bwd": True, "threat": True, "duelPct": True, "groundPct": True, "aerialPct": True}
    ranks = {}
    for key, higher in metrics.items():
        values = {row["squadId"]: float(row[key]) * (1 if higher else -1) for row in rows if row.get(key) is not None}
        ranks[key] = _rank_desc(values)
    for row in rows:
        row["ranks"] = {key: ranks[key].get(row["squadId"]) for key in metrics}
    rows.sort(key=lambda row: (row["ranks"].get("bwd") or 99, row["club"]))
    averages = {}
    for key in metrics:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        averages[key] = round(sum(values) / len(values), 2) if values else None
    return {"rows": rows, "of": len(rows), "averages": averages, "focus": next((r for r in rows if r["focus"]), None)}


# ---------------------------------------------------------------- lake I/O


def _cache_read(kind: str, key: str) -> dict | None:
    from app.analysis_cache import click_json

    payload = click_json(kind, key)
    return payload if isinstance(payload, dict) else None


def _cache_write(kind: str, key: str, data: dict) -> None:
    from app.analysis_cache import write_json

    write_json(kind, key, data)


def _fetch_event_kpis(match_id: int) -> list[dict[str, Any]]:
    from app.attacking_threat import _fetch_event_kpis as fetch

    return fetch(int(match_id))


def _fetch_events(match_id: int) -> list[dict[str, Any]]:
    from app.attacking_threat import _fetch_events as fetch

    return fetch(int(match_id))


def match_summary(match_id: int) -> dict[str, Any]:
    key = str(int(match_id))
    cached = _cache_read("iv-match", key)
    if cached and isinstance(cached.get("squads"), dict):
        return cached
    summary = summarize_match(_fetch_events(int(match_id)), _fetch_event_kpis(int(match_id)))
    summary["matchId"] = int(match_id)
    _cache_write("iv-match", key, summary)
    return summary


def _load_summaries(match_ids: list[int], *, lake_only: bool = False) -> dict[int, dict[str, Any]]:
    loaded: dict[int, dict[str, Any]] = {}
    pending = []
    for match_id in match_ids:
        cached = _cache_read("iv-match", str(match_id))
        if cached and isinstance(cached.get("squads"), dict):
            loaded[int(match_id)] = cached
        elif not lake_only:
            pending.append(int(match_id))
    if pending:
        with ThreadPoolExecutor(max_workers=min(2, len(pending))) as pool:
            futures = {pool.submit(match_summary, mid): mid for mid in pending}
            for future in as_completed(futures):
                try:
                    loaded[futures[future]] = future.result()
                except Exception:
                    logger.exception("Interventions match %s failed", futures[future])
    return loaded


def _evidence() -> dict[str, Any]:
    """League Two history r-values from What Wins Games, when saved."""
    try:
        from app import win_drivers

        history = win_drivers._read_json(win_drivers._history_disk_path()) or {}
        wanted = {"aerial_pct", "duel_pct", "ground_pct", "ball_wins_defenders", "offensive_interventions",
                  "defensive_interventions", "ball_win_threat"}
        stats = [
            {"key": row.get("key"), "label": row.get("label"), "r": row.get("r"),
             "rank": row.get("rank"), "why": row.get("why")}
            for row in history.get("stats") or []
            if row.get("key") in wanted and row.get("r") is not None
        ]
        if stats:
            return {"stats": stats, "sample": (history.get("story") or {}).get("sample")}
    except Exception:
        logger.debug("Win drivers history unreadable", exc_info=True)
    return {"stats": [dict(row) for row in FALLBACK_EVIDENCE], "sample": "Impect League Two, 96 team-seasons (22/23–25/26)."}


# ---------------------------------------------------------------- report


def _scope(scope: str | None) -> str:
    normalized = (scope or "season").strip().lower()
    if normalized not in {"match", "last6", "season"}:
        raise ValueError("scope must be match, last6, or season")
    return normalized


def report_cache_key(season: str | None, scope: str, match_id: int | None = None) -> str:
    season_key = str(season or "default").replace("/", "-")
    if scope == "match" and match_id:
        return f"{season_key}-match-{int(match_id)}"
    return f"{season_key}-{scope}"


POINT_FIELDS = ("side", "kind", "type", "player", "x", "y", "oi", "di", "bwd", "match")
POINT_KINDS = ("bw", "gw", "gl", "aw", "al")
POINT_TYPES = tuple(TYPE_LABELS) + ("OTHER",)


def encode_points(summaries: list[dict[str, Any]], opponents: dict[int, int], match_index: dict[int, int]) -> list[list[Any]]:
    """Compact map points (see POINT_FIELDS). side 0 = Port Vale, 1 = opponent.

    Opponent duels are the mirror of ours, so only their ball wins are kept.
    """
    out: list[list[Any]] = []
    for summary in summaries:
        match_id = int(summary.get("matchId") or 0)
        opponent_id = opponents.get(match_id)
        for point in summary.get("points") or []:
            side = 1 if int(point.get("s") or 0) == opponent_id else 0
            kind = str(point.get("k") or "bw")
            if side == 1 and kind != "bw":
                continue
            type_key = str(point.get("t") or "")
            out.append([
                side,
                POINT_KINDS.index(kind) if kind in POINT_KINDS else 0,
                (POINT_TYPES.index(type_key) if type_key in POINT_TYPES else len(POINT_TYPES) - 1) if kind == "bw" else -1,
                int(point.get("p") or 0),
                point.get("x"),
                point.get("y"),
                point.get("oi", 0),
                point.get("di", 0),
                point.get("bwd", 0),
                match_index.get(match_id, -1),
            ])
    return out[-MAX_POINTS:]


def build_insights(report: dict[str, Any]) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    us = report.get("us") or {}
    them = report.get("them") or {}
    table = report.get("league") or {}
    focus = table.get("focus") or {}
    ranks = focus.get("ranks") or {}
    averages = table.get("averages") or {}
    of = table.get("of") or 24
    battles = (report.get("leagueBattles") or {}).get("battles") or []
    vale_battles = report.get("battles") or []

    top = next((row for row in battles if row["id"] != "di" and row.get("ppgGap") is not None), None)
    if top and top["won"]["games"] >= 20:
        insights.append({
            "tone": "info",
            "title": f"League Two: win the {top['label'].lower()} battle",
            "text": (
                f"Sides that won it took {top['won']['ppg']:.2f} points a game; sides that lost it "
                f"{top['lost']['ppg']:.2f}. That is the biggest swing of any intervention battle "
                f"({(report.get('leagueBattles') or {}).get('matches')} matches)."
            ),
        })
    if us.get("duelPct") is not None and them.get("duelPct") is not None:
        diff = float(us["duelPct"]) - float(them["duelPct"])
        insights.append({
            "tone": "good" if diff >= 0 else "bad",
            "title": f"Duels: {us['duelPct']:.0f}% won",
            "text": (
                f"Aerials {us.get('aerialPct') or 0:.0f}%, ground {us.get('groundPct') or 0:.0f}%. "
                + (f"Season rank {ranks.get('duelPct')} of {of}. " if ranks.get("duelPct") else "")
                + ("We are winning more 50-50s than we lose." if diff >= 0 else "Opponents are winning more 50-50s than us.")
            ),
        })
    if us.get("highShare") is not None:
        insights.append({
            "tone": "good" if float(us["highShare"]) >= float(them.get("highShare") or 0) else "bad",
            "title": f"{us['highShare']:.0f}% of our ball wins are in their third",
            "text": (
                f"{us.get('high') or 0:.1f} final-third regains a game vs {them.get('high') or 0:.1f} by opponents. "
                f"{us.get('deepShare') or 0:.0f}% come in our own third."
            ),
        })
    if focus.get("bwd") is not None and averages.get("bwd") is not None:
        diff = float(focus["bwd"]) - float(averages["bwd"])
        insights.append({
            "tone": "good" if diff >= 0 else "bad",
            "title": f"Ball wins vs defenders: {ranks.get('bwd') or '—'} of {of}",
            "text": (
                f"{focus['bwd']:.1f} a game against a League Two average of {averages['bwd']:.1f}. "
                "Winning it off their back line is the regain most linked to winning."
            ),
        })
    if focus.get("di") is not None and averages.get("di") is not None and float(focus["di"]) > float(averages["di"]):
        insights.append({
            "tone": "bad",
            "title": "High defensive interventions",
            "text": (
                f"{focus['di']:.0f} a game vs average {averages['di']:.0f}. More of these usually means more time "
                "without the ball — not a number to chase."
            ),
        })
    best = next((row for row in vale_battles if row.get("ppgGap") is not None and row["won"]["games"] >= 2 and row["lost"]["games"] >= 2), None)
    if best:
        insights.append({
            "tone": "info",
            "title": f"Our games: {best['label'].lower()} matters most",
            "text": (
                f"When we won it: {best['won']['w']}W {best['won']['d']}D {best['won']['l']}L "
                f"({best['won']['ppg']:.2f} ppg). When we lost it: {best['lost']['w']}W {best['lost']['d']}D "
                f"{best['lost']['l']}L ({best['lost']['ppg']:.2f} ppg)."
            ),
        })
    players = report.get("players") or []
    if players:
        lead = players[0]
        insights.append({
            "tone": "info",
            "title": f"Top ball-winner: {lead['name']}",
            "text": (
                f"{lead['bwTotal']} ball wins ({lead['bw']:.1f} a game), mostly in the "
                f"{(lead.get('topZoneLabel') or 'middle').lower()}."
            ),
        })
    return insights[:6]


def build_report(base: dict[str, Any], scope: str, match_id: int | None = None, *, lake_only: bool = False) -> dict[str, Any]:
    normalized = _scope(scope)
    fixtures = list(base["fixtures"])
    if normalized == "match":
        chosen = match_id or (fixtures[-1]["matchId"] if fixtures else None)
        selected = [row for row in fixtures if int(row["matchId"]) == int(chosen or 0)]
    elif normalized == "last6":
        selected = fixtures[-6:]
    else:
        selected = fixtures
    loaded = _load_summaries([int(row["matchId"]) for row in selected], lake_only=lake_only)
    vale_id = int(base["valeId"])
    present = [row for row in selected if int(row["matchId"]) in loaded]
    games = len(present)
    ours = merge_squads([(loaded[int(r["matchId"])].get("squads") or {}).get(str(vale_id)) for r in present])
    theirs = merge_squads([(loaded[int(r["matchId"])].get("squads") or {}).get(str(r["opponentId"])) for r in present])
    names = base.get("players") or {}
    trend = match_trend(present, loaded, vale_id)
    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": base["season"],
        "competition": base.get("competition") or "League Two",
        "scope": normalized,
        "matchId": int(selected[-1]["matchId"]) if normalized == "match" and selected else None,
        "matchCount": games,
        "fixtures": present,
        "why": WHY,
        "evidence": base.get("evidence") or _evidence(),
        "us": headline_stats(ours, games),
        "them": headline_stats(theirs, games),
        "zones": {"us": zone_rows(ours, games), "them": zone_rows(theirs, games)},
        "units": {"us": unit_rows(ours, games), "them": unit_rows(theirs, games)},
        "types": {"us": type_rows(ours, games), "them": type_rows(theirs, games)},
        "periods": {"us": period_rows(ours, games), "them": period_rows(theirs, games)},
        "players": player_rows(ours, names),
        "points": encode_points(
            [loaded[int(r["matchId"])] for r in present],
            {int(r["matchId"]): int(r["opponentId"]) for r in present},
            {int(r["matchId"]): index for index, r in enumerate(present)},
        ),
        "pointFields": list(POINT_FIELDS),
        "pointKinds": list(POINT_KINDS),
        "pointTypes": list(POINT_TYPES),
        "trend": trend,
        "results": results_split(trend),
        "battles": battle_table(vale_observations(trend, loaded, vale_id)),
        "league": base.get("table") or {},
        "leagueBattles": base.get("leagueBattles") or {},
        "typeColors": TYPE_COLORS,
        "typeLabels": TYPE_LABELS,
        "ready": True,
    }
    report["insights"] = build_insights(report)
    return report


def _with_badges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def empty_report(season: str | None, scope: str, match_id: int | None = None) -> dict[str, Any]:
    return {
        "ready": False,
        "season": season or ALLOWED_SEASONS[0],
        "scope": scope,
        "matchId": match_id,
        "why": WHY,
        "message": LAKE_EMPTY,
        "matchCount": 0,
        "fixtures": [],
    }


def read_report(season: str | None, scope: str | None, match_id: int | None = None) -> dict[str, Any]:
    """Click path. Never calls Impect."""
    normalized = _scope(scope)
    key = report_cache_key(season, normalized, match_id if normalized == "match" else None)
    cached = _cache_read("iv-report", key)
    if not cached and normalized == "match" and not match_id:
        fixtures = read_fixtures(season).get("fixtures") or []
        if fixtures:
            cached = _cache_read("iv-report", report_cache_key(season, "match", int(fixtures[-1]["matchId"])))
    if not cached:
        payload = empty_report(season, normalized, match_id)
        progress = _cache_read("iv-progress", "default")
        if progress and progress.get("stage") not in {"done", "failed"}:
            payload["progress"] = progress
            payload["message"] = (
                "Saving Port Vale's interventions into the data lake now. "
                "This view fills in on its own in a few minutes."
            )
        return payload
    payload = dict(cached)
    league = dict(payload.get("league") or {})
    league["rows"] = _with_badges(league.get("rows") or [])
    payload["league"] = league
    payload["ready"] = True
    return payload


def read_meta() -> dict[str, Any]:
    cached = _cache_read("iv-meta", "default")
    if cached and cached.get("seasons"):
        return dict(cached)
    return {
        "seasons": [{"value": value, "label": value} for value in ALLOWED_SEASONS],
        "defaultSeason": ALLOWED_SEASONS[0],
        "why": WHY,
        "ready": False,
    }


def read_fixtures(season: str | None) -> dict[str, Any]:
    cached = _cache_read("iv-fixtures", str(season or "default").replace("/", "-"))
    if cached:
        return dict(cached)
    return {"season": season or "", "fixtures": [], "defaultMatchId": None, "ready": False}


# ---------------------------------------------------------------- warm (Impect)


def season_base(season: str) -> dict[str, Any]:
    from app import attacking_threat as at

    ctx = at._resolve_season(season)
    matches = at._iteration_matches(ctx["iterationId"])
    completed = at._completed(matches)
    table = build_league_table(at._flatten_kpis(ctx["iterationId"]), at._games_played(completed), ctx["names"], ctx["valeId"])
    return {
        "iterationId": ctx["iterationId"],
        "season": ctx["season"],
        "competition": ctx["competition"],
        "valeId": ctx["valeId"],
        "table": table,
        "fixtures": at._vale_fixtures(completed, ctx["valeId"], ctx["names"]),
        "completed": completed,
        "players": at._player_names(ctx["iterationId"]),
        "evidence": _evidence(),
    }


def _progress(stage: str, **extra: Any) -> None:
    _cache_write("iv-progress", "default", {"stage": stage, "at": datetime.now(UTC).isoformat(), **extra})


def _store(report: dict[str, Any]) -> None:
    key = report_cache_key(report.get("season"), str(report.get("scope") or "season"), report.get("matchId"))
    _cache_write("iv-report", key, report)


def store_views(base: dict[str, Any], *, lake_only: bool = False) -> dict[str, Any]:
    season = base["season"]
    season_report = build_report(base, "season", lake_only=lake_only)
    _store(season_report)
    _store(build_report(base, "last6", lake_only=lake_only))
    for row in base["fixtures"]:
        _store(build_report(base, "match", int(row["matchId"]), lake_only=lake_only))
    fixtures = list(base["fixtures"])
    _cache_write("iv-fixtures", str(season).replace("/", "-"), {
        "season": season,
        "fixtures": fixtures,
        "defaultMatchId": fixtures[-1]["matchId"] if fixtures else None,
        "ready": True,
    })
    return season_report


def warm_season(season: str) -> dict[str, Any]:
    base = season_base(season)
    _progress("vale", season=base["season"], matches=len(base["fixtures"]))
    _load_summaries([int(row["matchId"]) for row in base["fixtures"]])
    store_views(base)
    _progress("league", season=base["season"], matches=len(base["completed"]))
    base["leagueBattles"] = build_league_battles(base["completed"])
    season_report = store_views(base, lake_only=True)
    return {"season": base["season"], "matches": season_report.get("matchCount"),
            "leagueMatches": base["leagueBattles"].get("matches")}


def warm_interventions(*, include_previous: bool = True) -> dict[str, Any]:
    """Write the Interventions pack into the analysis lake. Not used on page open."""
    meta = {
        "seasons": [{"value": value, "label": value} for value in ALLOWED_SEASONS],
        "defaultSeason": ALLOWED_SEASONS[0],
        "why": WHY,
        "ready": True,
    }
    _cache_write("iv-meta", "default", meta)
    result: dict[str, Any] = {"ok": True, "seasons": []}
    seasons = list(ALLOWED_SEASONS) if include_previous else [ALLOWED_SEASONS[0]]
    try:
        for season in seasons:
            try:
                result["seasons"].append(warm_season(season))
            except Exception as exc:
                logger.exception("Interventions warm for %s failed", season)
                result.setdefault("errors", {})[season] = str(exc)
                if season == ALLOWED_SEASONS[0]:
                    result["ok"] = False
    finally:
        _progress("done" if result["ok"] else "failed")
    return result


# ---------------------------------------------------------------- routes


def register_interventions_routes(app: FastAPI) -> None:
    @app.get("/interventions")
    def interventions_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "interventions.html")

    @app.get("/api/interventions/meta")
    def interventions_meta() -> dict:
        return read_meta()

    @app.get("/api/interventions/fixtures")
    def interventions_fixtures(season: str | None = Query(None)) -> dict:
        return read_fixtures(season)

    @app.get("/api/interventions/report")
    def interventions_report(
        season: str | None = Query(None),
        scope: str | None = Query("season"),
        match_id: int | None = Query(None, alias="matchId"),
    ) -> JSONResponse:
        try:
            payload = read_report(season, scope, match_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
