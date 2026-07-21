from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.post_match.ball_progression import (
    _average_metric_values,
    _iteration_kpi_values,
    _performance_band,
    _rank_for_value,
    _top7_average,
)
from app.post_match.crosses import PITCH_GOAL_X, PITCH_HALF_WIDTH_M, PITCH_WIDTH_M, FINAL_THIRD_MIN_X
from app.post_match.impect_client import extract_rows, impect_get, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

SHOT_XG_KPI_ID = 82
RESTART_ACTIONS = frozenset({
    "CORNER",
    "THROW_IN",
    "FREE_KICK",
    "DIRECT_FREE_KICK",
    "INDIRECT_FREE_KICK",
    "PENALTY",
})
ATTACKING_RESTARTS = RESTART_ACTIONS
FIRST_CONTACT_ACTION_TYPES = frozenset({
    "RECEPTION",
    "LOOSE_BALL_REGAIN",
    "SHOT",
    "GK_SAVE",
    "BLOCK",
    "CLEARANCE",
    "GROUND_DUEL",
    "AERIAL_DUEL",
})
TYPE_LABELS = {
    "CORNER": "Corner",
    "THROW_IN": "Throw-in",
    "FREE_KICK": "Free kick",
    "DIRECT_FREE_KICK": "Direct FK",
    "INDIRECT_FREE_KICK": "Indirect FK",
    "PENALTY": "Penalty",
}
FREE_KICK_ACTIONS = frozenset({
    "FREE_KICK",
    "DIRECT_FREE_KICK",
    "INDIRECT_FREE_KICK",
})
CORNER_ACTION = "CORNER"
PENALTY_BOX_MIN_X = PITCH_GOAL_X - 16.5  # 36.0
PENALTY_BOX_HALF_WIDTH_M = 40.32 / 2.0  # 20.16

TEAM_METRIC_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "pxtSetPiece",
        "label": "Set Play Threat",
        "metricColor": "#0d9488",
        "kpiId": 1406,
        "format": "decimal",
        "higherIsBetter": True,
    },
    {
        "id": "shotXgSetPiece",
        "label": "Shot xG (Set Play)",
        "metricColor": "#2563eb",
        "kpiId": 1282,
        "format": "decimal",
        "higherIsBetter": True,
    },
    {
        "id": "bypassedDefendersSetPiece",
        "label": "Bypassed Defenders",
        "metricColor": "#22c55e",
        "kpiId": 226,
        "format": "decimal",
        "higherIsBetter": True,
    },
    {
        "id": "aerialDuelsWon",
        "label": "Aerial Duels Won",
        "metricColor": "#16a34a",
        "kpiId": 1189,
        "format": "decimal",
        "higherIsBetter": True,
    },
    {
        "id": "aerialDuelsLost",
        "label": "Aerial Duels Lost",
        "metricColor": "#dc2626",
        "kpiId": 1216,
        "format": "decimal",
        "higherIsBetter": False,
    },
)


def _player_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def _format_decimal(value: float | None) -> str | None:
    if value is None:
        return None
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _event_coords(event: dict[str, Any], *, prefer_end: bool = False) -> tuple[float, float] | None:
    point = event.get("end" if prefer_end else "start") or {}
    if prefer_end and not point.get("adjCoordinates"):
        point = event.get("start") or {}
    coords = point.get("adjCoordinates") or point.get("coordinates") or {}
    try:
        return float(coords.get("x")), float(coords.get("y"))
    except (TypeError, ValueError):
        return None


def _coords_in_penalty_box(coords: tuple[float, float] | None) -> bool:
    """Attacking-orientation Impect coords: goal at x=52.5."""
    if not coords:
        return False
    try:
        x, y = float(coords[0]), float(coords[1])
    except (TypeError, ValueError, IndexError):
        return False
    return x >= PENALTY_BOX_MIN_X and abs(y) <= PENALTY_BOX_HALF_WIDTH_M


def _chain_into_box(chain: dict[str, Any]) -> bool:
    if chain.get("intoBox") is not None:
        return bool(chain.get("intoBox"))
    return _coords_in_penalty_box(
        chain.get("deliveryCoords")
    ) or _coords_in_penalty_box(chain.get("firstContactCoords"))


