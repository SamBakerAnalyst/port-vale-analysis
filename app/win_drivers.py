"""What Wins Games — League Two Impect stats most linked to winning."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.club_strategy import (
    _build_standings,
    _competition_iterations,
    _is_focus_squad,
    _season_label,
    _unwrap_items,
)
from app.paths import STANDALONE_DIR, WIN_DRIVERS_CACHE_DIR
from app.scouting import SCOUTING_DIR

logger = logging.getLogger(__name__)

COMPETITION = "League Two"
TOP_N = 15
MIN_GAMES_HISTORY = 20
MIN_OBSERVATIONS = 16
COLLINEARITY_R = 0.90
HISTORY_TTL_SECONDS = 12 * 3600
TABLE_TTL_SECONDS = 1800
CACHE_VERSION = 7

# Impect squad KPI ids — prefer platform Absolute names (same as Impect Scout),
# not the *_RAW counts (1399 / 1400) which rank differently.
KPI_SHOT_XG = 82
KPI_CONCEDED_SHOT_XG = 1463
KPI_PACKING_XG = 83
KPI_CONCEDED_PACKING_XG = 1464
KPI_POSTSHOT_XG = 1401
KPI_CONCEDED_POSTSHOT_XG = 1462
KPI_BYPASSED_OPPONENTS = 0  # BYPASSED_OPPONENTS (platform Absolute)
KPI_BYPASSED_OPPONENTS_RAW = 1399
KPI_BYPASSED_DEFENDERS = 2  # BYPASSED_DEFENDERS (platform Absolute)
KPI_BYPASSED_DEFENDERS_RAW = 1400
KPI_SUFFERED_BYPASSED_DEFENDERS = 40
KPI_FINAL_THIRD_ENTRIES = 284
KPI_FINAL_THIRD_AGAINST = 149
KPI_OFFENSIVE_INTERVENTIONS = 24
KPI_DEFENSIVE_INTERVENTIONS = 23
KPI_BALL_WINS_DEFENDERS = 25
KPI_PXT_PASS = 1404
KPI_PXT_ATTACK = 1633
KPI_PXT_SHOT = 1408
KPI_PXT_SETPIECE = 1406
KPI_PXT_BALL_WIN = 1409
KPI_PRESSES = 1536
KPI_WON_GROUND = 94
KPI_LOST_GROUND = 95
KPI_WON_AERIAL = 96
KPI_LOST_AERIAL = 97

# Goals and scoreline stats are the result of winning, not a driver.
EXCLUDED_KPI_IDS = frozenset({28})  # goals scored

Candidate = dict[str, Any]

CANDIDATES: tuple[Candidate, ...] = (
    {
        "key": "xg_for",
        "label": "xG for",
        "short": "xG",
        "hint": "Shot expected goals created per game.",
        "kpi_ids": (KPI_SHOT_XG,),
        "fmt": "dec",
        "digits": 2,
        "unit": "xG/g",
    },
    {
        "key": "xg_against",
        "label": "xG against",
        "short": "xGA",
        "hint": "Shot expected goals conceded per game.",
        "kpi_ids": (KPI_CONCEDED_SHOT_XG,),
        "fmt": "dec",
        "digits": 2,
        "unit": "xGA/g",
    },
    {
        "key": "xg_diff",
        "label": "xG difference",
        "short": "xGD",
        "hint": "xG minus xGA per game — chance quality both ways.",
        "derived": "sub",
        "left_ids": (KPI_SHOT_XG,),
        "right_ids": (KPI_CONCEDED_SHOT_XG,),
        "fmt": "signed",
        "digits": 2,
        "unit": "xGD/g",
    },
    {
        "key": "packing_xg",
        "label": "Packing xG",
        "short": "PxG",
        "hint": "xG weighted by packing — chances that broke lines.",
        "kpi_ids": (KPI_PACKING_XG,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PxG/g",
    },
    {
        "key": "conceded_packing_xg",
        "label": "Packing xG against",
        "short": "PxGA",
        "hint": "Packing xG conceded per game.",
        "kpi_ids": (KPI_CONCEDED_PACKING_XG,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PxGA/g",
    },
    {
        "key": "postshot_xg",
        "label": "Post-shot xG",
        "short": "PSxG",
        "hint": "Expected goals after the shot is taken.",
        "kpi_ids": (KPI_POSTSHOT_XG,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PSxG/g",
    },
    {
        "key": "shots",
        "label": "Shots",
        "short": "Shots",
        "hint": "Shots at goal per game.",
        "kpi_names": ("SHOT_AT_GOAL_NUMBER",),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "sot",
        "label": "Shots on target",
        "short": "SoT",
        "hint": "Shots on target per game.",
        "kpi_names": ("SHOT_AT_GOAL_NUMBER_ON_TARGET",),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "sot_pct",
        "label": "On-target %",
        "short": "SoT%",
        "hint": "Share of shots that hit the target.",
        "derived": "rate",
        "num_names": ("SHOT_AT_GOAL_NUMBER_ON_TARGET",),
        "den_names": ("SHOT_AT_GOAL_NUMBER",),
        "fmt": "pct",
        "digits": 1,
        "unit": "%",
        "scale": 100.0,
    },
    {
        "key": "defenders_bypassed",
        "label": "Defenders bypassed",
        "short": "Def byp.",
        "hint": "Impect Absolute — opposition defenders packed / broken per game.",
        "kpi_ids": (KPI_BYPASSED_DEFENDERS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "ball_progression",
        "label": "Ball progression",
        "short": "Prog.",
        "hint": "Impect Absolute — opponents bypassed on the ball per game.",
        "kpi_ids": (KPI_BYPASSED_OPPONENTS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "defenders_bypassed_against",
        "label": "Defenders bypassed against",
        "short": "Def byp. ag",
        "hint": "How often the defensive line is broken. Lower is better.",
        "kpi_ids": (KPI_SUFFERED_BYPASSED_DEFENDERS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "final_third_entries",
        "label": "Final-third entries",
        "short": "F3",
        "hint": "Entries into the attacking third per game.",
        "kpi_ids": (KPI_FINAL_THIRD_ENTRIES,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "final_third_against",
        "label": "Final-third entries against",
        "short": "F3 ag",
        "hint": "Opposition entries into our third per game.",
        "kpi_ids": (KPI_FINAL_THIRD_AGAINST,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "offensive_interventions",
        "label": "Offensive interventions",
        "short": "OI",
        "hint": "Opponents removed on ball wins (Impect OI).",
        "kpi_ids": (KPI_OFFENSIVE_INTERVENTIONS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "defensive_interventions",
        "label": "Defensive interventions",
        "short": "DI",
        "hint": "Teammates packed in on ball wins (Impect DI).",
        "kpi_ids": (KPI_DEFENSIVE_INTERVENTIONS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "ball_wins_defenders",
        "label": "Ball wins vs defenders",
        "short": "BW def",
        "hint": "Regains that take out opposition defenders.",
        "kpi_ids": (KPI_BALL_WINS_DEFENDERS,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "altered_threat",
        "label": "Altered threat",
        "short": "PXT",
        "hint": "Packing expected threat on the pass.",
        "kpi_ids": (KPI_PXT_PASS,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PXT/g",
    },
    {
        "key": "pxt_attack",
        "label": "Attacking threat",
        "short": "PXT att",
        "hint": "Impect attacking PXT per game.",
        "kpi_ids": (KPI_PXT_ATTACK,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PXT/g",
    },
    {
        "key": "pxt_shot",
        "label": "Shot threat",
        "short": "PXT shot",
        "hint": "Impect shot PXT per game.",
        "kpi_ids": (KPI_PXT_SHOT,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PXT/g",
    },
    {
        "key": "set_piece_threat",
        "label": "Set-piece threat",
        "short": "SP PXT",
        "hint": "Impect set-piece PXT per game.",
        "kpi_ids": (KPI_PXT_SETPIECE,),
        "fmt": "dec",
        "digits": 2,
        "unit": "PXT/g",
    },
    {
        "key": "presses",
        "label": "Presses",
        "short": "Press",
        "hint": "Press actions per game.",
        "kpi_ids": (KPI_PRESSES,),
        "fmt": "dec",
        "digits": 1,
        "unit": "/g",
    },
    {
        "key": "duel_pct",
        "label": "Duel win %",
        "short": "Duels",
        "hint": "Ground + aerial duels won.",
        "derived": "rate",
        "num_ids": (KPI_WON_GROUND, KPI_WON_AERIAL),
        "den_ids": (KPI_WON_GROUND, KPI_LOST_GROUND, KPI_WON_AERIAL, KPI_LOST_AERIAL),
        "fmt": "pct",
        "digits": 1,
        "unit": "%",
        "scale": 100.0,
    },
    {
        "key": "aerial_pct",
        "label": "Aerial win %",
        "short": "Aerials",
        "hint": "Aerial duels won.",
        "derived": "rate",
        "num_ids": (KPI_WON_AERIAL,),
        "den_ids": (KPI_WON_AERIAL, KPI_LOST_AERIAL),
        "fmt": "pct",
        "digits": 1,
        "unit": "%",
        "scale": 100.0,
    },
    {
        "key": "ground_pct",
        "label": "Ground duel win %",
        "short": "Ground",
        "hint": "Ground duels won.",
        "derived": "rate",
        "num_ids": (KPI_WON_GROUND,),
        "den_ids": (KPI_WON_GROUND, KPI_LOST_GROUND),
        "fmt": "pct",
        "digits": 1,
        "unit": "%",
        "scale": 100.0,
    },
)

# Owner-facing "why this matters" — keep in one place so the table and the briefing match.
WHY_BY_KEY: dict[str, str] = {
    "xg_diff": "The number. Chance quality for, minus against. Strongest link to winning games and to finishing high.",
    "pxt_attack": "How much attacking threat we create on the ball. Second strongest. Sides that go up do this every week.",
    "xg_for": "The quality of the chances we create. You do not win this league consistently if this stays low.",
    "sot": "Shots that can actually go in. Follows chance quality — promoted sides put more on target.",
    "xg_against": "The chances we give up. Matters even more for where you finish: it turns 1–0s into 1–1s if it is high.",
    "shots": "How often we shoot. Volume that comes with creating chances — shots without quality do not get you up.",
    "pxt_shot": "Threat at the moment we shoot. Another cut of chance quality, weaker than xG itself.",
    "defenders_bypassed_against": "How often our defensive line is broken. Lower is better. This is the one we currently win.",
    "altered_threat": "Threat we add with the pass. Part of creating chances, but a long way behind shot xG.",
    "aerial_pct": "Winning the air. Helps in League Two. Not the thing that separates promotion sides from mid-table.",
    "duel_pct": "Winning 50-50s. Same band as aerials — useful, physical, not the promotion separator.",
    "ball_wins_defenders": "Winning the ball off their defenders. High-value turnovers, still behind chance quality.",
    "final_third_against": "Shows up in the ranking, but the sign is the wrong way for a defending stat. Do not coach off this.",
    "defensive_interventions": "More of these usually means we are living without the ball. Not a number to chase.",
    "defenders_bypassed": "Breaking their line. Helps create chances — weaker than the xG numbers themselves.",
    "packing_xg": "xG that actually broke a line. Same story as chance quality — kept out of the 15 because it duplicates xG.",
    "conceded_packing_xg": "Line-breaking chances we concede. Same story as xG against.",
    "postshot_xg": "Expected goals after the shot is taken. Same story as xG for.",
    "sot_pct": "Share of shots on target. Weaker than how many good chances we create.",
    "ball_progression": "Opponents beaten on the ball. Weakly linked to winning in this league.",
    "presses": "Press actions. Weak / noisy — not a promotion lever on this data.",
    "ground_pct": "Ground duels only. Weaker than overall duel or aerial win rate.",
    "offensive_interventions": "Opponents removed on ball wins. Barely linked to winning here.",
    "set_piece_threat": "Set-piece threat. Almost no relationship with winning in this sample.",
    "final_third_entries": "Entries into their third. No relationship with winning in this sample.",
}

STORY = {
    "headline": "League Two is won by chance quality both ways.",
    "bullets": [
        "xG difference is the strongest predictor of winning games and of finishing in the top 3 / top 7. That is the number.",
        "Next is creating those chances — attacking threat, xG for, shots on target.",
        "Then stopping theirs — xG against, and how often our line is broken. That is what keeps you in the promotion race rather than mid-table.",
        "Duels, aerials and winning the ball off defenders help. They are not what separates the sides that go up.",
    ],
    "sample": (
        "Impect League Two, 96 team-seasons (22/23–25/26), 20+ games each. "
        "Packing KPIs use Impect Absolute (same as Scout Absolute — not RAW counts). "
        "Ranked by how strongly each per-game stat tracks win percentage. "
        "Goals scored left out — they are the result, not the driver."
    ),
}


def _tier_for_rank(rank: int) -> dict[str, str]:
    if rank <= 5:
        return {
            "id": "process",
            "label": "What actually wins games",
            "blurb": "Chance quality. This is the promotion process.",
        }
    if rank <= 10:
        return {
            "id": "volume",
            "label": "The volume that comes with it",
            "blurb": "Shots and threat. They follow the process — they are not a shortcut around it.",
        }
    return {
        "id": "support",
        "label": "Useful, but weaker",
        "blurb": "Physical and territorial extras. Real, just not the thing that gets you up on its own.",
    }


def _strength_label(abs_r: float) -> str:
    if abs_r >= 0.65:
        return "Very strong"
    if abs_r >= 0.50:
        return "Strong"
    if abs_r >= 0.35:
        return "Moderate"
    return "Weak"


_history_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_table_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_kpi_name_to_id: tuple[float, dict[str, int]] | None = None


def _impect():
    from app import main as impect_main

    return impect_main


def _candidate_by_key(key: str) -> Candidate:
    for item in CANDIDATES:
        if item["key"] == key:
            return item
    raise KeyError(key)


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, 1-based, for Spearman."""
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    n = len(indexed)
    while index < n:
        end = index
        while end + 1 < n and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        avg = (index + end) / 2.0 + 1.0
        for pos in range(index, end + 1):
            ranks[indexed[pos][0]] = avg
        index = end + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return num / (den_x * den_y)


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 3:
        return 0.0
    return pearson(_ranks(xs), _ranks(ys))


