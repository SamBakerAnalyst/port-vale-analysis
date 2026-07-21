from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from app.paths import CLUB_STRATEGY_CACHE_DIR
from app.scouting import SCOUTING_DIR

COMPETITIONS = ("League One", "League Two")
DEFAULT_COMPETITION = "League Two"
FOCUS_SQUAD_TOKENS = ("port vale",)
LEAGUE_MATCH_LIMIT = 46
CACHE_TTL_SECONDS = 1800
DISK_CACHE_DIR = CLUB_STRATEGY_CACHE_DIR
DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)

SQUAD_SCORE_XPOINTS = 99

KPI_SHOTS = "SHOT_AT_GOAL_NUMBER"
KPI_SOT = "SHOT_AT_GOAL_NUMBER_ON_TARGET"
KPI_XG_FOR = "SHOT_XG"
KPI_XG_AGAINST = "CONCEDED_SHOT_XG"

TIME_BUCKETS: tuple[str, ...] = (
    "0-15",
    "16-30",
    "31-45",
    "45+",
    "45-60",
    "61-75",
    "76-90",
    "90+",
    "unknown",
)

TIME_BUCKET_LABELS: dict[str, str] = {
    "0-15": "0–15",
    "16-30": "16–30",
    "31-45": "31–45",
    "45+": "1H added",
    "45-60": "45–60",
    "61-75": "61–75",
    "76-90": "76–90",
    "90+": "2H added",
    "unknown": "Unknown",
}

_STOPPAGE_RE = re.compile(r"\(\+(\d+):(\d+(?:\.\d+)?)\)")
_MATCH_CLOCK_RE = re.compile(r"^(\d+):(\d+(?:\.\d+)?)")

_report_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_first_goal_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_match_events_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}


def _impect():
    from app import main as impect_main

    return impect_main


def _unwrap_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        nested = raw.get("data")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _is_focus_squad(name: str) -> bool:
    lowered = str(name or "").casefold().replace(".", "")
    return any(token in lowered for token in FOCUS_SQUAD_TOKENS)


def _is_league_match(match: dict[str, Any], competition: str) -> bool:
    match_day = match.get("matchDay")
    label = match_day.get("name") if isinstance(match_day, dict) else str(match_day or "")
    text = str(label)
    if competition not in text:
        return False
    lowered = text.lower()
    return "play-off" not in lowered and "playoff" not in lowered and "relegation" not in lowered


def _match_sort_key(match: dict[str, Any]) -> tuple[str, int, int]:
    match_day = match.get("matchDay")
    day_index = match_day.get("index") if isinstance(match_day, dict) else match_day
    return (
        str(match.get("scheduledDate") or ""),
        int(day_index) if day_index is not None else 0,
        int(match.get("id") or 0),
    )


def _match_is_complete(match: dict[str, Any]) -> bool:
    goals = match.get("goals") or {}
    home_goals = (goals.get("home") or {}).get("fullTime")
    away_goals = (goals.get("away") or {}).get("fullTime")
    return home_goals is not None and away_goals is not None


def _competition_iterations(competition: str) -> list[dict[str, Any]]:
    if competition not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported competition: {competition}")
    impect = _impect()
    rows = [
        item
        for item in impect._fetch_iterations()
        if str(item.get("competition_name") or "").strip() == competition
    ]
    rows.sort(key=lambda item: str(item.get("season") or ""), reverse=True)
    return rows


def _resolve_iteration(iteration_id: int) -> dict[str, Any]:
    impect = _impect()
    for item in impect._fetch_iterations():
        if int(item.get("id") or 0) != iteration_id:
            continue
        competition = str(item.get("competition_name") or "").strip()
        if competition not in COMPETITIONS:
            raise HTTPException(
                status_code=404,
                detail=f"Iteration {iteration_id} is not a supported league.",
            )
        return item
    raise HTTPException(status_code=404, detail="Season not found.")


def _squads_map(iteration_id: int) -> dict[int, str]:
    impect = _impect()
    rows = _unwrap_items(impect._impect_get(impect._squads_path(iteration_id))["data"])
    return {
        int(item["id"]): str(item.get("name") or "")
        for item in rows
        if item.get("id") is not None
    }


