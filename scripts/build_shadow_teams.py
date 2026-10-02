#!/usr/bin/env python3
"""Build data/shadow-teams.json — Impect history behind the Shadow Teams strategy tool.

Run from the repo root:

    PYTHONPATH=. .venv/bin/python scripts/build_shadow_teams.py
    PYTHONPATH=. .venv/bin/python scripts/build_shadow_teams.py --refresh-current

Raw Impect responses are cached under data/cache/impect-shadow-teams/raw, so a rerun
only fetches what is missing. Live shares the same Impect account, so calls are
throttled and 429s back off instead of hammering the API.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app.home_dashboard as _home  # noqa: E402

# Importing app.main boots the hub, which warms home caches against Impect. Not here.
_home._schedule_recruitment_refresh = lambda *a, **k: None
_home._schedule_strategy_refresh = lambda *a, **k: None

from fastapi import HTTPException  # noqa: E402

from app import main as impect  # noqa: E402
from app.club_strategy import _is_league_match  # noqa: E402
from app.pre_match import _coords_from_starting_position  # noqa: E402
from app.pv_archetypes import POSITION_PROFILES  # noqa: E402

RAW_DIR = ROOT / "data" / "cache" / "impect-shadow-teams" / "raw"
OUT_PATH = ROOT / "data" / "shadow-teams.json"
THROTTLE_SECONDS = 0.45

SHADOW_CLUBS: dict[str, dict[str, Any]] = {
    "lincoln": {"squad_id": 908, "name": "Lincoln City", "short": "Lincoln"},
    "stockport": {"squad_id": 906, "name": "Stockport County", "short": "Stockport"},
    "bradford": {"squad_id": 909, "name": "Bradford City", "short": "Bradford"},
}
VALE = {"key": "vale", "squad_id": 882, "name": "Port Vale", "short": "Port Vale"}

LEAGUES = ("League One", "League Two")
LEVEL = {"League One": 3, "League Two": 4, "National League": 5, "National League North": 6,
         "National League South": 6, "Premier League 2": 0, "Scottish Premiership": 0}
INDEX_COMPETITIONS = (
    "League One",
    "League Two",
    "National League",
    "National League North",
    "National League South",
    "Premier League 2",
    "Scottish Premiership",
)

POSITION_SHORT = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "CB",
    "LEFT_WINGBACK_DEFENDER": "LWB",
    "RIGHT_WINGBACK_DEFENDER": "RWB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "ST",
}
POSITION_GROUP = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "DEF",
    "LEFT_WINGBACK_DEFENDER": "DEF",
    "RIGHT_WINGBACK_DEFENDER": "DEF",
    "DEFENSE_MIDFIELD": "MID",
    "CENTRAL_MIDFIELD": "MID",
    "ATTACKING_MIDFIELD": "MID",
    "LEFT_WINGER": "ATT",
    "RIGHT_WINGER": "ATT",
    "CENTER_FORWARD": "ATT",
}

# Pass actions: (successful, unsuccessful, neutral) KPI ids.
PASS_ACTIONS = {
    "low": (289, 349, 1716),
    "diagonal": (290, 350, 1717),
    "chipped": (291, 351, 1718),
    "short_aerial": (292, 352, 1719),
    "low_cross": (293, 353, 1720),
    "high_cross": (294, 354, 1721),
}

# kind: kpi (per game) | score | derived. better: "high" | "low" | None (style, no good/bad).
METRICS: list[dict[str, Any]] = [
    {"key": "xg_for", "group": "chances", "label": "xG for", "unit": "/g", "digits": 2, "better": "high",
     "kind": "kpi", "ids": [82], "hi": "creates high-quality chances", "lo": "creates little chance quality"},
    {"key": "xg_against", "group": "chances", "label": "xG against", "unit": "/g", "digits": 2, "better": "low",
     "kind": "kpi", "ids": [1463], "hi": "concedes good chances", "lo": "gives almost nothing away"},
    {"key": "xg_diff", "group": "chances", "label": "xG difference", "unit": "/g", "digits": 2, "better": "high",
     "kind": "derived", "hi": "dominates chance quality", "lo": "is out-created"},
    {"key": "shots", "group": "chances", "label": "Shots", "unit": "/g", "digits": 1, "better": "high",
     "kind": "kpi", "ids": [100], "hi": "shoots a lot", "lo": "shoots rarely"},
    {"key": "xg_per_shot", "group": "chances", "label": "xG per shot", "unit": "", "digits": 3, "better": "high",
     "kind": "derived", "hi": "only shoots from good positions", "lo": "takes low-quality shots"},
    {"key": "finishing", "group": "chances", "label": "Goals minus xG", "unit": "/g", "digits": 2, "better": "high",
     "kind": "derived", "hi": "finishes above expectation", "lo": "finishes below expectation"},
    {"key": "keeping", "group": "chances", "label": "Goals prevented (post-shot xG − conceded)", "unit": "/g",
     "digits": 2, "better": "high", "kind": "derived", "hi": "keeper and blockers save goals", "lo": "concedes more than shots deserve"},
    {"key": "possession", "group": "possession", "label": "Possession", "unit": "%", "digits": 1, "better": None,
     "kind": "score", "ids": [23], "pct": True, "hi": "keeps the ball", "lo": "happy without the ball"},
    {"key": "pass_acc", "group": "possession", "label": "Pass success", "unit": "%", "digits": 1, "better": None,
     "kind": "score", "ids": [26], "pct": True, "hi": "secure in possession", "lo": "accepts losing the ball for territory"},
    {"key": "passes", "group": "possession", "label": "Passes", "unit": "/g", "digits": 0, "better": None,
     "kind": "derived", "hi": "high pass volume", "lo": "low pass volume"},
    {"key": "field_tilt", "group": "possession", "label": "Field tilt", "unit": "%", "digits": 1, "better": "high",
     "kind": "score", "ids": [111], "pct": True, "hi": "plays the game in the opposition half", "lo": "pinned back"},
    {"key": "progression", "group": "possession", "label": "Opponents bypassed", "unit": "/g", "digits": 0, "better": "high",
     "kind": "kpi", "ids": [0], "hi": "breaks lines on the ball", "lo": "rarely breaks lines"},
    {"key": "defenders_bypassed", "group": "possession", "label": "Defenders bypassed", "unit": "/g", "digits": 1,
     "better": "high", "kind": "kpi", "ids": [2], "hi": "gets in behind defenders", "lo": "rarely gets behind"},
    {"key": "pxt_attack", "group": "possession", "label": "Attacking threat (PXT)", "unit": "/g", "digits": 2,
     "better": "high", "kind": "kpi", "ids": [1633], "hi": "builds real threat", "lo": "low threat build-up"},
    {"key": "long_share", "group": "direct", "label": "Long & lofted pass share", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "direct — goes long early", "lo": "plays short on the floor"},
    {"key": "crosses", "group": "direct", "label": "Crosses", "unit": "/g", "digits": 1, "better": None,
     "kind": "derived", "hi": "attacks through crosses", "lo": "rarely crosses"},
    {"key": "high_cross_share", "group": "direct", "label": "High-cross share", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "aerial crossing", "lo": "low, driven crosses"},
    {"key": "throw_in_prog", "group": "direct", "label": "Throw-in progression", "unit": "/g", "digits": 2,
     "better": None, "kind": "kpi", "ids": [117], "hi": "uses throw-ins as a weapon", "lo": "throw-ins are a restart, not a weapon"},
    {"key": "ppda", "group": "pressing", "label": "PPDA (lower = more aggressive)", "unit": "", "digits": 1,
     "better": "low", "kind": "score", "ids": [112], "hi": "sits off", "lo": "presses aggressively"},
    {"key": "press_height", "group": "pressing", "label": "Average pressure height", "unit": "m", "digits": 1,
     "better": None, "kind": "score", "ids": [57], "hi": "presses high up the pitch", "lo": "defends deep"},
    {"key": "buildup_press", "group": "pressing", "label": "Pressure on opponent build-up", "unit": "%", "digits": 1,
     "better": None, "kind": "score", "ids": [62], "pct": True, "hi": "goes after the build-up", "lo": "lets them build"},
    {"key": "counterpress", "group": "pressing", "label": "High counter-press", "unit": "%", "digits": 1,
     "better": None, "kind": "score", "ids": [71], "pct": True, "hi": "counter-presses hard", "lo": "drops after losing it"},
    {"key": "presses", "group": "pressing", "label": "Presses", "unit": "/g", "digits": 0, "better": None,
     "kind": "kpi", "ids": [1536], "hi": "high press volume", "lo": "low press volume"},
    {"key": "ball_wins", "group": "pressing", "label": "Ball wins", "unit": "/g", "digits": 1, "better": "high",
     "kind": "kpi", "ids": [27], "hi": "wins the ball back a lot", "lo": "few regains"},
    {"key": "regains_defenders", "group": "pressing", "label": "Regains that take out defenders", "unit": "/g",
     "digits": 1, "better": "high", "kind": "kpi", "ids": [25], "hi": "high-value regains", "lo": "few high-value regains"},
    {"key": "aerial_pct", "group": "physical", "label": "Aerial duel win %", "unit": "%", "digits": 1, "better": "high",
     "kind": "score", "ids": [29], "pct": True, "hi": "dominant in the air", "lo": "loses in the air"},
    {"key": "aerials", "group": "physical", "label": "Aerial duels", "unit": "/g", "digits": 1, "better": None,
     "kind": "derived", "hi": "games are played in the air", "lo": "games stay on the floor"},
    {"key": "duel_pct", "group": "physical", "label": "Duel win %", "unit": "%", "digits": 1, "better": "high",
     "kind": "score", "ids": [27], "pct": True, "hi": "wins its battles", "lo": "loses its battles"},
    {"key": "second_ball_pct", "group": "physical", "label": "Second-ball win %", "unit": "%", "digits": 1,
     "better": "high", "kind": "score", "ids": [96], "pct": True, "hi": "owns the second ball", "lo": "loses second balls"},
    {"key": "fouls", "group": "physical", "label": "Fouls", "unit": "/g", "digits": 1, "better": None,
     "kind": "kpi", "ids": [1703], "hi": "fouls a lot", "lo": "rarely fouls"},
    {"key": "ball_in_play", "group": "physical", "label": "Ball-in-play time", "unit": "min", "digits": 1,
     "better": None, "kind": "derived", "hi": "high tempo, ball kept live", "lo": "slow, stop-start games"},
    {"key": "sp_xg", "group": "sources", "label": "Set-piece xG", "unit": "/g", "digits": 2, "better": "high",
     "kind": "kpi", "ids": [1282], "hi": "dangerous from set pieces", "lo": "little set-piece threat"},
    {"key": "sp_xg_share", "group": "sources", "label": "Set-piece share of xG", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "leans on set pieces", "lo": "open-play team"},
    {"key": "transition_xg_share", "group": "sources", "label": "Transition share of xG", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "counter-attacking threat", "lo": "few transition chances"},
    {"key": "second_ball_xg_share", "group": "sources", "label": "Second-ball share of xG", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "scores off loose balls", "lo": "few second-ball chances"},
    {"key": "header_xg_share", "group": "sources", "label": "Header share of xG", "unit": "%", "digits": 1,
     "better": None, "kind": "derived", "hi": "scores with its head", "lo": "few headed chances"},
]
METRIC_GROUPS = [
    {"id": "chances", "label": "Chance quality"},
    {"id": "possession", "label": "In possession"},
    {"id": "direct", "label": "Directness & delivery"},
    {"id": "pressing", "label": "Out of possession"},
    {"id": "physical", "label": "Physical & tempo"},
    {"id": "sources", "label": "Where the chances come from"},
]

GOAL_PHASES = {"possession": 1245, "transition": 1246, "set_piece": 1249, "second_ball": 1250}
GOAL_ACTIONS = {
    "header": 1223, "penalty": 1224, "free_kick": 1225, "corner": 1226,
    "long_range": 1218, "mid_range": 1219, "close_range": 1220, "one_v_one": 1221, "open_goal": 1222,
}
XG_PHASES = {"possession": 1278, "transition": 1279, "set_piece": 1282, "second_ball": 1283}
XG_ACTIONS = {
    "header": 1256, "penalty": 1257, "free_kick": 1258, "corner": 1259,
    "long_range": 1251, "mid_range": 1252, "close_range": 1253, "one_v_one": 1254, "open_goal": 1255,
}
ASSIST_PHASES = {"possession": 1393, "transition": 1394, "set_piece": 1397, "second_ball": 1398}
GOAL_LANES = {"left_wing": 1244, "left_half": 1243, "center": 1242, "right_half": 1241, "right_wing": 1240}
GOAL_ZONES = {"box": 1239, "final_third": 1238}
GOAL_KPI_IDS = frozenset(
    {28, 77, *GOAL_PHASES.values(), *GOAL_ACTIONS.values(), *ASSIST_PHASES.values(), *GOAL_LANES.values(), *GOAL_ZONES.values()}
)
# Pitch row (y %, attacking upward) per position; the shared pre-match helper puts DM and AM on one row.
POSITION_ROW = {
    "GOALKEEPER": 92, "CENTRAL_DEFENDER": 76, "LEFT_WINGBACK_DEFENDER": 66, "RIGHT_WINGBACK_DEFENDER": 66,
    "DEFENSE_MIDFIELD": 58, "CENTRAL_MIDFIELD": 48, "ATTACKING_MIDFIELD": 36,
    "LEFT_WINGER": 26, "RIGHT_WINGER": 26, "CENTER_FORWARD": 13,
}

_calls = 0
_fetched = 0


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _unwrap(raw: Any) -> Any:
    if isinstance(raw, dict) and "data" in raw and len(raw) <= 4:
        return raw["data"]
    return raw


def api(path: str, *, refresh: bool = False) -> Any:
    """GET an Impect v5 customer path with a permanent disk cache."""
    global _calls, _fetched
    _calls += 1
    key = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
    cache = RAW_DIR / f"{key}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    data: Any = None
    for attempt in range(7):
        try:
            data = _unwrap(impect._impect_get(f"/v5/{impect._api_prefix()}{path}")["data"])
            break
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                data = None
                break
            if exc.status_code in (401, 429, 500, 502, 503, 504) and attempt < 6:
                wait = 20 * (attempt + 1)
                log(f"  {exc.status_code} on {path} — waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    _fetched += 1
    time.sleep(THROTTLE_SECONDS)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def rows_of(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        for key in ("data", "items", "results"):
            if isinstance(raw.get(key), list):
                return [r for r in raw[key] if isinstance(r, dict)]
    return []


def season_start(season: str) -> int:
    token = str(season).split("/")[0].strip()
    year = int(token) if token.isdigit() else 0
    return year + 2000 if year < 100 else year


def prev_season(season: str) -> str:
    y = season_start(season) - 2000
    return f"{y - 1:02d}/{y:02d}"


def next_season(season: str) -> str:
    y = season_start(season) - 2000
    return f"{y + 1:02d}/{y + 2:02d}"


def season_long(season: str) -> str:
    y = season_start(season)
    return f"{y}/{str(y + 1)[-2:]}"


def age_on(birthdate: str | None, ref: date) -> float | None:
    if not birthdate:
        return None
    try:
        born = datetime.strptime(str(birthdate)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return round((ref - born).days / 365.25, 1)


def rnd(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


# ---------------------------------------------------------------- iterations


def load_iterations() -> list[dict[str, Any]]:
    out = []
    for row in rows_of(api("/iterations", refresh=True)):
        comp = row.get("competition")
        name = str(comp.get("name") if isinstance(comp, dict) else comp or "").strip()
        out.append({"id": int(row["id"]), "competition": name, "season": str(row.get("season") or "").strip()})
    return out


def is_current(season: str) -> bool:
    today = date.today()
    start = season_start(season)
    return start == (today.year if today.month >= 7 else today.year - 1)


# ---------------------------------------------------------------- league layer


def squads_of(iteration_id: int, refresh: bool) -> dict[int, dict[str, Any]]:
    return {
        int(r["id"]): {"name": str(r.get("name") or ""), "badge": r.get("imageUrl")}
        for r in rows_of(api(f"/iterations/{iteration_id}/squads", refresh=refresh))
        if r.get("id") is not None
    }


def squad_kpis(iteration_id: int, refresh: bool) -> dict[int, dict[int, float]]:
    table: dict[int, dict[int, float]] = {}
    for row in rows_of(api(f"/iterations/{iteration_id}/squad-kpis", refresh=refresh)):
        if row.get("squadId") is None:
            continue
        stats = table.setdefault(int(row["squadId"]), {})
        for item in row.get("kpis") or []:
            kid = item.get("kpiId", item.get("id"))
            if kid is not None and item.get("value") is not None:
                stats[int(kid)] = float(item["value"])
    return table


def squad_scores(iteration_id: int, refresh: bool) -> dict[int, dict[int, float]]:
    table: dict[int, dict[int, float]] = {}
    for row in rows_of(api(f"/iterations/{iteration_id}/squad-scores", refresh=refresh)):
        if row.get("squadId") is None:
            continue
        stats = table.setdefault(int(row["squadId"]), {})
        for item in row.get("squadScores") or []:
            if item.get("squadScoreId") is not None and item.get("value") is not None:
                stats[int(item["squadScoreId"])] = float(item["value"])
    return table


def coaches_of(iteration_id: int, refresh: bool) -> dict[int, str]:
    return {
        int(r["id"]): str(r.get("name") or "")
        for r in rows_of(api(f"/iterations/{iteration_id}/coaches", refresh=refresh))
        if r.get("id") is not None
    }


def completed_league_matches(iteration_id: int, competition: str, refresh: bool) -> list[dict[str, Any]]:
    out = []
    for m in rows_of(api(f"/iterations/{iteration_id}/matches", refresh=refresh)):
        if not _is_league_match(m, competition):
            continue
        goals = m.get("goals") or {}
        home_ft = (goals.get("home") or {}).get("fullTime")
        away_ft = (goals.get("away") or {}).get("fullTime")
        if home_ft is None or away_ft is None:
            continue
        out.append(m)
    out.sort(key=lambda m: str(m.get("scheduledDate") or ""))
    return out


def standings(matches: list[dict[str, Any]], squads: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    table: dict[int, dict[str, Any]] = {}

    def row(sid: int) -> dict[str, Any]:
        return table.setdefault(sid, {"squad_id": sid, "club": squads.get(sid, {}).get("name", str(sid)),
                                      "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "points": 0})

    for m in matches:
        h, a = int(m["homeSquadId"]), int(m["awaySquadId"])
        hg = int(m["goals"]["home"]["fullTime"])
        ag = int(m["goals"]["away"]["fullTime"])
        for sid, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = row(sid)
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["won"] += 1
                r["points"] += 3
            elif gf == ga:
                r["drawn"] += 1
                r["points"] += 1
            else:
                r["lost"] += 1
    rows = sorted(table.values(), key=lambda r: (-r["points"], -(r["gf"] - r["ga"]), -r["gf"], r["club"]))
    for i, r in enumerate(rows, 1):
        r["position"] = i
        r["gd"] = r["gf"] - r["ga"]
        r["ppg"] = round(r["points"] / r["played"], 2) if r["played"] else 0.0
    return rows


def pass_totals(stats: dict[int, float]) -> dict[str, float]:
    return {name: sum(stats.get(i, 0.0) for i in ids) for name, ids in PASS_ACTIONS.items()}


def score_value(scores: dict[int, float], sid: int, pct: bool) -> float | None:
    if sid not in scores:
        return None
    value = scores[sid]
    if pct and value <= 1.0:
        value *= 100.0
    return value


def metric_values(stats: dict[int, float], scores: dict[int, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    passes = pass_totals(stats)
    all_passes = sum(passes.values())
    crosses = passes["low_cross"] + passes["high_cross"]
    xg = stats.get(82)
    for spec in METRICS:
        key = spec["key"]
        if spec["kind"] == "kpi":
            out[key] = stats.get(spec["ids"][0])
        elif spec["kind"] == "score":
            out[key] = score_value(scores, spec["ids"][0], bool(spec.get("pct")))
    out["xg_diff"] = (xg - stats[1463]) if xg is not None and 1463 in stats else None
    shots = stats.get(100)
    out["xg_per_shot"] = (xg / shots) if xg is not None and shots else None
    out["finishing"] = (stats[28] - xg) if xg is not None and 28 in stats else None
    out["keeping"] = (stats[1462] - stats[1460]) if 1462 in stats and 1460 in stats else None
    out["passes"] = all_passes or None
    open_play = passes["low"] + passes["diagonal"] + passes["chipped"] + passes["short_aerial"]
    out["long_share"] = 100.0 * (passes["diagonal"] + passes["chipped"]) / open_play if open_play else None
    out["crosses"] = crosses or None
    out["high_cross_share"] = 100.0 * passes["high_cross"] / crosses if crosses else None
    aerials = stats.get(96, 0.0) + stats.get(97, 0.0)
    out["aerials"] = aerials or None
    bip = stats.get(1708)
    if bip is not None:
        out["ball_in_play"] = bip / 60.0 if bip > 200 else bip
    else:
        out["ball_in_play"] = None
    for key, kid in (("sp_xg_share", 1282), ("transition_xg_share", 1279), ("second_ball_xg_share", 1283),
                     ("header_xg_share", 1256)):
        out[key] = 100.0 * stats[kid] / xg if xg and kid in stats else None
    return out


def build_league(it: dict[str, Any], refresh: bool) -> dict[str, Any]:
    iid = it["id"]
    squads = squads_of(iid, refresh)
    matches = completed_league_matches(iid, it["competition"], refresh)
    table = standings(matches, squads)
    kpis = squad_kpis(iid, refresh)
    scores = squad_scores(iid, refresh)
    coaches = coaches_of(iid, refresh)
    values = {sid: metric_values(kpis.get(sid, {}), scores.get(sid, {})) for sid in squads}
    pos_of = {r["squad_id"]: r["position"] for r in table}
    ranks: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    averages: dict[str, dict[str, float | None]] = {}
    n_teams = len(table)
    for spec in METRICS:
        key = spec["key"]
        pool = [(sid, v[key]) for sid, v in values.items() if v.get(key) is not None and sid in pos_of]
        if not pool:
            continue
        ordered = sorted(pool, key=lambda item: item[1], reverse=True)  # rank 1 = highest value
        for idx, (sid, value) in enumerate(ordered, 1):
            pct_high = 100.0 * (len(ordered) - idx) / (len(ordered) - 1) if len(ordered) > 1 else 50.0
            ranks[sid][key] = {"value": rnd(value, spec["digits"] + 1), "rank_high": idx, "pct_high": round(pct_high)}
        vals = [v for _, v in pool]
        top3 = [values[r["squad_id"]][key] for r in table[:3] if values.get(r["squad_id"], {}).get(key) is not None]
        top7 = [values[r["squad_id"]][key] for r in table[:7] if values.get(r["squad_id"], {}).get(key) is not None]
        averages[key] = {
            "league": rnd(statistics.fmean(vals), spec["digits"] + 1),
            "top3": rnd(statistics.fmean(top3), spec["digits"] + 1) if top3 else None,
            "top7": rnd(statistics.fmean(top7), spec["digits"] + 1) if top7 else None,
            "min": rnd(min(vals), spec["digits"] + 1),
            "max": rnd(max(vals), spec["digits"] + 1),
        }
    xppg = {sid: s.get(99) for sid, s in scores.items()}
    return {
        "iteration_id": iid,
        "competition": it["competition"],
        "season": it["season"],
        "label": f"{it['competition']} {season_long(it['season'])}",
        "current": is_current(it["season"]),
        "teams": n_teams,
        "squads": squads,
        "matches": matches,
        "table": table,
        "kpis": kpis,
        "scores": scores,
        "coaches": coaches,
        "ranks": ranks,
        "averages": averages,
        "xppg": xppg,
    }


# ---------------------------------------------------------------- player index (where signings came from)


def squad_player_minutes(iteration_id: int, squad_id: int, refresh: bool) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows_of(api(f"/iterations/{iteration_id}/squads/{squad_id}/player-kpis", refresh=refresh)):
        pid = row.get("playerId")
        if pid is None:
            continue
        acc = out.setdefault(int(pid), {"seconds": 0.0, "positions": Counter(), "kpis": defaultdict(float),
                                        "pos_kpis": defaultdict(Counter)})
        secs = float(row.get("playDuration") or 0.0)
        share = float(row.get("matchShare") or 0.0)
        position = str(row.get("position") or "")
        acc["seconds"] += secs
        acc["positions"][position] += secs
        # Player KPI values are per-match averages for that position row.
        for item in row.get("kpis") or []:
            kid = item.get("kpiId", item.get("id"))
            if kid is not None and item.get("value") is not None:
                total = float(item["value"]) * share
                acc["kpis"][int(kid)] += total
                if int(kid) in GOAL_KPI_IDS:
                    acc["pos_kpis"][position][int(kid)] += total
    return out


def build_player_index(
    iterations: list[dict[str, Any]],
    wanted: dict[str, set[int]],
    known_squads: dict[str, dict[int, int]],
    refresh_current: bool,
) -> dict[str, dict[int, list[dict[str, Any]]]]:
    """season -> player_id -> [{squad, competition, minutes}] for the players we care about.

    Impect has no league-wide player→squad lookup, so: the iteration player list says which
    leagues a player appeared in, then squads in that league are scanned only until every
    wanted player is found. Squads already loaded for the tracked clubs are skipped.
    """
    index: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for season, player_ids in sorted(wanted.items()):
        its = [it for it in iterations if it["competition"] in INDEX_COMPETITIONS and it["season"] == season]
        for it in sorted(its, key=lambda it: LEVEL.get(it["competition"], 9)):
            refresh = refresh_current and is_current(season)
            listed = {int(p["id"]) for p in rows_of(api(f"/iterations/{it['id']}/players", refresh=refresh)) if p.get("id") is not None}
            pending = (player_ids & listed) - {pid for pid, sid in known_squads.get(season, {}).items()}
            if not pending:
                continue
            squads = squads_of(it["id"], refresh)
            log(f"Index {it['competition']} {season} — looking for {len(pending)} players in {len(squads)} squads")
            for sid, meta in squads.items():
                if not pending:
                    break
                found = squad_player_minutes(it["id"], sid, refresh)
                for pid, acc in found.items():
                    minutes = acc["seconds"] / 60.0
                    if pid not in player_ids or minutes <= 0:
                        continue
                    index[season][pid].append({
                        "squad_id": sid,
                        "club": meta["name"],
                        "competition": it["competition"],
                        "minutes": round(minutes),
                    })
                    pending.discard(pid)
    return index


def best_club(entries: list[dict[str, Any]], *, exclude: int | None = None) -> dict[str, Any] | None:
    pool = [e for e in entries if e["squad_id"] != exclude]
    if not pool:
        return None
    return max(pool, key=lambda e: e["minutes"])


# ---------------------------------------------------------------- club season


def club_matches(league: dict[str, Any], squad_id: int) -> list[dict[str, Any]]:
    return [m for m in league["matches"] if squad_id in (int(m["homeSquadId"]), int(m["awaySquadId"]))]


def match_detail(match_id: int) -> dict[str, Any]:
    raw = api(f"/matches/{match_id}")
    return raw if isinstance(raw, dict) else {}


def outcome_label(competition: str, position: int, teams: int, complete: bool) -> str:
    if not complete:
        return f"{_ordinal(position)} — in progress"
    if position == 1:
        return "Champions"
    if competition == "League Two":
        if position <= 3:
            return "Automatic promotion"
        if position <= 7:
            return "Play-offs"
        if position > teams - 2:
            return "Relegated"
    else:
        if position <= 2:
            return "Automatic promotion"
        if position <= 6:
            return "Play-offs"
        if position > teams - 4:
            return "Relegated"
    return _ordinal(position)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_patterns(results: list[dict[str, Any]], table: list[dict[str, Any]]) -> dict[str, Any]:
    teams = len(table)
    half = teams // 2

    def rec(rows: list[dict[str, Any]]) -> dict[str, Any]:
        w = sum(1 for r in rows if r["res"] == "W")
        d = sum(1 for r in rows if r["res"] == "D")
        l_ = sum(1 for r in rows if r["res"] == "L")
        pts = 3 * w + d
        n = len(rows)
        return {"p": n, "w": w, "d": d, "l": l_, "gf": sum(r["gf"] for r in rows), "ga": sum(r["ga"] for r in rows),
                "pts": pts, "ppg": round(pts / n, 2) if n else None}

    home = [r for r in results if r["ha"] == "H"]
    away = [r for r in results if r["ha"] == "A"]
    top_half = [r for r in results if r.get("opp_pos") and r["opp_pos"] <= half]
    bottom_half = [r for r in results if r.get("opp_pos") and r["opp_pos"] > half]
    top7 = [r for r in results if r.get("opp_pos") and r["opp_pos"] <= 7]

    ht = {"leading": [], "level": [], "trailing": []}
    for r in results:
        if r.get("ht_gf") is None:
            continue
        state = "leading" if r["ht_gf"] > r["ht_ga"] else ("trailing" if r["ht_gf"] < r["ht_ga"] else "level")
        ht[state].append(r)
    ht_out = {k: rec(v) for k, v in ht.items()}
    points_from_behind = sum(3 if r["res"] == "W" else 1 if r["res"] == "D" else 0 for r in ht["trailing"])
    dropped_from_ahead = sum(3 - (3 if r["res"] == "W" else 1 if r["res"] == "D" else 0) for r in ht["leading"])

    one_goal = [r for r in results if abs(r["gf"] - r["ga"]) == 1]
    blocks = []
    size = max(1, round(len(results) / 4)) if results else 1
    for i in range(0, len(results), size):
        chunk = results[i:i + size]
        blocks.append({"from": i + 1, "to": i + len(chunk), **rec(chunk)})

    def longest(pred) -> int:
        best = cur = 0
        for r in results:
            cur = cur + 1 if pred(r) else 0
            best = max(best, cur)
        return best

    cumulative = []
    total = 0
    for r in results:
        total += 3 if r["res"] == "W" else 1 if r["res"] == "D" else 0
        cumulative.append(total)

    return {
        "overall": rec(results),
        "home": rec(home),
        "away": rec(away),
        "vs_top_half": rec(top_half),
        "vs_bottom_half": rec(bottom_half),
        "vs_top7": rec(top7),
        "half_time": ht_out,
        "points_from_behind": points_from_behind,
        "points_dropped_from_ahead": dropped_from_ahead,
        "one_goal": {"won": sum(1 for r in one_goal if r["res"] == "W"), "lost": sum(1 for r in one_goal if r["res"] == "L")},
        "clean_sheets": sum(1 for r in results if r["ga"] == 0),
        "failed_to_score": sum(1 for r in results if r["gf"] == 0),
        "scored_2plus": rec([r for r in results if r["gf"] >= 2]),
        "conceded_2plus": rec([r for r in results if r["ga"] >= 2]),
        "blocks": blocks,
        "longest_unbeaten": longest(lambda r: r["res"] != "L"),
        "longest_winning": longest(lambda r: r["res"] == "W"),
        "longest_winless": longest(lambda r: r["res"] != "W"),
        "cumulative": cumulative,
    }


def build_club_season(
    club_key: str,
    squad_id: int,
    league: dict[str, Any],
    players_bio: dict[int, dict[str, Any]],
    refresh: bool,
) -> dict[str, Any] | None:
    table = league["table"]
    row = next((r for r in table if r["squad_id"] == squad_id), None)
    if not row:
        return None
    iid = league["iteration_id"]
    pos_of = {r["squad_id"]: r["position"] for r in table}
    matches = club_matches(league, squad_id)
    coaches = league["coaches"]

    results = []
    formations: Counter[str] = Counter()
    coach_games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    slot_counts: Counter[tuple[str, str]] = Counter()
    slot_players: dict[tuple[str, str], Counter[int]] = defaultdict(Counter)
    starts: Counter[int] = Counter()
    sub_apps: Counter[int] = Counter()
    formation_matches: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in matches:
        home = int(m["homeSquadId"]) == squad_id
        opp = int(m["awaySquadId"] if home else m["homeSquadId"])
        g = m["goals"]
        gf = int(g["home" if home else "away"]["fullTime"])
        ga = int(g["away" if home else "home"]["fullTime"])
        ht_gf = (g["home" if home else "away"] or {}).get("halfTime")
        ht_ga = (g["away" if home else "home"] or {}).get("halfTime")
        detail = match_detail(int(m["id"]))
        side = detail.get("squadHome") if home else detail.get("squadAway")
        side = side if isinstance(side, dict) and int(side.get("id") or -1) == squad_id else None
        coach = coaches.get(int(side.get("coachId") or 0), "") if side else ""
        formation = str(side.get("startingFormation") or "").strip() if side else ""
        res = "W" if gf > ga else ("L" if gf < ga else "D")
        item = {
            "match_id": int(m["id"]),
            "date": str(m.get("scheduledDate") or "")[:10],
            "opp": league["squads"].get(opp, {}).get("name", str(opp)),
            "opp_id": opp,
            "opp_pos": pos_of.get(opp),
            "ha": "H" if home else "A",
            "gf": gf,
            "ga": ga,
            "ht_gf": ht_gf,
            "ht_ga": ht_ga,
            "res": res,
            "coach": coach,
            "formation": formation,
        }
        results.append(item)
        if coach:
            coach_games[coach].append(item)
        if formation:
            formations[formation] += 1
        if side:
            starting = side.get("startingPositions") or []
            for sp in starting:
                pid = int(sp.get("playerId") or 0)
                if not pid:
                    continue
                starts[pid] += 1
            if formation:
                formation_matches[formation].append(side)
            for sub in side.get("substitutions") or []:
                if str(sub.get("substitutionType") or "").upper() == "SUB_ON" and sub.get("playerId"):
                    sub_apps[int(sub["playerId"])] += 1

    main_formation = formations.most_common(1)[0][0] if formations else ""
    for side in formation_matches.get(main_formation, []):
        for sp in side.get("startingPositions") or []:
            pid = int(sp.get("playerId") or 0)
            slot = (str(sp.get("position") or ""), str(sp.get("positionSide") or "CENTRE"))
            if pid:
                slot_counts[slot] += 1
                slot_players[slot][pid] += 1

    managers = []
    for name, games in coach_games.items():
        pts = sum(3 if r["res"] == "W" else 1 if r["res"] == "D" else 0 for r in games)
        managers.append({
            "name": name,
            "games": len(games),
            "points": pts,
            "ppg": round(pts / len(games), 2),
            "from": games[0]["date"],
            "to": games[-1]["date"],
        })
    managers.sort(key=lambda r: r["from"])

    # Players
    usage = squad_player_minutes(iid, squad_id, refresh)
    profile_rows = rows_of(api(
        f"/iterations/{iid}/squads/{squad_id}/positions/{','.join(POSITION_SHORT)}/player-profile-scores",
        refresh=refresh,
    ))
    # Impect scores every player against every profile, so keep only those for the player's main position.
    profiles: dict[int, list[tuple[str, float]]] = {}
    for prow in profile_rows:
        pid = prow.get("playerId")
        if pid is None or int(pid) not in usage:
            continue
        positions = usage[int(pid)]["positions"]
        main_pos = positions.most_common(1)[0][0] if positions else ""
        allowed = set(POSITION_PROFILES.get(main_pos, ()))
        scores = [(str(p.get("profileName") or ""), float(p.get("value") or 0.0)) for p in prow.get("profileScores") or []]
        scores = [(n.replace("PV - ", "").replace("PV #10 - ", "#10 ").strip(), v) for n, v in scores if n in allowed]
        if scores:
            profiles[int(pid)] = sorted(scores, key=lambda s: -s[1])

    season_mid = date(season_start(league["season"]) + 1, 1, 1)
    players = []
    for pid, acc in usage.items():
        minutes = acc["seconds"] / 60.0
        if minutes < 1 and starts.get(pid, 0) == 0 and sub_apps.get(pid, 0) == 0:
            continue
        bio = players_bio.get(pid, {})
        position = acc["positions"].most_common(1)[0][0] if acc["positions"] else ""
        prof = profiles.get(pid) or []
        name = (bio.get("commonname") or " ".join(x for x in (bio.get("firstname"), bio.get("lastname")) if x)
                or f"Player {pid}")
        players.append({
            "id": pid,
            "name": name,
            "position": position,
            "pos": POSITION_SHORT.get(position, position[:3]),
            "group": POSITION_GROUP.get(position, ""),
            "age": age_on(bio.get("birthdate"), season_mid),
            "birthdate": bio.get("birthdate"),
            "height": rnd(bio.get("height"), 2) if bio.get("height") else None,
            "foot": bio.get("leg"),
            "minutes": round(minutes),
            "starts": starts.get(pid, 0),
            "sub_apps": sub_apps.get(pid, 0),
            "goals": round(acc["kpis"].get(28, 0.0)),
            "assists": round(acc["kpis"].get(77, 0.0)),
            "xg": rnd(acc["kpis"].get(82, 0.0), 1),
            "profile": prof[0][0] if prof else None,
            "profile_score": rnd(prof[0][1] * 100, 0) if prof else None,
            "profiles": [{"name": n, "score": rnd(v * 100, 0)} for n, v in prof[:3]],
        })
    players.sort(key=lambda p: -p["minutes"])
    by_id = {p["id"]: p for p in players}

    xi = []
    used: set[int] = set()
    for slot, _count in slot_counts.most_common(11):
        for pid, n in slot_players[slot].most_common():
            if pid in used:
                continue
            used.add(pid)
            x, y = _coords_from_starting_position(slot[0], slot[1])
            y = POSITION_ROW.get(slot[0], y)
            p = by_id.get(pid, {})
            xi.append({"id": pid, "name": p.get("name") or f"Player {pid}", "slot": slot[0], "side": slot[1],
                       "pos": POSITION_SHORT.get(slot[0], slot[0][:3]), "x": x, "y": y, "starts_in_slot": n,
                       "age": p.get("age"), "minutes": p.get("minutes"), "goals": p.get("goals"),
                       "profile": p.get("profile")})
            break

    total_minutes = sum(p["minutes"] for p in players) or 1
    outfield = [p for p in players if p["group"] != "GK"]

    def weighted(key: str, pool: list[dict[str, Any]]) -> float | None:
        num = sum(p[key] * p["minutes"] for p in pool if p.get(key))
        den = sum(p["minutes"] for p in pool if p.get(key))
        return round(num / den, 2) if den else None

    sorted_mins = sorted((p["minutes"] for p in players), reverse=True)
    top11_share = 100.0 * sum(sorted_mins[:11]) / total_minutes
    left_mins = sum(p["minutes"] for p in outfield if str(p.get("foot") or "").upper() == "LEFT")
    out_mins = sum(p["minutes"] for p in outfield) or 1
    u23 = sum(p["minutes"] for p in players if p.get("age") is not None and p["age"] < 23)
    over30 = sum(p["minutes"] for p in players if p.get("age") is not None and p["age"] >= 30)
    goals_sorted = sorted(players, key=lambda p: -p["goals"])
    team_goals = sum(p["goals"] for p in players) or 1

    profile_mix: Counter[str] = Counter()
    for p in players:
        if p.get("profile") and p["minutes"] >= 450:
            profile_mix[p["profile"]] += p["minutes"]

    squad = {
        "players": players,
        "xi": xi,
        "formations": [{"formation": f, "games": n} for f, n in formations.most_common()],
        "main_formation": main_formation,
        "summary": {
            "players_used": len([p for p in players if p["minutes"] > 0]),
            "core_players": len([p for p in players if p["minutes"] >= 2000]),
            "avg_age": weighted("age", players),
            "avg_height": weighted("height", outfield),
            "left_foot_pct": round(100.0 * left_mins / out_mins, 1),
            "top11_share": round(top11_share, 1),
            "u23_share": round(100.0 * u23 / total_minutes, 1),
            "over30_share": round(100.0 * over30 / total_minutes, 1),
            "top_scorer": {"name": goals_sorted[0]["name"], "goals": goals_sorted[0]["goals"]} if goals_sorted else None,
            "top3_goal_share": round(100.0 * sum(p["goals"] for p in goals_sorted[:3]) / team_goals, 1),
            "scorers": len([p for p in players if p["goals"] > 0]),
        },
        "profile_mix": [{"profile": k, "minutes": v} for k, v in profile_mix.most_common(12)],
    }

    stats = league["kpis"].get(squad_id, {})
    played = row["played"]
    goal_phases = {k: round(stats.get(kid, 0.0) * played) for k, kid in GOAL_PHASES.items()}
    goal_actions = {k: round(stats.get(kid, 0.0) * played) for k, kid in GOAL_ACTIONS.items()}
    style = {}
    for spec in METRICS:
        cell = league["ranks"].get(squad_id, {}).get(spec["key"])
        if cell:
            style[spec["key"]] = cell
    goals = build_goals(league, squad_id, matches, usage, players, played, refresh)
    xppg = league["xppg"].get(squad_id)
    complete = played >= 46
    return {
        "club": club_key,
        "iteration_id": iid,
        "competition": league["competition"],
        "season": league["season"],
        "season_long": season_long(league["season"]),
        "label": league["label"],
        "current": league["current"],
        "teams": league["teams"],
        "table": {
            **{k: row[k] for k in ("position", "played", "won", "drawn", "lost", "gf", "ga", "gd", "points", "ppg")},
            "xppg": rnd(xppg, 2),
            "xg_for": rnd(stats.get(82), 2),
            "xg_against": rnd(stats.get(1463), 2),
            "outcome": outcome_label(league["competition"], row["position"], league["teams"], complete),
        },
        "managers": managers,
        "style": style,
        "goal_phases": goal_phases,
        "goal_actions": goal_actions,
        "goals": goals,
        "patterns": build_patterns(results, table),
        "results": results,
        "squad": squad,
    }


# ---------------------------------------------------------------- goals


def _league_breakdown(league: dict[str, Any], squad_id: int, ids: dict[str, int], played: int,
                      xg_ids: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    """Season totals per category with the club's league rank and the league average."""
    kpis = league["kpis"]
    in_table = {r["squad_id"]: r["played"] for r in league["table"]}
    out: dict[str, dict[str, Any]] = {}
    shares: dict[int, float] = {}
    for sid in in_table:
        shares[sid] = sum(kpis.get(sid, {}).get(kid, 0.0) for kid in ids.values()) or 0.0
    for key, kid in ids.items():
        per_game = {sid: kpis.get(sid, {}).get(kid, 0.0) for sid in in_table}
        ordered = sorted(per_game, key=lambda s: -per_game[s])
        mine = per_game.get(squad_id, 0.0)
        league_share = [100.0 * per_game[s] / shares[s] for s in in_table if shares[s]]
        cell = {
            "goals": round(mine * played),
            "per_game": rnd(mine, 3),
            "rank": ordered.index(squad_id) + 1 if squad_id in ordered else None,
            "league_avg": rnd(statistics.fmean(per_game.values()) * played, 1) if per_game else None,
            "share": rnd(100.0 * mine / shares[squad_id], 1) if shares.get(squad_id) else None,
            "league_share": rnd(statistics.fmean(league_share), 1) if league_share else None,
        }
        if xg_ids and key in xg_ids:
            cell["xg"] = rnd(kpis.get(squad_id, {}).get(xg_ids[key], 0.0) * played, 1)
        out[key] = cell
    return out


