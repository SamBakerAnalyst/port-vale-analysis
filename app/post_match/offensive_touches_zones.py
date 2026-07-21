from __future__ import annotations

from typing import Any

from app.post_match.impect_client import extract_rows, impect_get, unwrap_match_payload, v5_path
from app.post_match.phase_analysis import _recent_squad_match_ids

OFFENSIVE_TOUCHES_KPI_ID = 92

ZONE_KPI_IDS: dict[str, int] = {
    "FBL": 586,
    "CB": 585,
    "WL": 589,
    "DM": 587,
    "WR": 588,
    "CM": 590,
    "FBR": 584,
    "AM": 591,
    "IB": 594,
    "IBWL": 593,
    "IBWR": 592,
}

ZONE_LABELS: dict[str, str] = {
    "FBL": "Full-Back Left",
    "WL": "Wide Left",
    "IBWL": "In-Behind Wide Left",
    "CB": "Centre-Back",
    "DM": "Defensive-Mid",
    "CM": "Centre-Mid",
    "AM": "Attacking-Mid",
    "IB": "In-Behind Central",
    "FBR": "Full-Back Right",
    "WR": "Wide Right",
    "IBWR": "In-Behind Wide Right",
}

IN_BEHIND_ZONE_CODES = frozenset({"IBC", "IBR", "IBL", "IBWL", "IBWR"})
IN_BEHIND_GROUPS = frozenset({"IB", "IBWL", "IBWR"})

# Source zones on the compact conversion map.
SOURCE_ZONE_IDS: tuple[str, ...] = ("WL", "WR", "AM")

# Attacking packing zones on the deck map (no full-back / centre-back / defensive-mid).
DISPLAY_ZONE_IDS: tuple[str, ...] = (
    "IBWL",
    "IB",
    "IBWR",
    "WL",
    "AM",
    "WR",
    "CM",
)


def _parse_kpi_list(kpis: Any) -> dict[int, float]:
    parsed: dict[int, float] = {}
    if not isinstance(kpis, list):
        return parsed
    for item in kpis:
        if not isinstance(item, dict):
            continue
        kpi_id = item.get("kpiId") if item.get("kpiId") is not None else item.get("id")
        value = item.get("value")
        if kpi_id is None or value is None:
            continue
        try:
            parsed[int(kpi_id)] = float(value)
        except (TypeError, ValueError):
            continue
    return parsed


def _flatten_squad_kpis(raw_data: Any) -> dict[int, dict[int, float]]:
    payload = unwrap_match_payload(raw_data)
    lookup: dict[int, dict[int, float]] = {}

    if payload.get("squadHome") or payload.get("squadAway"):
        for key in ("squadHome", "squadAway"):
            squad = payload.get(key) or {}
            squad_id = squad.get("id")
            if squad_id is None:
                continue
            lookup[int(squad_id)] = _parse_kpi_list(squad.get("kpis"))
        return lookup

    for row in extract_rows(raw_data):
        squad_id = row.get("squadId") or row.get("squad_id")
        if squad_id is None:
            continue
        lookup[int(squad_id)] = _parse_kpi_list(row.get("kpis") or row)

    return lookup


def _player_directory(iteration_id: int) -> dict[int, str]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/players"))
    directory: dict[int, str] = {}
    for row in extract_rows(raw["data"]):
        player_id = row.get("id") or row.get("playerId")
        if player_id is None:
            continue
        name = (
            row.get("commonname")
            or row.get("commonName")
            or f"{row.get('firstname', '')} {row.get('lastname', '')}".strip()
            or f"Player {player_id}"
        )
        directory[int(player_id)] = str(name).strip()
    return directory


