from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids
from app.post_match.xg_race import impect_seconds_to_minute

FINAL_THIRD_POSITIONS = frozenset({"FINAL_THIRD", "OPPONENT_BOX"})
BLOCK_MINUTES = 15


def _is_final_third_event(event: dict[str, Any]) -> bool:
    start = event.get("start") or {}
    position = str(start.get("pitchPosition") or "").upper()
    return position in FINAL_THIRD_POSITIONS


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return []
    return events


def _iteration_match_lookup(iteration_id: int) -> dict[int, dict[str, Any]]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    lookup: dict[int, dict[str, Any]] = {}
    for row in extract_rows(raw["data"]):
        match_id = int(row.get("id") or 0)
        if match_id:
            lookup[match_id] = row
    return lookup


def _block_focus_tilts(
    events: list[dict[str, Any]],
    home_squad_id: int,
    away_squad_id: int,
    focus_squad_id: int,
    block_minutes: int,
) -> dict[int, float]:
    block_ft: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for event in events:
        squad_id = event.get("squadId")
        try:
            squad_id = int(squad_id)
        except (TypeError, ValueError):
            continue
        if squad_id not in (home_squad_id, away_squad_id):
            continue

        action = str(event.get("actionType") or "").upper()
        if action not in ("PASS", "DRIBBLE", "SHOT", "CROSS"):
            continue
        if not _is_final_third_event(event):
            continue

        game_time = event.get("gameTime") or {}
        try:
            seconds = float(game_time.get("gameTimeInSec") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        minute = impect_seconds_to_minute(seconds)
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)
        block_ft[block_start][squad_id] += 1

    focus_is_home = focus_squad_id == home_squad_id
    tilts: dict[int, float] = {}
    for start in range(0, 90, block_minutes):
        home_ft = block_ft[start].get(home_squad_id, 0)
        away_ft = block_ft[start].get(away_squad_id, 0)
        block_sum = home_ft + away_ft
        if block_sum:
            home_share = (home_ft / block_sum) * 100
            focus_share = home_share if focus_is_home else (100 - home_share)
        else:
            focus_share = 50.0
        tilts[start] = focus_share
    return tilts


def _overall_focus_tilt(
    events: list[dict[str, Any]],
    home_squad_id: int,
    away_squad_id: int,
    focus_squad_id: int,
) -> float:
    overall: dict[int, int] = defaultdict(int)
    for event in events:
        squad_id = event.get("squadId")
        try:
            squad_id = int(squad_id)
        except (TypeError, ValueError):
            continue
        if squad_id not in (home_squad_id, away_squad_id):
            continue
        action = str(event.get("actionType") or "").upper()
        if action not in ("PASS", "DRIBBLE", "SHOT", "CROSS"):
            continue
        if _is_final_third_event(event):
            overall[squad_id] += 1

    total_ft = overall[home_squad_id] + overall[away_squad_id]
    if not total_ft:
        return 50.0
    home_tilt = (overall[home_squad_id] / total_ft) * 100
    return home_tilt if focus_squad_id == home_squad_id else (100 - home_tilt)


