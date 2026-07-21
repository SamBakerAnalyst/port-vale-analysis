from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.pre_match import (
    DEFAULT_COMPETITION,
    PreMatchReportRequest,
    assign_lineup_formation_slots,
    _coords_from_starting_position,
    _fetch_match_detail,
    _format_foot,
    _format_kickoff,
    _match_squad_block,
    _ordinal,
    _player_age,
    _player_display_name,
    _player_match_stats,
    _player_names_map,
    _player_surname,
    _position_label,
    _rank_metric,
    _recent_completed_matches,
    _spread_players_horizontally,
    _squad_kpi_table,
    _squads_map,
    _unwrap_items,
    build_pre_match_fixtures,
    build_pre_match_report,
    pre_match_meta,
)
from app.handout_badges import HANDOUT_BADGE_DIR, enrich_team_badge
from app.scouting import SCOUTING_DIR
from app.scouting import _format_height as format_player_height

UK_TZ = ZoneInfo("Europe/London")

HANDOUT_DEFAULT_SEASON_INDEX = 0
HANDOUT_DEFAULT_OPPONENT_NAMES: tuple[str, ...] = ("Rotherham United", "Rotherham")
HANDOUT_DEFAULT_SEASON_TOKENS: tuple[str, ...] = ("25/26", "2025/26", "2025-26", "2526")
HANDOUT_PREVIOUS_LINEUP_LIMIT = 3
HANDOUT_FORM_LIMIT = 5
HANDOUT_KEY_PLAYER_LIMIT = 10

POSITION_ABBR: dict[str, str] = {
    "GOALKEEPER": "GK",
    "CENTRAL_DEFENDER": "CH",
    "LEFT_WINGBACK_DEFENDER": "LB",
    "RIGHT_WINGBACK_DEFENDER": "RB",
    "DEFENSE_MIDFIELD": "DM",
    "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM",
    "LEFT_WINGER": "LW",
    "RIGHT_WINGER": "RW",
    "CENTER_FORWARD": "CF",
    "SECOND_STRIKER": "SS",
}

PLAYER_ARCHETYPE: dict[str, str] = {
    "GOALKEEPER": "DISTRIBUTOR",
    "CENTRAL_DEFENDER": "PHYSICAL DEFENDER",
    "LEFT_WINGBACK_DEFENDER": "ATTACKING FULLBACK",
    "RIGHT_WINGBACK_DEFENDER": "DEFENSIVE FULLBACK",
    "DEFENSE_MIDFIELD": "BALL PLAYING MIDFIELDER",
    "CENTRAL_MIDFIELD": "BALL PLAYING MIDFIELDER",
    "ATTACKING_MIDFIELD": "CREATIVE FORWARD",
    "LEFT_WINGER": "TECHNICAL WINGER",
    "RIGHT_WINGER": "TECHNICAL WINGER",
    "CENTER_FORWARD": "PHYSICAL STRIKER",
    "SECOND_STRIKER": "CREATIVE FORWARD",
}

DEFAULT_IN_POSSESSION_STYLE = (
    "A possession-based team who look to build out from the back. "
    "Full backs will look to get high with the wide players rolling in centrally."
)
DEFAULT_OUT_OF_POSSESSION_STYLE = (
    "Typically sit in a mid block but have recently been looking to press teams "
    "who are trying to play out from the back."
)

DEFAULT_OPPONENT_KIT: dict[str, str] = {
    "primary": "#FFFFFF",
    "text": "#111111",
    "border": "#111111",
    "gk": "#111111",
    "gk_text": "#F5C518",
    "gk_border": "#F5C518",
}