def _league_matches(iteration_id: int, competition: str | None = None) -> list[dict[str, Any]]:
    if competition is None:
        competition = str(_resolve_iteration(iteration_id).get("competition_name") or "").strip()
    impect = _impect()
    matches = _unwrap_items(
        impect._impect_get(f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches")["data"]
    )
    rows = [
        match
        for match in matches
        if match.get("available") is not False
        and _is_league_match(match, competition)
        and _match_is_complete(match)
    ]
    rows.sort(key=_match_sort_key)
    return rows


def _squad_kpi_table(iteration_id: int) -> dict[int, dict[str, float]]:
    from app.pre_match import _squad_kpi_table

    return _squad_kpi_table(iteration_id)


def _iteration_xpoints(iteration_id: int) -> dict[int, float]:
    impect = _impect()
    raw = impect._impect_get(
        f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/squad-scores"
    )["data"]
    rows = raw if isinstance(raw, list) else _unwrap_items(raw)
    out: dict[int, float] = {}
    for row in rows:
        squad_id = row.get("squadId")
        if squad_id is None:
            continue
        for score in row.get("squadScores") or []:
            if int(score.get("squadScoreId") or -1) == SQUAD_SCORE_XPOINTS:
                out[int(squad_id)] = float(score.get("value") or 0.0)
                break
    return out


def _build_standings(iteration_id: int) -> list[dict[str, Any]]:
    squads = _squads_map(iteration_id)
    kpi_table = _squad_kpi_table(iteration_id)
    xppg_map = _iteration_xpoints(iteration_id)

    table: dict[int, dict[str, Any]] = {
        squad_id: {
            "squad_id": squad_id,
            "club": name,
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
            "clean_sheets": 0,
        }
        for squad_id, name in squads.items()
    }

    for match in _league_matches(iteration_id):
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        if home_id <= 0 or away_id <= 0:
            continue
        goals = match.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)

        for squad_id in (home_id, away_id):
            table.setdefault(
                squad_id,
                {
                    "squad_id": squad_id,
                    "club": squads.get(squad_id, f"Squad {squad_id}"),
                    "played": 0,
                    "won": 0,
                    "drawn": 0,
                    "lost": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "points": 0,
                    "clean_sheets": 0,
                },
            )

        table[home_id]["played"] += 1
        table[away_id]["played"] += 1
        table[home_id]["goals_for"] += home_goals
        table[home_id]["goals_against"] += away_goals
        table[away_id]["goals_for"] += away_goals
        table[away_id]["goals_against"] += home_goals

        # Clean sheet = did not concede (home: away scored 0; away: home scored 0).
        if away_goals == 0:
            table[home_id]["clean_sheets"] += 1
        if home_goals == 0:
            table[away_id]["clean_sheets"] += 1

        if home_goals > away_goals:
            table[home_id]["won"] += 1
            table[home_id]["points"] += 3
            table[away_id]["lost"] += 1
        elif away_goals > home_goals:
            table[away_id]["won"] += 1
            table[away_id]["points"] += 3
            table[home_id]["lost"] += 1
        else:
            table[home_id]["drawn"] += 1
            table[away_id]["drawn"] += 1
            table[home_id]["points"] += 1
            table[away_id]["points"] += 1

    rows: list[dict[str, Any]] = []
    for squad_id, row in table.items():
        played = int(row["played"])
        if played <= 0:
            continue
        stats = kpi_table.get(squad_id, {})
        shots_pg = float(stats.get(KPI_SHOTS) or 0.0)
        sot_pg = float(stats.get(KPI_SOT) or 0.0)
        xg_for_pg = float(stats.get(KPI_XG_FOR) or 0.0)
        xg_against_pg = float(stats.get(KPI_XG_AGAINST) or 0.0)
        shots = round(shots_pg * played)
        sot = round(sot_pg * played)
        xg_for = round(xg_for_pg * played, 1)
        xg_against = round(xg_against_pg * played, 1)
        points = int(row["points"])
        ppg = round(points / played, 2)
        xppg = round(xppg_map.get(squad_id, 0.0), 2)
        xpoints = round(xppg * played, 1)
        rows.append(
            {
                **row,
                "goal_difference": int(row["goals_for"]) - int(row["goals_against"]),
                "shots": shots,
                "sot": sot,
                "sot_pct": round((sot / shots) * 100, 1) if shots else 0.0,
                "clean_sheet_pct": round((int(row["clean_sheets"]) / played) * 100, 1),
                "ppg": ppg,
                "ppg_x46": round(ppg * 46, 2),
                "xg_for": xg_for,
                "xg_against": xg_against,
                "xg_difference": round(xg_for - xg_against, 1),
                "xppg": xppg,
                "xppg_x46": round(xppg * 46, 2),
                "xpoints": xpoints,
                "xp_vs_actual": round(points - xpoints, 2),
                "focus": _is_focus_squad(str(row["club"])),
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row["points"]),
            -int(row["goal_difference"]),
            -int(row["goals_for"]),
            str(row["club"]).casefold(),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["position"] = index
    return rows


def _match_minute_from_event(event: dict[str, Any]) -> float:
    """Parse Impect match clock, including stoppage e.g. 45:00.0 (+2:13.0)."""
    game_time = event.get("gameTime") or {}
    text = str(game_time.get("gameTime") or "").strip()
    stoppage = _STOPPAGE_RE.search(text)
    if stoppage:
        base_minute = 90.0 if text.startswith("90:") else 45.0
        return base_minute + int(stoppage.group(1)) + float(stoppage.group(2)) / 60.0

    match = _MATCH_CLOCK_RE.match(text)
    if match:
        return int(match.group(1)) + float(match.group(2)) / 60.0

    seconds = float(game_time.get("gameTimeInSec") or 0.0)
    if seconds >= 10000:
        return (seconds - 10000) / 60.0 + 45.0
    minute = seconds / 60.0
    if 0 < minute <= 130:
        return minute
    return 0.0


def _is_first_half_event(event: dict[str, Any]) -> bool:
    game_time = event.get("gameTime") or {}
    text = str(game_time.get("gameTime") or "")
    if "(+" in text and text.startswith("45:"):
        return True
    if "(+" in text and text.startswith("90:"):
        return False
    seconds = float(game_time.get("gameTimeInSec") or 0.0)
    return seconds < 10000


def _minute_bucket_for_event(event: dict[str, Any]) -> tuple[str, str, float]:
    """Return (bucket, half, minute)."""
    game_time = event.get("gameTime") or {}
    text = str(game_time.get("gameTime") or "")
    minute = _match_minute_from_event(event)
    first_half = _is_first_half_event(event)
    half = "first_half" if first_half else "second_half"

    if _STOPPAGE_RE.search(text):
        if text.startswith("90:") or not first_half:
            return "90+", half, minute
        return "45+", half, minute

    if first_half:
        if minute <= 15:
            return "0-15", half, minute
        if minute <= 30:
            return "16-30", half, minute
        return "31-45", half, minute

    # Second-half regulation clock is usually 45–90.
    if minute <= 60:
        return "45-60", half, minute
    if minute <= 75:
        return "61-75", half, minute
    if minute <= 90:
        return "76-90", half, minute
    return "90+", half, minute


def _goal_events_for_match(match_id: int, *, retries: int = 3) -> list[dict[str, Any]]:
    cached = _match_events_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    impect = _impect()
    last_error: Exception | None = None
    events: list[dict[str, Any]] = []
    for attempt in range(retries):
        try:
            raw = impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{match_id}/events")["data"]
            if isinstance(raw, dict) and isinstance(raw.get("data"), list):
                raw = raw["data"]
            events = raw if isinstance(raw, list) else _unwrap_items(raw)
            break
        except Exception as exc:  # noqa: BLE001 - retry transient Impect failures
            last_error = exc
            time.sleep(0.4 * (attempt + 1))
    if last_error is not None and not events:
        raise last_error

    goals = [
        event
        for event in events
        if isinstance(event, dict)
        and (
            (event.get("actionType") == "SHOT" and event.get("result") == "SUCCESS")
            or event.get("actionType") == "GOAL"
        )
    ]
    goals.sort(
        key=lambda event: (
            _match_minute_from_event(event),
            float((event.get("gameTime") or {}).get("gameTimeInSec") or 0.0),
            int(event.get("id") or 0),
        )
    )
    _match_events_cache[match_id] = (time.time(), goals)
    return goals


def _infer_first_scorer_from_scoreline(match: dict[str, Any]) -> dict[str, Any] | None:
    """When events are missing, infer first scorer from HT/FT if unambiguous."""
    goals = match.get("goals") or {}
    home = goals.get("home") or {}
    away = goals.get("away") or {}
    if home.get("fullTime") is None or away.get("fullTime") is None:
        return None
    ft_h = int(home.get("fullTime") or 0)
    ft_a = int(away.get("fullTime") or 0)
    ht_h = int(home.get("halfTime") or 0)
    ht_a = int(away.get("halfTime") or 0)
    home_id = int(match.get("homeSquadId") or 0)
    away_id = int(match.get("awaySquadId") or 0)

    if ft_h == 0 and ft_a == 0:
        return {"type": "nil_nil"}

    if ht_h > 0 and ht_a == 0:
        return {"type": "scored", "squad_id": home_id, "half": "first_half", "bucket": "unknown"}
    if ht_a > 0 and ht_h == 0:
        return {"type": "scored", "squad_id": away_id, "half": "first_half", "bucket": "unknown"}
    if ht_h == 0 and ht_a == 0:
        if ft_h > 0 and ft_a == 0:
            return {"type": "scored", "squad_id": home_id, "half": "second_half", "bucket": "unknown"}
        if ft_a > 0 and ft_h == 0:
            return {"type": "scored", "squad_id": away_id, "half": "second_half", "bucket": "unknown"}
    return None


def _empty_first_goal_row(squad_id: int, club: str) -> dict[str, Any]:
    return {
        "squad_id": squad_id,
        "club": club,
        "focus": _is_focus_squad(club),
        "fg_scored": 0,
        "nil_nil": 0,
        "fg_conceded": 0,
        "fgs_w": 0,
        "fgs_d": 0,
        "fgs_l": 0,
        "fgc_w": 0,
        "fgc_d": 0,
        "fgc_l": 0,
        "fgs_ppg": 0.0,
        "fgc_ppg": 0.0,
        "fgs_w_pct": 0.0,
        "fgs_d_pct": 0.0,
        "fgs_l_pct": 0.0,
        "fgc_w_pct": 0.0,
        "fgc_d_pct": 0.0,
        "fgc_l_pct": 0.0,
        "fg_scored_times": _empty_timing_block(),
        "fg_conceded_times": _empty_timing_block(),
    }


def _empty_timing_block() -> dict[str, Any]:
    return {
        "total": 0,
        "home": 0,
        "away": 0,
        "first_half": 0,
        "second_half": 0,
        "buckets": {label: {"total": 0, "home": 0, "away": 0} for label in TIME_BUCKETS},
    }


def _apply_first_goal_outcome(
    stats: dict[int, dict[str, Any]],
    *,
    home_id: int,
    away_id: int,
    first_squad: int,
    home_goals: int,
    away_goals: int,
    half: str,
    bucket: str,
) -> None:
    for squad_id, is_home in ((home_id, True), (away_id, False)):
        if squad_id not in stats:
            continue
        row = stats[squad_id]
        scored_first = first_squad == squad_id
        gf = home_goals if is_home else away_goals
        ga = away_goals if is_home else home_goals
        if gf > ga:
            outcome = "w"
        elif gf < ga:
            outcome = "l"
        else:
            outcome = "d"

        if scored_first:
            row["fg_scored"] += 1
            row[f"fgs_{outcome}"] += 1
            timing = row["fg_scored_times"]
        else:
            row["fg_conceded"] += 1
            row[f"fgc_{outcome}"] += 1
            timing = row["fg_conceded_times"]

        timing["total"] += 1
        timing[half] += 1
        side = "home" if is_home else "away"
        timing[side] += 1
        bucket_key = bucket if bucket in timing["buckets"] else "unknown"
        timing["buckets"][bucket_key]["total"] += 1
        timing["buckets"][bucket_key][side] += 1


def _build_first_goal_stats(iteration_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    squads = _squads_map(iteration_id)
    stats: dict[int, dict[str, Any]] = {
        squad_id: _empty_first_goal_row(squad_id, name) for squad_id, name in squads.items()
    }

    matches = _league_matches(iteration_id)
    match_ids = [int(match["id"]) for match in matches if match.get("id") is not None]

    events_by_match: dict[int, list[dict[str, Any]]] = {}
    fetch_errors: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_goal_events_for_match, match_id): match_id for match_id in match_ids}
        for future in as_completed(futures):
            match_id = futures[future]
            try:
                events_by_match[match_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                events_by_match[match_id] = []
                fetch_errors[match_id] = str(exc)

    missing_matches: list[dict[str, Any]] = []

    for match in matches:
        match_id = int(match.get("id") or 0)
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        if match_id <= 0 or home_id <= 0 or away_id <= 0:
            continue

        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        if home_goals is None or away_goals is None:
            continue
        home_goals = int(home_goals)
        away_goals = int(away_goals)

        goal_events = events_by_match.get(match_id) or []
        if not goal_events:
            inferred = _infer_first_scorer_from_scoreline(match)
            if inferred and inferred["type"] == "nil_nil":
                for squad_id in (home_id, away_id):
                    if squad_id in stats:
                        stats[squad_id]["nil_nil"] += 1
                continue
            if inferred and inferred["type"] == "scored":
                _apply_first_goal_outcome(
                    stats,
                    home_id=home_id,
                    away_id=away_id,
                    first_squad=int(inferred["squad_id"]),
                    home_goals=home_goals,
                    away_goals=away_goals,
                    half=str(inferred["half"]),
                    bucket=str(inferred["bucket"]),
                )
                missing_matches.append(
                    {
                        "match_id": match_id,
                        "date": str(match.get("scheduledDate") or "")[:10],
                        "home": squads.get(home_id, f"Squad {home_id}"),
                        "away": squads.get(away_id, f"Squad {away_id}"),
                        "score": f"{home_goals}-{away_goals}",
                        "half_time": (
                            f"{(goals.get('home') or {}).get('halfTime')}-"
                            f"{(goals.get('away') or {}).get('halfTime')}"
                        ),
                        "status": "inferred",
                        "reason": (
                            "No Impect goal events — first scorer inferred from HT/FT "
                            f"({inferred['half']}; minute unknown)"
                        ),
                        "inferred_first_squad": squads.get(int(inferred["squad_id"]), inferred["squad_id"]),
                    }
                )
                continue

            if home_goals == 0 and away_goals == 0:
                for squad_id in (home_id, away_id):
                    if squad_id in stats:
                        stats[squad_id]["nil_nil"] += 1
                continue

            missing_matches.append(
                {
                    "match_id": match_id,
                    "date": str(match.get("scheduledDate") or "")[:10],
                    "home": squads.get(home_id, f"Squad {home_id}"),
                    "away": squads.get(away_id, f"Squad {away_id}"),
                    "score": f"{home_goals}-{away_goals}",
                    "half_time": (
                        f"{(goals.get('home') or {}).get('halfTime')}-"
                        f"{(goals.get('away') or {}).get('halfTime')}"
                    ),
                    "status": "missing",
                    "reason": fetch_errors.get(match_id)
                    or "No goal events in Impect and first scorer cannot be inferred from HT/FT",
                }
            )
            continue

        first_goal = goal_events[0]
        first_squad = int(first_goal.get("squadId") or 0)
        bucket, half, _minute = _minute_bucket_for_event(first_goal)
        if first_squad not in (home_id, away_id):
            missing_matches.append(
                {
                    "match_id": match_id,
                    "date": str(match.get("scheduledDate") or "")[:10],
                    "home": squads.get(home_id, f"Squad {home_id}"),
                    "away": squads.get(away_id, f"Squad {away_id}"),
                    "score": f"{home_goals}-{away_goals}",
                    "reason": f"First goal event squadId={first_squad} not in match",
                }
            )
            continue

        _apply_first_goal_outcome(
            stats,
            home_id=home_id,
            away_id=away_id,
            first_squad=first_squad,
            home_goals=home_goals,
            away_goals=away_goals,
            half=half,
            bucket=bucket,
        )

    rows: list[dict[str, Any]] = []
    for row in stats.values():
        fg_scored = int(row["fg_scored"])
        fg_conceded = int(row["fg_conceded"])
        if fg_scored:
            row["fgs_ppg"] = round((row["fgs_w"] * 3 + row["fgs_d"]) / fg_scored, 2)
            row["fgs_w_pct"] = round((row["fgs_w"] / fg_scored) * 100, 1)
            row["fgs_d_pct"] = round((row["fgs_d"] / fg_scored) * 100, 1)
            row["fgs_l_pct"] = round((row["fgs_l"] / fg_scored) * 100, 1)
        if fg_conceded:
            row["fgc_ppg"] = round((row["fgc_w"] * 3 + row["fgc_d"]) / fg_conceded, 2)
            row["fgc_w_pct"] = round((row["fgc_w"] / fg_conceded) * 100, 1)
            row["fgc_d_pct"] = round((row["fgc_d"] / fg_conceded) * 100, 1)
            row["fgc_l_pct"] = round((row["fgc_l"] / fg_conceded) * 100, 1)
        rows.append(row)

    standings = _build_standings(iteration_id)
    position_by_squad = {row["squad_id"]: row["position"] for row in standings}
    rows.sort(key=lambda row: position_by_squad.get(int(row["squad_id"]), 99))
    for index, row in enumerate(rows, start=1):
        row["position"] = position_by_squad.get(int(row["squad_id"]), index)
    return rows, missing_matches


def _timing_averages(rows: list[dict[str, Any]], timing_key: str) -> dict[str, Any]:
    if not rows:
        return {}
    averages: dict[str, Any] = {}
    for field in ("total", "home", "away", "first_half", "second_half"):
        values = [float((row.get(timing_key) or {}).get(field) or 0.0) for row in rows]
        averages[field] = round(sum(values) / len(values), 2)

    bucket_avgs: dict[str, dict[str, float]] = {}
    for label in TIME_BUCKETS:
        bucket_avgs[label] = {}
        for sub in ("total", "home", "away"):
            values = [
                float(((row.get(timing_key) or {}).get("buckets") or {}).get(label, {}).get(sub) or 0.0)
                for row in rows
            ]
            bucket_avgs[label][sub] = round(sum(values) / len(values), 2)
    averages["buckets"] = bucket_avgs
    return averages


def _first_goal_averages(rows: list[dict[str, Any]]) -> dict[str, Any]:
    base = _averages(
        rows,
        [
            "fg_scored",
            "nil_nil",
            "fg_conceded",
            "fgs_w",
            "fgs_d",
            "fgs_l",
            "fgc_w",
            "fgc_d",
            "fgc_l",
            "fgs_ppg",
            "fgc_ppg",
        ],
    )
    base["fg_scored_times"] = _timing_averages(rows, "fg_scored_times")
    base["fg_conceded_times"] = _timing_averages(rows, "fg_conceded_times")
    return base


def _averages(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, float]:
    if not rows:
        return {key: 0.0 for key in keys}
    out: dict[str, float] = {}
    for key in keys:
        values = [float(row.get(key) or 0.0) for row in rows]
        out[key] = round(sum(values) / len(values), 2)
    return out


def _disk_cache_path(name: str, iteration_id: int) -> Path:
    DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return DISK_CACHE_DIR / f"{name}-{iteration_id}.json"


def _read_disk_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cached_at = float(payload.get("cached_at_epoch") or 0.0)
    if time.time() - cached_at > CACHE_TTL_SECONDS:
        return None
    return payload


def _write_disk_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_club_strategy_report(
    iteration_id: int,
    *,
    include_first_goal: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    memory_key = iteration_id if not include_first_goal else iteration_id + 100000
    if force_refresh:
        _report_cache.pop(memory_key, None)
        _first_goal_cache.pop(iteration_id, None)
        disk_name = "report" if not include_first_goal else "report-full"
        for name in (disk_name, "first-goal"):
            path = _disk_cache_path(name, iteration_id)
            if path.exists():
                path.unlink()

    cached = _report_cache.get(memory_key)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    disk_name = "report" if not include_first_goal else "report-full"
    disk_path = _disk_cache_path(disk_name, iteration_id)
    disk_payload = _read_disk_cache(disk_path)
    if disk_payload is not None:
        _report_cache[memory_key] = (now, disk_payload)
        return disk_payload

    iteration = _resolve_iteration(iteration_id)

    standings = _build_standings(iteration_id)
    numeric_keys = [
        "played",
        "won",
        "drawn",
        "lost",
        "goals_for",
        "goals_against",
        "goal_difference",
        "shots",
        "sot",
        "sot_pct",
        "clean_sheets",
        "clean_sheet_pct",
        "points",
        "ppg",
        "ppg_x46",
        "xg_for",
        "xg_against",
        "xg_difference",
        "xpoints",
        "xppg",
        "xppg_x46",
        "xp_vs_actual",
    ]
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": str(iteration.get("competition_name") or "").strip(),
        "season": iteration.get("season"),
        "iteration_id": iteration_id,
        "standings": standings,
        "averages": _averages(standings, numeric_keys),
        "first_goal": None,
    }

    _write_disk_cache(disk_path, {"cached_at_epoch": time.time(), **payload})
    _report_cache[memory_key] = (time.time(), payload)
    return payload


def build_first_goal_report(iteration_id: int, *, force_refresh: bool = False) -> dict[str, Any]:
    if force_refresh:
        _first_goal_cache.pop(iteration_id, None)
        _match_events_cache.clear()
        disk_path = _disk_cache_path("first-goal", iteration_id)
        if disk_path.exists():
            disk_path.unlink()

    cached = _first_goal_cache.get(iteration_id)
    now = time.time()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    disk_path = _disk_cache_path("first-goal", iteration_id)
    disk_payload = _read_disk_cache(disk_path)
    if disk_payload is not None:
        payload = {key: value for key, value in disk_payload.items() if key != "cached_at_epoch"}
        _first_goal_cache[iteration_id] = (now, payload)
        return payload

    iteration = _resolve_iteration(iteration_id)

    rows, gap_matches = _build_first_goal_stats(iteration_id)
    missing_matches = [row for row in gap_matches if row.get("status") == "missing"]
    inferred_matches = [row for row in gap_matches if row.get("status") == "inferred"]
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": str(iteration.get("competition_name") or "").strip(),
        "season": iteration.get("season"),
        "iteration_id": iteration_id,
        "rows": rows,
        "averages": _first_goal_averages(rows),
        "missing_matches": missing_matches,
        "inferred_matches": inferred_matches,
        "coverage": {
            "matches_total": len(_league_matches(iteration_id)),
            "matches_missing_first_goal": len(missing_matches),
            "matches_inferred_no_event_time": len(inferred_matches),
        },
    }
    _write_disk_cache(disk_path, {"cached_at_epoch": time.time(), **payload})
    _first_goal_cache[iteration_id] = (time.time(), payload)
    return payload