def _first_present(stats: dict[int, float], kpi_ids: tuple[int, ...]) -> float | None:
    for kpi_id in kpi_ids:
        if kpi_id in stats:
            return float(stats[kpi_id])
    return None


def _sum_present(stats: dict[int, float], kpi_ids: tuple[int, ...]) -> float | None:
    total = 0.0
    found = False
    for kpi_id in kpi_ids:
        if kpi_id not in stats:
            continue
        total += float(stats[kpi_id])
        found = True
    return total if found else None


def metric_value(
    stats: dict[int, float],
    spec: Candidate,
    *,
    name_to_id: dict[str, int] | None = None,
) -> float | None:
    derived = spec.get("derived")
    if derived == "sub":
        left = _first_present(stats, tuple(spec["left_ids"]))
        right = _first_present(stats, tuple(spec["right_ids"]))
        if left is None or right is None:
            return None
        return left - right
    if derived == "rate":
        num_ids = tuple(spec.get("num_ids") or ())
        den_ids = tuple(spec.get("den_ids") or ())
        mapping = name_to_id or {}
        if spec.get("num_names"):
            num_ids = tuple(mapping[name] for name in spec["num_names"] if name in mapping)
        if spec.get("den_names"):
            den_ids = tuple(mapping[name] for name in spec["den_names"] if name in mapping)
        num = _sum_present(stats, num_ids)
        den = _sum_present(stats, den_ids)
        if num is None or den is None or den <= 0:
            return None
        scale = float(spec.get("scale") or 1.0)
        return scale * num / den

    kpi_ids = tuple(spec.get("kpi_ids") or ())
    mapping = name_to_id or {}
    if spec.get("kpi_names"):
        extra = tuple(mapping[name] for name in spec["kpi_names"] if name in mapping)
        kpi_ids = extra + kpi_ids
    return _first_present(stats, kpi_ids)