def _chain_is_delivery_threat(chain: dict[str, Any]) -> bool:
    """Corners always; free kicks only when restarted from the attacking third.

    Deep/recycle free kicks can't reasonably be judged on 'into box'.
    """
    chain_type = str(chain.get("type") or "").upper()
    if chain_type == CORNER_ACTION:
        return True
    if chain_type not in FREE_KICK_ACTIONS:
        return True
    start = chain.get("startCoords")
    if not start:
        return False
    try:
        return float(start[0]) >= FINAL_THIRD_MIN_X
    except (TypeError, ValueError, IndexError):
        return False


def _event_minute(event: dict[str, Any]) -> float:
    game_time = event.get("gameTime") or {}
    try:
        return float(game_time.get("gameTimeInSec") or 0) / 60.0
    except (TypeError, ValueError):
        return 0.0


def _player_id(event: dict[str, Any]) -> int | None:
    player = event.get("player") or {}
    try:
        player_id = int(player.get("id") or 0)
    except (TypeError, ValueError):
        return None
    return player_id or None


def _player_name(event: dict[str, Any], player_names: dict[int, str]) -> str | None:
    player_id = _player_id(event)
    if player_id and player_names.get(player_id):
        return player_names[player_id]
    player = event.get("player") or {}
    return str(player.get("commonname") or player.get("name") or "").strip() or None


def _delivery_success(result: str | None) -> str:
    value = str(result or "").upper()
    if value == "SUCCESS":
        return "success"
    if value in {"FAIL", "FAILED"}:
        return "fail"
    return "neutral"


def _find_first_contact(
    events: list[dict[str, Any]],
    restart_index: int,
    restart_squad_id: int,
) -> dict[str, Any] | None:
    for event in events[restart_index + 1 :]:
        action_type = str(event.get("actionType") or "").upper()
        if action_type not in FIRST_CONTACT_ACTION_TYPES:
            continue
        squad_id = int(event.get("squadId") or 0)
        coords = _event_coords(event) or _event_coords(event, prefer_end=True)
        return {
            "eventId": int(event.get("id") or 0),
            "action": str(event.get("action") or ""),
            "actionType": action_type,
            "playerId": _player_id(event),
            "sameTeam": squad_id == restart_squad_id,
            "coords": coords,
        }
    return None


def _chain_outcome(
    events: list[dict[str, Any]],
    attacking_squad_id: int,
) -> str:
    for event in events:
        if str(event.get("actionType") or "").upper() != "SHOT":
            continue
        if int(event.get("squadId") or 0) != attacking_squad_id:
            continue
        if str(event.get("result") or "").upper() == "SUCCESS":
            return "goal"
        return "shot"
    last_same_phase = None
    for event in reversed(events):
        if str(event.get("phase") or "").upper() != "SET_PIECE":
            break
        last_same_phase = event
    if last_same_phase and int(last_same_phase.get("squadId") or 0) == attacking_squad_id:
        return "retained"
    return "lost"


