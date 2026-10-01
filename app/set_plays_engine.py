"""Set-play extraction and aggregation for the Set Plays tab.

Pure functions only: Impect match events in, compact set-play records out, and
league / Port Vale aggregates built from those records. No I/O here.

Coordinates are Impect ``adjCoordinates``: each event is drawn from the acting
squad's point of view, attacking towards x = +52.5, with +y the left wing.
Defending events are flipped back into the attacking squad's frame.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

SHOT_XG_KPI_ID = 82
SECOND_PHASE_SECONDS = 20.0
COUNTER_SECONDS = 30.0
SEASON_GAMES = 46
FINAL_THIRD_X = 17.5
BOX_X = 36.0
BOX_HALF_WIDTH = 20.16
SIX_YARD_X = 47.0
SIX_YARD_HALF_WIDTH = 9.16
HALF_OFFSETS = (0, 2700, 5400, 6300)

RESTART_TYPES = {"CORNER", "FREE_KICK", "THROW_IN"}
CONTACT_TYPES = {
    "RECEPTION", "LOOSE_BALL_REGAIN", "SHOT", "GK_SAVE", "GK_CATCH", "BLOCK",
    "CLEARANCE", "INTERCEPTION", "AERIAL_DUEL", "GROUND_DUEL", "PASS", "DRIBBLE",
}
GK_TYPES = {"GK_CATCH", "GK_SAVE"}

TYPE_LABELS = {
    "corner": "Corners",
    "free_kick": "Free kicks",
    "throw_in": "Attacking throw-ins",
    "penalty": "Penalties",
}
SUB_LABELS = {
    "direct": "Delivered straight in",
    "short": "Short routine",
    "direct_shot": "Shot direct",
    "cross": "Crossed into the box",
    "pass": "Played short / recycled",
    "long": "Long throw into the box",
}
ZONE_LABELS = {
    "near_post": "Near post",
    "goalmouth": "Goalmouth (GK zone)",
    "far_post": "Far post",
    "penalty_spot": "Penalty spot",
    "edge_box": "Edge of the box",
    "outside": "Outside the box",
}
ZONE_ORDER = ("near_post", "goalmouth", "far_post", "penalty_spot", "edge_box", "outside")
FK_AREA_LABELS = {
    "wide": "Wide, final third",
    "central": "Central, final third",
    "middle": "Opposition half, deep",
}

BUCKETS: tuple[dict[str, Any], ...] = (
    {"id": "all", "label": "All set plays (no pens)"},
    {"id": "corner", "label": "Corners"},
    {"id": "corner_in", "label": "Corners — inswinging"},
    {"id": "corner_out", "label": "Corners — outswinging"},
    {"id": "corner_short", "label": "Corners — short"},
    {"id": "fk_cross", "label": "Free kicks — crossed in"},
    {"id": "fk_direct", "label": "Free kicks — shot direct"},
    {"id": "fk_other", "label": "Free kicks — short / recycled"},
    {"id": "throw_long", "label": "Long throws into the box"},
    {"id": "throw_other", "label": "Other attacking throws"},
    {"id": "penalty", "label": "Penalties"},
)


# ---------------------------------------------------------------- helpers
def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _xy(point: Any) -> tuple[float, float] | None:
    coords = (point or {}).get("adjCoordinates") or (point or {}).get("coordinates") or {}
    try:
        return round(float(coords["x"]), 1), round(float(coords["y"]), 1)
    except (KeyError, TypeError, ValueError):
        return None


def _seconds(event: dict) -> float:
    return _num((event.get("gameTime") or {}).get("gameTimeInSec"))


def match_minute(seconds: float) -> int:
    """Impect restarts the clock at 10000s per period."""
    block = int(_num(seconds) // 10000)
    offset = HALF_OFFSETS[block] if 0 <= block < len(HALF_OFFSETS) else 0
    return int((_num(seconds) - block * 10000 + offset) // 60) + 1


def _player(event: dict) -> int:
    return _int((event.get("player") or {}).get("id"))


def _in_box(x: float, y: float) -> bool:
    return x >= BOX_X and abs(y) <= BOX_HALF_WIDTH


def _frame(event: dict, attacking_id: int, point: str = "start") -> tuple[float, float] | None:
    xy = _xy(event.get(point))
    if xy is None:
        return None
    if _int(event.get("squadId")) != attacking_id:
        return -xy[0], -xy[1]
    return xy


def side_of(y: float | None) -> str:
    if y is None:
        return "central"
    if y > 10:
        return "left"
    if y < -10:
        return "right"
    return "central"


def swing_of(side: str, foot: str) -> str | None:
    """Right-footer from the right is an outswinger; left-footer from the right swings in."""
    if side not in {"left", "right"} or foot not in {"R", "L"}:
        return None
    if side == "right":
        return "out" if foot == "R" else "in"
    return "in" if foot == "R" else "out"


def target_zone(x: float | None, y: float | None, near_sign: int) -> str:
    if x is None or y is None or not _in_box(x, y):
        return "outside"
    yn = y * near_sign
    if x >= 42.0:
        if yn > 3.0:
            return "near_post"
        if yn < -3.0:
            return "far_post"
        return "goalmouth" if x >= SIX_YARD_X else "penalty_spot"
    return "penalty_spot" if abs(yn) <= 9.0 else "edge_box"


def fk_area(x: float, y: float) -> str:
    if x >= FINAL_THIRD_X:
        return "central" if abs(y) <= BOX_HALF_WIDTH else "wide"
    return "middle"


def _foot(event: dict) -> str:
    body = str(event.get("bodyPartExtended") or event.get("bodyPart") or "").upper()
    if "RIGHT" in body:
        return "R"
    if "LEFT" in body:
        return "L"
    return ""


def _is_head(event: dict) -> bool:
    body = str(event.get("bodyPartExtended") or event.get("bodyPart") or "").upper()
    return "HEAD" in body or str(event.get("action") or "").upper() == "HEADER"


def xg_by_event(event_kpis: Iterable[dict]) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for row in event_kpis or []:
        if _int(row.get("kpiId")) != SHOT_XG_KPI_ID:
            continue
        event_id = _int(row.get("eventId"))
        if event_id > 0:
            out[event_id] += _num(row.get("value"))
    return dict(out)


# ---------------------------------------------------------------- extraction
def _is_penalty(event: dict) -> bool:
    return str(event.get("action") or "").upper() == "PENALTY_KICK"


def _restart_of(chain: list[dict]) -> dict | None:
    for event in chain:
        action_type = str(event.get("actionType") or "").upper()
        if _is_penalty(event):
            return None
        if action_type in RESTART_TYPES or action_type == "SHOT":
            return event
        if action_type == "GOAL_KICK" or action == "KICK_OFF":
            return None
    return None


def _ends_in_box(event: dict, attacking_id: int) -> bool:
    end = _frame(event, attacking_id, "end")
    return end is not None and _in_box(*end)


def _delivery_of(chain: list[dict], restart: dict, attacking_id: int) -> dict:
    """The ball that actually goes into the box. Short corners and worked free kicks come later in the chain."""
    action_type = str(restart.get("actionType") or "").upper()
    if action_type not in {"CORNER", "FREE_KICK"} or _ends_in_box(restart, attacking_id):
        return restart
    for event in chain[chain.index(restart) + 1:]:
        if _int(event.get("squadId")) != attacking_id:
            break
        kind = str(event.get("actionType") or "").upper()
        if kind == "SHOT" or (kind == "PASS" and _ends_in_box(event, attacking_id)):
            return event
    return restart


def _classify(restart: dict, delivery: dict, attacking_id: int) -> dict[str, Any] | None:
    action_type = str(restart.get("actionType") or "").upper()
    start = _frame(restart, attacking_id) or (0.0, 0.0)
    if action_type == "CORNER":
        short = not _ends_in_box(restart, attacking_id)
        return {"type": "corner", "sub": "short" if short else "direct", "area": None}
    if action_type == "THROW_IN":
        if start[0] < FINAL_THIRD_X:
            return None
        end = _frame(restart, attacking_id, "end")
        into_box = end is not None and _in_box(*end)
        return {"type": "throw_in", "sub": "long" if into_box else "pass", "area": None}
    # Free kick (or a free kick shot recorded straight as SHOT)
    if start[0] < 0:
        return None
    if action_type == "SHOT":
        return {"type": "free_kick", "sub": "direct_shot", "area": fk_area(*start)}
    first = delivery
    if str(first.get("actionType") or "").upper() == "SHOT":
        sub = "direct_shot"
    else:
        end = _frame(first, attacking_id, "end")
        sub = "cross" if end is not None and _in_box(*end) else "pass"
    return {"type": "free_kick", "sub": sub, "area": fk_area(*start)}


def _first_contact(chain: list[dict], delivery: dict, attacking_id: int) -> dict[str, Any]:
    receiver = ((delivery.get("pass") or {}).get("receiver") or {}) if isinstance(delivery.get("pass"), dict) else {}
    after = chain[chain.index(delivery) + 1:] if delivery in chain else []
    contact = next(
        (event for event in after if str(event.get("actionType") or "").upper() in CONTACT_TYPES),
        None,
    )
    result: dict[str, Any] = {"team": None, "pl": 0, "head": False, "loser": 0, "gk": False}
    if contact is not None:
        same = _int(contact.get("squadId")) == attacking_id
        result.update({
            "team": "att" if same else "def",
            "pl": _player(contact),
            "head": _is_head(contact),
            "gk": str(contact.get("actionType") or "").upper() in GK_TYPES,
        })
        duel = contact.get("duel") if isinstance(contact.get("duel"), dict) else {}
        if duel.get("playerId"):
            result["loser"] = _int(duel.get("playerId"))
        xy = _frame(contact, attacking_id)
        if xy:
            result["x"], result["y"] = xy
    rtype = str(receiver.get("type") or "").upper()
    if rtype in {"TEAMMATE", "TEAM"} and result["team"] is None:
        result.update({"team": "att", "pl": _int(receiver.get("playerId"))})
    elif rtype == "OPPONENT" and result["team"] is None:
        result.update({"team": "def", "pl": _int(receiver.get("playerId"))})
    return result


def extract_match(
    events: list[dict],
    event_kpis: list[dict],
    match_id: int,
) -> dict[str, Any]:
    """Every attacking set play in one match, for both squads."""
    xg = xg_by_event(event_kpis)
    ordered = sorted(
        (e for e in events or [] if isinstance(e, dict)),
        key=lambda e: (_int(e.get("periodId")), _int(e.get("index"))),
    )
    position = {id(event): i for i, event in enumerate(ordered)}
    chains: dict[int, list[dict]] = defaultdict(list)
    for event in ordered:
        chain_id = _int((event.get("setPiece") or {}).get("id"))
        if chain_id:
            chains[chain_id].append(event)

    starts: list[tuple[int, int]] = []
    for chain_id, chain in chains.items():
        restart = _restart_of(chain)
        if restart is not None:
            starts.append((position[id(restart)], chain_id))
    starts.sort()

    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"shots": 0, "xg": 0.0, "goals": 0})
    for event in ordered:
        if str(event.get("actionType") or "").upper() != "SHOT":
            continue
        squad = str(_int(event.get("squadId")))
        totals[squad]["shots"] += 1
        totals[squad]["xg"] += xg.get(_int(event.get("id")), 0.0)
        if str(event.get("result") or "").upper() == "SUCCESS":
            totals[squad]["goals"] += 1

    records: list[dict[str, Any]] = []
    for n, (pos, chain_id) in enumerate(starts):
        chain = chains[chain_id]
        restart = ordered[pos]
        attacking_id = _int(restart.get("squadId"))
        if attacking_id <= 0:
            continue
        delivery = _delivery_of(chain, restart, attacking_id)
        kind = _classify(restart, delivery, attacking_id)
        if kind is None:
            continue
        start = _frame(restart, attacking_id) or (0.0, 0.0)
        side = side_of(start[1]) if kind["type"] != "penalty" else "central"
        dstart = _frame(delivery, attacking_id) or start
        dend = _frame(delivery, attacking_id, "end")
        if str(delivery.get("actionType") or "").upper() == "SHOT":
            dend = dstart
        dside = side_of(dstart[1])
        near_sign = 1 if dstart[1] > 0 else -1
        foot = _foot(delivery)
        swing = swing_of(dside, foot) if kind["type"] in {"corner", "free_kick"} and kind["sub"] != "direct_shot" else None
        t0 = _seconds(restart)
        period = _int(restart.get("periodId"))
        chain_ids = {id(e) for e in chain}
        next_start = starts[n + 1][0] if n + 1 < len(starts) else len(ordered)

        shots: list[dict[str, Any]] = []
        counter = {"shots": 0, "xg": 0.0, "goals": 0}
        for event in ordered[pos:]:
            if _int(event.get("periodId")) != period:
                break
            elapsed = _seconds(event) - t0
            if elapsed > COUNTER_SECONDS:
                break
            if str(event.get("actionType") or "").upper() != "SHOT" or _is_penalty(event):
                continue
            squad = _int(event.get("squadId"))
            value = round(xg.get(_int(event.get("id")), 0.0), 4)
            goal = str(event.get("result") or "").upper() == "SUCCESS"
            if squad == attacking_id:
                in_chain = id(event) in chain_ids
                if not in_chain and (elapsed > SECOND_PHASE_SECONDS or position[id(event)] >= next_start):
                    continue
                xy = _frame(event, attacking_id) or (None, None)
                shots.append({
                    "pl": _player(event), "xg": value, "goal": goal,
                    "ph": "first" if in_chain else "second", "head": _is_head(event),
                    "x": xy[0], "y": xy[1],
                })
            else:
                counter["shots"] += 1
                counter["xg"] = round(counter["xg"] + value, 4)
                counter["goals"] += int(goal)

        contact = _first_contact(chain, delivery, attacking_id)
        record = {
            "id": chain_id,
            "m": int(match_id),
            "sq": attacking_id,
            "p": period,
            "min": match_minute(t0),
            "type": kind["type"],
            "sub": kind["sub"],
            "area": kind["area"],
            "side": side,
            "foot": foot,
            "swing": swing,
            "taker": _player(restart),
            "del": _player(delivery),
            "sx": start[0], "sy": start[1],
            "dx": dend[0] if dend else None,
            "dy": dend[1] if dend else None,
            "zone": target_zone(dend[0], dend[1], near_sign) if dend else "outside",
            "fc": contact,
            "shots": shots,
            "counter": counter,
        }
        records.append(record)

    for event in ordered:
        if not _is_penalty(event):
            continue
        attacking_id = _int(event.get("squadId"))
        xy = _frame(event, attacking_id) or (41.5, 0.0)
        records.append({
            "id": _int(event.get("id")),
            "m": int(match_id),
            "sq": attacking_id,
            "p": _int(event.get("periodId")),
            "min": match_minute(_seconds(event)),
            "type": "penalty", "sub": "direct", "area": None, "side": "central",
            "foot": _foot(event), "swing": None,
            "taker": _player(event), "del": _player(event),
            "sx": xy[0], "sy": xy[1], "dx": None, "dy": None, "zone": "penalty_spot",
            "fc": {},
            "shots": [{
                "pl": _player(event),
                "xg": round(xg.get(_int(event.get("id")), 0.0), 4),
                "goal": str(event.get("result") or "").upper() == "SUCCESS",
                "ph": "first", "head": False, "x": xy[0], "y": xy[1],
            }],
            "counter": {"shots": 0, "xg": 0.0, "goals": 0},
        })
    records.sort(key=lambda r: (r["p"], r["min"]))

    squads = sorted({_int(e.get("squadId")) for e in ordered if _int(e.get("squadId")) > 0})
    for record in records:
        others = [s for s in squads if s != record["sq"]]
        record["opp"] = others[0] if others else 0
    return {
        "matchId": int(match_id),
        "records": records,
        "totals": {k: {"shots": int(v["shots"]), "xg": round(v["xg"], 3), "goals": int(v["goals"])} for k, v in totals.items()},
    }


# ---------------------------------------------------------------- aggregation
def record_xg(record: dict) -> float:
    return sum(_num(s.get("xg")) for s in record.get("shots") or [])


def record_goals(record: dict) -> int:
    return sum(1 for s in record.get("shots") or [] if s.get("goal"))


def in_bucket(record: dict, bucket: str) -> bool:
    kind, sub = record.get("type"), record.get("sub")
    if bucket == "all":
        return kind != "penalty"
    if bucket == "corner":
        return kind == "corner"
    if bucket == "corner_in":
        return kind == "corner" and sub == "direct" and record.get("swing") == "in"
    if bucket == "corner_out":
        return kind == "corner" and sub == "direct" and record.get("swing") == "out"
    if bucket == "corner_short":
        return kind == "corner" and sub == "short"
    if bucket == "fk_cross":
        return kind == "free_kick" and sub == "cross"
    if bucket == "fk_direct":
        return kind == "free_kick" and sub == "direct_shot"
    if bucket == "fk_other":
        return kind == "free_kick" and sub == "pass"
    if bucket == "throw_long":
        return kind == "throw_in" and sub == "long"
    if bucket == "throw_other":
        return kind == "throw_in" and sub != "long"
    if bucket == "penalty":
        return kind == "penalty"
    return False


def _rate(part: float, whole: float, digits: int = 1) -> float | None:
    return round(100.0 * part / whole, digits) if whole else None


def _per(value: float, games: int, digits: int = 2) -> float:
    return round(value / games, digits) if games else 0.0


def summarize(records: list[dict], games: int, *, attacking: bool) -> dict[str, Any]:
    """Volume, quality and outcome for one side of a squad's set plays."""
    n = len(records)
    shots = sum(len(r.get("shots") or []) for r in records)
    with_shot = sum(1 for r in records if r.get("shots"))
    xg = sum(record_xg(r) for r in records)
    goals = sum(record_goals(r) for r in records)
    first_xg = sum(_num(s.get("xg")) for r in records for s in r.get("shots") or [] if s.get("ph") == "first")
    second_xg = xg - first_xg
    second_goals = sum(1 for r in records for s in r.get("shots") or [] if s.get("goal") and s.get("ph") == "second")
    headed = sum(1 for r in records for s in r.get("shots") or [] if s.get("head"))
    contested = [r for r in records if (r.get("fc") or {}).get("team")]
    att_won = sum(1 for r in contested if r["fc"]["team"] == "att")
    gk_claims = sum(1 for r in contested if r["fc"].get("gk"))
    in_box = [r for r in records if r.get("zone") != "outside"]
    counter_xg = sum(_num((r.get("counter") or {}).get("xg")) for r in records)
    counter_goals = sum(_int((r.get("counter") or {}).get("goals")) for r in records)
    fc_won = att_won if attacking else len(contested) - att_won
    return {
        "n": n,
        "perGame": _per(n, games),
        "shots": shots,
        "shotRate": _rate(with_shot, n),
        "xg": round(xg, 3),
        "xgPerGame": _per(xg, games, 3),
        "xgPer": round(xg / n, 4) if n else None,
        "goals": goals,
        "goalsPerGame": _per(goals, games),
        "firstXg": round(first_xg, 3),
        "secondXg": round(second_xg, 3),
        "secondGoals": second_goals,
        "headedShots": headed,
        "contested": len(contested),
        "fcWon": fc_won,
        "fcWonPct": _rate(fc_won, len(contested)),
        "gkClaims": gk_claims,
        "intoBoxPct": _rate(len(in_box), n),
        "counterXg": round(counter_xg, 3),
        "counterGoals": counter_goals,
    }