# Home/outfield kit colours for common opposition sides (keyed by name fragment).
OPPONENT_KITS_BY_KEY: dict[str, dict[str, str]] = {
    "rotherham": {
        "primary": "#E30613",
        "text": "#FFFFFF",
        "border": "#7A0409",
        "gk": "#111111",
        "gk_text": "#F5C518",
        "gk_border": "#F5C518",
    },
    "lincoln": {
        "primary": "#E4002B",
        "text": "#FFFFFF",
        "border": "#8B0018",
        "gk": "#111111",
        "gk_text": "#F5C518",
        "gk_border": "#F5C518",
    },
    "bolton": {
        "primary": "#FFFFFF",
        "text": "#003087",
        "border": "#003087",
        "gk": "#111111",
        "gk_text": "#F5C518",
        "gk_border": "#F5C518",
    },
    "peterborough": {
        "primary": "#0057B8",
        "text": "#FFFFFF",
        "border": "#003366",
        "gk": "#111111",
        "gk_text": "#F5C518",
        "gk_border": "#F5C518",
    },
    "wycombe": {
        "primary": "#009FE3",
        "text": "#FFFFFF",
        "border": "#005A8C",
        "gk": "#111111",
        "gk_text": "#F5C518",
        "gk_border": "#F5C518",
    },
}


def _resolve_opponent_kit(opponent: dict[str, Any]) -> dict[str, str]:
    name = str(opponent.get("name") or "").casefold()
    for key, kit in OPPONENT_KITS_BY_KEY.items():
        if key in name:
            return {**DEFAULT_OPPONENT_KIT, **kit}
    return dict(DEFAULT_OPPONENT_KIT)


class HandoutExportPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    image_data: str = Field(default="", alias="imageData")
    width: int = 0
    height: int = 0


class HandoutExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pages: list[HandoutExportPage] = Field(default_factory=list)
    document_title: str | None = None
    filename: str | None = None


