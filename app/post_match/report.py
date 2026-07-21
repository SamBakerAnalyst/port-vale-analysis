from __future__ import annotations

import re
from typing import Any

from app.post_match.config import PORT_VALE_SQUAD_ID
from app.post_match.field_tilt import build_field_tilt, build_field_tilt_baseline_last_n
from app.post_match.momentum_blocks import build_momentum_blocks
from app.post_match.phase_analysis import build_game_by_phase, build_phase_average_last_n
from app.post_match.ball_progression import build_ball_progression
from app.post_match.crosses import build_crosses
from app.post_match.duels import build_duels
from app.post_match.expected_threat import build_expected_threat
from app.post_match.set_plays import build_set_plays
from app.post_match.shots import build_shots
from app.post_match.shot_xg_consistency import validate_report_shot_xg
from app.post_match.offensive_touches_zones import (
    build_offensive_touches_baseline_last_n,
    build_offensive_touches_zones,
)
from app.post_match.squad_badges import enrich_squad
from app.post_match.xg_race import build_xg_race
from app.post_match.impect_client import (
    extract_rows,
    impect_get,
    unwrap_match_payload,
    v5_path,
)

KPI_BYPASSED_OPPONENTS_RAW = 1399
KPI_BYPASSED_DEFENDERS_RAW = 1400

# Squad comparison uses raw count KPIs so totals match the player breakdown slides.
HIGHLIGHT_KPI_IDS: list[int] = [
    KPI_BYPASSED_DEFENDERS_RAW,  # was 2 (weighted)
    40,  # SUFFERED_BYPASSED_DEFENDERS
    KPI_BYPASSED_OPPONENTS_RAW,  # was 0 (weighted)
    7,   # BYPASSED_OPPONENTS_RECEIVING
    82,  # SHOT_XG
    83,  # PACKING_XG
    1401,  # POSTSHOT_XG
    39,  # SUFFERED_BYPASSED_OPPONENTS
]

PLAYER_BAR_KPI_ID = KPI_BYPASSED_DEFENDERS_RAW

KPI_DISPLAY_LABELS: dict[int, str] = {
    KPI_BYPASSED_DEFENDERS_RAW: "Bypassed Defenders",
    KPI_BYPASSED_OPPONENTS_RAW: "Bypassed Opponents",
}


def humanize_kpi_name(name: str) -> str:
    text = re.sub(r"[_-]+", " ", name).strip()
    return text.title() if text else name


def _kpi_catalog() -> dict[int, dict[str, str]]:
    raw = impect_get(v5_path("/kpis"))
    catalog: dict[int, dict[str, str]] = {}
    for row in extract_rows(raw["data"]):
        kpi_id = row.get("id")
        if kpi_id is None:
            continue
        kpi_id = int(kpi_id)
        name = str(row.get("name") or "").strip()
        details = row.get("details") or {}
        label = str(details.get("label") or "").strip() or humanize_kpi_name(name)
        catalog[kpi_id] = {"name": name, "label": label}
    return catalog


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


def _squad_side(home_id: int, away_id: int, squad_id: int) -> str | None:
    if squad_id == home_id:
        return "home"
    if squad_id == away_id:
        return "away"
    return None


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


def _squad_details(iteration_id: int) -> dict[int, dict[str, Any]]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/squads"))
    directory: dict[int, dict[str, Any]] = {}
    for row in extract_rows(raw["data"]):
        squad_id = row.get("id")
        if squad_id is None:
            continue
        squad_id = int(squad_id)
        name = row.get("name") or row.get("commonName") or f"Squad {squad_id}"
        directory[squad_id] = enrich_squad(
            {
                "name": str(name).strip(),
                "imageUrl": row.get("imageUrl"),
            },
            squad_id,
            iteration_id,
        )
    return directory


def _squad_directory(iteration_id: int) -> dict[int, str]:
    return {sid: info["name"] for sid, info in _squad_details(iteration_id).items()}


