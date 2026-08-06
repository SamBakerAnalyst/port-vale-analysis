"""League Two Strategy Tracker — live Port Vale pace vs promotion report benchmarks."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.club_strategy import (
    DEFAULT_COMPETITION,
    LEAGUE_MATCH_LIMIT,
    _competition_iterations,
    _disk_cache_path,
    _is_focus_squad,
    _league_matches,
    _read_disk_cache,
    _season_label,
    build_club_strategy_report,
)
from app.paths import CACHE_ROOT, CLUB_STRATEGY_CACHE_DIR
from app.scouting import SCOUTING_DIR

# Multi-season Strategy Report averages (League Two top-seven finishers).
# Champ = 1st · Auto = avg of 2nd+3rd · Play-off = avg of 4th–7th.
REPORT_BENCHMARKS: dict[str, dict[str, float]] = {
    "points": {"champion": 87.6, "auto": 83.2, "playoff": 75.9},
    "goals_for": {"champion": 75.2, "auto": 71.9, "playoff": 69.2},
    "goals_against": {"champion": 44.4, "auto": 43.9, "playoff": 51.8},
    "home_wins": {"champion": 14.0, "auto": 14.5, "playoff": 11.6},
    "away_wins": {"champion": 11.2, "auto": 8.9, "playoff": 9.6},
    "clean_sheets": {"champion": 18.0, "auto": 17.0, "playoff": 15.0},
    "back_to_backs": {"champion": 9.2, "auto": 7.6, "playoff": 6.3},
    "max_win_streak": {"champion": 7.2, "auto": 4.8, "playoff": 4.6},
}

METRIC_META: dict[str, dict[str, Any]] = {
    "points": {
        "label": "Points",
        "unit": "pts",
        "lower_is_better": False,
        "project": True,
    },
    "goals_for": {
        "label": "Goals scored",
        "unit": "goals",
        "lower_is_better": False,
        "project": True,
    },
    "goals_against": {
        "label": "Goals conceded",
        "unit": "goals",
        "lower_is_better": True,
        "project": True,
    },
    "home_wins": {
        "label": "Home wins",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
    },
    "away_wins": {
        "label": "Away wins",
        "unit": "wins",
        "lower_is_better": False,
        "project": True,
    },
    "clean_sheets": {
        "label": "Clean sheets",
        "unit": "CS",
        "lower_is_better": False,
        "project": True,
    },
    "back_to_backs": {
        "label": "Back-to-back win pairs",
        "unit": "pairs",
        "lower_is_better": False,
        "project": False,
    },
    "max_win_streak": {
        "label": "Longest winning run",
        "unit": "wins",
        "lower_is_better": False,
        "project": False,
    },
}

_cache: dict[int, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 900
TRACKER_CACHE_DIR = CACHE_ROOT / "strategy-tracker"
TRACKER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
    return TRACKER_CACHE_DIR / f"tracker-{iteration_id}.json"


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


def _vale_match_progress(iteration_id: int, squad_id: int) -> dict[str, Any]:
    matches = _league_matches(iteration_id)
    results: list[str] = []
    points_series: list[dict[str, Any]] = []
    home_wins = away_wins = clean_sheets = 0
    goals_for = goals_against = points = 0
    played = 0

    for match in matches:
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        if squad_id not in (home_id, away_id):
            continue
        goals = match.get("goals") or {}
        home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
        away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
        is_home = squad_id == home_id
        scored = home_goals if is_home else away_goals
        conceded = away_goals if is_home else home_goals
        if scored > conceded:
            result = "W"
            points += 3
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
        points_series.append(
            {
                "played": played,
                "points": points,
                "result": result,
                "date": str(match.get("scheduledDate") or "")[:10],
            }
        )

    streaks = _streak_stats(results)
    return {
        "played": played,
        "points": points,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "clean_sheets": clean_sheets,
        "back_to_backs": streaks["back_to_backs"],
        "max_win_streak": streaks["max_win_streak"],
        "results": results,
        "points_series": points_series,
    }


def _metric_card(
    key: str,
    current: float,
    played: int,
) -> dict[str, Any]:
    meta = METRIC_META[key]
    bench = REPORT_BENCHMARKS[key]
    projected = _project(current, played) if meta["project"] else None
    compare = projected if projected is not None else current
    status = _status(compare, bench["auto"], lower_is_better=meta["lower_is_better"])
    return {
        "id": key,
        "label": meta["label"],
        "unit": meta["unit"],
        "lower_is_better": meta["lower_is_better"],
        "project": meta["project"],
        "current": current,
        "projected": projected,
        "compare": compare,
        "benchmarks": bench,
        "status": status,
        "delta_vs_auto": round(compare - bench["auto"], 1),
    }


def _pick_from_disk_reports() -> tuple[int, str | None] | None:
    """Newest League Two + Vale season from club-strategy disk cache (no Impect)."""
    candidates: list[tuple[str, int, str | None]] = []
    cache_dir = CLUB_STRATEGY_CACHE_DIR
    for path in cache_dir.glob("report-v2-*.json"):
        try:
            iteration_id = int(path.stem.rsplit("-", 1)[-1])
        except ValueError:
            continue
        report = _read_report_cheap(iteration_id)
        if report is None:
            continue
        if str(report.get("competition") or "").strip() != "League Two":
            continue
        if not _report_has_vale(report):
            continue
        season = str(report.get("season") or "")
        candidates.append((season, iteration_id, _season_label(season) or season or None))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, iteration_id, label = candidates[0]
    return iteration_id, label


def _pick_league_two_iteration() -> tuple[int, str | None]:
    """Prefer newest League Two season that includes Port Vale — disk-first, no meta probe."""
    disk_pick = _pick_from_disk_reports()
    if disk_pick is not None:
        return disk_pick

    try:
        seasons = _competition_iterations("League Two")[:6]
    except HTTPException:
        raise

    # Live fallback: only build until we find Vale (newest first).
    for season in seasons:
        try:
            iteration_id = int(season.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if iteration_id <= 0:
            continue
        label = _season_label(str(season.get("season") or "")) or season.get("season")
        try:
            report = build_club_strategy_report(iteration_id)
        except HTTPException:
            continue
        if _report_has_vale(report):
            return iteration_id, str(label) if label else None

    if seasons:
        first = seasons[0]
        return int(first.get("id") or 0), _season_label(str(first.get("season") or ""))
    return 0, None


def _assemble_tracker(
    *,
    iteration_id: int,
    season_label: str | None,
    force_refresh: bool,
) -> dict[str, Any]:
    report = build_club_strategy_report(iteration_id, force_refresh=force_refresh)
    standings = report.get("standings") or []
    vale_row = next((row for row in standings if row.get("focus")), None)
    if vale_row is None:
        vale_row = next(
            (row for row in standings if _is_focus_squad(str(row.get("club") or ""))),
            None,
        )
    if vale_row is None:
        raise HTTPException(
            status_code=404,
            detail="Port Vale not found in a League Two season yet. Tracker unlocks once Vale league fixtures are in Impect.",
        )

    squad_id = int(vale_row.get("squad_id") or 0)
    try:
        progress = _vale_match_progress(iteration_id, squad_id)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        # Standings-only fallback so the page still renders while Impect cools down.
        played = int(vale_row.get("played") or 0)
        points = float(vale_row.get("points") or 0)
        known = _KNOWN_SEASON_EXTRAS.get(iteration_id, {})
        progress = {
            "played": played,
            "points": points,
            "goals_for": float(vale_row.get("goals_for") or 0),
            "goals_against": float(vale_row.get("goals_against") or 0),
            "home_wins": float(known.get("home_wins") or 0),
            "away_wins": float(known.get("away_wins") or 0),
            "clean_sheets": float(known.get("clean_sheets") or 0),
            "back_to_backs": int(known.get("back_to_backs") or 0),
            "max_win_streak": int(known.get("max_win_streak") or 0),
            "results": [],
            "points_series": (
                [{"played": played, "points": points, "result": "", "date": ""}]
                if played
                else []
            ),
        }
    played = int(progress["played"] or vale_row.get("played") or 0)

    metrics = [
        _metric_card("points", float(progress["points"]), played),
        _metric_card("goals_for", float(progress["goals_for"]), played),
        _metric_card("goals_against", float(progress["goals_against"]), played),
        _metric_card("home_wins", float(progress["home_wins"]), played),
        _metric_card("away_wins", float(progress["away_wins"]), played),
        _metric_card("clean_sheets", float(progress["clean_sheets"]), played),
        _metric_card("back_to_backs", float(progress["back_to_backs"]), played),
        _metric_card("max_win_streak", float(progress["max_win_streak"]), played),
    ]

    points_metric = metrics[0]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "competition": "League Two",
        "season": report.get("season") or season_label,
        "iteration_id": iteration_id,
        "club": vale_row.get("club") or "Port Vale",
        "position": vale_row.get("position"),
        "played": played,
        "games_remaining": max(0, LEAGUE_MATCH_LIMIT - played),
        "summary": {
            "status": points_metric["status"],
            "projected_points": points_metric["projected"],
            "auto_target": REPORT_BENCHMARKS["points"]["auto"],
            "champion_target": REPORT_BENCHMARKS["points"]["champion"],
            "playoff_target": REPORT_BENCHMARKS["points"]["playoff"],
            "delta_vs_auto": points_metric["delta_vs_auto"],
        },
        "benchmarks": REPORT_BENCHMARKS,
        "metrics": metrics,
        "points_series": progress["points_series"],
        "source_note": (
            "Live Impect league matches · benchmarks from League Two Strategy Report "
            "(champ / auto / play-off multi-season averages)"
        ),
    }


def build_strategy_tracker(
    *,
    competition: str = DEFAULT_COMPETITION,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if competition != "League Two":
        raise HTTPException(status_code=400, detail="Strategy tracker is League Two only.")

    # Resolve season without club_strategy_meta (that probes every season's matches).
    try:
        iteration_id, season_label = _pick_league_two_iteration()
    except HTTPException as exc:
        # If iterations list itself is rate-limited, fall back to any disk tracker.
        if exc.status_code == 429:
            for path in sorted(TRACKER_CACHE_DIR.glob("tracker-*.json"), reverse=True):
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
        raise HTTPException(status_code=404, detail="No League Two season found.")

    if not force_refresh:
        cached = _read_tracker_cache(iteration_id)
        if cached is not None:
            return cached

    try:
        payload = _assemble_tracker(
            iteration_id=iteration_id,
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
        competition: str = Query(DEFAULT_COMPETITION),
    ) -> dict[str, Any]:
        return build_strategy_tracker(competition=competition, force_refresh=refresh)