def _ordinal_day(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "TH"
    else:
        suffix = {1: "ST", 2: "ND", 3: "RD"}.get(value % 10, "TH")
    return f"{value}{suffix}"


def _handout_header_datetime(scheduled: str | None) -> tuple[str, str]:
    if not scheduled:
        return "—", "—"
    try:
        normalized = str(scheduled).replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        dt = dt.astimezone(UK_TZ)
        date_line = (
            f"{dt.strftime('%A').upper()} {_ordinal_day(dt.day)} "
            f"{dt.strftime('%B %Y').upper()}"
        )
        time_line = dt.strftime("%I:%M%p").lstrip("0").upper()
        return date_line, time_line
    except (TypeError, ValueError):
        date_label, time_label = _format_kickoff(scheduled)
        return (date_label or "—").upper(), (time_label or "—").upper()


def _position_abbr(position: str | None) -> str:
    code = str(position or "").upper()
    if not code:
        return "—"
    return POSITION_ABBR.get(code, _position_label(position)[:3].upper())


def _height_short(player: dict[str, Any]) -> str:
    for key in ("heightCm", "height", "bodyHeight"):
        raw = player.get(key)
        if raw is None or raw == "":
            continue
        try:
            cm = int(float(raw))
        except (TypeError, ValueError):
            continue
        if cm <= 0:
            continue
        feet = int(cm // 30.48)
        inches = int(round((cm / 2.54) % 12))
        return f"{feet}'{inches}\""
    formatted = format_player_height(player)
    if formatted and "(" in formatted:
        return formatted.split("(", 1)[0].strip()
    return formatted or "—"


def _sum_passes(stats: dict[str, float]) -> float | None:
    for key in ("PASSES", "TOTAL_PASSES", "SUCCESSFUL_PASSES"):
        if key in stats:
            return float(stats[key])
    total = 0.0
    found = False
    for key, value in stats.items():
        if "PASS" not in key or "CROSS" in key:
            continue
        if key.startswith("SUCCESSFUL_PASSES") or key.startswith("UNSUCCESSFUL_PASSES"):
            total += float(value or 0.0)
            found = True
    return total if found else None


def _ppda_value(stats: dict[str, float]) -> float | None:
    for key in ("PPDA", "PPDA_OPPONENT", "PRESSING_PPDA"):
        if key in stats:
            return float(stats[key])
    presses = stats.get("NUMBER_OF_PRESSES")
    conceded_passes = stats.get("CONCEDED_PASSES") or stats.get("OPPONENT_PASSES")
    if presses and conceded_passes and float(presses) > 0:
        return float(conceded_passes) / float(presses)
    return None


def _handout_rankings(iteration_id: int, squad_id: int) -> list[dict[str, Any]]:
    table = _squad_kpi_table(iteration_id)
    specs = (
        {"key": "SHOT_XG", "label": "xG", "subtitle": "(Expected Goals)", "higher_better": True},
        {
            "key": "CONCEDED_SHOT_XG",
            "label": "xGA",
            "subtitle": "",
            "higher_better": False,
        },
        {
            "key": "PASSES",
            "label": "Passes",
            "subtitle": "",
            "higher_better": True,
            "compute": _sum_passes,
        },
        {
            "key": "PPDA",
            "label": "PPDA",
            "subtitle": "(Pressing)",
            "higher_better": False,
            "compute": _ppda_value,
        },
    )
    rankings: list[dict[str, Any]] = []
    stats = table.get(squad_id, {})
    for spec in specs:
        if spec.get("compute"):
            value = spec["compute"](stats)
            rank = None
            if value is not None:
                peer_values: list[tuple[int, float]] = []
                for sid, peer_stats in table.items():
                    peer_value = spec["compute"](peer_stats)
                    if peer_value is None:
                        continue
                    peer_values.append((sid, peer_value))
                if peer_values:
                    peer_values.sort(
                        key=lambda item: item[1],
                        reverse=bool(spec.get("higher_better", True)),
                    )
                    rank_lookup = {sid: index + 1 for index, (sid, _) in enumerate(peer_values)}
                    rank = rank_lookup.get(squad_id)
            rankings.append(
                {
                    "label": spec["label"],
                    "subtitle": spec["subtitle"],
                    "value": round(value, 2) if value is not None else None,
                    "rank": _ordinal(rank) if rank else None,
                }
            )
            continue
        value, rank = _rank_metric(
            table,
            squad_id,
            spec,
            higher_better=bool(spec.get("higher_better", True)),
        )
        rankings.append(
            {
                "label": spec["label"],
                "subtitle": spec["subtitle"],
                "value": round(value, 2) if value is not None else None,
                "rank": rank,
            }
        )
    return rankings


_match_events_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_match_card_cache: dict[int, tuple[float, dict[int, str]]] = {}


def _shirt_map(squad: dict[str, Any]) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for row in squad.get("players") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("id") or 0)
        shirt = row.get("shirtNumber")
        if not player_id or shirt is None:
            continue
        try:
            mapping[player_id] = int(shirt)
        except (TypeError, ValueError):
            continue
    return mapping


def _subbed_off_ids(squad: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for row in squad.get("substitutions") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("substitutionType") or "").upper() != "SUB_OFF":
            continue
        player_id = int(row.get("playerId") or 0)
        if player_id:
            out.add(player_id)
    return out


def _fetch_match_events(match_id: int) -> list[dict[str, Any]]:
    cached = _match_events_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]

    from app import main as impect_main

    raw = impect_main._impect_get(
        f"/v5/{impect_main._api_prefix()}/matches/{match_id}/events"
    )["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    items = raw if isinstance(raw, list) else _unwrap_items(raw)
    events = [item for item in items if isinstance(item, dict)]
    _match_events_cache[match_id] = (now, events)
    return events


def _dismissal_status_by_player(match_id: int, squad_id: int) -> dict[int, str]:
    """Return player_id -> 'sent_off' for red / second yellow dismissals."""
    cached = _match_card_cache.get(match_id)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return dict(cached[1])

    statuses: dict[int, str] = {}
    for event in _fetch_match_events(match_id):
        if int(event.get("squadId") or -1) != int(squad_id):
            continue
        action = str(event.get("action") or event.get("actionType") or "").upper()
        if action not in {"RED_CARD", "SECOND_YELLOW_CARD", "SECOND_YELLOW"}:
            continue
        player = event.get("player") or {}
        player_id = int(player.get("id") or event.get("playerId") or 0)
        if player_id:
            statuses[player_id] = "sent_off"
    _match_card_cache[match_id] = (now, statuses)
    return statuses


def _marker_status(player_id: int, *, subbed_off: set[int], dismissals: dict[int, str]) -> str:
    if dismissals.get(player_id) == "sent_off":
        return "sent_off"
    if player_id in subbed_off:
        return "subbed_off"
    return "normal"


def _layout_predicted_xi_coords(
    players: list[dict[str, Any]],
    *,
    formation_positioned: bool = False,
) -> list[dict[str, Any]]:
    """Keep predicted XI markers inside the pitch; spread only when not formation-slotted."""
    if not players:
        return players

    if not formation_positioned:
        from collections import defaultdict

        by_line: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for player in players:
            line_key = int(round(float(player.get("y_pct") or 50)))
            by_line[line_key].append(player)

        for line_players in by_line.values():
            line_players.sort(
                key=lambda item: (
                    float(item.get("x_pct") or 50),
                    str(item.get("name") or "").casefold(),
                )
            )
            _spread_players_horizontally(line_players, min_gap=15.0, margin=20.0)

    x_margin = 12.0 if formation_positioned else 20.0
    for player in players:
        y_val = float(player.get("y_pct") or 50)
        if y_val >= 84:
            player["y_pct"] = 86.0
        elif y_val <= 20:
            player["y_pct"] = 16.0
        else:
            player["y_pct"] = round(max(16.0, min(86.0, y_val)), 1)

        x_val = float(player.get("x_pct") or 50)
        player["x_pct"] = round(max(x_margin, min(100.0 - x_margin, x_val)), 1)

    return sorted(
        players,
        key=lambda item: (
            float(item.get("y_pct") or 50),
            float(item.get("x_pct") or 50),
            str(item.get("name") or "").casefold(),
        ),
    )


def _lineup_players_from_detail(
    detail: dict[str, Any],
    squad_id: int,
    player_names: dict[int, str],
    *,
    match_id: int | None = None,
) -> list[dict[str, Any]]:
    squad = _match_squad_block(detail, squad_id)
    if not squad:
        return []
    shirts = _shirt_map(squad)
    subbed_off = _subbed_off_ids(squad)
    dismissals = _dismissal_status_by_player(int(match_id), squad_id) if match_id else {}
    players: list[dict[str, Any]] = []
    for row in squad.get("startingPositions") or []:
        if not isinstance(row, dict):
            continue
        player_id = int(row.get("playerId") or 0)
        if not player_id:
            continue
        position = str(row.get("position") or "")
        x_pct, y_pct = _coords_from_starting_position(position, row.get("positionSide"))
        shirt_number = shirts.get(player_id)
        name = player_names.get(player_id, f"Player {player_id}")
        status = _marker_status(player_id, subbed_off=subbed_off, dismissals=dismissals)
        players.append(
            {
                "player_id": player_id,
                "shirt_number": shirt_number,
                "name": name,
                "surname": _player_surname(name).upper(),
                "position": position,
                "position_abbr": _position_abbr(position),
                "x_pct": x_pct,
                "y_pct": y_pct,
                "status": status,
                "subbed_off": status == "subbed_off",
                "sent_off": status == "sent_off",
            }
        )
    players.sort(key=lambda item: (float(item["y_pct"]), float(item["x_pct"])))
    return players


def _match_result_for_squad(match: dict[str, Any], squad_id: int) -> tuple[str, str, str]:
    home_id = int(match.get("homeSquadId") or -1)
    away_id = int(match.get("awaySquadId") or -1)
    goals = match.get("goals") or {}
    home_goals = int((goals.get("home") or {}).get("fullTime") or 0)
    away_goals = int((goals.get("away") or {}).get("fullTime") or 0)
    is_home = home_id == squad_id
    goals_for = home_goals if is_home else away_goals
    goals_against = away_goals if is_home else home_goals
    if goals_for > goals_against:
        result = "WON"
    elif goals_for < goals_against:
        result = "LOST"
    else:
        result = "DREW"
    return result, f"{goals_for}-{goals_against}", "H" if is_home else "A"


def _previous_lineups(
    iteration_id: int,
    squad_id: int,
    player_names: dict[int, str],
    *,
    limit: int = HANDOUT_PREVIOUS_LINEUP_LIMIT,
) -> list[dict[str, Any]]:
    squads = _squads_map(iteration_id)
    lineups: list[dict[str, Any]] = []
    for match in _recent_completed_matches(iteration_id, squad_id, limit=limit):
        detail = _fetch_match_detail(int(match["id"]))
        squad = _match_squad_block(detail, squad_id)
        if not squad:
            continue
        home_id = int(match.get("homeSquadId") or -1)
        away_id = int(match.get("awaySquadId") or -1)
        is_home = home_id == squad_id
        opponent_id = away_id if is_home else home_id
        opponent_name = str(squads.get(opponent_id, {}).get("name") or "Opponent")
        result, score, venue = _match_result_for_squad(match, squad_id)
        players = _lineup_players_from_detail(
            detail,
            squad_id,
            player_names,
            match_id=int(match["id"]),
        )
        if not players:
            continue
        lineups.append(
            {
                "match_id": int(match["id"]),
                "opponent": opponent_name,
                "venue": venue,
                "result": result,
                "score": score,
                "formation": str(squad.get("startingFormation") or "").strip() or None,
                "players": players,
            }
        )
    return list(reversed(lineups))


def _season_squad_appearance_list(
    iteration_id: int,
    squad_id: int,
    players_catalog: list[dict[str, Any]],
    player_names: dict[int, str],
) -> list[dict[str, Any]]:
    """Everyone who played for the squad this season, plus current roster members."""
    match_stats = _player_match_stats(iteration_id, squad_id)
    catalog_by_id = {
        int(player["id"]): player
        for player in players_catalog
        if player.get("id") is not None
    }
    current_ids = {
        int(player["id"])
        for player in players_catalog
        if player.get("id") is not None
        and int(player.get("currentSquadId") or -1) == squad_id
    }
    player_ids = set(match_stats.keys()) | current_ids

    rows: list[dict[str, Any]] = []
    for player_id in player_ids:
        catalog = catalog_by_id.get(player_id, {})
        stats = match_stats.get(player_id, {})
        positions = stats.get("positions") or set()
        primary_position = sorted(positions)[0] if positions else ""
        name = player_names.get(player_id) or _player_display_name(catalog) or f"Player {player_id}"
        rows.append(
            {
                "player_id": player_id,
                "name": name,
                "surname": _player_surname(name),
                "position": _position_label(primary_position) if primary_position else "—",
                "position_abbr": _position_abbr(primary_position),
                "age": _player_age(catalog) if catalog else None,
                "height": _height_short(catalog),
                "foot": _format_foot(catalog.get("leg")) if catalog else "—",
                "appearances": int(stats.get("appearances") or 0),
                "starts": int(stats.get("starts") or 0),
                "minutes": int(round(float(stats.get("minutes") or 0.0))),
                "goals": int(stats.get("goals") or 0),
                "assists": int(stats.get("assists") or 0),
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row.get("minutes") or 0),
            -int(row.get("appearances") or 0),
            str(row.get("name") or "").casefold(),
        )
    )
    return rows