def _iteration_match_row(iteration_id: int, match_id: int) -> dict[str, Any]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/matches"))
    for row in extract_rows(raw["data"]):
        if int(row.get("id") or 0) == match_id:
            return row
    return {}


def _match_meta(match_id: int, iteration_id: int | None = None) -> dict[str, Any]:
    raw = impect_get(v5_path(f"/matches/{match_id}"))
    payload = unwrap_match_payload(raw["data"]) or {}

    iter_id = iteration_id or payload.get("iterationId")
    match_row: dict[str, Any] = {}
    squad_names: dict[int, str] = {}
    squad_details: dict[int, dict[str, Any]] = {}
    if iter_id:
        iter_id = int(iter_id)
        match_row = _iteration_match_row(iter_id, match_id)
        squad_names = _squad_directory(iter_id)
        squad_details = _squad_details(iter_id)

    home_id = int(
        match_row.get("homeSquadId")
        or (payload.get("squadHome") or {}).get("id")
        or 0
    )
    away_id = int(
        match_row.get("awaySquadId")
        or (payload.get("squadAway") or {}).get("id")
        or 0
    )

    goals = match_row.get("goals") or {}
    home_goals = (goals.get("home") or {}).get("fullTime")
    away_goals = (goals.get("away") or {}).get("fullTime")

    home_detail = squad_details.get(home_id, {}) if iter_id else {}
    away_detail = squad_details.get(away_id, {}) if iter_id else {}

    return {
        "matchId": match_id,
        "iterationId": iter_id,
        "scheduledDate": match_row.get("scheduledDate") or payload.get("dateTime"),
        "matchDay": (match_row.get("matchDay") or {}).get("index") or match_row.get("matchDay"),
        "result": match_row.get("result"),
        "home": {
            "squadId": home_id or None,
            "name": squad_names.get(home_id) or (payload.get("squadHome") or {}).get("name"),
            "score": home_goals,
            "imageUrl": home_detail.get("imageUrl"),
            "badgeUrl": home_detail.get("badgeUrl"),
            "initials": home_detail.get("initials"),
        },
        "away": {
            "squadId": away_id or None,
            "name": squad_names.get(away_id) or (payload.get("squadAway") or {}).get("name"),
            "score": away_goals,
            "imageUrl": away_detail.get("imageUrl"),
            "badgeUrl": away_detail.get("badgeUrl"),
            "initials": away_detail.get("initials"),
        },
        "competitionId": match_row.get("competitionId") or payload.get("competitionId"),
        "idMappings": match_row.get("idMappings") or [],
    }