def _conceded(matches: list[dict[str, Any]], squad_id: int, refresh: bool) -> dict[str, Any]:
    """Opponent goal KPIs from every league match — Impect has no season-level conceded-by-phase."""
    phases: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    zones: Counter[str] = Counter()
    total = own_goals_for = 0.0
    covered = 0
    for m in matches:
        raw = api(f"/matches/{int(m['id'])}/squad-kpis", refresh=refresh)
        if not isinstance(raw, dict):
            continue
        sides = [raw.get("squadHome") or {}, raw.get("squadAway") or {}]
        opp = next((s for s in sides if s.get("id") and int(s["id"]) != squad_id), None)
        if not opp:
            continue
        stats = {int(i.get("kpiId", i.get("id"))): float(i["value"]) for i in opp.get("kpis") or []
                 if i.get("value") is not None and i.get("kpiId", i.get("id")) is not None}
        covered += 1
        total += stats.get(28, 0.0)
        own_goals_for += stats.get(38, 0.0)
        for key, kid in GOAL_PHASES.items():
            phases[key] += stats.get(kid, 0.0)
        for key, kid in GOAL_ACTIONS.items():
            actions[key] += stats.get(kid, 0.0)
        for key, kid in GOAL_ZONES.items():
            zones[key] += stats.get(kid, 0.0)
    return {
        "matches": covered,
        "total": round(total),
        "phases": {k: round(v) for k, v in phases.items()},
        "actions": {k: round(v) for k, v in actions.items()},
        "zones": {**{k: round(v) for k, v in zones.items()}, "outside": max(0, round(total - sum(zones.values())))},
        "opponent_own_goals": round(own_goals_for),
    }