def club_strategy_meta(competition: str = DEFAULT_COMPETITION) -> dict[str, Any]:
    if competition not in COMPETITIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported competition: {competition}")

    seasons = [
        {
            "iteration_id": int(item["id"]),
            "season": str(item.get("season") or ""),
            "label": _season_label(str(item.get("season") or "")),
            "competition": competition,
        }
        for item in _competition_iterations(competition)[:4]
    ]
    default_iteration_id = seasons[0]["iteration_id"] if seasons else None
    for season in seasons:
        if _league_matches(int(season["iteration_id"]), competition):
            default_iteration_id = int(season["iteration_id"])
            break
    return {
        "competition": competition,
        "competitions": [{"id": name, "label": name} for name in COMPETITIONS],
        "focus_club": "Port Vale",
        "default_iteration_id": default_iteration_id,
        "seasons": seasons,
        "tabs": [
            {"id": "standings", "label": "League + Shooting"},
            {"id": "strategy", "label": "Club Strategy (xG)"},
            {"id": "first_goal", "label": "First Goal Outcomes"},
            {"id": "fg_scored_times", "label": "Scored First — Times"},
            {"id": "fg_conceded_times", "label": "Conceded First — Times"},
        ],
    }


def _season_label(season: str) -> str:
    if not season or "-" not in season:
        return season
    start, end = season.split("-", 1)
    return f"{start[2:]}/{end}"