PACKING_ZONE_TO_DISPLAY: dict[str, str] = {
    "WL": "WL",
    "WR": "WR",
    "FBL": "FBL",
    "FBR": "FBR",
    "CBC": "CB",
    "CBL": "CB",
    "CBR": "CB",
    "DMC": "DM",
    "DML": "DM",
    "DMR": "DM",
    "CMC": "CM",
    "CML": "CM",
    "CMR": "CM",
    "AMC": "AM",
    "AML": "AM",
    "AMR": "AM",
    "IBC": "IB",
    "IBR": "IB",
    "IBL": "IB",
    "IBWL": "IBWL",
    "IBWR": "IBWR",
}


IN_BEHIND_PASS_TO_DISPLAY: dict[str, str] = {
    "IBC": "IB",
    "IBL": "IBWL",
    "IBR": "IBWR",
    "IBWL": "IBWL",
    "IBWR": "IBWR",
}


def _packing_to_in_behind_display(packing_zone: str | None) -> str | None:
    code = str(packing_zone or "").upper()
    if code not in IN_BEHIND_ZONE_CODES:
        return None
    display = IN_BEHIND_PASS_TO_DISPLAY.get(code)
    if display in IN_BEHIND_GROUPS:
        return display
    return None


def _source_zone_for_packing(packing_zone: str | None) -> str | None:
    code = str(packing_zone or "").upper()
    display = PACKING_ZONE_TO_DISPLAY.get(code)
    if display in SOURCE_ZONE_IDS:
        return display
    return None


def _display_zone_for_packing(packing_zone: str | None) -> str | None:
    code = str(packing_zone or "").upper()
    display = PACKING_ZONE_TO_DISPLAY.get(code)
    if display in DISPLAY_ZONE_IDS:
        return display
    return None


def _zone_touch_counts_from_events(
    match_id: int,
    focus_squad_id: int,
) -> dict[str, float]:
    touch_ids = _offensive_touch_event_ids(match_id)
    events = _fetch_match_events(match_id)
    counts: dict[str, float] = {zone_id: 0.0 for zone_id in DISPLAY_ZONE_IDS}
    for event in events:
        if event.get("squadId") != focus_squad_id:
            continue
        event_id = event.get("id")
        if event_id not in touch_ids:
            continue
        start = event.get("start") or {}
        display = _display_zone_for_packing(start.get("packingZone"))
        if display:
            counts[display] += 1.0
    return counts


def _passes_from_zone_into_in_behind(
    match_id: int,
    focus_squad_id: int,
) -> dict[str, float]:
    events = _fetch_match_events(match_id)
    counts: dict[str, float] = {zone_id: 0.0 for zone_id in SOURCE_ZONE_IDS}
    for event in events:
        if event.get("squadId") != focus_squad_id:
            continue
        if event.get("actionType") != "PASS":
            continue
        end = event.get("end") or {}
        if str(end.get("packingZone") or "") not in IN_BEHIND_ZONE_CODES:
            continue
        start = event.get("start") or {}
        source = _source_zone_for_packing(start.get("packingZone"))
        if source:
            counts[source] += 1.0
    return counts


def _conversion_zones_payload(counts: dict[str, float]) -> list[dict[str, Any]]:
    return [
        {
            "id": zone_id,
            "label": ZONE_LABELS[zone_id],
            "value": round(counts.get(zone_id, 0.0), 1),
        }
        for zone_id in SOURCE_ZONE_IDS
    ]


def _pass_counts_into_in_behind(
    match_id: int,
    focus_squad_id: int,
) -> dict[str, float]:
    events = _fetch_match_events(match_id)
    counts: dict[str, float] = {zone_id: 0.0 for zone_id in IN_BEHIND_GROUPS}
    for event in events:
        if event.get("squadId") != focus_squad_id:
            continue
        if event.get("actionType") != "PASS":
            continue
        end = event.get("end") or {}
        display = _packing_to_in_behind_display(end.get("packingZone"))
        if display:
            counts[display] += 1.0
    return counts