def _round_metric(value: float | None, spec: Candidate) -> float | None:
    if value is None:
        return None
    digits = int(spec.get("digits") or 2)
    return round(float(value), digits)


def select_top_stats(
    observations: list[dict[str, Any]],
    candidates: tuple[Candidate, ...] | list[Candidate] = CANDIDATES,
    *,
    top_n: int = TOP_N,
    collinearity_r: float = COLLINEARITY_R,
    min_observations: int = MIN_OBSERVATIONS,
) -> list[dict[str, Any]]:
    """Rank candidate stats by Spearman correlation with win percentage."""
    scored: list[dict[str, Any]] = []
    for spec in candidates:
        xs: list[float] = []
        ys: list[float] = []
        for row in observations:
            value = row.get("metrics", {}).get(spec["key"])
            win_pct = row.get("win_pct")
            if value is None or win_pct is None:
                continue
            xs.append(float(value))
            ys.append(float(win_pct))
        if len(xs) < min_observations:
            continue
        corr = spearman(xs, ys)
        if corr == 0.0:
            continue
        scored.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "short": spec.get("short") or spec["label"],
                "hint": spec.get("hint") or "",
                "why": str(spec.get("why") or WHY_BY_KEY.get(spec["key"]) or spec.get("hint") or ""),
                "fmt": spec.get("fmt") or "dec",
                "digits": int(spec.get("digits") or 2),
                "unit": spec.get("unit") or "",
                "r": round(corr, 3),
                "abs_r": abs(corr),
                "higher_better": corr >= 0,
                "n": len(xs),
            }
        )
    scored.sort(key=lambda item: (-item["abs_r"], item["label"]))

    selected: list[dict[str, Any]] = []
    for item in scored:
        if len(selected) >= top_n:
            break
        too_close = False
        for kept in selected:
            xs: list[float] = []
            ys: list[float] = []
            for row in observations:
                left = row.get("metrics", {}).get(item["key"])
                right = row.get("metrics", {}).get(kept["key"])
                if left is None or right is None:
                    continue
                xs.append(float(left))
                ys.append(float(right))
            if len(xs) < min_observations:
                continue
            if abs(spearman(xs, ys)) >= collinearity_r:
                too_close = True
                break
        if too_close:
            continue
        clean = dict(item)
        rank = len(selected) + 1
        clean["rank"] = rank
        clean["tier"] = _tier_for_rank(rank)
        clean["strength"] = _strength_label(float(clean["abs_r"]))
        if not clean.get("why"):
            clean["why"] = WHY_BY_KEY.get(clean["key"], "")
        selected.append(clean)
    return selected