def build_goals(league: dict[str, Any], squad_id: int, matches: list[dict[str, Any]],
                usage: dict[int, dict[str, Any]], players: list[dict[str, Any]], played: int,
                refresh: bool) -> dict[str, Any]:
    stats = league["kpis"].get(squad_id, {})
    total = round(stats.get(28, 0.0) * played)
    lanes = {k: round(stats.get(kid, 0.0) * played) for k, kid in GOAL_LANES.items()}
    zones = {k: round(stats.get(kid, 0.0) * played) for k, kid in GOAL_ZONES.items()}
    zones["outside"] = max(0, total - sum(zones.values()))

    groups: dict[str, dict[str, Any]] = {}
    positions: dict[str, dict[str, Any]] = {}
    for acc in usage.values():
        for position, kp in acc["pos_kpis"].items():
            group = POSITION_GROUP.get(position, "")
            if not group:
                continue
            for bucket, key in ((groups, group), (positions, position)):
                cell = bucket.setdefault(key, {"goals": 0.0, "assists": 0.0, "phases": Counter(), "actions": Counter()})
                cell["goals"] += kp.get(28, 0.0)
                cell["assists"] += kp.get(77, 0.0)
                for pk, kid in GOAL_PHASES.items():
                    cell["phases"][pk] += kp.get(kid, 0.0)
                for ak, kid in GOAL_ACTIONS.items():
                    cell["actions"][ak] += kp.get(kid, 0.0)

    def finish(cell: dict[str, Any]) -> dict[str, Any]:
        return {"goals": round(cell["goals"]), "assists": round(cell["assists"]),
                "phases": {k: round(v) for k, v in cell["phases"].items()},
                "actions": {k: round(v) for k, v in cell["actions"].items() if round(v)}}

    by_id = {p["id"]: p for p in players}
    scorers = []
    for pid, acc in usage.items():
        k = acc["kpis"]
        g = round(k.get(28, 0.0))
        a = round(k.get(77, 0.0))
        if not g and not a:
            continue
        p = by_id.get(pid, {})
        scorers.append({
            "id": pid, "name": p.get("name") or f"Player {pid}", "pos": p.get("pos"), "group": p.get("group"),
            "goals": g, "assists": a, "xg": rnd(k.get(82, 0.0), 1), "minutes": p.get("minutes"),
            "phases": {pk: round(k.get(kid, 0.0)) for pk, kid in GOAL_PHASES.items() if round(k.get(kid, 0.0))},
            "actions": {ak: round(k.get(kid, 0.0)) for ak, kid in GOAL_ACTIONS.items() if round(k.get(kid, 0.0))},
            "assist_phases": {pk: round(k.get(kid, 0.0)) for pk, kid in ASSIST_PHASES.items() if round(k.get(kid, 0.0))},
        })
    scorers.sort(key=lambda s: (-s["goals"], -s["assists"]))

    return {
        "total": total,
        "xg": rnd(stats.get(82, 0.0) * played, 1),
        "phases": _league_breakdown(league, squad_id, GOAL_PHASES, played, XG_PHASES),
        "actions": _league_breakdown(league, squad_id, GOAL_ACTIONS, played, XG_ACTIONS),
        "lanes": lanes,
        "zones": zones,
        "groups": {g: finish(c) for g, c in groups.items()},
        "positions": [{"position": pos, "pos": POSITION_SHORT.get(pos, pos[:3]), "group": POSITION_GROUP.get(pos, ""),
                       **finish(c)} for pos, c in sorted(positions.items(), key=lambda kv: -kv[1]["goals"])],
        "scorers": scorers[:14],
        "against": _conceded(matches, squad_id, refresh),
    }