def _parse_chains(
    events: list[dict[str, Any]],
    attacking_squad_id: int,
    player_names: dict[int, str],
    xg_by_event: dict[int, float],
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        set_piece = event.get("setPiece") or {}
        chain_id = set_piece.get("id")
        if chain_id is None:
            continue
        try:
            grouped[int(chain_id)].append(event)
        except (TypeError, ValueError):
            continue

    chains: list[dict[str, Any]] = []
    for chain_events in grouped.values():
        chain_events.sort(
            key=lambda row: float((row.get("gameTime") or {}).get("gameTimeInSec") or 0),
        )
        restart = next(
            (
                event
                for event in chain_events
                if (event.get("setPiece") or {}).get("mainEvent")
            ),
            chain_events[0],
        )
        restart_action = str(restart.get("action") or "").upper()
        if restart_action not in ATTACKING_RESTARTS:
            continue
        if int(restart.get("squadId") or 0) != attacking_squad_id:
            continue

        restart_index = chain_events.index(restart)
        first_contact = _find_first_contact(chain_events, restart_index, attacking_squad_id)
        start_coords = _event_coords(restart)
        delivery_coords = _event_coords(restart, prefer_end=True) or start_coords
        minute = round(_event_minute(restart), 1)
        delivery_result = _delivery_success(restart.get("result"))
        deliverer_id = _player_id(restart)
        deliverer_name = _player_name(restart, player_names)
        # Impect +y = left wing from attacking team's perspective.
        side: str | None = None
        if restart_action == CORNER_ACTION and start_coords is not None:
            if start_coords[1] > 0:
                side = "left"
            elif start_coords[1] < 0:
                side = "right"

        shots = [
            {
                "eventId": int(event.get("id") or 0),
                "xg": round(xg_by_event.get(int(event.get("id") or 0), 0.0), 3),
                "isGoal": str(event.get("result") or "").upper() == "SUCCESS",
            }
            for event in chain_events
            if str(event.get("actionType") or "").upper() == "SHOT"
            and int(event.get("squadId") or 0) == attacking_squad_id
        ]

        first_contact_player_id = first_contact.get("playerId") if first_contact else None
        first_contact_name = None
        if first_contact_player_id:
            first_contact_name = player_names.get(
                int(first_contact_player_id),
                f"Player {first_contact_player_id}",
            )

        chains.append(
            {
                "setPieceId": int((restart.get("setPiece") or {}).get("id") or 0),
                "minute": minute,
                "minuteLabel": f"{int(minute)}'",
                "type": restart_action.lower(),
                "typeLabel": TYPE_LABELS.get(restart_action, restart_action.title()),
                "side": side,
                "deliveryResult": delivery_result,
                "delivererId": deliverer_id,
                "delivererName": deliverer_name,
                "delivererInitials": _player_initials(deliverer_name),
                "startCoords": start_coords,
                "firstContact": {
                    "playerId": first_contact_player_id,
                    "playerName": first_contact_name,
                    "playerInitials": _player_initials(first_contact_name),
                    "sameTeam": first_contact.get("sameTeam") if first_contact else None,
                    "actionType": first_contact.get("actionType") if first_contact else None,
                }
                if first_contact
                else None,
                "outcome": _chain_outcome(chain_events, attacking_squad_id),
                "shots": shots,
                "shotCount": len(shots),
                "deliveryCoords": delivery_coords,
                "firstContactCoords": first_contact.get("coords") if first_contact else None,
            }
        )

    chains.sort(key=lambda row: row["minute"])
    return chains


def _first_contact_won_for_focus(
    first_contact: dict[str, Any] | None,
    *,
    defending: bool,
) -> bool | None:
    """Return whether first contact was a success for the focus team."""
    if not first_contact:
        return None
    same_team = first_contact.get("sameTeam")
    if same_team is None:
        return None
    attacker_won = bool(same_team)
    # Attacking set plays: success = our attacker wins first contact.
    # Defending set plays: success = Port Vale (defender) wins first contact.
    return (not attacker_won) if defending else attacker_won


def _annotate_first_contact_perspective(
    chains: list[dict[str, Any]],
    *,
    defending: bool,
) -> list[dict[str, Any]]:
    for chain in chains:
        first_contact = chain.get("firstContact")
        if not first_contact:
            continue
        won = _first_contact_won_for_focus(first_contact, defending=defending)
        first_contact["won"] = won
        first_contact["defending"] = defending
    return chains


def _map_points_from_chains(
    chains: list[dict[str, Any]],
    *,
    defending: bool = False,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for chain in chains:
        start_coords = chain.get("startCoords")
        chain_type = str(chain.get("type") or "").upper()
        # Free kicks can start anywhere — plot take location so deep/recycle FKs still appear.
        if start_coords and chain_type in FREE_KICK_ACTIONS:
            points.append(
                {
                    "kind": "take",
                    "impectX": start_coords[0],
                    "impectY": start_coords[1],
                    "result": chain.get("deliveryResult"),
                    "deliveryThreat": bool(chain.get("deliveryThreat")),
                    "typeLabel": chain.get("typeLabel"),
                    "playerInitials": chain.get("delivererInitials"),
                    "minuteLabel": chain.get("minuteLabel"),
                }
            )
        delivery_coords = chain.get("deliveryCoords")
        if delivery_coords:
            points.append(
                {
                    "kind": "delivery",
                    "impectX": delivery_coords[0],
                    "impectY": delivery_coords[1],
                    "result": chain.get("deliveryResult"),
                    "typeLabel": chain.get("typeLabel"),
                    "playerInitials": chain.get("delivererInitials"),
                    "minuteLabel": chain.get("minuteLabel"),
                }
            )
        first_contact = chain.get("firstContact")
        first_coords = chain.get("firstContactCoords")
        if first_contact and first_coords:
            won = first_contact.get("won")
            if won is None:
                won = _first_contact_won_for_focus(first_contact, defending=defending)
            points.append(
                {
                    "kind": "firstContact",
                    "impectX": first_coords[0],
                    "impectY": first_coords[1],
                    "sameTeam": first_contact.get("sameTeam"),
                    "won": won,
                    "playerInitials": first_contact.get("playerInitials"),
                    "minuteLabel": chain.get("minuteLabel"),
                }
            )
    return points


def _summarize_chains(
    chains: list[dict[str, Any]],
    *,
    defending: bool = False,
) -> dict[str, Any]:
    deliveries = len(chains)
    successful = sum(1 for chain in chains if chain.get("deliveryResult") == "success")
    with_first_contact = [chain for chain in chains if chain.get("firstContact")]
    first_contact_won = 0
    into_box = 0
    shot_routines = 0
    deliverable = 0
    into_box_deliverable = 0
    for chain in chains:
        chain["intoBox"] = _chain_into_box(chain)
        chain["deliveryThreat"] = _chain_is_delivery_threat(chain)
        if chain["intoBox"]:
            into_box += 1
        if chain["deliveryThreat"]:
            deliverable += 1
            if chain["intoBox"]:
                into_box_deliverable += 1
        if (chain.get("shotCount") or 0) > 0:
            shot_routines += 1
    for chain in with_first_contact:
        first_contact = chain.get("firstContact") or {}
        won = first_contact.get("won")
        if won is None:
            won = _first_contact_won_for_focus(first_contact, defending=defending)
        if won:
            first_contact_won += 1
    shots = sum(chain.get("shotCount") or 0 for chain in chains)
    goals = sum(
        1
        for chain in chains
        for shot in chain.get("shots") or []
        if shot.get("isGoal")
    )
    shot_xg = round(
        sum(
            float(shot.get("xg") or 0)
            for chain in chains
            for shot in chain.get("shots") or []
        ),
        3,
    )
    by_type: dict[str, int] = defaultdict(int)
    for chain in chains:
        by_type[chain.get("typeLabel") or "Other"] += 1

    delivery_success_pct = (
        round((successful / deliveries) * 100) if deliveries else None
    )
    first_contact_won_pct = (
        round((first_contact_won / len(with_first_contact)) * 100)
        if with_first_contact
        else None
    )
    into_box_pct = (
        round((into_box_deliverable / deliverable) * 100) if deliverable else None
    )
    shot_pct = round((shot_routines / deliveries) * 100) if deliveries else None

    return {
        "chains": deliveries,
        "deliveries": deliveries,
        "successfulDeliveries": successful,
        "deliverySuccessPct": delivery_success_pct,
        "intoBox": into_box_deliverable,
        "intoBoxTotal": into_box,
        "intoBoxPct": into_box_pct,
        "deliverable": deliverable,
        "contested": len(with_first_contact),
        "firstContacts": len(with_first_contact),
        "firstContactWon": first_contact_won,
        "firstContactWonPct": first_contact_won_pct,
        "shotRoutines": shot_routines,
        "shotPct": shot_pct,
        "shots": shots,
        "goals": goals,
        "shotXg": shot_xg,
        "byType": dict(by_type),
        "defending": defending,
        "scopeNote": None,
    }


def _view_from_chains(
    chains: list[dict[str, Any]],
    *,
    defending: bool = False,
) -> dict[str, Any]:
    annotated = _annotate_first_contact_perspective(chains, defending=defending)
    return {
        "summary": _summarize_chains(annotated, defending=defending),
        "chains": annotated,
        "mapPoints": _map_points_from_chains(annotated, defending=defending),
        "defending": defending,
    }


def _filter_chains(
    chains: list[dict[str, Any]],
    *,
    types: frozenset[str] | None = None,
    side: str | None = None,
) -> list[dict[str, Any]]:
    filtered = chains
    if types is not None:
        filtered = [
            chain
            for chain in filtered
            if str(chain.get("type") or "").upper() in types
        ]
    if side is not None:
        filtered = [chain for chain in filtered if chain.get("side") == side]
    return filtered


def _is_free_kick_chain(chain: dict[str, Any]) -> bool:
    return str(chain.get("type") or "").upper() in FREE_KICK_ACTIONS


def _is_corner_chain(chain: dict[str, Any]) -> bool:
    return str(chain.get("type") or "").upper() == CORNER_ACTION


def _match_chain_summary(
    match_id: int,
    attacking_squad_id: int,
    player_names: dict[int, str],
    *,
    defending: bool = False,
) -> dict[str, Any]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return _summarize_chains([], defending=defending)

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    xg_by_event: dict[int, float] = {}
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            if row.get("kpiId") == SHOT_XG_KPI_ID and row.get("eventId") is not None:
                try:
                    xg_by_event[int(row["eventId"])] = float(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue

    chains = _parse_chains(events, attacking_squad_id, player_names, xg_by_event)
    chains = _annotate_first_contact_perspective(chains, defending=defending)
    return _summarize_chains(chains, defending=defending)


def _baseline_chain_summary(
    iteration_id: int,
    focus_squad_id: int,
    *,
    before_match_id: int,
    attacking: bool,
    opponent_squad_id: int | None = None,
    game_count: int = 7,
) -> dict[str, Any]:
    from app.post_match.report import _match_meta

    recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )
    if not recent_ids:
        return {"gameCount": 0}

    totals = defaultdict(float)
    counts = defaultdict(int)
    for match_id in recent_ids:
        if attacking:
            attacking_squad_id = focus_squad_id
        else:
            meta = _match_meta(match_id, iteration_id)
            home_id = int(meta["home"]["squadId"] or 0)
            away_id = int(meta["away"]["squadId"] or 0)
            if focus_squad_id == home_id and away_id:
                attacking_squad_id = away_id
            elif focus_squad_id == away_id and home_id:
                attacking_squad_id = home_id
            else:
                continue
        summary = _match_chain_summary(
            match_id,
            attacking_squad_id,
            {},
            defending=not attacking,
        )
        for key in (
            "chains",
            "successfulDeliveries",
            "firstContactWon",
            "firstContacts",
            "shots",
            "goals",
            "shotXg",
        ):
            totals[key] += float(summary.get(key) or 0)
        counts["games"] += 1

    games = counts["games"] or 1
    avg_delivery_pct = None
    if totals["chains"]:
        avg_delivery_pct = round((totals["successfulDeliveries"] / totals["chains"]) * 100)
    avg_fc_pct = None
    if totals["firstContacts"]:
        avg_fc_pct = round((totals["firstContactWon"] / totals["firstContacts"]) * 100)

    return {
        "gameCount": counts["games"],
        "avgChains": round(totals["chains"] / games, 1),
        "avgDeliverySuccessPct": avg_delivery_pct,
        "avgFirstContactWonPct": avg_fc_pct,
        "avgShots": round(totals["shots"] / games, 2),
        "avgGoals": round(totals["goals"] / games, 2),
        "avgShotXg": round(totals["shotXg"] / games, 2),
    }


def _build_team_metrics(
    iteration_id: int,
    focus_squad_id: int,
    match_id: int,
    *,
    before_match_id: int,
    game_count: int = 7,
) -> list[dict[str, Any]]:
    from app.post_match.report import _flatten_squad_kpis

    recent_ids = _recent_squad_match_ids(
        iteration_id,
        focus_squad_id,
        before_match_id=before_match_id,
        count=game_count,
    )
    match_kpis = _flatten_squad_kpis(
        impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"],
    ).get(focus_squad_id, {})

    rows: list[dict[str, Any]] = []
    for spec in TEAM_METRIC_SPECS:
        kpi_id = int(spec["kpiId"])
        focus_values: list[float] = []
        for recent_id in recent_ids:
            kpis = _flatten_squad_kpis(
                impect_get(v5_path(f"/matches/{recent_id}/squad-kpis"))["data"],
            ).get(focus_squad_id, {})
            value = kpis.get(kpi_id)
            if value is not None:
                focus_values.append(float(value))
        avg_value = _average_metric_values(focus_values)
        match_value = match_kpis.get(kpi_id)
        rank_values = _iteration_kpi_values(iteration_id, kpi_id)
        higher_is_better = bool(spec["higherIsBetter"])
        top7_value = _top7_average(rank_values, higher_is_better=higher_is_better)
        rows.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "metricColor": spec["metricColor"],
                "avgValue": avg_value,
                "avgDisplay": _format_decimal(avg_value),
                "avgRank": _rank_for_value(
                    rank_values,
                    focus_squad_id,
                    higher_is_better=higher_is_better,
                ),
                "top7AvgValue": top7_value,
                "top7AvgDisplay": _format_decimal(top7_value),
                "matchValue": float(match_value) if match_value is not None else None,
                "matchDisplay": _format_decimal(float(match_value))
                if match_value is not None
                else None,
                "matchBand": _performance_band(
                    float(match_value) if match_value is not None else None,
                    avg_value,
                    higher_is_better=higher_is_better,
                ),
                "higherIsBetter": higher_is_better,
            }
        )
    return rows