def build_field_tilt(
    match_id: int,
    home_squad_id: int,
    away_squad_id: int,
    focus_squad_id: int,
    home_name: str | None = None,
    away_name: str | None = None,
    block_minutes: int = BLOCK_MINUTES,
) -> dict[str, Any]:
    events = _fetch_match_events(match_id)
    block_tilts = _block_focus_tilts(
        events, home_squad_id, away_squad_id, focus_squad_id, block_minutes
    )

    overall: dict[int, int] = defaultdict(int)
    block_ft: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for event in events:
        squad_id = event.get("squadId")
        try:
            squad_id = int(squad_id)
        except (TypeError, ValueError):
            continue
        if squad_id not in (home_squad_id, away_squad_id):
            continue

        action = str(event.get("actionType") or "").upper()
        if action not in ("PASS", "DRIBBLE", "SHOT", "CROSS"):
            continue

        game_time = event.get("gameTime") or {}
        try:
            seconds = float(game_time.get("gameTimeInSec") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        minute = impect_seconds_to_minute(seconds)
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)

        if _is_final_third_event(event):
            overall[squad_id] += 1
            block_ft[block_start][squad_id] += 1

    total_ft = overall[home_squad_id] + overall[away_squad_id]
    home_tilt = round((overall[home_squad_id] / total_ft) * 100, 1) if total_ft else 50.0
    away_tilt = round((overall[away_squad_id] / total_ft) * 100, 1) if total_ft else 50.0

    timeline: list[dict[str, Any]] = []
    for start in range(0, 90, block_minutes):
        end = min(start + block_minutes, 90)
        home_ft = block_ft[start].get(home_squad_id, 0)
        away_ft = block_ft[start].get(away_squad_id, 0)
        block_sum = home_ft + away_ft
        tilt_home = round((home_ft / block_sum) * 100, 1) if block_sum else 50.0
        focus_share = round(block_tilts.get(start, 50.0), 1)
        timeline.append(
            {
                "startMinute": start,
                "endMinute": end,
                "label": f"{start}–{end}'",
                "homeFinalThird": home_ft,
                "awayFinalThird": away_ft,
                "homeTiltPercent": tilt_home,
                "awayTiltPercent": round(100 - tilt_home, 1) if block_sum else 50.0,
                "focusTiltPercent": focus_share,
            }
        )

    focus_is_home = focus_squad_id == home_squad_id
    focus_tilt = home_tilt if focus_is_home else away_tilt

    return {
        "title": "Field Tilt",
        "description": "Share of attacking-third possession vs opponent (final third + opponent box) · 15-minute blocks",
        "blockMinutes": block_minutes,
        "home": {
            "squadId": home_squad_id,
            "name": home_name,
            "tiltPercent": home_tilt,
            "finalThirdActions": overall[home_squad_id],
        },
        "away": {
            "squadId": away_squad_id,
            "name": away_name,
            "tiltPercent": away_tilt,
            "finalThirdActions": overall[away_squad_id],
        },
        "focusSquadId": focus_squad_id,
        "focusTiltPercent": focus_tilt,
        "timeline": timeline,
    }


def build_field_tilt_baseline_last_n(
    iteration_id: int,
    focus_squad_id: int,
    *,
    before_match_id: int | None = None,
    game_count: int = 7,
    block_minutes: int = BLOCK_MINUTES,
) -> dict[str, Any]:
    match_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )
    match_lookup = _iteration_match_lookup(iteration_id)

    block_sums: dict[int, float] = defaultdict(float)
    block_counts: dict[int, int] = defaultdict(int)
    overall_sums: list[float] = []
    used_match_ids: list[int] = []

    for match_id in match_ids:
        row = match_lookup.get(match_id)
        if not row:
            continue
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        if focus_squad_id not in (home_id, away_id):
            continue

        events = _fetch_match_events(match_id)
        block_tilts = _block_focus_tilts(events, home_id, away_id, focus_squad_id, block_minutes)
        overall_sums.append(_overall_focus_tilt(events, home_id, away_id, focus_squad_id))
        used_match_ids.append(match_id)

        for start, share in block_tilts.items():
            block_sums[start] += share
            block_counts[start] += 1

    games_used = len(used_match_ids)
    timeline: list[dict[str, Any]] = []
    for start in range(0, 90, block_minutes):
        end = min(start + block_minutes, 90)
        if games_used:
            avg = round(block_sums[start] / block_counts[start], 1)
        else:
            avg = 50.0
        timeline.append(
            {
                "startMinute": start,
                "endMinute": end,
                "label": f"{start}–{end}'",
                "focusTiltPercent": avg,
            }
        )

    focus_tilt_avg = round(sum(overall_sums) / len(overall_sums), 1) if overall_sums else 50.0

    return {
        "title": f"Last {game_count} games average",
        "gameCount": game_count,
        "gamesUsed": games_used,
        "matchIds": used_match_ids,
        "focusTiltPercent": focus_tilt_avg,
        "timeline": timeline,
    }