# ---------------------------------------------------------------- recruitment


def classify_source(prev: dict[str, Any] | None, competition: str) -> str:
    if not prev:
        return "outside"
    comp = prev["competition"]
    if comp == "Premier League 2":
        return "academy"
    if comp == "Scottish Premiership":
        return "scotland"
    here = LEVEL.get(competition, 4)
    there = LEVEL.get(comp, 0)
    if there > here:
        return "step_up"
    if there == here:
        return "same_level"
    return "drop_down"


SOURCE_LABELS = {
    "step_up": "Stepped up from a lower league",
    "same_level": "Same division",
    "drop_down": "Dropped down from a higher division",
    "academy": "Premier League 2 / academy",
    "scotland": "Scottish Premiership",
    "outside": "Outside Impect cover (Championship, abroad, non-league, released)",
}


def build_recruitment(
    seasons: list[dict[str, Any]],
    index: dict[str, dict[int, list[dict[str, Any]]]],
    squad_id: int,
    players_bio_all: dict[int, dict[str, Any]],
) -> None:
    by_season = {s["season"]: s for s in seasons}
    for cs in seasons:
        prev = by_season.get(prev_season(cs["season"]))
        players = cs["squad"]["players"]
        arrivals, departures = [], []
        rec: dict[str, Any] = {"covered": prev is not None}
        prev_season_key = prev_season(cs["season"])
        prior_index = index.get(prev_season_key, {})
        this_index = index.get(cs["season"], {})
        if prev is None:
            rec["note"] = (
                f"The club's {season_long(prev_season_key)} season is outside Impect cover, so this summer's "
                "arrivals cannot be separated from players already at the club."
            )
            cs["recruitment"] = rec
            continue
        prev_players = {p["id"]: p for p in prev["squad"]["players"]}
        prev_total = sum(p.get("minutes", 0) for p in prev_players.values()) or 1
        this_total = sum(p["minutes"] for p in players) or 1
        retained_mins_prev = sum(p.get("minutes", 0) for pid, p in prev_players.items() if any(x["id"] == pid for x in players))
        for p in players:
            if p["id"] in prev_players:
                p["status"] = "retained"
                continue
            prior = best_club(prior_index.get(p["id"], []), exclude=squad_id)
            source = classify_source(prior, cs["competition"])
            p["status"] = "new"
            p["arrived_from"] = prior["club"] if prior else None
            arrivals.append({
                "id": p["id"],
                "name": p["name"],
                "pos": p["pos"],
                "age": p["age"],
                "minutes": p["minutes"],
                "starts": p["starts"],
                "goals": p["goals"],
                "assists": p["assists"],
                "profile": p.get("profile"),
                "profile_score": p.get("profile_score"),
                "from_club": prior["club"] if prior else None,
                "from_competition": prior["competition"] if prior else None,
                "from_minutes": prior["minutes"] if prior else None,
                "source": source,
                "impact": "core" if p["minutes"] >= 2000 else ("rotation" if p["minutes"] >= 900 else "fringe"),
            })
        arrivals.sort(key=lambda a: -a["minutes"])
        this_ids = {p["id"] for p in players}
        for pid, p in prev_players.items():
            if pid in this_ids:
                continue
            nxt = best_club(this_index.get(pid, []), exclude=squad_id)
            bio = players_bio_all.get(pid, {})
            name = p.get("name") or bio.get("commonname") or f"Player {pid}"
            departures.append({
                "id": pid,
                "name": name,
                "pos": p.get("pos"),
                "age": p.get("age"),
                "minutes_before": p.get("minutes", 0),
                "share_before": round(100.0 * p.get("minutes", 0) / prev_total, 1),
                "to_club": nxt["club"] if nxt else None,
                "to_competition": nxt["competition"] if nxt else None,
                "to_minutes": nxt["minutes"] if nxt else None,
            })
        departures.sort(key=lambda d: -d["minutes_before"])
        new_minutes = sum(a["minutes"] for a in arrivals)
        mix: Counter[str] = Counter()
        mix_minutes: Counter[str] = Counter()
        for a in arrivals:
            mix[a["source"]] += 1
            mix_minutes[a["source"]] += a["minutes"]
        ages = [a["age"] for a in arrivals if a.get("age") is not None and a["minutes"] >= 900]
        rec.update({
            "arrivals": arrivals,
            "departures": departures,
            "retained_share_prev": round(100.0 * retained_mins_prev / prev_total, 1),
            "new_minutes_share": round(100.0 * new_minutes / this_total, 1),
            "arrivals_count": len(arrivals),
            "arrivals_core": len([a for a in arrivals if a["impact"] == "core"]),
            "arrivals_rotation": len([a for a in arrivals if a["impact"] == "rotation"]),
            "hit_rate": round(100.0 * len([a for a in arrivals if a["minutes"] >= 900]) / len(arrivals), 0) if arrivals else None,
            "avg_age_used_arrivals": round(statistics.fmean(ages), 1) if ages else None,
            "source_mix": [
                {"source": k, "label": SOURCE_LABELS[k], "count": mix[k], "minutes": mix_minutes[k]}
                for k in SOURCE_LABELS if mix[k]
            ],
        })
        cs["recruitment"] = rec


