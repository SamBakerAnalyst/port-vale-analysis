from __future__ import annotations

import re
from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, v5_path

SHOT_XG_KPI_ID = 82

_STOPPAGE_RE = re.compile(r"\(\+(\d+):(\d+(?:\.\d+)?)\)")
_CLOCK_RE = re.compile(r"(\d+):(\d+(?:\.\d+)?)")


def parse_impect_minute(game_time: dict[str, Any]) -> float:
    """Convert Impect gameTime to continuous match minutes (supports 45+ / 90+)."""
    gt_str = str(game_time.get("gameTime") or "")
    stoppage = _STOPPAGE_RE.search(gt_str)
    if stoppage:
        base_minute = 90 if gt_str.startswith("90:") else 45
        extra = int(stoppage.group(1)) + float(stoppage.group(2)) / 60.0
        return base_minute + extra

    clock = _CLOCK_RE.match(gt_str)
    if clock:
        return int(clock.group(1)) + float(clock.group(2)) / 60.0

    seconds = float(game_time.get("gameTimeInSec") or 0)
    if seconds >= 10000:
        return (seconds - 10000) / 60.0 + 45.0
    return seconds / 60.0


def impect_seconds_to_minute(seconds: float) -> float:
    """Legacy helper — prefer parse_impect_minute when gameTime dict is available."""
    if seconds >= 10000:
        return (seconds - 10000) / 60.0 + 45.0
    return seconds / 60.0


def _is_first_half(game_time: dict[str, Any]) -> bool:
    gt_str = str(game_time.get("gameTime") or "")
    if "(+" in gt_str and gt_str.startswith("45:"):
        return True
    seconds = float(game_time.get("gameTimeInSec") or 0)
    return seconds < 10000


def _compute_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    fh_stoppage = 0.0
    sh_stoppage = 0.0
    max_fh_minute = 0.0
    max_sh_minute = 45.0

    for event in events:
        game_time = event.get("gameTime") or {}
        if not isinstance(game_time, dict):
            continue
        gt_str = str(game_time.get("gameTime") or "")
        minute = parse_impect_minute(game_time)
        seconds = float(game_time.get("gameTimeInSec") or 0)

        if "(+" in gt_str and gt_str.startswith("45:"):
            fh_stoppage = max(fh_stoppage, minute - 45.0)
            max_fh_minute = max(max_fh_minute, minute)
        elif "(+" in gt_str and gt_str.startswith("90:"):
            sh_stoppage = max(sh_stoppage, minute - 90.0)
            max_sh_minute = max(max_sh_minute, minute)
        elif _is_first_half(game_time):
            max_fh_minute = max(max_fh_minute, min(minute, 45.0))
        elif seconds >= 10000:
            max_sh_minute = max(max_sh_minute, minute)

    first_half_end = round(45.0 + fh_stoppage, 2) if fh_stoppage > 0.01 else 45.0
    if fh_stoppage > 0.01:
        first_half_end = round(max(first_half_end, max_fh_minute), 2)

    second_half_end = round(90.0 + sh_stoppage, 2) if sh_stoppage > 0.01 else 90.0
    if sh_stoppage > 0.01:
        second_half_end = round(max(second_half_end, max_sh_minute), 2)
    else:
        second_half_end = round(max(90.0, max_sh_minute), 2)

    return {
        "firstHalfEnd": first_half_end,
        "firstHalfStoppageMinutes": round(fh_stoppage, 2),
        "hasFirstHalfStoppage": fh_stoppage > 0.01,
        "secondHalfStart": 45.0,
        "secondHalfEnd": second_half_end,
        "secondHalfStoppageMinutes": round(sh_stoppage, 2),
        "hasSecondHalfStoppage": sh_stoppage > 0.01,
    }


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    if isinstance(events_payload, dict) and isinstance(events_payload.get("data"), list):
        return events_payload["data"]
    return extract_rows(events_payload)


