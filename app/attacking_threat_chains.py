"""Threat chains and player links for Attacking Threat.

Works on compact per-match event packs saved in the data lake (kind
``at-events``). A possession is one Impect ``sequenceIndex`` in a period while
Port Vale are the attacking squad. Threat per action is the same positive
packing threat used everywhere else on the page.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.post_match.phase_analysis import PHASE_LABELS, _phase_bucket

SHOT_XG_KPI_ID = 82
THREAT_KPIS = {1404, 1405, 1406, 1408, 1409}
NOT_A_STEP = {
    "RECEPTION", "OUT", "NO_VIDEO", "FOUL", "OFFSIDE", "FINAL_WHISTLE", "KICK_OFF",
    "YELLOW_CARD", "RED_CARD", "SECOND_YELLOW", "REFEREE_INTERCEPTION", "GOAL", "SUBSTITUTION",
}
SET_PIECE_TYPES = {"CORNER", "FREE_KICK", "PENALTY", "PENALTY_KICK"}
REGAIN_TYPES = {"LOOSE_BALL_REGAIN", "INTERCEPTION", "BALL_WIN", "GROUND_DUEL", "AERIAL_DUEL", "BLOCK", "CLEARANCE"}
GK_TYPES = {"GK_CATCH", "GK_SAVE", "GOAL_KICK"}
THREAT_STEP_MIN = 0.01
THREATENING_CHAIN = 0.1
PATTERN_LENGTH = 3
TOP_CHAINS = 14
TOP_PAIRS = 16
PAIR_LINES = 14
NETWORK_EDGES = 14
NETWORK_MIN_TOUCHES = 8
NETWORK_MAX_NODES = 11
HALF_OFFSETS = (0, 2700, 5400, 6300)

ORIGINS = (
    ("regain_high", "Regain in the final third", "#f5c518"),
    ("regain_mid", "Regain in midfield", "#fbbf24"),
    ("regain_low", "Regain in our third", "#f59e0b"),
    ("set_piece", "Corner or free kick", "#c084fc"),
    ("throw_in", "Throw-in", "#a78bfa"),
    ("goalkeeper", "From the goalkeeper", "#60a5fa"),
    ("build_up", "Build-up from the back", "#34d399"),
    ("settled", "Settled possession", "#38bdf8"),
)
ORIGIN_LABELS = {key: label for key, label, _ in ORIGINS}
ORIGIN_COLORS = {key: color for key, _, color in ORIGINS}
LENGTH_BUCKETS = (
    ("direct", "Direct (0–1 passes)", 0, 1),
    ("quick", "Quick (2–4 passes)", 2, 4),
    ("patient", "Patient (5–8 passes)", 5, 8),
    ("long", "Long (9+ passes)", 9, 10_000),
)


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


def compact_events(events: list[dict], event_kpis: list[dict]) -> list[dict]:
    """Shrink one match of Impect events to what chains and links need."""
    threat: dict[int, float] = defaultdict(float)
    xg: dict[int, float] = defaultdict(float)
    for row in event_kpis or []:
        kpi_id = _int(row.get("kpiId"))
        event_id = _int(row.get("eventId"))
        value = _num(row.get("value"))
        if event_id <= 0:
            continue
        if kpi_id in THREAT_KPIS and value > 0:
            threat[event_id] += value
        elif kpi_id == SHOT_XG_KPI_ID:
            xg[event_id] += value
    out = []
    for event in events or []:
        event_id = _int(event.get("id"))
        squad_id = _int(event.get("squadId"))
        action_type = str(event.get("actionType") or "").upper()
        if event_id <= 0 or squad_id <= 0 or action_type in NOT_A_STEP:
            continue
        attacking = _int(event.get("currentAttackingSquadId")) or squad_id
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        receiver = ((event.get("pass") or {}).get("receiver") or {}) if isinstance(event.get("pass"), dict) else {}
        start = _xy(event.get("start"))
        end = _xy(event.get("end"))
        game_time = event.get("gameTime") if isinstance(event.get("gameTime"), dict) else {}
        row = {
            "id": event_id,
            "i": _int(event.get("index")),
            "p": _int(event.get("periodId")),
            "s": _int(event.get("sequenceIndex")),
            "t": round(_num(game_time.get("gameTimeInSec")), 1),
            "sq": squad_id,
            "att": attacking,
            "pl": _int(player.get("id")),
            "a": str(event.get("action") or action_type or "OTHER").upper(),
            "at": action_type,
            "ph": _phase_bucket(str(event.get("phase") or "") or None, attacking, squad_id) or "OTHER",
            "res": str(event.get("result") or "").upper(),
            "v": round(threat.get(event_id, 0.0), 4),
        }
        if str(receiver.get("type") or "").upper() in {"TEAM", "TEAMMATE"} and _int(receiver.get("playerId")):
            row["rc"] = _int(receiver.get("playerId"))
        if start:
            row["x1"], row["y1"] = start
        if end:
            row["x2"], row["y2"] = end
        if xg.get(event_id):
            row["xg"] = round(xg[event_id], 4)
        out.append(row)
    out.sort(key=lambda item: (item["p"], item["i"]))
    return out


def possessions(events: list[dict], squad_id: int, match_id: int) -> list[dict]:
    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for event in events:
        if event.get("att") != squad_id:
            continue
        grouped[(event["p"], event["s"])].append(event)
    result = []
    for (period, seq), rows in grouped.items():
        steps = [row for row in rows if row.get("sq") == squad_id]
        if not steps:
            continue
        steps.sort(key=lambda row: row["i"])
        result.append({"matchId": match_id, "period": period, "seq": seq, "steps": steps})
    result.sort(key=lambda row: (row["period"], row["steps"][0]["i"]))
    return result


def match_minute(seconds: float) -> int:
    """Impect restarts the clock at 10000s per period (second half 10000 = 45:00)."""
    seconds = _num(seconds)
    block = int(seconds // 10000)
    offset = HALF_OFFSETS[block] if 0 <= block < len(HALF_OFFSETS) else 0
    return int((seconds - block * 10000 + offset) // 60) + 1


def receiver_of(steps: list[dict], index: int) -> int:
    step = steps[index]
    if step.get("rc"):
        return int(step["rc"])
    if step.get("at") != "PASS" or step.get("res") != "SUCCESS":
        return 0
    for later in steps[index + 1:]:
        if later.get("pl") and later.get("pl") != step.get("pl"):
            return int(later["pl"])
        if later.get("pl") == step.get("pl"):
            return 0
    return 0


def _third(x: float | None) -> str:
    if x is None:
        return "mid"
    if x >= 17.5:
        return "high"
    if x <= -17.5:
        return "low"
    return "mid"


def origin_of(steps: list[dict]) -> str:
    first = steps[0]
    action_type = first.get("at") or ""
    if action_type == "THROW_IN" or first.get("a") == "THROW_IN":
        return "throw_in"
    if action_type in SET_PIECE_TYPES or first.get("a") in SET_PIECE_TYPES:
        return "set_piece"
    if action_type in GK_TYPES:
        return "goalkeeper"
    if action_type in REGAIN_TYPES:
        return f"regain_{_third(first.get('x1'))}"
    if _third(first.get("x1")) == "low":
        return "build_up"
    return "settled"


def _label(action: str, labeler) -> str:
    return labeler(action) if labeler else action.replace("_", " ").title()


def chain_record(possession: dict, labeler=None, familier=None) -> dict:
    steps = possession["steps"]
    threat = sum(_num(step.get("v")) for step in steps)
    shots = [step for step in steps if step.get("at") == "SHOT"]
    goal = any(step.get("res") == "SUCCESS" for step in shots)
    xg = sum(_num(step.get("xg")) for step in shots)
    passes = sum(1 for step in steps if step.get("at") == "PASS")
    threat_steps = [step for step in steps if _num(step.get("v")) >= THREAT_STEP_MIN]
    end_at = len(steps)
    if shots:
        last_shot = steps.index(shots[-1])
        end_at = last_shot + 1
        threat_steps = [step for step in steps[:end_at] if _num(step.get("v")) >= THREAT_STEP_MIN or step is shots[-1]]
    pattern_steps = threat_steps[-PATTERN_LENGTH:]
    pattern = []
    for step in pattern_steps:
        label = _label(step["a"], labeler)
        if pattern and pattern[-1]["label"] == label:
            pattern[-1]["times"] += 1
            continue
        pattern.append({"action": step["a"], "label": label, "family": familier(step["a"]) if familier else "other", "times": 1})
    outcome = "goal" if goal else ("shot" if shots else ("threat" if threat >= THREATENING_CHAIN else "none"))
    return {
        "id": f"{possession['matchId']}-{possession['period']}-{possession['seq']}",
        "matchId": possession["matchId"],
        "minute": match_minute(steps[0].get("t")),
        "threat": round(threat, 4),
        "xg": round(xg, 3),
        "shots": len(shots),
        "goal": goal,
        "outcome": outcome,
        "passes": passes,
        "origin": origin_of(steps),
        "pattern": pattern,
        "patternKey": " → ".join(
            f"{item['label']}{' ×' + str(item['times']) if item['times'] > 1 else ''}" for item in pattern
        ),
        "steps": steps,
    }


def _step_view(step: dict, names: dict, labeler, familier, colors) -> dict:
    family = familier(step["a"]) if familier else "other"
    view = {
        "player": names.get(step.get("pl")) or (f"Player {step.get('pl')}" if step.get("pl") else ""),
        "playerId": step.get("pl"),
        "action": step["a"],
        "label": _label(step["a"], labeler),
        "family": family,
        "color": (colors or {}).get(family, "#94a3b8"),
        "pxt": round(_num(step.get("v")), 4),
        "phase": PHASE_LABELS.get(step.get("ph"), step.get("ph")),
    }
    for key in ("x1", "y1", "x2", "y2", "xg"):
        if key in step:
            view[key] = step[key]
    if step.get("at") == "SHOT":
        view["shot"] = True
        view["goal"] = step.get("res") == "SUCCESS"
        if "x2" not in view and "x1" in view:
            view["x2"], view["y2"] = 52.5, round(_num(view.get("y1")) * 0.3, 1)
    return view


def _per(total: float, games: int) -> float:
    return round(total / games, 3) if games else 0.0


def analyse_chains(chains: list[dict], games: int, names: dict, fixtures: dict, *, labeler=None, familier=None, colors=None) -> dict:
    total = sum(chain["threat"] for chain in chains) or 0.0
    threatening = [chain for chain in chains if chain["threat"] >= THREATENING_CHAIN or chain["shots"]]
    patterns: dict[str, dict] = {}
    for chain in threatening:
        if not chain["pattern"]:
            continue
        row = patterns.setdefault(chain["patternKey"], {
            "key": chain["patternKey"], "steps": chain["pattern"], "count": 0, "threat": 0.0,
            "shots": 0, "xg": 0.0, "goals": 0, "exampleId": chain["id"], "best": 0.0,
        })
        row["count"] += 1
        row["threat"] += chain["threat"]
        row["shots"] += 1 if chain["shots"] else 0
        row["xg"] += chain["xg"]
        row["goals"] += 1 if chain["goal"] else 0
        if chain["threat"] > row["best"]:
            row["best"] = chain["threat"]
            row["exampleId"] = chain["id"]
    pattern_rows = sorted(patterns.values(), key=lambda row: row["threat"], reverse=True)
    for row in pattern_rows:
        for step in row["steps"]:
            step["color"] = (colors or {}).get(step["family"], "#94a3b8")
        row["threat"] = round(row["threat"], 3)
        row["perGame"] = _per(row["threat"], games)
        row["perChain"] = round(row["threat"] / row["count"], 3) if row["count"] else 0
        row["share"] = round(100 * row["threat"] / total, 1) if total else 0
        row["xg"] = round(row["xg"], 2)
        row["shotRate"] = round(100 * row["shots"] / row["count"], 0) if row["count"] else 0
        row.pop("best", None)

    origins = {key: {"id": key, "label": label, "color": color, "count": 0, "threat": 0.0, "shots": 0, "goals": 0, "xg": 0.0} for key, label, color in ORIGINS}
    for chain in chains:
        row = origins[chain["origin"]]
        row["count"] += 1
        row["threat"] += chain["threat"]
        row["shots"] += 1 if chain["shots"] else 0
        row["goals"] += 1 if chain["goal"] else 0
        row["xg"] += chain["xg"]
    origin_rows = []
    for row in origins.values():
        if not row["count"]:
            continue
        row["share"] = round(100 * row["threat"] / total, 1) if total else 0
        row["perChain"] = round(row["threat"] / row["count"], 3)
        row["perGame"] = _per(row["threat"], games)
        row["shotRate"] = round(100 * row["shots"] / row["count"], 1)
        row["threat"] = round(row["threat"], 3)
        row["xg"] = round(row["xg"], 2)
        origin_rows.append(row)
    origin_rows.sort(key=lambda row: row["threat"], reverse=True)

    lengths = []
    for key, label, low, high in LENGTH_BUCKETS:
        bucket = [chain for chain in chains if low <= chain["passes"] <= high]
        if not bucket:
            continue
        threat = sum(chain["threat"] for chain in bucket)
        shots = sum(1 for chain in bucket if chain["shots"])
        lengths.append({
            "id": key, "label": label, "count": len(bucket),
            "threat": round(threat, 3), "perChain": round(threat / len(bucket), 3),
            "share": round(100 * threat / total, 1) if total else 0,
            "shotRate": round(100 * shots / len(bucket), 1),
            "goals": sum(1 for chain in bucket if chain["goal"]),
        })

    top = sorted(chains, key=lambda chain: (chain["goal"], chain["threat"]), reverse=True)
    top = sorted(top[: TOP_CHAINS * 2], key=lambda chain: chain["threat"], reverse=True)[:TOP_CHAINS]
    top_rows = []
    for chain in top:
        fixture = fixtures.get(chain["matchId"]) or {}
        steps = [_step_view(step, names, labeler, familier, colors) for step in chain["steps"]]
        involved = []
        for step in steps:
            if step["player"] and step["player"] not in involved:
                involved.append(step["player"])
        top_rows.append({
            "id": chain["id"], "matchId": chain["matchId"], "opponent": fixture.get("opponent") or "",
            "home": fixture.get("home"), "date": fixture.get("date"), "minute": chain["minute"],
            "threat": chain["threat"], "xg": chain["xg"], "goal": chain["goal"], "outcome": chain["outcome"],
            "origin": ORIGIN_LABELS.get(chain["origin"], chain["origin"]), "passes": chain["passes"],
            "patternKey": chain["patternKey"], "players": involved, "steps": steps,
        })

    top_share = 0.0
    if chains and total:
        ranked = sorted((chain["threat"] for chain in chains), reverse=True)
        cut = max(1, len(ranked) // 10)
        top_share = round(100 * sum(ranked[:cut]) / total, 1)
    return {
        "summary": {
            "possessions": len(chains),
            "perGame": _per(len(chains), games),
            "threatening": len(threatening),
            "threateningPerGame": _per(len(threatening), games),
            "shotEnding": sum(1 for chain in chains if chain["shots"]),
            "goals": sum(1 for chain in chains if chain["goal"]),
            "topTenShare": top_share,
            "avgPassesThreatening": round(sum(chain["passes"] for chain in threatening) / len(threatening), 1) if threatening else 0,
            "threatPerPossession": round(total / len(chains), 4) if chains else 0,
        },
        "patterns": pattern_rows[:12],
        "origins": origin_rows,
        "lengths": lengths,
        "top": top_rows,
    }


def analyse_links(possession_list: list[dict], games: int, names: dict, *, labeler=None) -> dict:
    pairs: dict[tuple[int, int], dict] = {}
    trios: dict[tuple[int, int, int], dict] = {}
    touches: dict[int, dict] = {}
    received: dict[int, float] = defaultdict(float)
    for possession in possession_list:
        steps = possession["steps"]
        for index, step in enumerate(steps):
            player = step.get("pl")
            if player:
                node = touches.setdefault(player, {"id": player, "x": 0.0, "y": 0.0, "n": 0, "threat": 0.0, "count": 0})
                node["count"] += 1
                node["threat"] += _num(step.get("v"))
                if "x1" in step:
                    node["x"] += _num(step["x1"])
                    node["y"] += _num(step["y1"])
                    node["n"] += 1
            receiver = receiver_of(steps, index)
            if not player or not receiver or receiver == player or step.get("at") != "PASS":
                continue
            follow = 0.0
            follow_steps = []
            for later in steps[index + 1:]:
                if later.get("pl") != receiver:
                    break
                follow += _num(later.get("v"))
                follow_steps.append(later)
            pass_threat = _num(step.get("v"))
            received[receiver] += pass_threat
            row = pairs.setdefault((player, receiver), {
                "from": player, "to": receiver, "count": 0, "passThreat": 0.0, "followThreat": 0.0,
                "actions": defaultdict(float), "shots": 0, "goals": 0, "lines": [],
            })
            row["count"] += 1
            row["passThreat"] += pass_threat
            row["followThreat"] += follow
            row["actions"][step["a"]] += pass_threat
            follow_shots = [later for later in follow_steps if later.get("at") == "SHOT"]
            if follow_shots:
                row["shots"] += 1
                row["goals"] += 1 if any(later.get("res") == "SUCCESS" for later in follow_shots) else 0
            if "x1" in step and "x2" in step:
                row["lines"].append({
                    "x1": round(_num(step["x1"]), 1), "y1": round(_num(step["y1"]), 1),
                    "x2": round(_num(step["x2"]), 1), "y2": round(_num(step["y2"]), 1),
                    "v": round(pass_threat + follow, 3), "shot": bool(follow_shots),
                })
            next_index = index + 1 + len(follow_steps)
            last_index = index + len(follow_steps)
            third = receiver_of(steps, last_index) if follow_steps and follow_steps[-1].get("at") == "PASS" else 0
            if third:
                if third not in {player, receiver}:
                    tail = 0.0
                    for later in steps[next_index:]:
                        if later.get("pl") != third:
                            break
                        tail += _num(later.get("v"))
                    trio = trios.setdefault((player, receiver, third), {"ids": [player, receiver, third], "count": 0, "threat": 0.0})
                    trio["count"] += 1
                    trio["threat"] += pass_threat + follow + tail

    def _name(player_id: int) -> str:
        return names.get(player_id) or f"Player {player_id}"

    pair_rows = []
    for row in pairs.values():
        total = row["passThreat"] + row["followThreat"]
        top_action = max(row["actions"].items(), key=lambda item: item[1])[0] if row["actions"] else ""
        pair_rows.append({
            "from": row["from"], "to": row["to"], "fromName": _name(row["from"]), "toName": _name(row["to"]),
            "count": row["count"], "passThreat": round(row["passThreat"], 3), "followThreat": round(row["followThreat"], 3),
            "total": round(total, 3), "perGame": _per(total, games),
            "topAction": _label(top_action, labeler) if top_action else "",
            "shots": row["shots"], "goals": row["goals"],
            "lines": sorted(row["lines"], key=lambda line: line["v"], reverse=True)[:PAIR_LINES],
        })
    pair_rows.sort(key=lambda row: row["total"], reverse=True)

    nodes = []
    involvement: dict[int, float] = defaultdict(float)
    for row in pairs.values():
        value = row["passThreat"] + row["followThreat"]
        involvement[row["from"]] += value
        involvement[row["to"]] += value
    busiest = sorted(
        touches.values(),
        key=lambda item: (involvement.get(item["id"], 0.0) + item["threat"], item["count"]),
        reverse=True,
    )[:NETWORK_MAX_NODES]
    for node in busiest:
        if node["count"] < NETWORK_MIN_TOUCHES or not node["n"]:
            continue
        nodes.append({
            "id": node["id"], "name": _name(node["id"]), "x": round(node["x"] / node["n"], 1), "y": round(node["y"] / node["n"], 1),
            "threat": round(node["threat"], 3), "touches": node["count"], "received": round(received.get(node["id"], 0.0), 3),
        })
    node_ids = {node["id"] for node in nodes}
    edges = [
        {key: value for key, value in row.items() if key != "lines"}
        for row in pair_rows if row["from"] in node_ids and row["to"] in node_ids and row["count"] >= 2
    ][:NETWORK_EDGES]
    matrix = [
        {"from": row["from"], "to": row["to"], "total": row["total"], "count": row["count"], "shots": row["shots"]}
        for row in pair_rows if row["from"] in node_ids and row["to"] in node_ids
    ]

    trio_rows = []
    for row in sorted(trios.values(), key=lambda item: item["threat"], reverse=True)[:8]:
        trio_rows.append({
            "names": [_name(player_id) for player_id in row["ids"]], "ids": row["ids"],
            "count": row["count"], "threat": round(row["threat"], 3), "perGame": _per(row["threat"], games),
        })
    return {
        "pairs": pair_rows[:TOP_PAIRS],
        "network": {"nodes": nodes, "edges": edges, "matrix": matrix},
        "trios": trio_rows,
        "received": {player_id: round(value, 3) for player_id, value in received.items()},
    }


def player_profiles(base_players: list[dict], links: dict, chains: list[dict], names: dict) -> list[dict]:
    involvement: dict[int, dict] = defaultdict(lambda: {"chains": 0, "shotChains": 0, "goalChains": 0})
    for chain in chains:
        if chain["threat"] < THREATENING_CHAIN and not chain["shots"]:
            continue
        seen = {step.get("pl") for step in chain["steps"] if step.get("pl")}
        for player_id in seen:
            row = involvement[player_id]
            row["chains"] += 1
            row["shotChains"] += 1 if chain["shots"] else 0
            row["goalChains"] += 1 if chain["goal"] else 0
    partners: dict[int, list] = defaultdict(list)
    for pair in links.get("pairs") or []:
        partners[pair["from"]].append({"name": pair["toName"], "total": pair["total"]})
    received = links.get("received") or {}
    rows = []
    for row in base_players:
        player_id = int(row.get("id") or 0)
        item = dict(row)
        item["name"] = names.get(player_id) or item.get("name")
        item["received"] = round(_num(received.get(player_id)), 3)
        item.update(involvement.get(player_id, {"chains": 0, "shotChains": 0, "goalChains": 0}))
        item["partners"] = sorted(partners.get(player_id, []), key=lambda p: p["total"], reverse=True)[:2]
        rows.append(item)
    return rows


def build_insights(report: dict) -> list[dict]:
    detail = report.get("detail") or {}
    chains = report.get("chains") or {}
    links = report.get("links") or {}
    out = []
    ranked = [row for row in detail.get("actions") or [] if row.get("rank") and row.get("family") not in {"other", "regain"}]
    weapons = [row for row in ranked if row.get("share", 0) >= 4]
    if weapons:
        best = min(weapons, key=lambda row: (row["rank"], -row.get("perGame", 0)))
        out.append({"tone": "good", "title": f"{best['label']} is a weapon",
                    "text": f"{best['label']}s rank {best['rank']} of {best.get('of') or 24} in League Two for threat per game ({best['perGame']:.2f})."})
        big = [row for row in ranked if row.get("share", 0) >= 5]
        if big:
            worst = max(big, key=lambda row: row["rank"])
            out.append({"tone": "bad", "title": f"{worst['label']}s are under-delivering",
                        "text": f"{worst['share']:.0f}% of our threat, but only {worst['rank']} of {worst.get('of') or 24} in the league."})
    patterns = chains.get("patterns") or []
    if patterns:
        top = patterns[0]
        out.append({"tone": "good", "title": "Our most dangerous chain",
                    "text": f"{top['key']} — {top['count']} times, {top['share']:.0f}% of all possession threat, {top['shots']} ended in a shot."})
    origins = chains.get("origins") or []
    if origins:
        best = max(origins, key=lambda row: row.get("perChain", 0))
        out.append({"tone": "info", "title": f"Best start: {best['label'].lower()}",
                    "text": f"Each one is worth {best['perChain']:.3f} threat on average, and {best['shotRate']:.0f}% end in a shot."})
    pairs = links.get("pairs") or []
    if pairs:
        top = pairs[0]
        out.append({"tone": "good", "title": "Strongest link",
                    "text": f"{top['fromName']} → {top['toName']}: {top['count']} passes, {top['total']:.2f} threat including what {top['toName']} did next."})
    summary = chains.get("summary") or {}
    if summary.get("topTenShare"):
        out.append({"tone": "info", "title": "Where the threat lives",
                    "text": f"Our best 10% of possessions create {summary['topTenShare']:.0f}% of all our threat."})
    return out[:6]
