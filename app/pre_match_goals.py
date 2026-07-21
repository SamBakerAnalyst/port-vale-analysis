"""Opponent goals analysis for pre-match: phases, types, and pitch maps."""

from __future__ import annotations

import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

GOALS_MATCH_LIMIT = 46

# Attacking-half pitch view (goal at top) — taller than final-third crop.
PITCH = {
    "goalX": 52.5,
    "minX": 0.0,
    "widthM": 68.0,
    "depthM": 52.5,
    "penaltyBoxDepthM": 16.5,
    "penaltyBoxWidthM": 40.32,
    "sixYardDepthM": 5.5,
    "sixYardWidthM": 18.32,
    "penaltySpotM": 11.0,
    "penaltyArcM": 9.15,
}

PHASE_ORDER = ("possession", "transition", "set_play")
PHASE_LABELS = {
    "possession": "Possession",
    "transition": "Transition",
    "set_play": "Set play",
}
PHASE_MARKER = {
    "possession": "Possession",
    "transition": "Transition",
    "set_play": "Set Play",
}

_set_piece_cache: dict[int, tuple[float, dict[int, str]]] = {}


def _impect():
    from app import main as impect_main

    return impect_main


def _fetch_events(match_id: int) -> list[dict[str, Any]]:
    from app.xg_chance_analysis import _fetch_match_events

    return _fetch_match_events(match_id)


def _fetch_shot_xg(match_id: int) -> dict[int, float]:
    from app.xg_chance_analysis import _fetch_shot_xg_by_event

    return _fetch_shot_xg_by_event(match_id)


def _fetch_set_piece_categories(match_id: int) -> dict[int, str]:
    cached = _set_piece_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]

    impect = _impect()
    mapping: dict[int, str] = {}
    try:
        raw = impect._impect_get(
            f"/v5/{impect._api_prefix()}/matches/{match_id}/set-pieces"
        )["data"]
        rows = raw.get("data") if isinstance(raw, dict) else raw
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                cat = str(
                    row.get("adjSetPieceCategory")
                    or row.get("setPieceCategory")
                    or ""
                ).upper()
                mapping[int(row["id"])] = cat
    except Exception:  # noqa: BLE001 - optional enrichment
        mapping = {}

    _set_piece_cache[match_id] = (now, mapping)
    return mapping