# ---------------------------------------------------------------- insights


def metric_spec(key: str) -> dict[str, Any]:
    return next(m for m in METRICS if m["key"] == key)


def fmt_value(spec: dict[str, Any], value: float | None) -> str:
    if value is None:
        return "—"
    digits = spec["digits"]
    text = f"{value:.{digits}f}"
    unit = spec.get("unit") or ""
    if unit == "%":
        return f"{text}%"
    if unit == "/g":
        return f"{text} a game"
    if unit == "m":
        return f"{text} m"
    if unit == "min":
        return f"{text} min"
    return text


def season_insights(cs: dict[str, Any], prev: dict[str, Any] | None, name: str) -> list[dict[str, Any]]:
    teams = cs["teams"]
    out: list[dict[str, Any]] = []
    for spec in METRICS:
        cell = cs["style"].get(spec["key"])
        if not cell:
            continue
        rank = cell["rank_high"]
        if rank <= 2 or rank >= teams - 1:
            top = rank <= 2
            phrase = spec["hi"] if top else spec["lo"]
            pos = rank if top else teams - rank + 1
            where = "highest" if top else "lowest"
            if spec["better"] == "high":
                tone = "good" if top else "bad"
            elif spec["better"] == "low":
                tone = "bad" if top else "good"
            else:
                tone = "style"
            order = "" if pos == 1 else f"{_ordinal(pos)} "
            out.append({
                "tone": tone,
                "metric": spec["key"],
                "title": f"{spec['label']}: {order}{where} in the league",
                "text": f"{phrase[:1].upper()}{phrase[1:]}: {fmt_value(spec, cell['value'])} ({_ordinal(rank)} of {teams}).",
                "weight": 3 if spec["group"] == "chances" else 2,
            })
    p = cs["patterns"]
    if p["home"]["p"] and p["away"]["p"]:
        out.append({"tone": "style", "metric": "home_away", "title": "Home and away",
                    "text": f"{p['home']['ppg']} points a game at home, {p['away']['ppg']} away.", "weight": 1})
    trailing = p["half_time"]["trailing"]
    if trailing["p"]:
        out.append({"tone": "good" if p["points_from_behind"] >= trailing["p"] else "style", "metric": "comebacks",
                    "title": "Behind at half-time",
                    "text": f"Took {p['points_from_behind']} points from {trailing['p']} games they trailed at the break.",
                    "weight": 1})
    leading = p["half_time"]["leading"]
    if leading["p"]:
        out.append({"tone": "good" if p["points_dropped_from_ahead"] <= leading["p"] else "bad", "metric": "game_mgmt",
                    "title": "Ahead at half-time",
                    "text": f"Won {leading['w']} of {leading['p']} games they led at the break "
                            f"({p['points_dropped_from_ahead']} points dropped).", "weight": 1})
    if prev:
        jumps = []
        for spec in METRICS:
            a, b = prev["style"].get(spec["key"]), cs["style"].get(spec["key"])
            if not a or not b:
                continue
            jumps.append((b["pct_high"] - a["pct_high"], spec, a, b))
        jumps.sort(key=lambda j: -abs(j[0]))
        for delta, spec, a, b in jumps[:3]:
            if abs(delta) < 35:
                continue
            direction = "up" if delta > 0 else "down"
            out.append({"tone": "change", "metric": spec["key"],
                        "title": f"Changed from {prev['season_long']}: {spec['label']}",
                        "text": f"{fmt_value(spec, a['value'])} → {fmt_value(spec, b['value'])} "
                                f"(league percentile {a['pct_high']} → {b['pct_high']}, {direction}).",
                        "weight": 1})
    out.sort(key=lambda i: -i["weight"])
    return out