def _zones_payload(
    values: dict[str, float],
    pass_values: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zone_id in DISPLAY_ZONE_IDS:
        is_in_behind = zone_id in IN_BEHIND_GROUPS
        row: dict[str, Any] = {
            "id": zone_id,
            "label": ZONE_LABELS[zone_id],
            "value": round(values.get(zone_id, 0.0), 1),
            "isInBehind": is_in_behind,
        }
        if is_in_behind and pass_values is not None:
            row["passValue"] = round(pass_values.get(zone_id, 0.0), 1)
        rows.append(row)
    return rows


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    events_payload = impect_get(v5_path(f"/matches/{match_id}/events"))["data"]
    events = events_payload.get("data") if isinstance(events_payload, dict) else events_payload
    if not isinstance(events, list):
        return []
    return events


def _offensive_touch_event_ids(match_id: int) -> set[int]:
    ekpi_payload = impect_get(v5_path(f"/matches/{match_id}/event-kpis"))["data"]
    rows = ekpi_payload.get("data") if isinstance(ekpi_payload, dict) else ekpi_payload
    if not isinstance(rows, list):
        return set()
    ids: set[int] = set()
    for row in rows:
        if row.get("kpiId") != OFFENSIVE_TOUCHES_KPI_ID:
            continue
        try:
            if float(row.get("value") or 0) <= 0:
                continue
            ids.add(int(row["eventId"]))
        except (TypeError, ValueError):
            continue
    return ids


def _in_behind_label(zone_code: str) -> str:
    mapping = {
        "IBC": "In-Behind Central",
        "IBL": "In-Behind Wide Left",
        "IBR": "In-Behind Wide Right",
        "IBWL": "In-Behind Wide Left",
        "IBWR": "In-Behind Wide Right",
    }
    return mapping.get(zone_code, zone_code)


def build_in_behind_detail(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int,
) -> dict[str, Any]:
    from app.post_match.report import _iteration_goalkeeper_ids

    players = _player_directory(iteration_id)
    goalkeeper_ids = _iteration_goalkeeper_ids(iteration_id)
    events = _fetch_match_events(match_id)
    touch_ids = _offensive_touch_event_ids(match_id)

    touch_counts: dict[int, dict[str, Any]] = {}
    pass_counts: dict[int, dict[str, Any]] = {}

    for event in events:
        if event.get("squadId") != focus_squad_id:
            continue

        player = event.get("player") or {}
        player_id = player.get("id")
        try:
            player_id_int = int(player_id) if player_id is not None else None
        except (TypeError, ValueError):
            player_id_int = None

        event_id = event.get("id")
        start = event.get("start") or {}
        end = event.get("end") or {}
        start_zone = str(start.get("packingZone") or "")

        if event_id in touch_ids and start_zone in IN_BEHIND_ZONE_CODES:
            if player_id_int is None or player_id_int in goalkeeper_ids:
                continue
            bucket = touch_counts.setdefault(
                player_id_int,
                {
                    "playerId": player_id_int,
                    "playerName": players.get(player_id_int, f"Player {player_id_int}"),
                    "touchCount": 0,
                    "zones": {},
                },
            )
            bucket["touchCount"] += 1
            zone_label = _in_behind_label(start_zone)
            bucket["zones"][zone_label] = bucket["zones"].get(zone_label, 0) + 1

        if event.get("actionType") == "PASS":
            end_zone = str(end.get("packingZone") or "")
            if end_zone not in IN_BEHIND_ZONE_CODES:
                continue
            if player_id_int is None or player_id_int in goalkeeper_ids:
                continue
            pass_bucket = pass_counts.setdefault(
                player_id_int,
                {
                    "playerId": player_id_int,
                    "playerName": players.get(player_id_int, f"Player {player_id_int}"),
                    "passCount": 0,
                    "zones": {},
                },
            )
            pass_bucket["passCount"] += 1
            zone_label = _in_behind_label(end_zone)
            pass_bucket["zones"][zone_label] = pass_bucket["zones"].get(zone_label, 0) + 1

    touch_players = sorted(
        touch_counts.values(),
        key=lambda row: (-row["touchCount"], row["playerName"]),
    )
    pass_players = sorted(
        pass_counts.values(),
        key=lambda row: (-row["passCount"], row["playerName"]),
    )

    return {
        "touchPlayers": touch_players,
        "passPlayers": pass_players,
        "totalTouches": sum(row["touchCount"] for row in touch_players),
        "totalPassesIntoInBehind": sum(row["passCount"] for row in pass_players),
    }


def _average_in_behind_player_rows(
    rows: list[dict[str, Any]],
    games_used: int,
    count_key: str,
) -> list[dict[str, Any]]:
    if games_used <= 0:
        return []
    averaged: list[dict[str, Any]] = []
    for row in rows:
        zones = {
            label: round(count / games_used, 1)
            for label, count in row.get("zones", {}).items()
        }
        averaged.append(
            {
                "playerId": row["playerId"],
                "playerName": row["playerName"],
                count_key: round(row[count_key] / games_used, 1),
                "zones": zones,
            }
        )
    return sorted(
        averaged,
        key=lambda item: (-item[count_key], item["playerName"]),
    )


def build_in_behind_detail_baseline_last_n(
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

    touch_agg: dict[int, dict[str, Any]] = {}
    pass_agg: dict[int, dict[str, Any]] = {}
    games_used = 0

    for match_id in match_ids:
        detail = build_in_behind_detail(match_id, focus_squad_id, iteration_id)
        if not detail["touchPlayers"] and not detail["passPlayers"]:
            continue
        games_used += 1
        for row in detail["touchPlayers"]:
            bucket = touch_agg.setdefault(
                row["playerId"],
                {
                    "playerId": row["playerId"],
                    "playerName": row["playerName"],
                    "touchCount": 0.0,
                    "zones": {},
                },
            )
            bucket["touchCount"] += row["touchCount"]
            for label, count in row["zones"].items():
                bucket["zones"][label] = bucket["zones"].get(label, 0) + count
        for row in detail["passPlayers"]:
            bucket = pass_agg.setdefault(
                row["playerId"],
                {
                    "playerId": row["playerId"],
                    "playerName": row["playerName"],
                    "passCount": 0.0,
                    "zones": {},
                },
            )
            bucket["passCount"] += row["passCount"]
            for label, count in row["zones"].items():
                bucket["zones"][label] = bucket["zones"].get(label, 0) + count

    touch_players = _average_in_behind_player_rows(
        list(touch_agg.values()),
        games_used,
        "touchCount",
    )
    pass_players = _average_in_behind_player_rows(
        list(pass_agg.values()),
        games_used,
        "passCount",
    )

    total_touches = round(
        sum(row["touchCount"] for row in touch_players),
        1,
    )
    total_passes = round(
        sum(row["passCount"] for row in pass_players),
        1,
    )

    return {
        "touchPlayers": touch_players,
        "passPlayers": pass_players,
        "totalTouches": total_touches,
        "totalPassesIntoInBehind": total_passes,
        "gamesUsed": games_used,
    }


def build_offensive_touches_zones(
    match_id: int,
    focus_squad_id: int,
    iteration_id: int | None = None,
) -> dict[str, Any]:
    raw = impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"]
    lookup = _flatten_squad_kpis(raw)
    squad_kpis = lookup.get(focus_squad_id, {})
    values = _zone_touch_counts_from_events(match_id, focus_squad_id)
    pass_into = _pass_counts_into_in_behind(match_id, focus_squad_id)
    conversion = _passes_from_zone_into_in_behind(match_id, focus_squad_id)
    total = squad_kpis.get(OFFENSIVE_TOUCHES_KPI_ID)

    in_behind: dict[str, Any] | None = None
    if iteration_id is not None:
        in_behind = build_in_behind_detail(match_id, focus_squad_id, int(iteration_id))

    return {
        "title": "Offensive Touches by Zone",
        "description": "Touches in in-behind (green) · passes from wide left, att mid & wide right into in-behind (gold)",
        "focusSquadId": focus_squad_id,
        "totalOffensiveTouches": round(float(total), 1) if total is not None else None,
        "totalPassesIntoInBehind": round(sum(pass_into.values()), 1),
        "conversionZones": _conversion_zones_payload(conversion),
        "zones": _zones_payload(values, pass_into),
        "inBehind": in_behind,
    }


def build_offensive_touches_baseline_last_n(
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

    zone_sums: dict[str, float] = {zone_id: 0.0 for zone_id in DISPLAY_ZONE_IDS}
    pass_sums: dict[str, float] = {zone_id: 0.0 for zone_id in IN_BEHIND_GROUPS}
    conversion_sums: dict[str, float] = {zone_id: 0.0 for zone_id in SOURCE_ZONE_IDS}
    total_sum = 0.0
    pass_total_sum = 0.0
    used_match_ids: list[int] = []

    in_behind_baseline: dict[str, Any] | None = None
    if iteration_id:
        in_behind_baseline = build_in_behind_detail_baseline_last_n(
            iteration_id,
            focus_squad_id,
            before_match_id=before_match_id,
            game_count=game_count,
        )

    for match_id in match_ids:
        values = _zone_touch_counts_from_events(match_id, focus_squad_id)
        pass_into = _pass_counts_into_in_behind(match_id, focus_squad_id)
        conversion = _passes_from_zone_into_in_behind(match_id, focus_squad_id)
        raw = impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))["data"]
        lookup = _flatten_squad_kpis(raw)
        squad_kpis = lookup.get(focus_squad_id, {})
        if not squad_kpis and not any(values.values()):
            continue
        for zone_id in DISPLAY_ZONE_IDS:
            zone_sums[zone_id] += values.get(zone_id, 0.0)
        for zone_id in IN_BEHIND_GROUPS:
            pass_sums[zone_id] += pass_into.get(zone_id, 0.0)
        for zone_id in SOURCE_ZONE_IDS:
            conversion_sums[zone_id] += conversion.get(zone_id, 0.0)
        pass_total_sum += sum(pass_into.values())
        total_raw = squad_kpis.get(OFFENSIVE_TOUCHES_KPI_ID)
        if total_raw is not None:
            total_sum += float(total_raw)
        used_match_ids.append(match_id)

    games_used = len(used_match_ids)
    if games_used:
        avg_values = {zone_id: zone_sums[zone_id] / games_used for zone_id in DISPLAY_ZONE_IDS}
        avg_pass = {zone_id: pass_sums[zone_id] / games_used for zone_id in IN_BEHIND_GROUPS}
        avg_conversion = {
            zone_id: conversion_sums[zone_id] / games_used for zone_id in SOURCE_ZONE_IDS
        }
        total_avg = total_sum / games_used
        pass_total_avg = pass_total_sum / games_used
    else:
        avg_values = {zone_id: 0.0 for zone_id in DISPLAY_ZONE_IDS}
        avg_pass = {zone_id: 0.0 for zone_id in IN_BEHIND_GROUPS}
        avg_conversion = {zone_id: 0.0 for zone_id in SOURCE_ZONE_IDS}
        total_avg = 0.0
        pass_total_avg = 0.0

    return {
        "title": f"Last {game_count} games average",
        "gameCount": game_count,
        "gamesUsed": games_used,
        "matchIds": used_match_ids,
        "totalOffensiveTouches": round(total_avg, 1),
        "totalPassesIntoInBehind": round(pass_total_avg, 1),
        "conversionZones": _conversion_zones_payload(avg_conversion),
        "zones": _zones_payload(avg_values, avg_pass),
        "inBehind": in_behind_baseline,
    }