def _kpi_name_lookup() -> dict[str, int]:
    global _kpi_name_to_id
    now = time.time()
    if _kpi_name_to_id and now - _kpi_name_to_id[0] < 6 * 3600:
        return _kpi_name_to_id[1]
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/kpis")["data"]
    mapping: dict[str, int] = {}
    for item in _unwrap_items(raw):
        kpi_id = item.get("id") if item.get("id") is not None else item.get("kpiId")
        name = str(item.get("name") or "").strip()
        if kpi_id is None or not name:
            continue
        mapping[name] = int(kpi_id)
    _kpi_name_to_id = (now, mapping)
    return mapping


def _flatten_squad_kpis(iteration_id: int) -> dict[int, dict[int, float]]:
    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/squad-kpis"
    )["data"]
    table: dict[int, dict[int, float]] = {}
    for row in _unwrap_items(raw):
        squad_id = row.get("squadId")
        if squad_id is None:
            continue
        stats = table.setdefault(int(squad_id), {})
        for item in row.get("kpis") or []:
            kpi_id = item.get("kpiId") if item.get("kpiId") is not None else item.get("id")
            value = item.get("value")
            if kpi_id is None or value is None:
                continue
            kid = int(kpi_id)
            if kid in EXCLUDED_KPI_IDS:
                continue
            stats[kid] = float(value)
    return table


def _observation_metrics(
    stats: dict[int, float],
    *,
    name_to_id: dict[str, int],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for spec in CANDIDATES:
        value = metric_value(stats, spec, name_to_id=name_to_id)
        rounded = _round_metric(value, spec)
        if rounded is None:
            continue
        out[spec["key"]] = rounded
    return out


def _history_disk_path() -> Path:
    WIN_DRIVERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return WIN_DRIVERS_CACHE_DIR / f"history-v{CACHE_VERSION}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _season_rows() -> list[dict[str, Any]]:
    rows = [
        {
            "iteration_id": int(item["id"]),
            "season": str(item.get("season") or ""),
            "label": _season_label(str(item.get("season") or "")),
            "competition": COMPETITION,
        }
        for item in _competition_iterations(COMPETITION)
    ]
    rows.sort(key=lambda item: str(item.get("season") or ""), reverse=True)
    return rows


def build_history(*, force_refresh: bool = False) -> dict[str, Any]:
    cache_key = "league-two"
    now = time.time()
    if not force_refresh:
        cached = _history_cache.get(cache_key)
        if cached:
            return cached[1]
        disk = _read_json(_history_disk_path())
        if disk:
            # Serve forever until hub snapshot Refresh / daily job rebuilds.
            payload = {key: value for key, value in disk.items() if key != "cached_at_epoch"}
            _history_cache[cache_key] = (now, payload)
            return payload

    name_to_id = _kpi_name_lookup()
    observations: list[dict[str, Any]] = []
    seasons_used: list[dict[str, Any]] = []
    for season in _season_rows():
        iteration_id = int(season["iteration_id"])
        standings = _build_standings(iteration_id)
        kpi_table = _flatten_squad_kpis(iteration_id)
        season_obs = 0
        for row in standings:
            played = int(row.get("played") or 0)
            if played < MIN_GAMES_HISTORY:
                continue
            squad_id = int(row["squad_id"])
            metrics = _observation_metrics(kpi_table.get(squad_id) or {}, name_to_id=name_to_id)
            if not metrics:
                continue
            won = int(row.get("won") or 0)
            observations.append(
                {
                    "season": season["season"],
                    "club": row.get("club"),
                    "played": played,
                    "win_pct": round(100.0 * won / played, 3),
                    "ppg": float(row.get("ppg") or 0.0),
                    "metrics": metrics,
                }
            )
            season_obs += 1
        if season_obs:
            seasons_used.append({**season, "teams": season_obs})

    top = select_top_stats(observations)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": COMPETITION,
        "method": (
            "Spearman rank correlation of Impect Absolute per-game squad stats with win "
            "percentage, pooled across every League Two team-season in the data "
            f"(minimum {MIN_GAMES_HISTORY} league games). Packing uses Scout Absolute "
            "KPIs (BYPASSED_DEFENDERS / BYPASSED_OPPONENTS), not RAW event counts. "
            "Goals scored are excluded because they are the result, not the driver. "
            "Near-duplicate stats are dropped so the fifteen columns stay distinct."
        ),
        "story": STORY,
        "team_seasons": len(observations),
        "seasons": seasons_used,
        "stats": top,
    }
    _write_json(_history_disk_path(), {"cached_at_epoch": now, **payload})
    _history_cache[cache_key] = (now, payload)
    return payload


def _stat_ranks(rows: list[dict[str, Any]], stats: list[dict[str, Any]]) -> dict[int, dict[str, int]]:
    ranks: dict[int, dict[str, int]] = {int(row["squad_id"]): {} for row in rows}
    for spec in stats:
        key = spec["key"]
        higher_better = bool(spec.get("higher_better", True))
        ordered = [
            row
            for row in rows
            if row.get(key) is not None
        ]
        ordered.sort(
            key=lambda row, k=key, hb=higher_better: (
                float(row[k]) if hb else -float(row[k]),
                str(row.get("club") or ""),
            ),
            reverse=True,
        )
        for index, row in enumerate(ordered, start=1):
            ranks[int(row["squad_id"])][key] = index
    return ranks