def bucket_rows(records: list[dict], games: int, *, attacking: bool) -> list[dict[str, Any]]:
    rows = []
    for spec in BUCKETS:
        subset = [r for r in records if in_bucket(r, spec["id"])]
        if not subset and spec["id"] != "all":
            continue
        row = summarize(subset, games, attacking=attacking)
        row.update({"id": spec["id"], "label": spec["label"]})
        rows.append(row)
    return rows


def zone_rows(records: list[dict], *, attacking: bool) -> list[dict[str, Any]]:
    by_zone: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("type") in {"corner", "free_kick"} and record.get("sub") != "direct_shot":
            by_zone[str(record.get("zone") or "outside")].append(record)
    total = sum(len(v) for v in by_zone.values())
    rows = []
    for zone in ZONE_ORDER:
        subset = by_zone.get(zone) or []
        contested = [r for r in subset if (r.get("fc") or {}).get("team")]
        att_won = sum(1 for r in contested if r["fc"]["team"] == "att")
        won = att_won if attacking else len(contested) - att_won
        xg = sum(record_xg(r) for r in subset)
        rows.append({
            "id": zone,
            "label": ZONE_LABELS[zone],
            "n": len(subset),
            "share": _rate(len(subset), total),
            "fcWonPct": _rate(won, len(contested)),
            "xg": round(xg, 3),
            "xgPer": round(xg / len(subset), 4) if subset else None,
            "goals": sum(record_goals(r) for r in subset),
        })
    return rows