STYLE_TAGS = [
    ("long_share", 75, "Direct", "Goes long and early more than most of the league."),
    ("long_share", -25, "Builds short", "Plays on the floor — one of the least direct sides."),
    ("possession", 75, "Ball-dominant", "Top quarter for possession."),
    ("possession", -25, "Comfortable without the ball", "Bottom quarter for possession."),
    ("ppda", -25, "Aggressive press", "Lets opponents make few passes before engaging."),
    ("ppda", 75, "Mid/low block", "Sits off and lets the opposition have it."),
    ("press_height", 75, "Presses high", "Average pressure applied high up the pitch."),
    ("aerials", 75, "Aerial games", "Matches are played in the air."),
    ("aerial_pct", 75, "Wins the air", "Top quarter for aerial duel success."),
    ("second_ball_pct", 75, "Second-ball kings", "Top quarter for winning loose balls."),
    ("crosses", 75, "Cross-heavy", "Attacks through wide delivery."),
    ("sp_xg", 75, "Set-piece threat", "Top quarter for set-piece xG."),
    ("throw_in_prog", 80, "Throw-in weapon", "Gains territory/threat from throw-ins."),
    ("transition_xg_share", 75, "Transition threat", "Unusually high share of xG from transitions."),
    ("xg_against", -15, "Hard to create against", "Among the lowest xG conceded."),
    ("xg_for", 85, "Chance machine", "Among the highest xG created."),
    ("field_tilt", 75, "Territorial", "Plays the game in the opponent's half."),
]