def _build_side(
    match_id: int,
    attacking_squad_id: int,
    player_names: dict[int, str],
    iteration_id: int | None,
    *,
    before_match_id: int,
    focus_squad_id: int,
    attacking: bool,
) -> dict[str, Any]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    events = events if isinstance(events, list) else []

    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    ekpi_rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    xg_by_event: dict[int, float] = {}
    if isinstance(ekpi_rows, list):
        for row in ekpi_rows:
            if row.get("kpiId") == SHOT_XG_KPI_ID and row.get("eventId") is not None:
                try:
                    xg_by_event[int(row["eventId"])] = float(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue

    chains = _parse_chains(events, attacking_squad_id, player_names, xg_by_event)
    defending = not attacking
    corner_chains = [chain for chain in chains if _is_corner_chain(chain)]
    free_kick_chains = [chain for chain in chains if _is_free_kick_chain(chain)]
    # Attacking-third free kicks only — deep/recycle restarts are out of scope.
    free_kick_chains = [chain for chain in free_kick_chains if _chain_is_delivery_threat(chain)]
    free_kicks_view = _view_from_chains(free_kick_chains, defending=defending)
    free_kicks_view["summary"]["scopeNote"] = (
        "Final-third free kicks only (deep/recycle restarts excluded)."
    )

    return {
        "corners": {
            "left": _view_from_chains(
                _filter_chains(corner_chains, side="left"),
                defending=defending,
            ),
            "right": _view_from_chains(
                _filter_chains(corner_chains, side="right"),
                defending=defending,
            ),
            "all": _view_from_chains(corner_chains, defending=defending),
        },
        "freeKicks": free_kicks_view,
    }


def _empty_view() -> dict[str, Any]:
    return _view_from_chains([])


def _empty_corners() -> dict[str, Any]:
    return {
        "left": _empty_view(),
        "right": _empty_view(),
        "all": _empty_view(),
    }


def build_set_plays(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None,
    *,
    opponent_squad_id: int | None = None,
    opponent_name: str | None = None,
) -> dict[str, Any]:
    empty = {
        "title": "Set Plays",
        "description": "Corners and free kicks · deliveries, first contacts, outcomes",
        "opponentLabel": opponent_name or "Opponent",
        "cornersFor": _empty_corners(),
        "cornersAgainst": _empty_corners(),
        "freeKicksFor": _empty_view(),
        "freeKicksAgainst": _empty_view(),
        "teamMetrics": [],
        "pitch": {},
        "freeKickPitch": {},
        "leagueSize": 24,
    }
    if not iteration_id:
        return empty

    from app.post_match.report import _player_directory

    iteration_id = int(iteration_id)
    player_names = _player_directory(iteration_id)

    attacking = _build_side(
        match_id,
        focus_squad_id,
        player_names,
        iteration_id,
        before_match_id=match_id,
        focus_squad_id=focus_squad_id,
        attacking=True,
    )
    defensive_attacking_squad = opponent_squad_id or focus_squad_id
    defensive = _build_side(
        match_id,
        defensive_attacking_squad,
        player_names,
        iteration_id,
        before_match_id=match_id,
        focus_squad_id=focus_squad_id,
        attacking=False,
    )

    team_metrics = _build_team_metrics(
        iteration_id,
        focus_squad_id,
        match_id,
        before_match_id=match_id,
    )

    return {
        "title": "Set Plays",
        "description": "Corners and free kicks · deliveries, first contacts, outcomes",
        "opponentLabel": opponent_name or "Opponent",
        "cornersFor": attacking["corners"],
        "cornersAgainst": defensive["corners"],
        "freeKicksFor": attacking["freeKicks"],
        "freeKicksAgainst": defensive["freeKicks"],
        "teamMetrics": team_metrics,
        "pitch": {
            "goalX": PITCH_GOAL_X,
            "minX": FINAL_THIRD_MIN_X,
            "widthM": PITCH_WIDTH_M,
            "depthM": PITCH_GOAL_X - FINAL_THIRD_MIN_X,
            "penaltySpotM": 11.0,
            "penaltyArcM": 9.15,
            "penaltyBoxDepthM": 16.5,
        },
        "freeKickPitch": {
            "goalX": PITCH_GOAL_X,
            "minX": -PITCH_GOAL_X,
            "widthM": PITCH_WIDTH_M,
            "depthM": PITCH_GOAL_X * 2,
            "penaltySpotM": 11.0,
            "penaltyArcM": 9.15,
            "penaltyBoxDepthM": 16.5,
            "fullPitch": True,
        },
        "leagueSize": len(_iteration_kpi_values(iteration_id, 1406)) or 24,
    }