def squad_games(match_rows: Iterable[dict]) -> dict[int, int]:
    games: dict[int, int] = defaultdict(int)
    for match in match_rows:
        for key in ("homeSquadId", "awaySquadId"):
            squad = _int(match.get(key))
            if squad:
                games[squad] += 1
    return dict(games)


LEAGUE_METRICS: tuple[dict[str, Any], ...] = (
    {"id": "goalsFor", "label": "Set-play goals for / game (no pens)", "better": "high", "fmt": 2},
    {"id": "goalsAgainst", "label": "Set-play goals against / game (no pens)", "better": "low", "fmt": 2},
    {"id": "xgFor", "label": "Set-play xG for / game", "better": "high", "fmt": 2},
    {"id": "xgAgainst", "label": "Set-play xG against / game", "better": "low", "fmt": 2},
    {"id": "xgDiff", "label": "Set-play xG difference / game", "better": "high", "fmt": 2},
    {"id": "cornersFor", "label": "Corners won / game", "better": "high", "fmt": 1},
    {"id": "cornersAgainst", "label": "Corners conceded / game", "better": "low", "fmt": 1},
    {"id": "xgPerCornerFor", "label": "xG per corner (attack)", "better": "high", "fmt": 3},
    {"id": "xgPerCornerAgainst", "label": "xG per corner (defence)", "better": "low", "fmt": 3},
    {"id": "fcAttack", "label": "First contacts won attacking", "better": "high", "fmt": 0, "pct": True},
    {"id": "fcDefence", "label": "First contacts won defending", "better": "high", "fmt": 0, "pct": True},
    {"id": "shotRateFor", "label": "Set plays ending in a shot", "better": "high", "fmt": 0, "pct": True},
    {"id": "shotRateAgainst", "label": "Opposition set plays ending in a shot", "better": "low", "fmt": 0, "pct": True},
    {"id": "secondXgFor", "label": "Second-ball xG for / game", "better": "high", "fmt": 2},
    {"id": "secondXgAgainst", "label": "Second-ball xG against / game", "better": "low", "fmt": 2},
    {"id": "counterXgAgainst", "label": "Counter xG conceded off our set plays / game", "better": "low", "fmt": 3},
    {"id": "spShareFor", "label": "Share of our goals from set plays (no pens)", "better": "high", "fmt": 0, "pct": True},
)