def _coords(point: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(point, dict):
        return None
    coords = point.get("adjCoordinates") or point.get("coordinates") or {}
    try:
        return float(coords["x"]), float(coords["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _side_from_y(y: float | None) -> str:
    if y is None:
        return ""
    if y <= -8.0:
        return "L"
    if y >= 8.0:
        return "R"
    return ""


def _is_set_piece_goal(goal: dict[str, Any]) -> bool:
    if goal.get("inferredSetPiece") or goal.get("setPiece"):
        return True
    return str(goal.get("phase") or "").upper() == "SET_PIECE"


def _set_piece_id(goal: dict[str, Any]) -> int | None:
    payload = goal.get("inferredSetPiece") or goal.get("setPiece")
    if isinstance(payload, dict) and payload.get("id") is not None:
        try:
            return int(payload["id"])
        except (TypeError, ValueError):
            return None
    return None


def _find_assist(
    events: list[dict[str, Any]],
    goal: dict[str, Any],
) -> dict[str, Any] | None:
    seq = goal.get("sequenceIndex")
    if seq is None:
        return None
    goal_id = int(goal.get("id") or 0)
    passes = [
        event
        for event in events
        if event.get("sequenceIndex") == seq
        and str(event.get("actionType") or "").upper() == "PASS"
        and str(event.get("result") or "").upper() == "SUCCESS"
        and int(event.get("id") or 0) < goal_id
    ]
    return passes[-1] if passes else None


def _is_cutback(assist: dict[str, Any] | None) -> bool:
    if not assist:
        return False
    coords = _coords(assist.get("start"))
    if not coords:
        return False
    x_val, y_val = coords
    return x_val >= 40.0 and abs(y_val) >= 12.0


def _player_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _format_xg(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(float(value), 2)
    if rounded <= 0:
        return "0"
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def _event_player_name(
    event: dict[str, Any],
    player_names: dict[int, str],
) -> str:
    player = event.get("player") if isinstance(event.get("player"), dict) else {}
    try:
        player_id = int(player.get("id") or event.get("playerId") or 0)
    except (TypeError, ValueError):
        player_id = 0
    if player_id and player_names.get(player_id):
        return str(player_names[player_id])
    return str(player.get("commonname") or player.get("name") or "").strip()


def _in_pitch_view(coords: tuple[float, float] | None) -> bool:
    if coords is None:
        return False
    x_val, y_val = coords
    if x_val < float(PITCH["minX"]) - 0.5 or x_val > float(PITCH["goalX"]) + 1.0:
        return False
    half = float(PITCH["widthM"]) / 2.0
    return abs(y_val) <= half + 0.5


def _in_final_third(coords: tuple[float, float] | None) -> bool:
    return _in_pitch_view(coords)


def _classify_goal_type(
    goal: dict[str, Any],
    assist: dict[str, Any] | None,
    set_piece_cats: dict[int, str],
) -> str:
    action = str(goal.get("action") or "").upper()
    phase = str(goal.get("phase") or "").upper()

    if action == "PENALTY_KICK":
        return "Penalties"
    if action == "DIRECT_FREE_KICK":
        return "Direct free kick"

    if _is_set_piece_goal(goal):
        sp_id = _set_piece_id(goal)
        cat = set_piece_cats.get(sp_id or -1, "")
        if "CORNER" in cat:
            return "Corners"
        if "FREE_KICK" in cat:
            return "Free kicks"
        if "THROW" in cat:
            return "Throw-ins"
        return "Set piece"

    assist_action = str((assist or {}).get("action") or "").upper()
    assist_coords = _coords((assist or {}).get("start"))
    side = _side_from_y(assist_coords[1] if assist_coords else None)

    if assist_action == "HIGH_CROSS":
        return f"High cross {side}".strip()
    if assist_action == "LOW_CROSS":
        return f"Low cross {side}".strip()
    if assist_action in {"CHIPPED_PASS", "DIAGONAL_PASS"}:
        return "Through pass"
    if _is_cutback(assist):
        side_bit = f" {side}" if side else ""
        return f"Cut back{side_bit}".strip()
    if phase == "ATTACKING_TRANSITION":
        return "Counter attack"

    shot = goal.get("shot") if isinstance(goal.get("shot"), dict) else {}
    try:
        distance = float(shot.get("distance") or goal.get("distanceToGoal") or 0.0)
    except (TypeError, ValueError):
        distance = 0.0
    if distance >= 20.0 or (action == "MID_RANGE_SHOT" and distance >= 18.0):
        return "Long range"
    if action == "ONE_VS_ONE_AGAINST_GK":
        return "Solo / 1v1"
    if action == "HEADER":
        return "Header (open play)"
    return "Open play"


def _classify_phase(goal: dict[str, Any], type_label: str) -> str:
    action = str(goal.get("action") or "").upper()
    if action in {"PENALTY_KICK", "DIRECT_FREE_KICK"}:
        return "set_play"
    if type_label in {
        "Penalties",
        "Direct free kick",
        "Corners",
        "Free kicks",
        "Throw-ins",
        "Set piece",
    } or _is_set_piece_goal(goal):
        return "set_play"

    phase = str(goal.get("phase") or "").upper()
    if "TRANSITION" in phase:
        return "transition"
    if phase in {"IN_POSSESSION", "POSSESSION", "ATTACKING_POSSESSION"}:
        return "possession"
    if type_label == "Counter attack":
        return "transition"
    return "possession"


def _rank_type_counts(counter: Counter[str], *, limit: int = 8) -> list[dict[str, Any]]:
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0].casefold()))
    ranked: list[dict[str, Any]] = []
    prev_count: int | None = None
    prev_rank = 0
    for index, (label, count) in enumerate(items[:limit], start=1):
        if count != prev_count:
            prev_rank = index
            prev_count = count
            rank_label = str(prev_rank)
        else:
            rank_label = f"={prev_rank}"
        ranked.append({"rank": rank_label, "label": label, "goals": count})
    return ranked


def _phase_payload(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in PHASE_ORDER:
        count = int(counter.get(key, 0))
        rows.append(
            {
                "key": key,
                "label": PHASE_LABELS[key],
                "goals": count,
                "pct": round(100.0 * count / total, 1) if total else 0.0,
            }
        )
    return rows


def _goal_map_payload(points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "style": "pitch_points",
        "kind": "goals",
        "orientation": "vertical",
        "zone": "attacking_half",
        "pitch": dict(PITCH),
        "points": points,
        "total": len(points),
    }


def _assist_map_payload(points: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "style": "pitch_points",
        "kind": "assists",
        "orientation": "vertical",
        "zone": "attacking_half",
        "pitch": dict(PITCH),
        "points": points,
        "total": len(points),
    }


def _shot_goals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    goals: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if (
            str(event.get("actionType") or "").upper() == "SHOT"
            and str(event.get("result") or "").upper() == "SUCCESS"
        ):
            goals.append(event)
    return goals


def _blank_side() -> dict[str, Any]:
    return {
        "total": 0,
        "phases": Counter(),
        "types": Counter(),
        "open_play": 0,
        "goal_points": [],
        "assist_points": [],
        "assists_found": 0,
        "assists_mapped": 0,
        "goals_mapped": 0,
    }


def _process_match(
    match_id: int,
    squad_id: int,
    player_names: dict[int, str],
) -> dict[str, Any]:
    events = _fetch_events(match_id)
    set_cats = _fetch_set_piece_categories(match_id)
    shot_xg = _fetch_shot_xg(match_id)
    sides = {"for": _blank_side(), "against": _blank_side()}

    for goal in _shot_goals(events):
        try:
            scorer_squad = int(goal.get("squadId") or 0)
        except (TypeError, ValueError):
            continue
        if scorer_squad <= 0:
            continue
        side_key = "for" if scorer_squad == squad_id else "against"
        bucket = sides[side_key]
        assist = _find_assist(events, goal)
        label = _classify_goal_type(goal, assist, set_cats)
        phase = _classify_phase(goal, label)
        bucket["total"] += 1
        bucket["phases"][phase] += 1
        bucket["types"][label] += 1

        if phase == "set_play":
            continue

        bucket["open_play"] += 1
        goal_coords = _coords(goal.get("start"))
        if _in_final_third(goal_coords):
            assert goal_coords is not None
            scorer_name = _event_player_name(goal, player_names)
            xg = round(float(shot_xg.get(int(goal.get("id") or 0), 0.0)), 4)
            bucket["goal_points"].append(
                {
                    "impectX": goal_coords[0],
                    "impectY": goal_coords[1],
                    "hasLocation": True,
                    "outcome": "scored",
                    "phase": PHASE_MARKER.get(phase, "Possession"),
                    "xg": xg,
                    "xgDisplay": _format_xg(xg),
                    "playerInitials": _player_initials(scorer_name),
                    "playerName": scorer_name or None,
                }
            )
            bucket["goals_mapped"] += 1

        if assist:
            bucket["assists_found"] += 1
            assist_coords = _coords(assist.get("start"))
            if _in_final_third(assist_coords):
                assert assist_coords is not None
                assister_name = _event_player_name(assist, player_names)
                bucket["assist_points"].append(
                    {
                        "impectX": assist_coords[0],
                        "impectY": assist_coords[1],
                        "hasLocation": True,
                        "outcome": "assist",
                        "phase": PHASE_MARKER.get(phase, "Possession"),
                        "xg": 0.0,
                        "xgDisplay": "",
                        "playerInitials": _player_initials(assister_name),
                        "playerName": assister_name or None,
                    }
                )
                bucket["assists_mapped"] += 1

    return sides


def _side_payload(side: dict[str, Any]) -> dict[str, Any]:
    total = int(side["total"])
    return {
        "total": total,
        "phases": _phase_payload(side["phases"], total),
        "types": _rank_type_counts(side["types"]),
        "open_play": int(side["open_play"]),
        "goal_map": _goal_map_payload(side["goal_points"]),
        "assist_map": _assist_map_payload(side["assist_points"]),
        "map_meta": {
            "goals_mapped": int(side["goals_mapped"]),
            "assists_found": int(side["assists_found"]),
            "assists_mapped": int(side["assists_mapped"]),
        },
    }


def build_goals_analysis(
    iteration_id: int,
    squad_id: int,
    *,
    before: str | datetime | None = None,
    exclude_match_id: int | None = None,
    match_limit: int = GOALS_MATCH_LIMIT,
    player_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    from app.pre_match import _recent_completed_matches

    names = player_names or {}
    matches = _recent_completed_matches(
        iteration_id,
        squad_id,
        limit=match_limit,
        before=before,
        exclude_match_id=exclude_match_id,
    )
    merged = {"for": _blank_side(), "against": _blank_side()}
    match_count = 0

    empty = {
        "matches": 0,
        "for": _side_payload(merged["for"]),
        "against": _side_payload(merged["against"]),
        "summary": {
            "goals_for": 0,
            "goals_against": 0,
            "open_play_for": 0,
            "set_play_for": 0,
            "open_play_against": 0,
            "set_play_against": 0,
        },
        "types_for": [],
        "types_against": [],
        "goal_map": _side_payload(merged["for"])["goal_map"],
        "assist_map": _side_payload(merged["for"])["assist_map"],
    }
    if not matches:
        return empty

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(_process_match, int(match["id"]), squad_id, names)
            for match in matches
        ]
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:  # noqa: BLE001 - skip bad matches
                continue
            match_count += 1
            for side_key in ("for", "against"):
                src = result[side_key]
                dst = merged[side_key]
                dst["total"] += src["total"]
                dst["open_play"] += src["open_play"]
                dst["assists_found"] += src["assists_found"]
                dst["assists_mapped"] += src["assists_mapped"]
                dst["goals_mapped"] += src["goals_mapped"]
                dst["phases"].update(src["phases"])
                dst["types"].update(src["types"])
                dst["goal_points"].extend(src["goal_points"])
                dst["assist_points"].extend(src["assist_points"])

    for_payload = _side_payload(merged["for"])
    against_payload = _side_payload(merged["against"])
    phase_for = {row["key"]: row["goals"] for row in for_payload["phases"]}
    phase_against = {row["key"]: row["goals"] for row in against_payload["phases"]}

    return {
        "matches": match_count,
        "for": for_payload,
        "against": against_payload,
        "summary": {
            "goals_for": for_payload["total"],
            "goals_against": against_payload["total"],
            "open_play_for": for_payload["open_play"],
            "set_play_for": phase_for.get("set_play", 0),
            "open_play_against": against_payload["open_play"],
            "set_play_against": phase_against.get("set_play", 0),
            "possession_for": phase_for.get("possession", 0),
            "transition_for": phase_for.get("transition", 0),
            "possession_against": phase_against.get("possession", 0),
            "transition_against": phase_against.get("transition", 0),
        },
        "types_for": for_payload["types"],
        "types_against": against_payload["types"],
        "goal_map": for_payload["goal_map"],
        "assist_map": for_payload["assist_map"],
    }