def _flatten_player_kpis(
    raw_data: Any,
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    payload = unwrap_match_payload(raw_data)
    rows: list[dict[str, Any]] = []

    if payload.get("squadHome") or payload.get("squadAway"):
        for squad_key in ("squadHome", "squadAway"):
            squad = payload.get(squad_key) or {}
            squad_id = squad.get("id")
            squad_name = squad.get("name")
            for player in squad.get("players") or []:
                if not isinstance(player, dict):
                    continue
                player_id = player.get("id") or player.get("playerId")
                if player_id is None:
                    continue
                player_id = int(player_id)
                rows.append(
                    {
                        "playerId": player_id,
                        "name": player_names.get(player_id, f"Player {player_id}"),
                        "squadId": int(squad_id) if squad_id is not None else None,
                        "squadName": squad_name,
                        "shirtNumber": player.get("shirtNumber"),
                        "position": player.get("position"),
                        "minutes": player.get("playedMinutes") or player.get("playDuration"),
                        "kpis": _parse_kpi_list(player.get("kpis")),
                    }
                )
        return rows

    for row in extract_rows(raw_data):
        player_id = row.get("playerId") or row.get("id")
        if player_id is None:
            continue
        player_id = int(player_id)
        rows.append(
            {
                "playerId": player_id,
                "name": player_names.get(player_id, row.get("name") or f"Player {player_id}"),
                "squadId": row.get("squadId"),
                "squadName": row.get("squadName"),
                "shirtNumber": row.get("shirtNumber"),
                "position": row.get("position"),
                "minutes": row.get("playedMinutes") or row.get("playDuration"),
                "kpis": _parse_kpi_list(row.get("kpis") or row),
            }
        )
    return rows


def _pick_highlight_kpis(
    catalog: dict[int, dict[str, str]],
    squad_kpis: dict[int, dict[int, float]],
) -> list[int]:
    available: set[int] = set()
    for kpis in squad_kpis.values():
        available.update(kpis.keys())

    ordered: list[int] = []
    for kpi_id in HIGHLIGHT_KPI_IDS:
        if kpi_id in available:
            ordered.append(kpi_id)

    if len(ordered) < 6:
        for kpi_id in sorted(available):
            if kpi_id not in ordered:
                ordered.append(kpi_id)
            if len(ordered) >= 8:
                break

    return ordered[:8]


def _is_goalkeeper_position(position: Any) -> bool:
    text = str(position or "").upper().replace("_", " ").strip()
    return text in {"GOALKEEPER", "GK", "GOAL KEEPER"}


def _exclude_goalkeepers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not _is_goalkeeper_position(row.get("position"))]


def _iteration_goalkeeper_ids(iteration_id: int) -> set[int]:
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/players"))
    goalkeeper_ids: set[int] = set()
    for row in extract_rows(raw["data"]):
        player_id = row.get("id") or row.get("playerId")
        if player_id is None:
            continue
        if _is_goalkeeper_position(row.get("position")):
            goalkeeper_ids.add(int(player_id))
    return goalkeeper_ids


def _exclude_goalkeeper_ids(
    rows: list[dict[str, Any]],
    goalkeeper_ids: set[int],
    *,
    player_id_key: str = "playerId",
) -> list[dict[str, Any]]:
    if not goalkeeper_ids:
        return rows
    return [
        row
        for row in rows
        if int(row.get(player_id_key) or 0) not in goalkeeper_ids
    ]


def _combine_stint_kpi_values(values: list[float]) -> float:
    """Merge KPI values across position stints for one player in a match."""
    if not values:
        return 0.0
    if len(values) > 1 and len(set(values)) == 1:
        # Match-total KPI duplicated on each position row (e.g. raw defender bypass count).
        return values[0]
    return sum(values)


