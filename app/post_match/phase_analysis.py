from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, v5_path

PHASE_ORDER = [
    "SECOND_BALL",
    "IN_POSSESSION",
    "ATTACKING_TRANSITION",
    "OUT_OF_POSSESSION",
    "DEFENSIVE_TRANSITION",
    "SET_PIECE",
]

PHASE_LABELS = {
    "IN_POSSESSION": "In Possession",
    "OUT_OF_POSSESSION": "Out of Possession",
    "ATTACKING_TRANSITION": "Attacking Transition",
    "DEFENSIVE_TRANSITION": "Defensive Transition",
    "SECOND_BALL": "Second Ball",
    "SET_PIECE": "Set Piece",
}

PHASE_COLORS = {
    "SECOND_BALL": "#c8e6c9",
    "IN_POSSESSION": "#a5d6a7",
    "ATTACKING_TRANSITION": "#81c784",
    "OUT_OF_POSSESSION": "#2e7d32",
    "DEFENSIVE_TRANSITION": "#66bb6a",
    "SET_PIECE": "#b2dfdb",
}


def _phase_bucket(phase: str | None, attacking_squad_id: int | None, focus_squad_id: int) -> str | None:
    if not phase:
        return None
    if phase == "IN_POSSESSION":
        return "IN_POSSESSION" if attacking_squad_id == focus_squad_id else "OUT_OF_POSSESSION"
    if phase == "ATTACKING_TRANSITION":
        return "ATTACKING_TRANSITION" if attacking_squad_id == focus_squad_id else "DEFENSIVE_TRANSITION"
    if phase in ("SET_PIECE", "SECOND_BALL"):
        return phase
    return phase


def _parse_scheduled_date(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _recent_squad_match_ids(
    iteration_id: int,
    squad_id: int,
    *,
    before_match_id: int | None = None,
    count: int = 7,
) -> list[int]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    rows = extract_rows(raw["data"])
    cutoff: datetime | None = None
    if before_match_id is not None:
        for row in rows:
            if int(row.get("id") or 0) == before_match_id:
                cutoff = _parse_scheduled_date(row.get("scheduledDate"))
                break

    candidates: list[tuple[datetime, int]] = []

    for row in rows:
        if row.get("available") is False:
            continue
        match_id = int(row.get("id") or 0)
        if not match_id:
            continue
        home_id = int(row.get("homeSquadId") or 0)
        away_id = int(row.get("awaySquadId") or 0)
        if squad_id not in (home_id, away_id):
            continue
        if before_match_id is not None and match_id == before_match_id:
            continue
        scheduled = _parse_scheduled_date(row.get("scheduledDate"))
        if scheduled is None:
            continue
        if cutoff is not None and scheduled >= cutoff:
            continue
        candidates.append((scheduled, match_id))

    candidates.sort(key=lambda item: item[0])
    return [match_id for _, match_id in candidates[-count:]]


def _phase_durations_from_events(events: list[dict[str, Any]], focus_squad_id: int) -> dict[str, float]:
    durations: dict[str, float] = defaultdict(float)
    for event in events:
        phase = event.get("phase")
        if not phase:
            continue
        try:
            duration = float(event.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if duration <= 0:
            continue
        label = _phase_bucket(phase, event.get("currentAttackingSquadId"), focus_squad_id)
        if label:
            durations[label] += duration
    return durations


def _phases_from_durations(durations: dict[str, float]) -> tuple[list[dict[str, Any]], float]:
    total = sum(durations.values())
    phases: list[dict[str, Any]] = []
    for key in PHASE_ORDER:
        seconds = durations.get(key, 0.0)
        if seconds <= 0 and total > 0:
            continue
        percent = round((seconds / total) * 100, 1) if total > 0 else 0.0
        phases.append(
            {
                "id": key,
                "label": PHASE_LABELS.get(key, key),
                "percent": percent,
                "seconds": round(seconds, 1),
                "color": PHASE_COLORS.get(key, "#9ca3af"),
            }
        )
    return phases, total


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return []
    return events


def build_game_by_phase(match_id: int, focus_squad_id: int) -> dict[str, Any]:
    events = _fetch_match_events(match_id)
    durations = _phase_durations_from_events(events, focus_squad_id)
    phases, total = _phases_from_durations(durations)

    return {
        "title": "Game by Phase",
        "focusSquadId": focus_squad_id,
        "totalSeconds": round(total, 1),
        "phases": phases,
    }


def build_phase_average_last_n(
    iteration_id: int,
    focus_squad_id: int,
    *,
    before_match_id: int | None = None,
    game_count: int = 7,
) -> dict[str, Any]:
    match_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )

    percent_sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    used_match_ids: list[int] = []

    for match_id in match_ids:
        events = _fetch_match_events(match_id)
        durations = _phase_durations_from_events(events, focus_squad_id)
        total = sum(durations.values())
        if total <= 0:
            continue
        used_match_ids.append(match_id)
        for key in PHASE_ORDER:
            percent = (durations.get(key, 0.0) / total) * 100
            percent_sums[key] += percent
            counts[key] += 1

    games_used = len(used_match_ids)
    phases: list[dict[str, Any]] = []
    for key in PHASE_ORDER:
        if games_used == 0:
            percent = 0.0
        else:
            percent = round(percent_sums[key] / games_used, 1)
        phases.append(
            {
                "id": key,
                "label": PHASE_LABELS.get(key, key),
                "percent": percent,
                "color": PHASE_COLORS.get(key, "#9ca3af"),
            }
        )

    return {
        "title": f"Last {game_count} games average",
        "gameCount": game_count,
        "gamesUsed": games_used,
        "matchIds": used_match_ids,
        "phases": phases,
    }