def league_table(
    records: list[dict],
    games: dict[int, int],
    names: dict[int, str],
    goals_total: dict[int, int],
    focus_id: int,
) -> dict[str, Any]:
    by_for: dict[int, list[dict]] = defaultdict(list)
    by_against: dict[int, list[dict]] = defaultdict(list)
    for record in records:
        by_for[_int(record.get("sq"))].append(record)
        by_against[_int(record.get("opp"))].append(record)
    rows = []
    for squad, played in games.items():
        if played <= 0:
            continue
        att_all = [r for r in by_for.get(squad, []) if r.get("type") != "penalty"]
        def_all = [r for r in by_against.get(squad, []) if r.get("type") != "penalty"]
        att = summarize(att_all, played, attacking=True)
        dfn = summarize(def_all, played, attacking=False)
        corners_for = [r for r in att_all if r.get("type") == "corner"]
        corners_against = [r for r in def_all if r.get("type") == "corner"]
        pens_for = [r for r in by_for.get(squad, []) if r.get("type") == "penalty"]
        pens_against = [r for r in by_against.get(squad, []) if r.get("type") == "penalty"]
        sp_goals = att["goals"]
        total_goals = int(goals_total.get(squad) or 0)
        cf_xg = sum(record_xg(r) for r in corners_for)
        ca_xg = sum(record_xg(r) for r in corners_against)
        rows.append({
            "squadId": squad,
            "club": names.get(squad) or f"Squad {squad}",
            "focus": squad == focus_id,
            "played": played,
            "goalsForTotal": sp_goals,
            "goalsAgainstTotal": dfn["goals"],
            "goalsFor": _per(sp_goals, played),
            "goalsAgainst": _per(dfn["goals"], played),
            "xgFor": _per(att["xg"], played, 3),
            "xgAgainst": _per(dfn["xg"], played, 3),
            "xgDiff": round(_per(att["xg"], played, 3) - _per(dfn["xg"], played, 3), 3),
            "cornersFor": _per(len(corners_for), played),
            "cornersAgainst": _per(len(corners_against), played),
            "xgPerCornerFor": round(cf_xg / len(corners_for), 4) if corners_for else None,
            "xgPerCornerAgainst": round(ca_xg / len(corners_against), 4) if corners_against else None,
            "fcAttack": att["fcWonPct"],
            "fcDefence": dfn["fcWonPct"],
            "shotRateFor": att["shotRate"],
            "shotRateAgainst": dfn["shotRate"],
            "secondXgFor": _per(att["secondXg"], played, 3),
            "secondXgAgainst": _per(dfn["secondXg"], played, 3),
            "counterXgAgainst": _per(att["counterXg"], played, 3),
            "spShareFor": _rate(sp_goals, total_goals, 0) if total_goals else None,
            "pensFor": len(pens_for),
            "pensScored": sum(record_goals(r) for r in pens_for),
            "pensAgainst": len(pens_against),
            "goalDiffTotal": sp_goals - dfn["goals"],
        })
    for metric in LEAGUE_METRICS:
        key = metric["id"]
        valued = [r for r in rows if r.get(key) is not None]
        reverse = metric["better"] == "high"
        valued.sort(key=lambda r: (r[key], -r["squadId"]) if reverse else (-r[key], -r["squadId"]), reverse=True)
        for index, row in enumerate(valued, start=1):
            row.setdefault("ranks", {})[key] = index
    rows.sort(key=lambda r: (-(r["xgDiff"]), r["club"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return {"rows": rows, "of": len(rows)}


def benchmarks(table: dict[str, Any], focus_id: int) -> list[dict[str, Any]]:
    rows = table.get("rows") or []
    focus = next((r for r in rows if r["squadId"] == focus_id), None)
    out = []
    for metric in LEAGUE_METRICS:
        key = metric["id"]
        valued = [r for r in rows if r.get(key) is not None]
        if not valued:
            continue
        high = metric["better"] == "high"
        ordered = sorted(valued, key=lambda r: r[key], reverse=high)
        best = ordered[0]
        top3 = ordered[:3]
        avg = sum(r[key] for r in valued) / len(valued)
        out.append({
            "id": key,
            "label": metric["label"],
            "better": metric["better"],
            "digits": metric["fmt"],
            "pct": bool(metric.get("pct")),
            "vale": focus.get(key) if focus else None,
            "rank": (focus.get("ranks") or {}).get(key) if focus else None,
            "of": len(valued),
            "leagueAvg": round(avg, 4),
            "top3Avg": round(sum(r[key] for r in top3) / len(top3), 4),
            "best": best[key],
            "bestClub": best["club"],
        })
    return out


def points_per_goal(results: list[tuple[int, int, int, int]]) -> float:
    """Least-squares points per game against goal difference per game, from this season's results."""
    points: dict[int, float] = defaultdict(float)
    diff: dict[int, float] = defaultdict(float)
    games: dict[int, int] = defaultdict(int)
    for home, away, hg, ag in results:
        games[home] += 1
        games[away] += 1
        diff[home] += hg - ag
        diff[away] += ag - hg
        if hg > ag:
            points[home] += 3
        elif hg < ag:
            points[away] += 3
        else:
            points[home] += 1
            points[away] += 1
    xs = [diff[s] / games[s] for s in games if games[s]]
    ys = [points[s] / games[s] for s in games if games[s]]
    if len(xs) < 6:
        return 0.75
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return 0.75
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    return round(min(1.5, max(0.3, slope)), 3)