def _consolidate_player_match_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge Impect position-stint rows into one row per player with raw match totals."""
    grouped: dict[int, dict[str, Any]] = {}
    kpi_stints: dict[int, dict[int, list[float]]] = {}

    for row in rows:
        player_id = int(row["playerId"])
        if player_id not in grouped:
            grouped[player_id] = {
                "playerId": player_id,
                "name": row["name"],
                "squadId": row.get("squadId"),
                "squadName": row.get("squadName"),
                "shirtNumber": row.get("shirtNumber"),
                "position": row.get("position"),
                "minutes": 0.0,
                "kpis": {},
            }
            kpi_stints[player_id] = {}

        bucket = grouped[player_id]
        stint_seconds = float(row.get("minutes") or 0)
        bucket["minutes"] += stint_seconds
        if stint_seconds >= float(bucket.get("_max_stint_seconds") or 0):
            bucket["_max_stint_seconds"] = stint_seconds
            bucket["position"] = row.get("position")
            bucket["shirtNumber"] = row.get("shirtNumber")

        for kpi_id, value in (row.get("kpis") or {}).items():
            kpi_key = int(kpi_id)
            kpi_stints[player_id].setdefault(kpi_key, []).append(float(value))

    consolidated: list[dict[str, Any]] = []
    for player_id, bucket in grouped.items():
        bucket["kpis"] = {
            kpi_id: _combine_stint_kpi_values(values)
            for kpi_id, values in kpi_stints[player_id].items()
        }
        bucket.pop("_max_stint_seconds", None)
        consolidated.append(bucket)

    return _exclude_goalkeepers(consolidated)


def _top_players_for_kpi(
    players: list[dict[str, Any]],
    squad_id: int,
    kpi_id: int,
    limit: int = 15,
) -> list[dict[str, Any]]:
    squad_players = _consolidate_player_match_rows(
        [p for p in players if int(p.get("squadId") or 0) == squad_id]
    )
    ranked = sorted(
        squad_players,
        key=lambda p: p.get("kpis", {}).get(kpi_id, 0),
        reverse=True,
    )
    top = [p for p in ranked if p.get("kpis", {}).get(kpi_id, 0) > 0][:limit]
    seen: set[int] = set()
    unique_top: list[dict[str, Any]] = []
    for p in top:
        pid = int(p["playerId"])
        if pid in seen:
            continue
        seen.add(pid)
        unique_top.append(p)
    return [
        {
            "playerId": p["playerId"],
            "name": p["name"],
            "shirtNumber": p.get("shirtNumber"),
            "position": p.get("position"),
            "value": int(round(p["kpis"].get(kpi_id, 0))),
        }
        for p in unique_top
    ]


def build_match_report(
    match_id: int,
    focus_squad_id: int = PORT_VALE_SQUAD_ID,
    iteration_id: int | None = None,
) -> dict[str, Any]:
    catalog = _kpi_catalog()
    meta = _match_meta(match_id, iteration_id=iteration_id)
    iter_id = meta.get("iterationId")
    player_names: dict[int, str] = {}
    if iter_id:
        player_names = _player_directory(int(iter_id))

    squad_raw = impect_get(v5_path(f"/matches/{match_id}/squad-kpis"))
    squad_kpis = _flatten_squad_kpis(squad_raw["data"])

    player_raw = impect_get(v5_path(f"/matches/{match_id}/player-kpis"))
    players = _flatten_player_kpis(player_raw["data"], player_names)

    home_id = int(meta["home"]["squadId"] or 0)
    away_id = int(meta["away"]["squadId"] or 0)
    opponent_id = away_id if focus_squad_id == home_id else home_id

    highlight_ids = _pick_highlight_kpis(catalog, squad_kpis)
    squad_compare = []
    for kpi_id in highlight_ids:
        info = catalog.get(kpi_id, {})
        squad_compare.append(
            {
                "kpiId": kpi_id,
                "label": KPI_DISPLAY_LABELS.get(kpi_id)
                or info.get("label")
                or humanize_kpi_name(info.get("name", str(kpi_id))),
                "home": squad_kpis.get(home_id, {}).get(kpi_id),
                "away": squad_kpis.get(away_id, {}).get(kpi_id),
                "focus": squad_kpis.get(focus_squad_id, {}).get(kpi_id),
                "opponent": squad_kpis.get(opponent_id, {}).get(kpi_id),
                "format": "int" if kpi_id in (KPI_BYPASSED_DEFENDERS_RAW, KPI_BYPASSED_OPPONENTS_RAW) else "decimal",
            }
        )

    bar_kpi_id = PLAYER_BAR_KPI_ID if PLAYER_BAR_KPI_ID in catalog else highlight_ids[0]
    bar_info = catalog.get(bar_kpi_id, {})
    player_bars = _top_players_for_kpi(players, focus_squad_id, bar_kpi_id)

    focus_side = _squad_side(home_id, away_id, focus_squad_id)

    xg_race = build_xg_race(
        match_id,
        home_squad_id=home_id,
        away_squad_id=away_id,
        home_name=meta["home"].get("name"),
        away_name=meta["away"].get("name"),
    )
    # Port Vale = focus team → green line (away in Stockport fixture).
    if focus_squad_id == home_id:
        xg_race["home"]["color"] = "#22c55e"
        xg_race["away"]["color"] = "#3b82f6"
    else:
        xg_race["home"]["color"] = "#3b82f6"
        xg_race["away"]["color"] = "#22c55e"

    game_by_phase = build_game_by_phase(match_id, focus_squad_id)
    if iter_id:
        game_by_phase["baseline"] = build_phase_average_last_n(
            int(iter_id),
            focus_squad_id,
            before_match_id=match_id,
            game_count=7,
        )
    momentum_blocks = build_momentum_blocks(
        match_id,
        home_squad_id=home_id,
        away_squad_id=away_id,
        focus_squad_id=focus_squad_id,
        home_name=meta["home"].get("name"),
        away_name=meta["away"].get("name"),
    )
    field_tilt = build_field_tilt(
        match_id,
        home_squad_id=home_id,
        away_squad_id=away_id,
        focus_squad_id=focus_squad_id,
        home_name=meta["home"].get("name"),
        away_name=meta["away"].get("name"),
    )
    if iter_id:
        field_tilt["baseline"] = build_field_tilt_baseline_last_n(
            int(iter_id),
            focus_squad_id,
            before_match_id=match_id,
            game_count=7,
        )

    offensive_touches = build_offensive_touches_zones(
        match_id,
        focus_squad_id,
        iteration_id=int(iter_id) if iter_id else None,
    )
    if iter_id:
        offensive_touches["baseline"] = build_offensive_touches_baseline_last_n(
            int(iter_id),
            focus_squad_id,
            before_match_id=match_id,
            game_count=7,
        )

    opponent_name = meta["away"]["name"] if focus_squad_id == home_id else meta["home"]["name"]
    ball_progression = build_ball_progression(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_name=opponent_name,
        game_count=7,
    )
    expected_threat = build_expected_threat(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_name=opponent_name,
        game_count=7,
    )
    crosses = build_crosses(
        match_id,
        focus_squad_id,
        iteration_id=int(iter_id) if iter_id else None,
    )
    opponent_crosses = build_crosses(
        match_id,
        focus_squad_id,
        iteration_id=int(iter_id) if iter_id else None,
        opponent_squad_id=opponent_id,
        title="Out of Possession — Crosses",
        defensive=True,
    )
    shots = build_shots(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_name=opponent_name,
        game_count=7,
    )
    shots_against = build_shots(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_name=opponent_name,
        opponent_squad_id=opponent_id,
        game_count=7,
        title="Out of Possession — Shots",
        defensive=True,
    )
    duels = build_duels(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_name=opponent_name,
        game_count=7,
    )
    set_plays = build_set_plays(
        match_id,
        focus_squad_id,
        int(iter_id) if iter_id else None,
        opponent_squad_id=opponent_id,
        opponent_name=opponent_name,
    )

    report = {
        "meta": meta,
        "focusSquadId": focus_squad_id,
        "focusSide": focus_side,
        "opponentSquadId": opponent_id,
        "xgRace": xg_race,
        "gameByPhase": game_by_phase,
        "momentumBlocks": momentum_blocks,
        "fieldTilt": field_tilt,
        "offensiveTouchesZones": offensive_touches,
        "ballProgression": ball_progression,
        "expectedThreat": expected_threat,
        "crosses": crosses,
        "opponentCrosses": opponent_crosses,
        "shots": shots,
        "shotsAgainst": shots_against,
        "setPlays": set_plays,
        "duels": duels,
        "squadCompare": squad_compare,
        "playerBars": {
            "kpiId": bar_kpi_id,
            "label": bar_info.get("label") or humanize_kpi_name(bar_info.get("name", "")),
            "players": player_bars,
        },
        "sources": {
            "impect": True,
            "fotmob": False,
            "fbref": False,
            "soccerstats": False,
        },
    }
    validate_report_shot_xg(report)
    return report