def _mean_stat(
    rows: list[dict[str, Any]],
    key: str,
    *,
    digits: int,
    positions: set[int] | None = None,
) -> float | None:
    selected = rows
    if positions is not None:
        selected = [row for row in rows if int(row.get("position") or 0) in positions]
    values = [float(row[key]) for row in selected if row.get(key) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def _vs_bar(
    value: float | None,
    bar: float | None,
    *,
    higher_better: bool,
    digits: int,
) -> tuple[float | None, bool | None]:
    if value is None or bar is None:
        return None, None
    delta = round(float(value) - float(bar), digits)
    above = float(value) >= float(bar) if higher_better else float(value) <= float(bar)
    return delta, above


def build_table(iteration_id: int, *, force_refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force_refresh:
        cached = _table_cache.get(iteration_id)
        if cached:
            return cached[1]
        disk = _read_json(WIN_DRIVERS_CACHE_DIR / f"table-{iteration_id}-v{CACHE_VERSION}.json")
        if disk:
            # Serve forever until hub snapshot Refresh / daily job rebuilds.
            payload = {key: value for key, value in disk.items() if key != "cached_at_epoch"}
            _table_cache[iteration_id] = (now, payload)
            return payload

    # History correlation is expensive and changes slowly.
    # Rebuild it only when the disk cache is missing or explicitly refreshed.
    history = build_history(force_refresh=False)
    stats = list(history.get("stats") or [])
    if not stats:
        raise HTTPException(status_code=503, detail="Win-driver ranking is not ready yet.")

    name_to_id = _kpi_name_lookup()
    standings = _build_standings(iteration_id)
    kpi_table = _flatten_squad_kpis(iteration_id)
    spec_by_key = {item["key"]: _candidate_by_key(item["key"]) for item in stats}

    rows: list[dict[str, Any]] = []
    for row in standings:
        squad_id = int(row["squad_id"])
        metrics = _observation_metrics(kpi_table.get(squad_id) or {}, name_to_id=name_to_id)
        played = int(row.get("played") or 0)
        won = int(row.get("won") or 0)
        item: dict[str, Any] = {
            "squad_id": squad_id,
            "club": row.get("club"),
            "position": row.get("position"),
            "played": played,
            "won": won,
            "drawn": int(row.get("drawn") or 0),
            "lost": int(row.get("lost") or 0),
            "points": int(row.get("points") or 0),
            "ppg": float(row.get("ppg") or 0.0),
            "win_pct": round(100.0 * won / played, 1) if played else 0.0,
            "focus": _is_focus_squad(str(row.get("club") or "")),
        }
        for spec in stats:
            key = spec["key"]
            value = metrics.get(key)
            item[key] = _round_metric(value, spec_by_key[key]) if value is not None else None
        rows.append(item)

    ranks = _stat_ranks(rows, stats)
    for row in rows:
        row["stat_ranks"] = ranks.get(int(row["squad_id"])) or {}

    numeric_keys = ["played", "won", "drawn", "lost", "points", "ppg", "win_pct"] + [
        spec["key"] for spec in stats
    ]
    averages: dict[str, float | None] = {}
    for key in numeric_keys:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        spec = spec_by_key.get(key)
        digits = int(spec["digits"]) if spec else (2 if key in {"ppg", "win_pct"} else 1)
        averages[key] = round(sum(values) / len(values), digits) if values else None

    focus = next((row for row in rows if row.get("focus")), None)
    focus_cards: list[dict[str, Any]] = []
    if focus:
        n_clubs = len(rows)
        for spec in stats:
            key = spec["key"]
            value = focus.get(key)
            rank = (focus.get("stat_ranks") or {}).get(key)
            league = averages.get(key)
            digits = int(spec.get("digits") or 2)
            higher_better = bool(spec.get("higher_better", True))
            top7 = _mean_stat(rows, key, digits=digits, positions={1, 2, 3, 4, 5, 6, 7})
            delta, above = _vs_bar(value if value is None else float(value), league, higher_better=higher_better, digits=digits)
            delta_top7, above_top7 = _vs_bar(
                value if value is None else float(value),
                top7,
                higher_better=higher_better,
                digits=digits,
            )
            focus_cards.append(
                {
                    "key": key,
                    "label": spec["label"],
                    "short": spec.get("short") or spec["label"],
                    "hint": spec.get("hint") or "",
                    "why": spec.get("why") or WHY_BY_KEY.get(key, ""),
                    "importance": spec.get("rank"),
                    "tier": spec.get("tier") or _tier_for_rank(int(spec.get("rank") or 99)),
                    "strength": spec.get("strength") or _strength_label(abs(float(spec.get("r") or 0))),
                    "r": spec.get("r"),
                    "higher_better": spec.get("higher_better", True),
                    "value": value,
                    "fmt": spec.get("fmt") or "dec",
                    "digits": spec.get("digits") or 2,
                    "unit": spec.get("unit") or "",
                    "rank": rank,
                    "of": n_clubs,
                    "league_avg": league,
                    "top7_avg": top7,
                    "delta_vs_league": delta,
                    "delta_vs_top7": delta_top7,
                    "above_league": above,
                    "above_top7": above_top7,
                }
            )

    season = next(
        (item for item in _season_rows() if int(item["iteration_id"]) == int(iteration_id)),
        {"iteration_id": iteration_id, "season": "", "label": str(iteration_id)},
    )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": COMPETITION,
        "iteration_id": iteration_id,
        "season": season.get("season"),
        "season_label": season.get("label"),
        "method": history.get("method"),
        "story": history.get("story") or STORY,
        "team_seasons": history.get("team_seasons"),
        "history_seasons": history.get("seasons"),
        "stats": stats,
        "rows": rows,
        "averages": averages,
        "focus": {
            "club": focus.get("club") if focus else "Port Vale",
            "position": focus.get("position") if focus else None,
            "played": focus.get("played") if focus else 0,
            "won": focus.get("won") if focus else 0,
            "points": focus.get("points") if focus else 0,
            "ppg": focus.get("ppg") if focus else None,
            "win_pct": focus.get("win_pct") if focus else None,
            "cards": focus_cards,
        },
    }
    _write_json(
        WIN_DRIVERS_CACHE_DIR / f"table-{iteration_id}-v{CACHE_VERSION}.json",
        {"cached_at_epoch": now, **payload},
    )
    _table_cache[iteration_id] = (now, payload)
    return payload


# Impect player-kpis report these as the team concession while the player was on the pitch.
ON_PITCH_KEYS = frozenset({"xg_against", "defenders_bypassed_against"})
BREAKDOWN_CACHE_VERSION = 2
MATCH_RAW_CACHE_VERSION = 1

POSITION_SHORT = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "CB",
    "LEFT_WINGBACK_DEFENDER": "LB",
    "RIGHT_WINGBACK_DEFENDER": "RB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "ST",
    "SECOND_STRIKER": "SS",
}

