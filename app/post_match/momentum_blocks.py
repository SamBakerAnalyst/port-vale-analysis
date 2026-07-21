from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.post_match.impect_client import impect_get, v5_path
from app.post_match.xg_race import impect_seconds_to_minute, _fetch_shots_with_xg

SHOT_XG_KPI_ID = 82
BLOCK_MINUTES = 15
FOCUS_REGAIN_ACTIONS = frozenset({"LOOSE_BALL_REGAIN", "INTERCEPTION"})
DUEL_WIN_KPI_IDS = frozenset({94, 96})
DUEL_LOSS_KPI_IDS = frozenset({95, 97})
DUEL_COUNT_KPI_IDS = DUEL_WIN_KPI_IDS | DUEL_LOSS_KPI_IDS


def _event_dominance_score(event: dict[str, Any], xg_by_event: dict[int, float]) -> float:
    score = 0.0
    event_id = event.get("id")
    if event_id is not None:
        score += float(xg_by_event.get(int(event_id), 0.0)) * 3.0

    pxt = event.get("pxT")
    if isinstance(pxt, dict):
        try:
            score += float(pxt.get("team") or 0) * 2.0
        except (TypeError, ValueError):
            pass

    action = str(event.get("actionType") or "").upper()
    if action in ("SHOT", "PASS", "DRIBBLE", "CROSS"):
        score += 0.03
    if str(event.get("result") or "").upper() == "SUCCESS":
        score += 0.02

    return score


def _duel_stats_by_block(
    events: list[dict[str, Any]],
    event_kpi_rows: list[dict[str, Any]],
    focus_squad_id: int,
    block_minutes: int,
) -> dict[int, dict[str, int | float | None]]:
    event_lookup: dict[int, dict[str, Any]] = {}
    for event in events:
        event_id = event.get("id")
        if event_id is None:
            continue
        try:
            event_lookup[int(event_id)] = event
        except (TypeError, ValueError):
            continue

    wins: dict[int, int] = defaultdict(int)
    losses: dict[int, int] = defaultdict(int)
    for row in event_kpi_rows:
        try:
            kpi_id = int(row.get("kpiId") or 0)
            if kpi_id not in DUEL_COUNT_KPI_IDS:
                continue
            if float(row.get("value") or 0) <= 0:
                continue
            event_id = int(row["eventId"])
        except (TypeError, ValueError, KeyError):
            continue

        event = event_lookup.get(event_id)
        if not event or int(event.get("squadId") or 0) != focus_squad_id:
            continue
        game_time = event.get("gameTime") or {}
        try:
            seconds = float(game_time.get("gameTimeInSec") or 0)
        except (TypeError, ValueError):
            continue
        minute = impect_seconds_to_minute(seconds)
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)
        if kpi_id in DUEL_WIN_KPI_IDS:
            wins[block_start] += 1
        else:
            losses[block_start] += 1

    stats: dict[int, dict[str, int | float | None]] = {}
    for block_start in set(wins) | set(losses):
        won = wins[block_start]
        lost = losses[block_start]
        total = won + lost
        stats[block_start] = {
            "wins": won,
            "losses": lost,
            "total": total,
            "winPct": round((won / total) * 100) if total else None,
        }
    return stats