def _export_filename(competition: str, season: str) -> str:
    comp = competition.casefold().replace(" ", "-")
    season_slug = str(season or "season").replace("/", "-")
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"club-strategy-{comp}-{season_slug}-{stamp}.pdf"


def register_club_strategy_routes(app: FastAPI) -> None:
    @app.get("/club-strategy", response_class=HTMLResponse)
    def club_strategy_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "club-strategy.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Club strategy UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/club-strategy/meta")
    def club_strategy_meta_route(
        competition: str = Query(DEFAULT_COMPETITION),
    ) -> dict[str, Any]:
        return club_strategy_meta(competition)

    @app.get("/api/club-strategy/report")
    def club_strategy_report_route(
        iteration_id: int = Query(..., ge=1),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        return build_club_strategy_report(iteration_id, force_refresh=refresh)

    @app.get("/api/club-strategy/first-goal")
    def club_strategy_first_goal_route(
        iteration_id: int = Query(..., ge=1),
        refresh: bool = Query(False),
    ) -> dict[str, Any]:
        return build_first_goal_report(iteration_id, force_refresh=refresh)

    @app.get("/api/club-strategy/export-pdf")
    def club_strategy_export_pdf_route(
        iteration_id: int = Query(..., ge=1),
    ) -> Response:
        from app.club_strategy_pdf import build_club_strategy_pdf

        try:
            pdf_bytes, meta = build_club_strategy_pdf(iteration_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        filename = _export_filename(
            str(meta.get("competition") or "league"),
            str(meta.get("season") or "season"),
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