_breakdown_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_breakdown_locks: dict[int, threading.Lock] = {}
_breakdown_locks_guard = threading.Lock()
_breakdown_retrying: set[int] = set()
BREAKDOWN_RETRY_SECONDS = 10 * 60


def player_mode(key: str) -> str:
    if key == "xg_diff":
        return "xgd"
    if key in ON_PITCH_KEYS:
        return "on_pitch"
    spec = _candidate_by_key(key)
    if spec.get("derived") == "rate":
        return "rate"
    return "own"


def _rate_ids(spec: Candidate, name_to_id: dict[str, int]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    num_ids = tuple(spec.get("num_ids") or ())
    den_ids = tuple(spec.get("den_ids") or ())
    if spec.get("num_names"):
        num_ids = tuple(name_to_id[name] for name in spec["num_names"] if name in name_to_id)
    if spec.get("den_names"):
        den_ids = tuple(name_to_id[name] for name in spec["den_names"] if name in name_to_id)
    return num_ids, den_ids


def _match_raw_path(match_id: int) -> Path:
    folder = WIN_DRIVERS_CACHE_DIR / "matches"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{match_id}-v{MATCH_RAW_CACHE_VERSION}.json"


def _int_keyed(stats: dict[Any, Any]) -> dict[int, float]:
    return {int(k): float(v) for k, v in (stats or {}).items() if v is not None}


def _fetch_match_raw(match_id: int, *, force_refresh: bool = False) -> dict[str, Any]:
    """Squad + player KPIs for one finished match. Played matches never change, so cache forever."""
    path = _match_raw_path(match_id)
    if not force_refresh:
        disk = _read_json(path)
        if disk is not None:
            return {
                "squads": {int(k): _int_keyed(v) for k, v in (disk.get("squads") or {}).items()},
                "players": [
                    {**row, "kpis": _int_keyed(row.get("kpis") or {})}
                    for row in disk.get("players") or []
                ],
            }

    from app.post_match.impect_client import impect_get, v5_path
    from app.post_match.report import (
        _combine_stint_kpi_values,
        _flatten_player_kpis,
        _flatten_squad_kpis as _flatten_match_squad_kpis,
    )

    squads = _flatten_match_squad_kpis(impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"])
    stints = _flatten_player_kpis(impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"], {})

    grouped: dict[int, dict[str, Any]] = {}
    for row in stints:
        player_id = int(row.get("playerId") or 0)
        if player_id <= 0:
            continue
        bucket = grouped.setdefault(
            player_id,
            {
                "player_id": player_id,
                "squad_id": int(row.get("squadId") or 0),
                "position": row.get("position"),
                "shirt": row.get("shirtNumber"),
                "minutes": 0.0,
                "_best": -1.0,
                "_kpis": {},
            },
        )
        minutes = float(row.get("minutes") or 0.0)
        bucket["minutes"] += minutes
        if minutes > bucket["_best"]:
            bucket["_best"] = minutes
            bucket["position"] = row.get("position") or bucket["position"]
        for kpi_id, value in (row.get("kpis") or {}).items():
            bucket["_kpis"].setdefault(int(kpi_id), []).append(float(value))

    players: list[dict[str, Any]] = []
    for bucket in grouped.values():
        kpis = {kid: _combine_stint_kpi_values(values) for kid, values in bucket.pop("_kpis").items()}
        bucket.pop("_best", None)
        bucket["minutes"] = round(bucket["minutes"], 1)
        bucket["kpis"] = kpis
        players.append(bucket)

    body = {"squads": squads, "players": players}
    if not squads:
        return body
    _write_json(
        path,
        {
            "squads": {str(k): {str(kid): v for kid, v in stats.items()} for k, stats in squads.items()},
            "players": [
                {**row, "kpis": {str(kid): v for kid, v in row["kpis"].items()}} for row in players
            ],
        },
    )
    return body


def _breakdown_disk_path(iteration_id: int) -> Path:
    WIN_DRIVERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return WIN_DRIVERS_CACHE_DIR / f"breakdown-{iteration_id}-v{CACHE_VERSION}.{BREAKDOWN_CACHE_VERSION}.json"


def _opponent_badge(squad_id: int, name: str, iteration_id: int) -> tuple[str | None, str]:
    from app.post_match.squad_badges import resolve_badge_url, squad_initials

    url: str | None = None
    try:
        url = resolve_badge_url(squad_id, iteration_id)
    except Exception:
        url = None
    if not url:
        try:
            from app.handout_badges import fotmob_crest_url_for_club

            url = fotmob_crest_url_for_club(name)
        except Exception:
            url = None
    return url, squad_initials(name)


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _cached_breakdown(iteration_id: int) -> tuple[float, dict[str, Any]] | None:
    cached = _breakdown_cache.get(iteration_id)
    if cached:
        return cached
    disk = _read_json(_breakdown_disk_path(iteration_id))
    if not disk:
        return None
    entry = (
        float(disk.get("cached_at_epoch") or 0.0),
        {key: value for key, value in disk.items() if key != "cached_at_epoch"},
    )
    _breakdown_cache[iteration_id] = entry
    return entry


def _breakdown_lock(iteration_id: int) -> threading.Lock:
    with _breakdown_locks_guard:
        return _breakdown_locks.setdefault(iteration_id, threading.Lock())


def _retry_incomplete_breakdown(iteration_id: int, cached_at: float) -> None:
    """Fill games Impect refused (rate limit) in the background; callers keep the saved copy."""
    if time.time() - cached_at < BREAKDOWN_RETRY_SECONDS:
        return
    with _breakdown_locks_guard:
        if iteration_id in _breakdown_retrying:
            return
        _breakdown_retrying.add(iteration_id)

    def run() -> None:
        try:
            build_breakdown(iteration_id, force_refresh=True)
        except Exception:
            logger.exception("What Wins Games breakdown retry failed for iteration %s", iteration_id)
        finally:
            with _breakdown_locks_guard:
                _breakdown_retrying.discard(iteration_id)

    threading.Thread(target=run, daemon=True, name=f"win-drivers-breakdown-{iteration_id}").start()


def build_breakdown(iteration_id: int, *, force_refresh: bool = False) -> dict[str, Any]:
    """Port Vale match-by-match and player-by-player numbers for every one of the 15 stats."""
    if not force_refresh:
        entry = _cached_breakdown(iteration_id)
        if entry:
            if entry[1].get("incomplete"):
                _retry_incomplete_breakdown(iteration_id, entry[0])
            return entry[1]

    with _breakdown_lock(iteration_id):
        if not force_refresh:
            entry = _cached_breakdown(iteration_id)
            if entry:
                return entry[1]
        try:
            return _build_breakdown_now(iteration_id)
        except HTTPException:
            entry = _cached_breakdown(iteration_id)
            if entry:
                return entry[1]
            raise


def _build_breakdown_now(iteration_id: int) -> dict[str, Any]:
    now = time.time()
    from concurrent.futures import ThreadPoolExecutor

    from app.club_strategy import _league_matches, _squads_map

    table = build_table(iteration_id, force_refresh=False)
    stats = list(table.get("stats") or [])
    focus_row = next((row for row in table.get("rows") or [] if row.get("focus")), None)
    base: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "iteration_id": iteration_id,
        "season_label": table.get("season_label"),
        "club": (focus_row or {}).get("club") or "Port Vale",
        "stats": [],
        "matches": [],
        "players": [],
    }
    if not focus_row:
        base["message"] = "Port Vale were not in League Two this season."
        return base

    squad_id = int(focus_row["squad_id"])
    name_to_id = _kpi_name_lookup()
    squads = _squads_map(iteration_id)
    vale_matches = [
        match
        for match in _league_matches(iteration_id, COMPETITION)
        if squad_id in (int(match.get("homeSquadId") or 0), int(match.get("awaySquadId") or 0))
    ]

    raw_by_match: dict[int, dict[str, Any]] = {}
    match_ids = [int(match["id"]) for match in vale_matches if match.get("id") is not None]
    failed: list[int] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {match_id: pool.submit(_fetch_match_raw, match_id) for match_id in match_ids}
        for match_id, future in futures.items():
            try:
                raw_by_match[match_id] = future.result()
            except Exception:
                failed.append(match_id)
    for match_id in failed:
        try:
            raw_by_match[match_id] = _fetch_match_raw(match_id)
        except Exception:
            raw_by_match[match_id] = {"squads": {}, "players": []}

    keys = [item["key"] for item in stats]
    player_keys = list(dict.fromkeys([*keys, "xg_for", "xg_against"]))
    specs = {key: _candidate_by_key(key) for key in player_keys}
    rate_ids = {key: _rate_ids(spec, name_to_id) for key, spec in specs.items() if spec.get("derived") == "rate"}

    try:
        from app.post_match.report import _player_directory

        names = _player_directory(iteration_id)
    except Exception:
        names = {}

    matches_out: list[dict[str, Any]] = []
    players: dict[int, dict[str, Any]] = {}
    for match in vale_matches:
        match_id = int(match["id"])
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        is_home = squad_id == home_id
        opp_id = away_id if is_home else home_id
        goals = match.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
        scored = home_goals if is_home else away_goals
        conceded = away_goals if is_home else home_goals
        raw = raw_by_match.get(match_id) or {"squads": {}, "players": []}
        vale_stats = raw["squads"].get(squad_id) or {}
        opp_stats = raw["squads"].get(opp_id) or {}
        values: dict[str, float | None] = {}
        opp_values: dict[str, float | None] = {}
        for item in stats:
            spec = specs[item["key"]]
            digits = int(spec.get("digits") or 2) + 1
            values[item["key"]] = _round_or_none(metric_value(vale_stats, spec, name_to_id=name_to_id), digits)
            opp_values[item["key"]] = _round_or_none(metric_value(opp_stats, spec, name_to_id=name_to_id), digits)
        opp_name = squads.get(opp_id) or f"Squad {opp_id}"
        badge_url, initials = _opponent_badge(opp_id, opp_name, iteration_id)
        matches_out.append(
            {
                "match_id": match_id,
                "date": str(match.get("scheduledDate") or "")[:10],
                "venue": "H" if is_home else "A",
                "opponent": opp_name,
                "opponent_id": opp_id,
                "badge_url": badge_url,
                "initials": initials,
                "scored": scored,
                "conceded": conceded,
                "result": "W" if scored > conceded else ("L" if scored < conceded else "D"),
                "has_data": bool(vale_stats),
                "values": values,
                "opp_values": opp_values,
            }
        )

        for row in raw["players"]:
            if int(row.get("squad_id") or 0) != squad_id:
                continue
            minutes = float(row.get("minutes") or 0.0)
            if minutes <= 0:
                continue
            player_id = int(row["player_id"])
            acc = players.setdefault(
                player_id,
                {
                    "player_id": player_id,
                    "name": names.get(player_id) or f"Player {player_id}",
                    "position": row.get("position"),
                    "_pos_minutes": {},
                    "minutes": 0.0,
                    "apps": 0,
                    "totals": {key: None for key in player_keys},
                    "counts": {key: [0.0, 0.0] for key in rate_ids},
                    "by_match": {},
                },
            )
            acc["minutes"] += minutes
            acc["apps"] += 1
            pos = str(row.get("position") or "")
            if pos:
                acc["_pos_minutes"][pos] = acc["_pos_minutes"].get(pos, 0.0) + minutes
            kpis = row.get("kpis") or {}
            cell: dict[str, Any] = {}
            for key in player_keys:
                spec = specs[key]
                if key in rate_ids:
                    num_ids, den_ids = rate_ids[key]
                    won = _sum_present(kpis, num_ids) or 0.0
                    total = _sum_present(kpis, den_ids) or 0.0
                    acc["counts"][key][0] += won
                    acc["counts"][key][1] += total
                    cell[key] = [round(won, 1), round(total, 1)] if total > 0 else None
                    continue
                if key == "xg_diff":
                    continue
                value = metric_value(kpis, spec, name_to_id=name_to_id)
                if value is None:
                    continue
                acc["totals"][key] = float(acc["totals"][key] or 0.0) + float(value)
                cell[key] = round(float(value), int(spec.get("digits") or 2) + 1)
            acc["by_match"][str(match_id)] = {"minutes": round(minutes, 1), "values": cell}

    players_out: list[dict[str, Any]] = []
    for acc in players.values():
        minutes = float(acc["minutes"])
        pos_minutes = acc.pop("_pos_minutes")
        if pos_minutes:
            acc["position"] = max(pos_minutes.items(), key=lambda item: item[1])[0]
        acc["position_short"] = POSITION_SHORT.get(str(acc.get("position") or ""), "—")
        acc["minutes"] = round(minutes, 1)
        totals: dict[str, float | None] = {}
        per90: dict[str, float | None] = {}
        for key in player_keys:
            spec = specs[key]
            digits = int(spec.get("digits") or 2) + 1
            if key in rate_ids:
                won, total = acc["counts"][key]
                totals[key] = round(100.0 * won / total, 1) if total > 0 else None
                per90[key] = None
                continue
            total_value = acc["totals"].get(key)
            totals[key] = _round_or_none(total_value, digits)
            per90[key] = round(float(total_value) * 90.0 / minutes, digits) if total_value is not None and minutes >= 1 else None
        acc["totals"] = totals
        acc["per90"] = per90
        acc["counts"] = {key: [round(v[0], 1), round(v[1], 1)] for key, v in acc["counts"].items()}
        players_out.append(acc)
    players_out.sort(key=lambda item: (-float(item["minutes"]), str(item["name"])))

    cards = {card["key"]: card for card in (table.get("focus") or {}).get("cards") or []}
    stats_out: list[dict[str, Any]] = []
    for item in stats:
        key = item["key"]
        card = cards.get(key) or {}
        stats_out.append(
            {
                "key": key,
                "rank": item.get("rank"),
                "label": item.get("label"),
                "short": item.get("short"),
                "why": item.get("why") or WHY_BY_KEY.get(key, ""),
                "hint": item.get("hint") or "",
                "strength": item.get("strength"),
                "r": item.get("r"),
                "fmt": item.get("fmt"),
                "digits": item.get("digits"),
                "unit": item.get("unit"),
                "higher_better": item.get("higher_better", True),
                "player_mode": player_mode(key),
                "season_value": card.get("value"),
                "league_rank": card.get("rank"),
                "of": card.get("of"),
                "league_avg": card.get("league_avg"),
                "top7_avg": card.get("top7_avg"),
            }
        )

    payload = {
        **base,
        "squad_id": squad_id,
        "player_keys": player_keys,
        "stats": stats_out,
        "matches": matches_out,
        "players": players_out,
    }
    payload["incomplete"] = any(not row["has_data"] for row in matches_out)
    _write_json(_breakdown_disk_path(iteration_id), {"cached_at_epoch": now, **payload})
    _breakdown_cache[iteration_id] = (now, payload)
    return payload


def _meta_disk_path() -> Path:
    WIN_DRIVERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return WIN_DRIVERS_CACHE_DIR / "meta.json"


def win_drivers_meta(*, force_refresh: bool = False) -> dict[str, Any]:
    path = _meta_disk_path()
    if not force_refresh:
        disk = _read_json(path)
        if disk and disk.get("seasons"):
            return disk

    try:
        seasons = _season_rows()[:6]
    except HTTPException:
        disk = _read_json(path)
        if disk and disk.get("seasons"):
            return disk
        raise
    payload = {
        "competition": COMPETITION,
        "focus_club": "Port Vale",
        "default_iteration_id": seasons[0]["iteration_id"] if seasons else None,
        "seasons": seasons,
        "top_n": TOP_N,
    }
    if seasons:
        _write_json(path, payload)
    return payload


def register_win_drivers_routes(app: FastAPI) -> None:
    @app.get("/win-drivers", response_class=HTMLResponse)
    def win_drivers_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "win-drivers.html"
        if not html_path.exists():
            html_path = STANDALONE_DIR / "win-drivers.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="What Wins Games UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/win-drivers/meta")
    def win_drivers_meta_route() -> dict[str, Any]:
        return win_drivers_meta()

    @app.get("/api/win-drivers/table")
    def win_drivers_table_route(
        iteration_id: int = Query(..., ge=1),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        # Click paths always serve the 5am snapshot. Rebuild via hub-snapshots.
        _ = refresh
        return build_table(iteration_id, force_refresh=False)

    @app.get("/api/win-drivers/breakdown")
    def win_drivers_breakdown_route(iteration_id: int = Query(..., ge=1)) -> dict[str, Any]:
        return build_breakdown(iteration_id, force_refresh=False)
