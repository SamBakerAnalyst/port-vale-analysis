"""Season Progress Report — live Port Vale pace vs promotion benchmarks."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from app.club_strategy import (
    COMPETITIONS,
    LEAGUE_MATCH_LIMIT,
    TIME_BUCKETS,
    TIME_BUCKET_LABELS,
    _competition_iterations,
    _disk_cache_path,
    _goal_events_for_match,
    _is_focus_squad,
    _league_matches,
    _minute_bucket_for_event,
    _read_disk_cache,
    _season_label,
    _squads_map,
    build_club_strategy_report,
)
from app.paths import CACHE_ROOT, CLUB_STRATEGY_CACHE_DIR
from app.scouting import SCOUTING_DIR

# Multi-season averages of 1st / 2nd+3rd / 4th–7th.
# League Two: Strategy Report (21/22–25/26). League One: 22/23–25/26 EFL tables.
REPORT_BENCHMARKS: dict[str, dict[str, dict[str, float]]] = {
    "League Two": {
        "points": {"champion": 87.6, "auto": 83.2, "playoff": 75.9},
        "wins": {"champion": 25.2, "auto": 23.4, "playoff": 21.2},
        "goals_for": {"champion": 75.2, "auto": 71.9, "playoff": 69.2},
        "goals_against": {"champion": 44.4, "auto": 43.9, "playoff": 51.8},
        "goal_difference": {"champion": 30.8, "auto": 28.0, "playoff": 17.4},
        "home_wins": {"champion": 14.0, "auto": 14.5, "playoff": 11.6},
        "away_wins": {"champion": 11.2, "auto": 8.9, "playoff": 9.6},
        "clean_sheets": {"champion": 18.0, "auto": 17.0, "playoff": 15.0},
        "back_to_backs": {"champion": 9.2, "auto": 7.6, "playoff": 6.3},
        "max_win_streak": {"champion": 7.2, "auto": 4.8, "playoff": 4.6},
    },
    "League One": {
        "points": {"champion": 98.0, "auto": 89.0, "playoff": 77.0},
        "wins": {"champion": 29.0, "auto": 26.0, "playoff": 21.5},
        "goals_for": {"champion": 84.0, "auto": 76.0, "playoff": 68.0},
        "goals_against": {"champion": 42.0, "auto": 48.0, "playoff": 55.0},
        "goal_difference": {"champion": 42.0, "auto": 28.0, "playoff": 13.0},
        "home_wins": {"champion": 16.0, "auto": 14.5, "playoff": 12.0},
        "away_wins": {"champion": 13.0, "auto": 11.5, "playoff": 9.5},
        "clean_sheets": {"champion": 18.0, "auto": 16.0, "playoff": 13.0},
        "back_to_backs": {"champion": 10.0, "auto": 8.0, "playoff": 6.5},
        "max_win_streak": {"champion": 8.0, "auto": 5.5, "playoff": 4.5},
    },
}

METRIC_META: dict[str, dict[str, Any]] = {
    "points": {
        "label": "Points",
        "unit": "pts",
        "lower_is_better": False,
        "project": True,
        "hint": "Cumulative league points after each game",
    },
    "wins": {
        "label": "Wins",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
        "hint": "League wins accumulated through the season",
    },
    "goals_for": {
        "label": "Goals scored",
        "unit": "goals",
        "lower_is_better": False,
        "project": True,
        "hint": "Goals scored in league matches",
    },
    "goals_against": {
        "label": "Goals conceded",
        "unit": "goals",
        "lower_is_better": True,
        "project": True,
        "hint": "Goals conceded — lower is better",
    },
    "goal_difference": {
        "label": "Goal difference",
        "unit": "GD",
        "lower_is_better": False,
        "project": True,
        "hint": "Running goal difference",
    },
    "home_wins": {
        "label": "Home wins",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
        "hint": "League wins at Vale Park",
    },
    "away_wins": {
        "label": "Away wins",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
        "hint": "League wins on the road",
    },
    "clean_sheets": {
        "label": "Clean sheets",
        "unit": "CS",
        "lower_is_better": False,
        "project": True,
        "hint": "Matches with no goals conceded",
    },
    "back_to_backs": {
        "label": "Back-to-back win pairs",
        "unit": "pairs",
        "lower_is_better": False,
        "project": False,
        "hint": "Non-overlapping pairs of consecutive wins",
    },
    "max_win_streak": {
        "label": "Longest winning run",
        "unit": "wins",
        "lower_is_better": False,
        "project": False,
        "hint": "Best winning streak so far this season",
    },
}

_cache: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 900
TRACKER_CACHE_DIR = CACHE_ROOT / "strategy-tracker"
TRACKER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRACKER_CACHE_VERSION = 3

# Match-level Impect KPIs (same IDs as post-match / Blocks Analysis).
KPI_BYPASSED_OPPONENTS = 1399
KPI_BYPASSED_DEFENDERS = 1400
KPI_SUFFERED_BYPASSED_DEFENDERS = 40
KPI_SHOT_XG = 82
KPI_CONCEDED_SHOT_XG = 1463
KPI_PACKING_XG = 83
KPI_DEFENSIVE_INTERVENTIONS = 23  # BALL_WIN_ADDED_TEAMMATES
KPI_OFFENSIVE_INTERVENTIONS = 24  # BALL_WIN_REMOVED_OPPONENTS
KPI_BALL_WINS_DEFENDERS = 25
KPI_ALTERED_THREAT = 1404  # PXT_PASS
KPI_WON_GROUND_DUELS = 94
KPI_LOST_GROUND_DUELS = 95
KPI_WON_AERIAL_DUELS = 96
KPI_LOST_AERIAL_DUELS = 97
OFFENSIVE_INTERVENTION_ACTIONS = (963, 964, 965, 966)

IMPECT_MATCH_CACHE_TTL = 6 * 3600
IMPECT_VOLUME_KEYS = (
    "defenders_bypassed",
    "ball_progression",
    "xg_for",
    "xg_against",
    "offensive_interventions",
    "defensive_interventions",
    "ball_wins_defenders",
    "altered_threat",
    "packing_xg",
    "defenders_bypassed_against",
)

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

STYLE_METRIC_META: dict[str, dict[str, Any]] = {
    "defenders_bypassed": {
        "label": "Defenders bypassed",
        "unit": "def",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": True,
        "hint": "Packing — breaking opposition defensive lines. Strong link to chance quality.",
    },
    "ball_progression": {
        "label": "Ball progression",
        "unit": "opp",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": True,
        "hint": "Opponents bypassed on the ball (Impect ball progression).",
    },
    "xg_for": {
        "label": "xG",
        "unit": "xG",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 1,
        "player": True,
        "hint": "Shot xG created — the cleanest attacking quality signal.",
    },
    "xg_against": {
        "label": "xG against",
        "unit": "xGA",
        "lower_is_better": True,
        "project": True,
        "chart": "cumulative",
        "digits": 1,
        "player": False,
        "hint": "Shot xG conceded — lower is better.",
    },
    "xg_diff": {
        "label": "xG difference",
        "unit": "xGD",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 1,
        "player": False,
        "hint": "xG minus xGA. Highest correlation with points among underlying metrics.",
    },
    "duel_rate": {
        "label": "Duel rate",
        "unit": "%",
        "lower_is_better": False,
        "project": False,
        "chart": "running_rate",
        "digits": 1,
        "player": True,
        "hint": "Ground + aerial duels won. Season-to-date win rate.",
    },
    "offensive_interventions": {
        "label": "Offensive interventions",
        "unit": "OI",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": True,
        "hint": "Opponents removed on ball wins (Impect offensive interventions).",
    },
    "defensive_interventions": {
        "label": "Defensive interventions",
        "unit": "DI",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": True,
        "hint": "Teammates packed in on ball wins (Impect defensive interventions).",
    },
    "ball_wins_defenders": {
        "label": "Ball wins from defenders",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": True,
        "hint": "Regains that take out opposition defenders — high-value turnovers.",
    },
    "altered_threat": {
        "label": "Altered threat",
        "unit": "PXT",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 1,
        "player": True,
        "hint": "Packing expected threat on the pass (PXT). Chance creation before the shot.",
    },
    "packing_xg": {
        "label": "Packing xG",
        "unit": "PxG",
        "lower_is_better": False,
        "project": True,
        "chart": "cumulative",
        "digits": 1,
        "player": True,
        "hint": "xG weighted by packing — threat that actually broke lines.",
    },
    "defenders_bypassed_against": {
        "label": "Defenders bypassed against",
        "unit": "def",
        "lower_is_better": True,
        "project": True,
        "chart": "cumulative",
        "digits": 0,
        "player": False,
        "hint": "How often Vale’s defensive line is broken. Lower is better.",
    },
}

STYLE_METRIC_KEYS = tuple(STYLE_METRIC_META.keys())

# Completed seasons verified against Strategy Report / prior smoke tests.
# Used only when live match lists are unavailable (e.g. Impect 429).
_KNOWN_SEASON_EXTRAS: dict[int, dict[str, int]] = {
    1021: {"home_wins": 12, "away_wins": 10, "back_to_backs": 8, "max_win_streak": 5},
}


def _project(value: float, played: int) -> float | None:
    if played <= 0:
        return None
    return round((value / played) * LEAGUE_MATCH_LIMIT, 1)


def _status(current: float, auto: float, *, lower_is_better: bool) -> str:
    if lower_is_better:
        if current <= auto:
            return "ahead"
        if current <= auto * 1.05:
            return "on_track"
        return "behind"
    if current >= auto:
        return "ahead"
    if current >= auto * 0.97:
        return "on_track"
    return "behind"


def _streak_stats(results: list[str]) -> dict[str, int]:
    max_run = 0
    run = 0
    run_lengths: list[int] = []
    for result in results:
        if result == "W":
            run += 1
            max_run = max(max_run, run)
        else:
            if run:
                run_lengths.append(run)
            run = 0
    if run:
        run_lengths.append(run)
    # Match Strategy Report: non-overlapping pairs within each win run.
    back_to_backs = sum(length // 2 for length in run_lengths)
    return {"max_win_streak": max_run, "back_to_backs": back_to_backs}


def _tracker_disk_path(iteration_id: int) -> Path:
    return TRACKER_CACHE_DIR / f"tracker-v{TRACKER_CACHE_VERSION}-{iteration_id}.json"


def _read_tracker_cache(iteration_id: int, *, allow_stale: bool = False) -> dict[str, Any] | None:
    now = time.time()
    cached = _cache.get(iteration_id)
    if cached and (allow_stale or now - cached[0] < CACHE_TTL_SECONDS):
        return cached[1]

    path = _tracker_disk_path(iteration_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = float(payload.get("cached_at_epoch") or 0.0)
    body = {key: value for key, value in payload.items() if key != "cached_at_epoch"}
    if not allow_stale and now - cached_at > CACHE_TTL_SECONDS:
        return None
    _cache[iteration_id] = (cached_at or now, body)
    return body


def _write_tracker_cache(iteration_id: int, payload: dict[str, Any]) -> None:
    now = time.time()
    _cache[iteration_id] = (now, payload)
    path = _tracker_disk_path(iteration_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cached_at_epoch": now, **payload}, indent=2),
        encoding="utf-8",
    )


def _report_has_vale(report: dict[str, Any]) -> bool:
    standings = report.get("standings") or []
    return any(
        row.get("focus") or _is_focus_squad(str(row.get("club") or ""))
        for row in standings
    )


def _read_report_cheap(iteration_id: int) -> dict[str, Any] | None:
    """Prefer memory/fresh disk, then stale disk — never call Impect."""
    path = _disk_cache_path("report-v2", iteration_id)
    fresh = _read_disk_cache(path)
    if fresh is not None:
        return {key: value for key, value in fresh.items() if key != "cached_at_epoch"}
    stale = _read_disk_cache(path, allow_stale=True)
    if stale is None:
        return None
    return {key: value for key, value in stale.items() if key != "cached_at_epoch"}


def _benchmarks_for(competition: str) -> dict[str, dict[str, float]]:
    return REPORT_BENCHMARKS.get(competition) or REPORT_BENCHMARKS["League Two"]


def _empty_goal_side() -> dict[str, Any]:
    return {
        "total": 0,
        "home": 0,
        "away": 0,
        "first_half": 0,
        "second_half": 0,
        "added": 0,
        "buckets": {label: {"total": 0, "home": 0, "away": 0} for label in TIME_BUCKETS},
    }


def _add_goal_to_side(side: dict[str, Any], *, bucket: str, half: str, is_home: bool) -> None:
    side["total"] += 1
    venue = "home" if is_home else "away"
    side[venue] += 1
    if half == "first_half":
        side["first_half"] += 1
    else:
        side["second_half"] += 1
    if bucket in {"45+", "90+"}:
        side["added"] += 1
    key = bucket if bucket in side["buckets"] else "unknown"
    side["buckets"][key]["total"] += 1
    side["buckets"][key][venue] += 1


def _kpi(kpis: dict[int, float], kpi_id: int) -> float:
    return float(kpis.get(kpi_id) or 0.0)


def _style_from_kpis(kpis: dict[int, float]) -> dict[str, float]:
    won = _kpi(kpis, KPI_WON_GROUND_DUELS) + _kpi(kpis, KPI_WON_AERIAL_DUELS)
    lost = _kpi(kpis, KPI_LOST_GROUND_DUELS) + _kpi(kpis, KPI_LOST_AERIAL_DUELS)
    total = won + lost
    offensive = _kpi(kpis, KPI_OFFENSIVE_INTERVENTIONS)
    if offensive <= 0:
        offensive = sum(_kpi(kpis, kpi_id) for kpi_id in OFFENSIVE_INTERVENTION_ACTIONS)
    xg_for = _kpi(kpis, KPI_SHOT_XG)
    xg_against = _kpi(kpis, KPI_CONCEDED_SHOT_XG)
    altered = _kpi(kpis, KPI_ALTERED_THREAT)
    return {
        "defenders_bypassed": _kpi(kpis, KPI_BYPASSED_DEFENDERS),
        "ball_progression": _kpi(kpis, KPI_BYPASSED_OPPONENTS),
        "xg_for": xg_for,
        "xg_against": xg_against,
        "xg_diff": round(xg_for - xg_against, 3),
        "duel_won": won,
        "duel_total": total,
        "duel_rate": (100.0 * won / total) if total else 0.0,
        "offensive_interventions": offensive,
        "defensive_interventions": _kpi(kpis, KPI_DEFENSIVE_INTERVENTIONS),
        "ball_wins_defenders": _kpi(kpis, KPI_BALL_WINS_DEFENDERS),
        "altered_threat": altered,
        "packing_xg": _kpi(kpis, KPI_PACKING_XG),
        "defenders_bypassed_against": _kpi(kpis, KPI_SUFFERED_BYPASSED_DEFENDERS),
    }


def _impect_match_cache_path(match_id: int) -> Path:
    folder = TRACKER_CACHE_DIR / "impect-matches"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{match_id}.json"


def _read_impect_match_cache(match_id: int) -> dict[str, Any] | None:
    path = _impect_match_cache_path(match_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = float(payload.get("cached_at_epoch") or 0.0)
    if time.time() - cached_at > IMPECT_MATCH_CACHE_TTL:
        return None
    return payload.get("body")


def _write_impect_match_cache(match_id: int, body: dict[str, Any]) -> None:
    path = _impect_match_cache_path(match_id)
    path.write_text(
        json.dumps({"cached_at_epoch": time.time(), "body": body}),
        encoding="utf-8",
    )


def _fetch_match_impect(match_id: int, squad_id: int, *, force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = _read_impect_match_cache(match_id)
        if cached is not None:
            return cached
    from app.post_match.impect_client import impect_get, v5_path
    from app.post_match.report import (
        _combine_stint_kpi_values,
        _flatten_player_kpis,
        _flatten_squad_kpis,
    )

    squad_lookup = _flatten_squad_kpis(impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"])
    team = _style_from_kpis(squad_lookup.get(squad_id) or {})
    players_raw = _flatten_player_kpis(
        impect_get(v5_path(f"/matches/{match_id}/player-kpis"))["data"],
        {},
    )
    by_player: dict[int, dict[str, Any]] = {}
    for row in players_raw:
        if int(row.get("squadId") or 0) != squad_id:
            continue
        player_id = int(row.get("playerId") or 0)
        if player_id <= 0:
            continue
        bucket = by_player.setdefault(
            player_id,
            {
                "player_id": player_id,
                "name": row.get("name") or f"Player {player_id}",
                "position": row.get("position"),
                "minutes": 0.0,
                "kpi_lists": {key: [] for key in (*IMPECT_VOLUME_KEYS, "duel_won", "duel_total")},
            },
        )
        bucket["minutes"] += float(row.get("minutes") or 0.0)
        if row.get("position"):
            bucket["position"] = row.get("position")
        extracted = _style_from_kpis(row.get("kpis") or {})
        for key in (*IMPECT_VOLUME_KEYS, "duel_won", "duel_total"):
            bucket["kpi_lists"][key].append(float(extracted.get(key) or 0.0))

    players: list[dict[str, Any]] = []
    for bucket in by_player.values():
        merged = {
            key: _combine_stint_kpi_values(values)
            for key, values in bucket["kpi_lists"].items()
        }
        duel_total = merged.get("duel_total") or 0.0
        players.append(
            {
                "player_id": bucket["player_id"],
                "name": bucket["name"],
                "position": bucket["position"],
                "minutes": round(bucket["minutes"], 1),
                **{key: merged.get(key) or 0.0 for key in IMPECT_VOLUME_KEYS},
                "duel_won": merged.get("duel_won") or 0.0,
                "duel_total": duel_total,
                "duel_rate": (100.0 * (merged.get("duel_won") or 0.0) / duel_total) if duel_total else 0.0,
            }
        )
    body = {"team": team, "players": players}
    _write_impect_match_cache(match_id, body)
    return body


def _pack_average(values: list[float], count: int, *, lower_is_better: bool) -> float | None:
    if not values:
        return None
    ordered = sorted(values, reverse=not lower_is_better)
    take = ordered[: max(1, min(count, len(ordered)))]
    return round(sum(take) / len(take), 3)


def _league_style_rates(iteration_id: int) -> dict[str, dict[str, float]]:
    from app.post_match.impect_client import extract_rows, impect_get, v5_path

    rows = extract_rows(impect_get(v5_path(f"/iterations/{iteration_id}/squad-kpis"))["data"])
    per_squad: dict[int, dict[str, float]] = {}
    for row in rows:
        squad_id = int(row.get("squadId") or 0)
        if not squad_id:
            continue
        kpis: dict[int, float] = {}
        for item in row.get("kpis") or []:
            kpi_id = item.get("kpiId")
            value = item.get("value")
            if kpi_id is None or value is None:
                continue
            kpis[int(kpi_id)] = float(value)
        per_squad[squad_id] = _style_from_kpis(kpis)

    out: dict[str, dict[str, float]] = {}
    for key, meta in STYLE_METRIC_META.items():
        values = [float(stats.get(key) or 0.0) for stats in per_squad.values()]
        if not values:
            continue
        lower = bool(meta["lower_is_better"])
        league = round(sum(values) / len(values), 3)
        top7 = _pack_average(values, 7, lower_is_better=lower)
        top3 = _pack_average(values, 3, lower_is_better=lower)
        out[key] = {
            "league": league,
            "top7": top7 if top7 is not None else league,
            "top3": top3 if top3 is not None else league,
        }
    return out


def _position_short(position: Any) -> str:
    raw = str(position or "").strip()
    if not raw:
        return "—"
    return POSITION_SHORT.get(raw, raw.replace("_", " ").title()[:3])


def _empty_style_snapshot() -> dict[str, float]:
    snap = {key: 0.0 for key in IMPECT_VOLUME_KEYS}
    snap.update({"duel_won": 0.0, "duel_total": 0.0, "duel_rate": 0.0, "xg_diff": 0.0})
    return snap


def _vale_impect_bundle(
    vale_matches: list[dict[str, Any]],
    squad_id: int,
    iteration_id: int,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    by_match: dict[int, dict[str, float]] = {}
    player_acc: dict[int, dict[str, Any]] = {}
    match_ids = [int(match["id"]) for match in vale_matches if match.get("id") is not None]
    if match_ids:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_fetch_match_impect, match_id, squad_id, force_refresh=force_refresh): match_id
                for match_id in match_ids
            }
            for future in as_completed(futures):
                match_id = futures[future]
                try:
                    payload = future.result()
                except Exception:
                    payload = {"team": _empty_style_snapshot(), "players": []}
                by_match[match_id] = payload.get("team") or _empty_style_snapshot()
                for player in payload.get("players") or []:
                    player_id = int(player.get("player_id") or 0)
                    if player_id <= 0:
                        continue
                    acc = player_acc.setdefault(
                        player_id,
                        {
                            "player_id": player_id,
                            "name": player.get("name") or f"Player {player_id}",
                            "position": player.get("position"),
                            "minutes": 0.0,
                            "appearances": 0,
                            **{key: 0.0 for key in IMPECT_VOLUME_KEYS},
                            "duel_won": 0.0,
                            "duel_total": 0.0,
                        },
                    )
                    acc["minutes"] += float(player.get("minutes") or 0.0)
                    if float(player.get("minutes") or 0.0) > 0:
                        acc["appearances"] += 1
                    if player.get("position"):
                        acc["position"] = player.get("position")
                    if player.get("name") and not str(acc["name"]).startswith("Player "):
                        pass
                    elif player.get("name"):
                        acc["name"] = player["name"]
                    for key in IMPECT_VOLUME_KEYS:
                        acc[key] += float(player.get(key) or 0.0)
                    acc["duel_won"] += float(player.get("duel_won") or 0.0)
                    acc["duel_total"] += float(player.get("duel_total") or 0.0)

    names: dict[int, str] = {}
    try:
        from app.post_match.report import _player_directory

        names = _player_directory(iteration_id)
    except Exception:
        names = {}

    players: list[dict[str, Any]] = []
    for acc in player_acc.values():
        minutes = float(acc["minutes"] or 0.0)
        p90 = (90.0 / minutes) if minutes >= 1 else 0.0
        duel_total = float(acc["duel_total"] or 0.0)
        name = names.get(int(acc["player_id"])) or acc["name"]
        row = {
            "player_id": acc["player_id"],
            "name": name,
            "position": acc.get("position"),
            "position_short": _position_short(acc.get("position")),
            "minutes": round(minutes, 1),
            "appearances": int(acc["appearances"]),
            "duel_rate": round(100.0 * float(acc["duel_won"] or 0.0) / duel_total, 1) if duel_total else None,
        }
        for key in IMPECT_VOLUME_KEYS:
            total = round(float(acc[key] or 0.0), 2)
            row[key] = total
            row[f"{key}_p90"] = round(total * p90, 2) if p90 else 0.0
        players.append(row)
    players.sort(key=lambda item: (-float(item["minutes"]), str(item["name"])))

    league: dict[str, dict[str, float]] = {}
    try:
        league = _league_style_rates(iteration_id)
    except Exception:
        league = {}

    return {"by_match": by_match, "players": players, "league": league}


def _style_metric_card(
    key: str,
    current: float,
    played: int,
    league: dict[str, dict[str, float]],
) -> dict[str, Any]:
    meta = STYLE_METRIC_META[key]
    digits = int(meta.get("digits") or 0)
    pack = league.get(key) or {}
    per_game = (current / played) if played else 0.0
    is_rate = meta.get("chart") == "running_rate"
    if is_rate:
        projected = None
        compare = round(current, digits)
        bench = {
            "playoff": pack.get("league"),
            "auto": pack.get("top7"),
            "champion": pack.get("top3"),
        }
    else:
        projected = _project(current, played)
        compare = projected if projected is not None else round(current, digits)
        multiplier = LEAGUE_MATCH_LIMIT if played else 1
        bench = {
            "playoff": round(float(pack["league"]) * multiplier, digits) if pack.get("league") is not None else None,
            "auto": round(float(pack["top7"]) * multiplier, digits) if pack.get("top7") is not None else None,
            "champion": round(float(pack["top3"]) * multiplier, digits) if pack.get("top3") is not None else None,
        }
    auto = bench.get("auto")
    if played <= 0 or auto is None:
        status = "awaiting"
        delta = None
    else:
        status = _status(float(compare), float(auto), lower_is_better=meta["lower_is_better"])
        delta = round(float(compare) - float(auto), 1)
    return {
        "id": key,
        "label": meta["label"],
        "unit": meta["unit"],
        "hint": meta.get("hint") or "",
        "group": "impect",
        "benchmark_set": "league_pack",
        "benchmark_labels": {"playoff": "League", "auto": "Top 7", "champion": "Top 3"},
        "lower_is_better": meta["lower_is_better"],
        "project": meta["project"],
        "chart": meta.get("chart") or "cumulative",
        "digits": digits,
        "has_line": True,
        "has_player": bool(meta.get("player")),
        "current": round(current, digits if digits else 1) if digits else round(current),
        "per_game": round(per_game, 2),
        "projected": projected,
        "compare": compare,
        "benchmarks": bench,
        "status": status,
        "delta_vs_auto": delta,
    }


def _vale_goal_times(
    vale_matches: list[dict[str, Any]],
    squad_id: int,
) -> dict[str, Any]:
    scored = _empty_goal_side()
    conceded = _empty_goal_side()
    missing = 0
    with_events = 0
    match_ids = [int(match["id"]) for match in vale_matches if match.get("id") is not None]
    events_by_match: dict[int, list[dict[str, Any]]] = {}
    if match_ids:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_goal_events_for_match, match_id): match_id for match_id in match_ids}
            for future in as_completed(futures):
                match_id = futures[future]
                try:
                    events_by_match[match_id] = future.result()
                except Exception:
                    events_by_match[match_id] = []

    for match in vale_matches:
        match_id = int(match.get("id") or 0)
        home_id = int(match.get("homeSquadId") or 0)
        is_home = squad_id == home_id
        goals = match.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
        expected = home_goals + away_goals
        events = events_by_match.get(match_id) or []
        vale_gf = home_goals if is_home else away_goals
        vale_ga = away_goals if is_home else home_goals
        if expected > 0 and not events:
            missing += 1
            for _ in range(vale_gf):
                _add_goal_to_side(scored, bucket="unknown", half="second_half", is_home=is_home)
            for _ in range(vale_ga):
                _add_goal_to_side(conceded, bucket="unknown", half="second_half", is_home=is_home)
            continue
        if events:
            with_events += 1
        for event in events:
            bucket, half, _minute = _minute_bucket_for_event(event)
            scorer = int(event.get("squadId") or 0)
            if scorer == squad_id:
                _add_goal_to_side(scored, bucket=bucket, half=half, is_home=is_home)
            else:
                _add_goal_to_side(conceded, bucket=bucket, half=half, is_home=is_home)

    return {
        "for": scored,
        "against": conceded,
        "matches_with_events": with_events,
        "matches_missing_events": missing,
        "bucket_labels": dict(TIME_BUCKET_LABELS),
        "bucket_order": [label for label in TIME_BUCKETS if label != "unknown"],
    }


def _find_vale_squad(
    iteration_id: int,
    standings: list[dict[str, Any]] | None = None,
) -> tuple[int, str] | None:
    for row in standings or []:
        if row.get("focus") or _is_focus_squad(str(row.get("club") or "")):
            return int(row.get("squad_id") or 0), str(row.get("club") or "Port Vale")
    try:
        squads = _squads_map(iteration_id)
    except HTTPException:
        return None
    for squad_id, name in squads.items():
        if _is_focus_squad(name):
            return squad_id, name
    return None


def _vale_match_progress(
    iteration_id: int,
    squad_id: int,
    *,
    competition: str,
    include_goal_times: bool = True,
    include_impect: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    matches = _league_matches(iteration_id, competition)
    squads: dict[int, str] = {}
    try:
        squads = _squads_map(iteration_id)
    except HTTPException:
        squads = {}

    results: list[str] = []
    series: list[dict[str, Any]] = []
    vale_matches: list[dict[str, Any]] = []
    home_wins = away_wins = clean_sheets = wins = 0
    goals_for = goals_against = points = 0
    played = 0

    for match in matches:
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        if squad_id not in (home_id, away_id):
            continue
        vale_matches.append(match)
        match_id = int(match.get("id") or 0)
        goals = match.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
        is_home = squad_id == home_id
        scored = home_goals if is_home else away_goals
        conceded = away_goals if is_home else home_goals
        opponent_id = away_id if is_home else home_id
        if scored > conceded:
            result = "W"
            points += 3
            wins += 1
            if is_home:
                home_wins += 1
            else:
                away_wins += 1
        elif scored < conceded:
            result = "L"
        else:
            result = "D"
            points += 1
        played += 1
        goals_for += scored
        goals_against += conceded
        if conceded == 0:
            clean_sheets += 1
        results.append(result)
        streaks = _streak_stats(results)
        series.append(
            {
                "played": played,
                "date": str(match.get("scheduledDate") or "")[:10],
                "result": result,
                "venue": "H" if is_home else "A",
                "opponent": squads.get(opponent_id, f"Squad {opponent_id}"),
                "scored": scored,
                "conceded": conceded,
                "points": points,
                "wins": wins,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "goal_difference": goals_for - goals_against,
                "home_wins": home_wins,
                "away_wins": away_wins,
                "clean_sheets": clean_sheets,
                "back_to_backs": streaks["back_to_backs"],
                "max_win_streak": streaks["max_win_streak"],
                "match_id": match_id,
            }
        )

    streaks = _streak_stats(results)
    goal_times = (
        _vale_goal_times(vale_matches, squad_id)
        if include_goal_times and vale_matches
        else {
            "for": _empty_goal_side(),
            "against": _empty_goal_side(),
            "matches_with_events": 0,
            "matches_missing_events": 0,
            "bucket_labels": dict(TIME_BUCKET_LABELS),
            "bucket_order": [label for label in TIME_BUCKETS if label != "unknown"],
        }
    )
    impect = (
        _vale_impect_bundle(
            vale_matches,
            squad_id,
            iteration_id,
            force_refresh=force_refresh,
        )
        if include_impect and vale_matches
        else {"by_match": {}, "players": [], "league": {}}
    )
    running = {key: 0.0 for key in IMPECT_VOLUME_KEYS}
    duel_won = duel_total = 0.0
    by_match = impect.get("by_match") or {}
    for row in series:
        snap = by_match.get(int(row.get("match_id") or 0)) or _empty_style_snapshot()
        for key in IMPECT_VOLUME_KEYS:
            running[key] += float(snap.get(key) or 0.0)
            row[key] = round(running[key], 2)
        duel_won += float(snap.get("duel_won") or 0.0)
        duel_total += float(snap.get("duel_total") or 0.0)
        row["duel_rate"] = round((100.0 * duel_won / duel_total), 1) if duel_total else 0.0
        row["xg_diff"] = round(running["xg_for"] - running["xg_against"], 2)
        row["duel_won"] = round(duel_won, 1)
        row["duel_total"] = round(duel_total, 1)
    style_totals = {**running, "duel_rate": (100.0 * duel_won / duel_total) if duel_total else 0.0}
    style_totals["xg_diff"] = running["xg_for"] - running["xg_against"]
    return {
        "played": played,
        "points": points,
        "wins": wins,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goals_for - goals_against,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "clean_sheets": clean_sheets,
        "back_to_backs": streaks["back_to_backs"],
        "max_win_streak": streaks["max_win_streak"],
        "results": results,
        "form": results[-6:],
        "series": series,
        "goal_times": goal_times,
        "style_totals": style_totals,
        "players": impect.get("players") or [],
        "style_league": impect.get("league") or {},
    }


def _goal_spotlight(goal_times: dict[str, Any]) -> dict[str, Any]:
    order = [key for key in (goal_times.get("bucket_order") or []) if key != "unknown"]
    labels = goal_times.get("bucket_labels") or {}
    scored_buckets = (goal_times.get("for") or {}).get("buckets") or {}
    conceded_buckets = (goal_times.get("against") or {}).get("buckets") or {}

    def peak(buckets: dict[str, Any]) -> dict[str, Any] | None:
        if not order:
            return None
        best_key = max(order, key=lambda key: int((buckets.get(key) or {}).get("total") or 0))
        total = int((buckets.get(best_key) or {}).get("total") or 0)
        if total <= 0:
            return None
        return {"bucket": best_key, "label": labels.get(best_key) or best_key, "total": total}

    scored = goal_times.get("for") or {}
    conceded = goal_times.get("against") or {}
    return {
        "best_scoring": peak(scored_buckets),
        "most_conceded": peak(conceded_buckets),
        "first_half_for": int(scored.get("first_half") or 0),
        "second_half_for": int(scored.get("second_half") or 0),
        "first_half_against": int(conceded.get("first_half") or 0),
        "second_half_against": int(conceded.get("second_half") or 0),
        "added_for": int(scored.get("added") or 0),
        "added_against": int(conceded.get("added") or 0),
        "home_for": int(scored.get("home") or 0),
        "away_for": int(scored.get("away") or 0),
        "home_against": int(conceded.get("home") or 0),
        "away_against": int(conceded.get("away") or 0),
    }


def _metric_card(
    key: str,
    current: float,
    played: int,
    *,
    competition: str,
) -> dict[str, Any]:
    meta = METRIC_META[key]
    bench = _benchmarks_for(competition)[key]
    projected = _project(current, played) if meta["project"] else None
    compare = projected if projected is not None else current
    if played <= 0:
        status = "awaiting"
        delta = None
    else:
        status = _status(compare, bench["auto"], lower_is_better=meta["lower_is_better"])
        delta = round(compare - bench["auto"], 1)
    return {
        "id": key,
        "label": meta["label"],
        "unit": meta["unit"],
        "hint": meta.get("hint") or "",
        "lower_is_better": meta["lower_is_better"],
        "project": meta["project"],
        "has_line": True,
        "group": "outcome",
        "benchmark_set": "promotion",
        "benchmark_labels": {"playoff": "PO", "auto": "Auto", "champion": "Champ"},
        "chart": "cumulative",
        "digits": 0,
        "current": current,
        "projected": projected,
        "compare": compare,
        "benchmarks": bench,
        "status": status,
        "delta_vs_auto": delta,
    }


def _pick_from_disk_reports(competition: str | None) -> tuple[int, str, str | None] | None:
    """Newest Vale season from club-strategy disk cache (no Impect)."""
    wanted = (competition,) if competition in COMPETITIONS else COMPETITIONS
    candidates: list[tuple[str, int, str, str | None]] = []
    cache_dir = CLUB_STRATEGY_CACHE_DIR
    for path in cache_dir.glob("report-v2-*.json"):
        try:
            iteration_id = int(path.stem.rsplit("-", 1)[-1])
        except ValueError:
            continue
        report = _read_report_cheap(iteration_id)
        if report is None:
            continue
        comp = str(report.get("competition") or "").strip()
        if comp not in wanted:
            continue
        if not _report_has_vale(report):
            standings = report.get("standings") or []
            preseason = not standings or all(int(row.get("played") or 0) == 0 for row in standings)
            if not preseason:
                continue
            if _find_vale_squad(iteration_id, standings) is None:
                continue
        season = str(report.get("season") or "")
        candidates.append((season, iteration_id, comp, _season_label(season) or season or None))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, iteration_id, comp, label = candidates[0]
    return iteration_id, comp, label


def _live_season_candidates(competition: str | None) -> list[tuple[str, int, str, str | None]]:
    comps = (competition,) if competition in COMPETITIONS else COMPETITIONS
    rows: list[tuple[str, int, str, str | None]] = []
    for comp in comps:
        try:
            seasons = _competition_iterations(comp)[:6]
        except HTTPException:
            continue
        for season in seasons:
            try:
                iteration_id = int(season.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if iteration_id <= 0:
                continue
            raw = str(season.get("season") or "")
            label = _season_label(raw) or raw or None
            rows.append((raw or str(label or ""), iteration_id, comp, str(label) if label else None))
    rows.sort(key=lambda item: item[0], reverse=True)
    return rows


def _pick_vale_iteration(competition: str | None) -> tuple[int, str, str | None]:
    """Newest campaign that includes Port Vale — live iterations first, disk only as fallback."""
    last_seen: tuple[int, str, str | None] | None = None
    for _season_key, iteration_id, comp, label in _live_season_candidates(competition):
        last_seen = (iteration_id, comp, label)
        if _find_vale_squad(iteration_id) is not None:
            return iteration_id, comp, label

    disk_pick = _pick_from_disk_reports(competition)
    if disk_pick is not None:
        return disk_pick
    if last_seen:
        return last_seen
    return 0, competition or "League Two", None


def _assemble_tracker(
    *,
    iteration_id: int,
    competition: str,
    season_label: str | None,
    force_refresh: bool,
) -> dict[str, Any]:
    try:
        report = build_club_strategy_report(iteration_id, force_refresh=force_refresh)
    except HTTPException as exc:
        if exc.status_code not in {404, 429}:
            raise
        report = _read_report_cheap(iteration_id) or {}
    standings = report.get("standings") or []
    vale = _find_vale_squad(iteration_id, standings)
    if vale is None:
        raise HTTPException(
            status_code=404,
            detail="Port Vale not found in this season yet. Tracker unlocks once Vale are in the Impect squad list.",
        )
    squad_id, club_name = vale
    vale_row = next((row for row in standings if int(row.get("squad_id") or 0) == squad_id), None) or {}
    competition = str(report.get("competition") or competition or "League Two").strip()
    benches = _benchmarks_for(competition)

    try:
        progress = _vale_match_progress(
            iteration_id,
            squad_id,
            competition=competition,
            include_goal_times=True,
            include_impect=True,
            force_refresh=force_refresh,
        )
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        played = int(vale_row.get("played") or 0)
        points = float(vale_row.get("points") or 0)
        known = _KNOWN_SEASON_EXTRAS.get(iteration_id, {})
        gf = float(vale_row.get("goals_for") or 0)
        ga = float(vale_row.get("goals_against") or 0)
        progress = {
            "played": played,
            "points": points,
            "wins": float(known.get("home_wins") or 0) + float(known.get("away_wins") or 0),
            "goals_for": gf,
            "goals_against": ga,
            "goal_difference": gf - ga,
            "home_wins": float(known.get("home_wins") or 0),
            "away_wins": float(known.get("away_wins") or 0),
            "clean_sheets": float(vale_row.get("clean_sheets") or known.get("clean_sheets") or 0),
            "back_to_backs": int(known.get("back_to_backs") or 0),
            "max_win_streak": int(known.get("max_win_streak") or 0),
            "results": [],
            "form": [],
            "series": (
                [{"played": played, "points": points, "result": "", "date": "", "wins": 0,
                  "goals_for": gf, "goals_against": ga, "goal_difference": gf - ga,
                  "home_wins": 0, "away_wins": 0, "clean_sheets": 0,
                  "back_to_backs": 0, "max_win_streak": 0}]
                if played
                else []
            ),
            "goal_times": {
                "for": _empty_goal_side(),
                "against": _empty_goal_side(),
                "matches_with_events": 0,
                "matches_missing_events": 0,
                "bucket_labels": dict(TIME_BUCKET_LABELS),
                "bucket_order": [label for label in TIME_BUCKETS if label != "unknown"],
            },
            "style_totals": _empty_style_snapshot(),
            "players": [],
            "style_league": {},
        }
    played = int(progress["played"] or vale_row.get("played") or 0)

    metric_keys = (
        "points",
        "wins",
        "goals_for",
        "goals_against",
        "goal_difference",
        "home_wins",
        "away_wins",
        "clean_sheets",
        "back_to_backs",
        "max_win_streak",
    )
    metrics = [
        _metric_card(key, float(progress.get(key) or 0), played, competition=competition)
        for key in metric_keys
    ]
    style_totals = progress.get("style_totals") or _empty_style_snapshot()
    style_league = progress.get("style_league") or {}
    style_metrics = [
        _style_metric_card(key, float(style_totals.get(key) or 0), played, style_league)
        for key in STYLE_METRIC_KEYS
    ]

    points_metric = next(m for m in metrics if m["id"] == "points")
    goal_times = progress.get("goal_times") or {
        "for": _empty_goal_side(),
        "against": _empty_goal_side(),
        "matches_with_events": 0,
        "matches_missing_events": 0,
        "bucket_labels": dict(TIME_BUCKET_LABELS),
        "bucket_order": [label for label in TIME_BUCKETS if label != "unknown"],
    }
    source = (
        "Live Impect league matches · League Two benchmarks from the Strategy Report "
        "(champ / auto / play-off multi-season averages)"
        if competition == "League Two"
        else         "Live Impect league matches · League One benchmarks from recent EFL seasons "
        "(1st / auto 2nd–3rd / play-off 4th–7th averages)"
    )
    source = (
        f"{source} · style stats vs this season’s league / top-7 / top-3 per-match rates"
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": competition,
        "season": report.get("season") or season_label,
        "iteration_id": iteration_id,
        "club": club_name or vale_row.get("club") or "Port Vale",
        "position": vale_row.get("position"),
        "played": played,
        "games_remaining": max(0, LEAGUE_MATCH_LIMIT - played),
        "kickoff_ready": played <= 0,
        "xg_for": vale_row.get("xg_for"),
        "xg_against": vale_row.get("xg_against"),
        "xp_vs_actual": vale_row.get("xp_vs_actual"),
        "form": progress.get("form") or [],
        "summary": {
            "status": points_metric["status"],
            "projected_points": points_metric["projected"],
            "auto_target": benches["points"]["auto"],
            "champion_target": benches["points"]["champion"],
            "playoff_target": benches["points"]["playoff"],
            "delta_vs_auto": points_metric["delta_vs_auto"],
        },
        "benchmarks": benches,
        "metrics": metrics,
        "style_metrics": style_metrics,
        "players": progress.get("players") or [],
        "series": progress.get("series") or [],
        "points_series": progress.get("series") or [],
        "goal_times": goal_times,
        "goal_spotlight": _goal_spotlight(goal_times),
        "source_note": source,
    }


def build_strategy_tracker(
    *,
    competition: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    wanted = competition.strip() if isinstance(competition, str) else None
    if wanted in {"", "auto", "current"}:
        wanted = None
    if wanted and wanted not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported competition: {wanted}")

    try:
        iteration_id, resolved_comp, season_label = _pick_vale_iteration(wanted)
    except HTTPException as exc:
        if exc.status_code == 429:
            for path in sorted(TRACKER_CACHE_DIR.glob(f"tracker-v{TRACKER_CACHE_VERSION}-*.json"), reverse=True):
                try:
                    iid = int(path.stem.split("-")[-1])
                except ValueError:
                    continue
                stale = _read_tracker_cache(iid, allow_stale=True)
                if stale is not None:
                    stale = {**stale, "source_note": (stale.get("source_note") or "") + " · cached (rate limited)"}
                    return stale
        raise

    if not iteration_id:
        raise HTTPException(status_code=404, detail="No season found for Port Vale.")

    if not force_refresh:
        cached = _read_tracker_cache(iteration_id)
        if cached is not None:
            return cached

    try:
        payload = _assemble_tracker(
            iteration_id=iteration_id,
            competition=resolved_comp,
            season_label=season_label,
            force_refresh=force_refresh,
        )
    except HTTPException as exc:
        if exc.status_code == 429:
            stale = _read_tracker_cache(iteration_id, allow_stale=True)
            if stale is not None:
                note = stale.get("source_note") or ""
                if "rate limited" not in note:
                    stale = {**stale, "source_note": f"{note} · cached (rate limited)".strip(" ·")}
                return stale
        raise

    _write_tracker_cache(iteration_id, payload)
    return payload


def register_strategy_tracker_routes(app: FastAPI) -> None:
    @app.get("/strategy-tracker", response_class=HTMLResponse)
    def strategy_tracker_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "strategy-tracker.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Strategy tracker UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/strategy-tracker")
    def strategy_tracker_api(
        refresh: bool = Query(False),
        competition: str = Query(""),
    ) -> dict[str, Any]:
        return build_strategy_tracker(competition=competition, force_refresh=refresh)

    @app.get("/api/strategy-tracker/export-pdf")
    def strategy_tracker_export_pdf(competition: str = Query("")) -> Response:
        from app.strategy_tracker_pdf import build_season_progress_pdf

        payload = build_strategy_tracker(competition=competition, force_refresh=False)
        pdf_bytes = build_season_progress_pdf(payload)
        season = str(payload.get("season") or "season").replace("/", "-")
        comp = str(payload.get("competition") or "league").replace(" ", "-").lower()
        filename = f"season-progress-{comp}-{season}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