def style_tags(cs: dict[str, Any]) -> list[dict[str, str]]:
    tags = []
    for key, threshold, label, why in STYLE_TAGS:
        cell = cs["style"].get(key)
        if not cell:
            continue
        pct = cell["pct_high"]
        if (threshold > 0 and pct >= threshold) or (threshold < 0 and pct <= -threshold):
            tags.append({"label": label, "why": why, "metric": key})
    return tags


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-current", action="store_true", help="Refetch the in-progress season.")
    args = parser.parse_args()

    started = time.time()
    iterations = load_iterations()
    league_its = sorted(
        [it for it in iterations if it["competition"] in LEAGUES],
        key=lambda it: (season_start(it["season"]), it["competition"]),
    )
    log(f"{len(league_its)} League One / League Two seasons in Impect")

    leagues: dict[int, dict[str, Any]] = {}
    for it in league_its:
        refresh = args.refresh_current and is_current(it["season"])
        log(f"League {it['competition']} {it['season']} ({it['id']})")
        try:
            leagues[it["id"]] = build_league(it, refresh)
        except HTTPException as exc:
            log(f"  skipped: {exc.detail}")

    tracked = {**{k: v["squad_id"] for k, v in SHADOW_CLUBS.items()}, "vale": VALE["squad_id"]}
    club_seasons: dict[str, list[dict[str, Any]]] = {k: [] for k in tracked}
    bios: dict[int, dict[str, Any]] = {}
    for iid, league in sorted(leagues.items(), key=lambda kv: season_start(kv[1]["season"])):
        present = [k for k, sid in tracked.items() if any(r["squad_id"] == sid for r in league["table"])]
        if not present:
            continue
        refresh = args.refresh_current and league["current"]
        players_bio = {int(p["id"]): p for p in rows_of(api(f"/iterations/{iid}/players", refresh=refresh)) if p.get("id") is not None}
        bios.update(players_bio)
        for key in present:
            log(f"Club season {key} {league['label']}")
            cs = build_club_season(key, tracked[key], league, players_bio, refresh)
            if cs:
                club_seasons[key].append(cs)

    # Who we need to trace: arrivals (season before) and departures (season after).
    wanted: dict[str, set[int]] = defaultdict(set)
    known: dict[str, dict[int, int]] = defaultdict(dict)
    seed: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for key, seasons in club_seasons.items():
        seasons.sort(key=lambda s: season_start(s["season"]))
        by_season = {s["season"]: s for s in seasons}
        for cs in seasons:
            for p in cs["squad"]["players"]:
                if p["minutes"] > 0:
                    known[cs["season"]][p["id"]] = tracked[key]
                    seed[cs["season"]][p["id"]].append({
                        "squad_id": tracked[key], "club": SHADOW_CLUBS.get(key, VALE)["name"],
                        "competition": cs["competition"], "minutes": p["minutes"],
                    })
            prev = by_season.get(prev_season(cs["season"]))
            if not prev:
                continue
            now_ids = {p["id"] for p in cs["squad"]["players"]}
            prev_ids = {p["id"] for p in prev["squad"]["players"]}
            wanted[prev["season"]].update(now_ids - prev_ids)
            wanted[cs["season"]].update(prev_ids - now_ids)

    index = build_player_index(iterations, wanted, known, args.refresh_current)
    for season, players in seed.items():
        for pid, entries in players.items():
            index[season][pid].extend(entries)

    for key, seasons in club_seasons.items():
        build_recruitment(seasons, index, tracked[key], bios)
        for i, cs in enumerate(seasons):
            prev = seasons[i - 1] if i else None
            name = SHADOW_CLUBS.get(key, VALE)["short"]
            cs["insights"] = season_insights(cs, prev, name)
            cs["tags"] = style_tags(cs)

    # League context per season for the clubs we track.
    league_payload = {}
    for iid, league in leagues.items():
        league_payload[str(iid)] = {
            "iteration_id": iid,
            "competition": league["competition"],
            "season": league["season"],
            "label": league["label"],
            "teams": league["teams"],
            "current": league["current"],
            "averages": league["averages"],
            "table": [
                {k: r[k] for k in ("position", "club", "squad_id", "played", "points", "gd", "ppg")}
                | {"badge": league["squads"].get(r["squad_id"], {}).get("badge")}
                for r in league["table"]
            ],
            "promotion_line": next((r["points"] for r in league["table"] if r["position"] == (3 if league["competition"] == "League Two" else 2)), None),
            "playoff_line": next((r["points"] for r in league["table"] if r["position"] == (7 if league["competition"] == "League Two" else 6)), None),
        }

    badges = {}
    for league in leagues.values():
        for sid, meta in league["squads"].items():
            if meta.get("badge"):
                badges[str(sid)] = meta["badge"]

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": (
            "Impect League One (20/21 on) and League Two (22/23 on). Squad KPIs are per game; "
            "rates and pressing use Impect squad scores. Where signings came from is traced through "
            "every League One, League Two, National League (North/South), Premier League 2 and "
            "Scottish Premiership squad in Impect the season before."
        ),
        "metric_groups": METRIC_GROUPS,
        "metrics": [{k: v for k, v in m.items() if k not in ("ids", "kind")} for m in METRICS],
        "source_labels": SOURCE_LABELS,
        "clubs": {
            key: {
                "key": key,
                **meta,
                "badge": badges.get(str(meta["squad_id"])),
                "seasons": club_seasons[key],
            }
            for key, meta in SHADOW_CLUBS.items()
        },
        "vale": {**VALE, "badge": badges.get(str(VALE["squad_id"])), "seasons": club_seasons["vale"]},
        "leagues": league_payload,
    }
    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    log(f"Wrote {OUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB) — {_calls} lookups, {_fetched} Impect calls, "
        f"{time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