def _appearance_list(
    squad_rows: list[dict[str, Any]],
    players_catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog_by_id = {
        int(player["id"]): player
        for player in players_catalog
        if player.get("id") is not None
    }
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(squad_rows, start=1):
        player_id = int(row["id"])
        catalog = catalog_by_id.get(player_id, {})
        rows.append(
            {
                "number": index,
                "player_id": player_id,
                "name": row["name"],
                "surname": _player_surname(str(row["name"] or "")),
                "position": row.get("position") or "—",
                "position_abbr": _position_abbr(row.get("position_code")),
                "age": row.get("age"),
                "height": _height_short(catalog),
                "foot": row.get("foot") or "—",
                "appearances": row.get("appearances") or 0,
                "starts": row.get("starts") or 0,
                "minutes": row.get("minutes") or 0,
                "goals": row.get("goals") or 0,
                "assists": row.get("assists") or 0,
            }
        )
    return rows


def _key_player_profiles(
    pitch_players: list[dict[str, Any]],
    squad_rows: list[dict[str, Any]],
    players_catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog_by_id = {
        int(player["id"]): player
        for player in players_catalog
        if player.get("id") is not None
    }
    stats_by_id = {int(row["id"]): row for row in squad_rows}
    profiles: list[dict[str, Any]] = []
    for player in pitch_players[:HANDOUT_KEY_PLAYER_LIMIT]:
        player_id = int(player["player_id"])
        catalog = catalog_by_id.get(player_id, {})
        stats = stats_by_id.get(player_id, {})
        position = str(player.get("position") or stats.get("position_code") or "")
        profiles.append(
            {
                "player_id": player_id,
                "shirt_number": player.get("shirt_number") or stats.get("shirt_number"),
                "name": player.get("name") or stats.get("name") or "Player",
                "surname": _player_surname(player.get("name") or "").upper(),
                "archetype": PLAYER_ARCHETYPE.get(position, _position_label(position).upper()),
                "foot": (stats.get("foot") or _format_foot(catalog.get("leg")) or "—").upper(),
                "height": _height_short(catalog),
                "summary": "",
            }
        )
    return profiles


def _form_sequence(form: list[dict[str, Any]], *, limit: int = HANDOUT_FORM_LIMIT) -> list[str]:
    return [str(match.get("result") or "?") for match in form[-limit:]]


def build_pre_match_handout_report(body: PreMatchReportRequest) -> dict[str, Any]:
    base = build_pre_match_report(body)
    iteration_id = int(body.iteration_id)
    squad_id = int(body.squad_id)

    from app import main as impect_main

    players = _unwrap_items(
        impect_main._impect_get(impect_main._players_path(iteration_id))["data"]
    )
    player_names = _player_names_map(players)
    squad_players = [
        player for player in players if int(player.get("currentSquadId") or -1) == squad_id
    ]

    fixture = base.get("fixture") or {}
    opponent = base.get("opponent") or {}
    fixture = {
        **fixture,
        "port_vale": enrich_team_badge(fixture.get("port_vale") or {"name": "Port Vale"}, iteration_id),
        "opponent": enrich_team_badge(
            fixture.get("opponent") or {"id": squad_id, "name": opponent.get("name", "")},
            iteration_id,
        ),
    }
    squad_list = base.get("squad_list") or {}
    pitch_players = list(squad_list.get("pitch_players") or [])
    previous_lineups = _previous_lineups(iteration_id, squad_id, player_names)

    formations = [
        str(lineup.get("formation") or "").strip()
        for lineup in previous_lineups
        if lineup.get("formation")
    ]
    if formations:
        formation = formations[-1]
    else:
        formation = str(squad_list.get("formation") or "").split("/")[0].strip() or None

    predicted_xi_meta: dict[str, Any] = {}
    if previous_lineups:
        latest_source = previous_lineups[-1]
        latest_players = list(latest_source.get("players") or [])
        pool = [
            {
                **player,
                "starts": 90,
                "minutes": 8100,
                "status": "normal",
                "subbed_off": False,
                "sent_off": False,
            }
            for player in latest_players
        ]
        predicted_xi = assign_lineup_formation_slots(pool, formation)
        predicted_xi_meta = {
            "source_match_id": latest_source.get("match_id"),
            "source_opponent": latest_source.get("opponent"),
            "source_venue": latest_source.get("venue"),
            "source_score": latest_source.get("score"),
            "source_result": latest_source.get("result"),
            "formation": formation,
            "squad_name": str(opponent.get("name") or ""),
            "squad_id": squad_id,
        }
    else:
        predicted_xi = assign_lineup_formation_slots(pitch_players, formation)

    shirt_lookup: dict[int, int] = {}
    for match in _recent_completed_matches(iteration_id, squad_id, limit=5):
        detail = _fetch_match_detail(int(match["id"]))
        squad = _match_squad_block(detail, squad_id) or {}
        for player_id, shirt in _shirt_map(squad).items():
            shirt_lookup.setdefault(player_id, shirt)

    for player in predicted_xi:
        player_id = int(player["player_id"])
        catalog = next(
            (row for row in squad_players if int(row.get("id") or 0) == player_id),
            {},
        )
        shirt = shirt_lookup.get(player_id, catalog.get("shirtNumber"))
        try:
            player["shirt_number"] = int(shirt) if shirt is not None else player.get("shirt_number")
        except (TypeError, ValueError):
            player["shirt_number"] = player.get("shirt_number")
        player["surname"] = _player_surname(str(player.get("name") or "")).upper()
        player["status"] = "normal"
        player["subbed_off"] = False
        player["sent_off"] = False

    predicted_xi = _layout_predicted_xi_coords(
        predicted_xi,
        formation_positioned=bool(previous_lineups),
    )
    opponent_kit = _resolve_opponent_kit(opponent)

    appearance_list = _season_squad_appearance_list(
        iteration_id,
        squad_id,
        players,
        player_names,
    )
    for row in appearance_list:
        shirt = shirt_lookup.get(int(row["player_id"]))
        if shirt is not None:
            row["shirt_number"] = shirt
            row["number"] = shirt

    scheduled = fixture.get("scheduled_date")
    date_line, time_line = _handout_header_datetime(scheduled)
    venue_code = "H" if fixture.get("is_home") else "A"
    opponent_name = str(opponent.get("name") or "Opponent").upper()
    header_title = f"OPPOSITION REPORT | {opponent_name} ({venue_code})"

    form = list(base.get("form") or [])
    momentum = form[-HANDOUT_PREVIOUS_LINEUP_LIMIT:]
    rankings = _handout_rankings(iteration_id, squad_id)

    return {
        **base,
        "fixture": fixture,
        "handout": {
            "header_title": header_title,
            "date_line": date_line,
            "time_line": time_line,
            "position_label": (
                f"POSITION: {_ordinal(int(base['opponent']['league_position']))}"
                if base.get("opponent", {}).get("league_position")
                else "POSITION: —"
            ),
            "form_sequence": _form_sequence(form),
            "previous_lineups": previous_lineups,
            "momentum": momentum,
            "predicted_xi": predicted_xi,
            "predicted_xi_meta": predicted_xi_meta,
            "opponent_kit": opponent_kit,
            "formation": formation,
            "appearance_list": appearance_list,
            "team_style": {
                "in_possession": DEFAULT_IN_POSSESSION_STYLE,
                "out_of_possession": DEFAULT_OUT_OF_POSSESSION_STYLE,
            },
            "rankings": rankings,
            "key_players": _key_player_profiles(predicted_xi, base.get("squad") or [], squad_players),
            "availability": {
                "confirmed_out": [],
                "possibly_out": [],
                "suspended": [],
            },
        },
    }


def _season_matches_handout_default(season: str) -> bool:
    text = str(season or "").casefold().replace(" ", "")
    return any(token.casefold().replace(" ", "") in text for token in HANDOUT_DEFAULT_SEASON_TOKENS)


def _pick_handout_iteration(iterations: list[dict[str, Any]]) -> dict[str, Any]:
    for item in iterations:
        season_label = str(item.get("season") or item.get("label") or "")
        if _season_matches_handout_default(season_label):
            return item
    index = min(HANDOUT_DEFAULT_SEASON_INDEX, len(iterations) - 1)
    return iterations[index]


def _opponent_name_matches(name: str, preferred: str) -> bool:
    return preferred.casefold() in str(name or "").casefold()


def _default_handout_fixture(iteration_id: int) -> dict[str, Any] | None:
    fixtures = build_pre_match_fixtures(iteration_id)
    if not fixtures:
        return None

    for preferred_name in HANDOUT_DEFAULT_OPPONENT_NAMES:
        home_match = next(
            (
                fixture
                for fixture in fixtures
                if _opponent_name_matches(
                    str(fixture.get("opponent", {}).get("name") or ""),
                    preferred_name,
                )
                and bool(fixture.get("is_home"))
            ),
            None,
        )
        if home_match:
            return home_match

    for preferred_name in HANDOUT_DEFAULT_OPPONENT_NAMES:
        any_match = next(
            (
                fixture
                for fixture in fixtures
                if _opponent_name_matches(
                    str(fixture.get("opponent", {}).get("name") or ""),
                    preferred_name,
                )
            ),
            None,
        )
        if any_match:
            return any_match

    return None


def handout_meta(competition_name: str = DEFAULT_COMPETITION) -> dict[str, Any]:
    meta = pre_match_meta(competition_name)
    iterations = meta.get("iterations") or []
    if iterations:
        default_iteration = _pick_handout_iteration(iterations)
        meta["default_iteration_id"] = int(default_iteration["id"])
        default_fixture = _default_handout_fixture(int(default_iteration["id"]))
        if default_fixture:
            meta["default_fixture"] = {
                "match_id": default_fixture.get("match_id"),
                "opponent_id": default_fixture.get("opponent", {}).get("id"),
                "opponent_name": default_fixture.get("opponent", {}).get("name"),
                "is_home": bool(default_fixture.get("is_home")),
            }
        else:
            meta["default_fixture"] = None
        meta["default_opponent_names"] = list(HANDOUT_DEFAULT_OPPONENT_NAMES)
    return meta


def register_pre_match_handout_routes(app: FastAPI) -> None:
    @app.get("/pre-match-handout", response_class=HTMLResponse)
    def pre_match_handout_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "pre-match-handout.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Pre-match handout UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/pre-match-handout/meta")
    def pre_match_handout_meta_route(
        competition: str = Query(DEFAULT_COMPETITION, min_length=1),
    ) -> dict[str, Any]:
        return handout_meta(competition)

    @app.get("/api/pre-match-handout/fixtures")
    def pre_match_handout_fixtures(iteration_id: int = Query(..., ge=1)) -> dict[str, Any]:
        return {"fixtures": build_pre_match_fixtures(iteration_id)}

    @app.post("/api/pre-match-handout/report")
    def pre_match_handout_report(body: PreMatchReportRequest) -> dict[str, Any]:
        return build_pre_match_handout_report(body)

    @app.get("/api/pre-match-handout/badge/{squad_id}")
    def pre_match_handout_badge(squad_id: int) -> FileResponse:
        path = HANDOUT_BADGE_DIR / f"{int(squad_id)}.png"
        if not path.is_file() or path.stat().st_size <= 0:
            raise HTTPException(status_code=404, detail="Badge not found.")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/pre-match-handout/export-pdf")
    def pre_match_handout_export_pdf(body: HandoutExportRequest) -> Response:
        from app.handout_export import build_handout_export_pdf
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pdf_bytes = build_handout_export_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = _safe_export_filename(body.filename or "port-vale-pre-match-handout.pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)

    @app.post("/api/pre-match-handout/export-pptx")
    def pre_match_handout_export_pptx(body: HandoutExportRequest) -> Response:
        from app.handout_export import build_handout_export_pptx
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.pages:
            raise HTTPException(status_code=400, detail="No export pages provided.")
        try:
            pptx_bytes = build_handout_export_pptx(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = _safe_export_filename(
            body.filename or "port-vale-pre-match-handout.pptx",
            default_ext=".pptx",
        )
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pptx_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(
            content=pptx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers=headers,
        )