def build_momentum_blocks(
    match_id: int,
    home_squad_id: int,
    away_squad_id: int,
    focus_squad_id: int,
    home_name: str | None = None,
    away_name: str | None = None,
    block_minutes: int = BLOCK_MINUTES,
) -> dict[str, Any]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        events = []

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    if not isinstance(ekpi_rows, list):
        ekpi_rows = []
    xg_by_event: dict[int, float] = {}
    if ekpi_rows:
        for row in ekpi_rows:
            if row.get("kpiId") == SHOT_XG_KPI_ID and row.get("eventId") is not None:
                try:
                    xg_by_event[int(row["eventId"])] = float(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue

    block_scores: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    block_press_intensity: dict[int, list[float]] = defaultdict(list)
    block_press_count: dict[int, int] = defaultdict(int)
    block_regains: dict[int, int] = defaultdict(int)
    block_focus_xg: dict[int, float] = defaultdict(float)
    block_opponent_xg: dict[int, float] = defaultdict(float)
    block_focus_shots: dict[int, int] = defaultdict(int)
    block_opponent_shots: dict[int, int] = defaultdict(int)
    opponent_squad_id = away_squad_id if focus_squad_id == home_squad_id else home_squad_id

    for event in events:
        game_time = event.get("gameTime") or {}
        try:
            seconds = float(game_time.get("gameTimeInSec") or 0)
            squad_id = int(event.get("squadId") or 0)
        except (TypeError, ValueError):
            continue
        if squad_id not in (home_squad_id, away_squad_id):
            continue
        minute = impect_seconds_to_minute(seconds)
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)
        block_scores[block_start][squad_id] += _event_dominance_score(event, xg_by_event)

        action = str(event.get("action") or event.get("actionType") or "").upper()
        if squad_id == focus_squad_id and action in FOCUS_REGAIN_ACTIONS:
            block_regains[block_start] += 1

        if squad_id == opponent_squad_id:
            try:
                pressure = float(event.get("pressure") or 0)
            except (TypeError, ValueError):
                pressure = 0.0
            if pressure > 0:
                block_press_intensity[block_start].append(pressure)
            if event.get("pressingPlayerId"):
                block_press_count[block_start] += 1

    block_duel_stats = _duel_stats_by_block(events, ekpi_rows, focus_squad_id, block_minutes)

    shots, _ = _fetch_shots_with_xg(match_id)
    goals_by_block: dict[int, list[dict[str, Any]]] = defaultdict(list)
    all_goals: list[dict[str, Any]] = []
    for shot in shots:
        minute = float(shot["minute"])
        squad_id = int(shot["squadId"])
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)
        shot_xg = float(shot.get("xg") or 0)
        if squad_id == focus_squad_id:
            block_focus_xg[block_start] += shot_xg
            block_focus_shots[block_start] += 1
        elif squad_id == opponent_squad_id:
            block_opponent_xg[block_start] += shot_xg
            block_opponent_shots[block_start] += 1
        if not shot.get("isGoal"):
            continue
        goal = {
            "minute": round(minute, 1),
            "squadId": squad_id,
            "isFocus": squad_id == focus_squad_id,
        }
        all_goals.append(goal)
        block_start = min(int(minute // block_minutes) * block_minutes, 90 - block_minutes)
        goals_by_block[block_start].append(goal)

    all_goals.sort(key=lambda g: g["minute"])

    focus_is_home = focus_squad_id == home_squad_id
    blocks: list[dict[str, Any]] = []
    all_press_values: list[float] = []
    for start in range(0, 90, block_minutes):
        end = min(start + block_minutes, 90)
        home_score = block_scores[start].get(home_squad_id, 0.0)
        away_score = block_scores[start].get(away_squad_id, 0.0)
        total_score = home_score + away_score
        if total_score > 0:
            home_share = round((home_score / total_score) * 100, 1)
            away_share = round((away_score / total_score) * 100, 1)
        else:
            home_share = 50.0
            away_share = 50.0

        margin = home_score - away_score
        if abs(margin) < 0.05:
            controller = "even"
        elif margin > 0:
            controller = "home"
        else:
            controller = "away"

        focus_score = away_score if focus_squad_id == away_squad_id else home_score
        opponent_score = home_score if focus_squad_id == away_squad_id else away_score
        focus_share = away_share if focus_squad_id == away_squad_id else home_share
        opponent_share = home_share if focus_squad_id == away_squad_id else away_share
        focus_controller = (
            "focus"
            if focus_score > opponent_score + 0.05
            else "opponent"
            if opponent_score > focus_score + 0.05
            else "even"
        )

        press_values = block_press_intensity.get(start, [])
        mean_pressure = (
            round(sum(press_values) / len(press_values), 1) if press_values else None
        )
        press_count = block_press_count.get(start, 0)
        regain_count = block_regains.get(start, 0)
        duel_stats = block_duel_stats.get(start, {})
        duel_wins = int(duel_stats.get("wins") or 0)
        duel_total = int(duel_stats.get("total") or 0)
        duel_win_pct = duel_stats.get("winPct")
        regain_rate = (
            round((regain_count / press_count) * 100)
            if press_count > 0
            else None
        )
        if press_values:
            all_press_values.extend(press_values)

        blocks.append(
            {
                "startMinute": start,
                "endMinute": end,
                "label": f"{start}–{end}'",
                "homeScore": round(home_score, 3),
                "awayScore": round(away_score, 3),
                "homeSharePercent": home_share,
                "awaySharePercent": away_share,
                "focusSharePercent": focus_share,
                "opponentSharePercent": opponent_share,
                "margin": round(margin, 3),
                "controller": controller,
                "focusController": focus_controller,
                "goals": goals_by_block.get(start, []),
                "focusPressCount": press_count,
                "focusMeanPressure": mean_pressure,
                "focusRegains": regain_count,
                "focusRegainRate": regain_rate,
                "focusDuelWins": duel_wins,
                "focusDuelTotal": duel_total,
                "focusDuelWinPct": duel_win_pct,
                "focusXg": round(block_focus_xg.get(start, 0.0), 2),
                "opponentXg": round(block_opponent_xg.get(start, 0.0), 2),
                "focusShots": block_focus_shots.get(start, 0),
                "opponentShots": block_opponent_shots.get(start, 0),
            }
        )

    focus_wins = sum(1 for b in blocks if b["focusController"] == "focus")
    opponent_wins = sum(1 for b in blocks if b["focusController"] == "opponent")
    match_mean_pressure = (
        round(sum(all_press_values) / len(all_press_values), 1) if all_press_values else None
    )
    match_press_count = sum(block_press_count.values())
    match_regains = sum(block_regains.values())
    match_duel_wins = sum(int(s.get("wins") or 0) for s in block_duel_stats.values())
    match_duel_total = sum(int(s.get("total") or 0) for s in block_duel_stats.values())
    match_duel_win_pct = (
        round((match_duel_wins / match_duel_total) * 100) if match_duel_total else None
    )
    match_focus_xg = round(sum(block_focus_xg.values()), 2)
    match_opponent_xg = round(sum(block_opponent_xg.values()), 2)
    match_focus_shots = sum(block_focus_shots.values())
    match_opponent_shots = sum(block_opponent_shots.values())
    max_block_pressure = max(
        (b["focusMeanPressure"] or 0 for b in blocks),
        default=0,
    )

    return {
        "title": "Match Momentum",
        "blockMinutes": block_minutes,
        "home": {"squadId": home_squad_id, "name": home_name, "color": "#3b82f6"},
        "away": {"squadId": away_squad_id, "name": away_name, "color": "#22c55e"},
        "focusSquadId": focus_squad_id,
        "focusIsHome": focus_is_home,
        "blocks": blocks,
        "goals": all_goals,
        "summary": {
            "focusBlocksWon": focus_wins,
            "opponentBlocksWon": opponent_wins,
            "evenBlocks": len(blocks) - focus_wins - opponent_wins,
            "matchMeanPressure": match_mean_pressure,
            "matchPressCount": match_press_count,
            "matchRegains": match_regains,
            "matchDuelWins": match_duel_wins,
            "matchDuelTotal": match_duel_total,
            "matchDuelWinPct": match_duel_win_pct,
            "matchFocusXg": match_focus_xg,
            "matchOpponentXg": match_opponent_xg,
            "matchFocusShots": match_focus_shots,
            "matchOpponentShots": match_opponent_shots,
            "matchRegainRate": round((match_regains / match_press_count) * 100)
            if match_press_count > 0
            else None,
            "maxBlockPressure": max_block_pressure,
        },
    }