def _fetch_shots_with_xg(match_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = _fetch_match_events(match_id)

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    xg_by_event: dict[int, float] = {}
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            if row.get("kpiId") == SHOT_XG_KPI_ID and row.get("eventId") is not None:
                try:
                    event_id = int(row["eventId"])
                    xg_by_event[event_id] = xg_by_event.get(event_id, 0.0) + float(
                        row.get("value") or 0
                    )
                except (TypeError, ValueError):
                    continue

    shots: list[dict[str, Any]] = []
    for event in events:
        if event.get("actionType") != "SHOT":
            continue
        event_id = event.get("id")
        game_time = event.get("gameTime") or {}
        if not isinstance(game_time, dict):
            continue
        try:
            seconds = float(game_time.get("gameTimeInSec") or 0)
            squad_id = int(event.get("squadId") or 0)
        except (TypeError, ValueError):
            continue
        minute = round(parse_impect_minute(game_time), 2)
        shots.append(
            {
                "eventId": int(event_id) if event_id is not None else None,
                "squadId": squad_id,
                "minute": minute,
                "seconds": seconds,
                "isFirstHalf": _is_first_half(game_time),
                "xg": xg_by_event.get(int(event_id), 0.0) if event_id is not None else 0.0,
                "isGoal": str(event.get("result") or "").upper() == "SUCCESS",
                "action": event.get("action"),
            }
        )

    shots.sort(key=lambda row: (row["seconds"], row.get("eventId") or 0))
    return shots, events


def _cumulative_series(
    shots: list[dict[str, Any]],
    squad_id: int,
    timeline: dict[str, Any],
) -> list[dict[str, Any]]:
    squad_shots = [s for s in shots if s["squadId"] == squad_id]
    first_half_end = float(timeline["firstHalfEnd"])
    second_half_start = float(timeline["secondHalfStart"])
    second_half_end = float(timeline["secondHalfEnd"])

    fh_shots = [s for s in squad_shots if s.get("isFirstHalf")]
    sh_shots = [s for s in squad_shots if not s.get("isFirstHalf")]

    cumulative = 0.0
    series: list[dict[str, Any]] = [{"minute": 0.0, "xg": 0.0, "isGoal": False, "half": "first"}]

    for shot in fh_shots:
        cumulative += float(shot["xg"])
        series.append(
            {
                "minute": shot["minute"],
                "xg": round(cumulative, 4),
                "isGoal": shot["isGoal"],
                "eventId": shot.get("eventId"),
                "half": "first",
            }
        )

    fh_total = round(cumulative, 4)
    if not series or series[-1]["minute"] < first_half_end:
        series.append({"minute": first_half_end, "xg": fh_total, "isGoal": False, "half": "first"})

    if not sh_shots:
        if series[-1]["minute"] < second_half_end:
            series.append(
                {"minute": second_half_end, "xg": fh_total, "isGoal": False, "half": "second"}
            )
        return series

    series.append(
        {"minute": second_half_start, "xg": fh_total, "isGoal": False, "half": "second"}
    )

    for shot in sh_shots:
        cumulative += float(shot["xg"])
        series.append(
            {
                "minute": shot["minute"],
                "xg": round(cumulative, 4),
                "isGoal": shot["isGoal"],
                "eventId": shot.get("eventId"),
                "half": "second",
            }
        )

    final_xg = round(cumulative, 4)
    if series[-1]["minute"] < second_half_end:
        series.append(
            {"minute": second_half_end, "xg": final_xg, "isGoal": False, "half": "second"}
        )

    return series


def build_xg_race(
    match_id: int,
    home_squad_id: int,
    away_squad_id: int,
    home_name: str | None = None,
    away_name: str | None = None,
) -> dict[str, Any]:
    shots, events = _fetch_shots_with_xg(match_id)
    timeline = _compute_timeline(events)
    home_series = _cumulative_series(shots, home_squad_id, timeline)
    away_series = _cumulative_series(shots, away_squad_id, timeline)

    home_goals = [
        {"minute": p["minute"], "xg": p["xg"]}
        for p in home_series
        if p.get("isGoal")
    ]
    away_goals = [
        {"minute": p["minute"], "xg": p["xg"]}
        for p in away_series
        if p.get("isGoal")
    ]

    return {
        "title": "Shot-based xG",
        "kpiId": SHOT_XG_KPI_ID,
        "timeline": timeline,
        "home": {
            "squadId": home_squad_id,
            "name": home_name,
            "color": "#3b82f6",
            "series": home_series,
            "goals": home_goals,
            "totalXg": home_series[-1]["xg"] if home_series else 0,
        },
        "away": {
            "squadId": away_squad_id,
            "name": away_name,
            "color": "#22c55e",
            "series": away_series,
            "goals": away_goals,
            "totalXg": away_series[-1]["xg"] if away_series else 0,
        },
        "shots": shots,
    }
