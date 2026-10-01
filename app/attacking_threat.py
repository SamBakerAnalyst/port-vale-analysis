"""Attacking threat — how Port Vale create Impect PXT, and where they rank.

League rank uses squad KPI 1633 (PXT attack): the figure What Wins Games ranks
as the second-strongest link to winning League Two matches.

Actions, phases, zones and the pass map come from positive event-level packing
threat, so a low cross can be separated from a low pass.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from app.attacking_threat_chains import build_insights
from app.paths import STANDALONE_DIR
from app.post_match.offensive_touches_zones import PACKING_ZONE_TO_DISPLAY, ZONE_LABELS
from app.post_match.phase_analysis import PHASE_COLORS, PHASE_LABELS, PHASE_ORDER, _phase_bucket

logger = logging.getLogger(__name__)

KPI_PXT_ATTACK = 1633
THREAT_KPIS = {1404, 1405, 1406, 1408, 1409}
COMPONENT_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "pass", "label": "Passes", "kpiId": 1404},
    {"id": "dribble", "label": "Dribbles", "kpiId": 1405},
    {"id": "shot", "label": "Shots", "kpiId": 1408},
    {"id": "setPiece", "label": "Set pieces", "kpiId": 1406},
    {"id": "ballWin", "label": "Ball wins", "kpiId": 1409},
)
MIN_MAP_PXT = 0.02
MAX_MAP_EVENTS = 90
ALLOWED_SEASONS = ("26/27", "25/26")
WHY = (
    "Attacking threat is the second strongest link to winning League Two games, "
    "behind xG difference. It is the threat we add while we have the ball."
)
ACTION_LABELS = {
    "LOW_CROSS": "Low cross",
    "HIGH_CROSS": "High cross",
    "LOW_PASS": "Low pass",
    "HIGH_PASS": "High pass",
    "DIAGONAL_PASS": "Diagonal pass",
    "CHIPPED_PASS": "Chipped pass",
    "SHORT_AERIAL_PASS": "Short aerial pass",
    "LAY_OFF": "Lay-off",
    "THROUGH_BALL": "Through ball",
    "DRIBBLE": "Dribble",
    "CORNER": "Corner",
    "FREE_KICK": "Free kick",
    "THROW_IN": "Throw-in",
    "GOAL_KICK": "Goal kick",
    "PENALTY_KICK": "Penalty",
    "HEADER": "Header",
    "BALL_WIN": "Ball win",
    "LOOSE_BALL_REGAIN": "Loose-ball regain",
    "INTERCEPTION": "Interception",
    "SHOT": "Shot",
    "CLOSE_RANGE_SHOT": "Close-range shot",
    "MID_RANGE_SHOT": "Mid-range shot",
    "LONG_RANGE_SHOT": "Long-range shot",
}
FAMILY_COLORS = {
    "cross": "#38bdf8",
    "pass": "#34d399",
    "dribble": "#f97316",
    "shot": "#ef4444",
    "setPiece": "#c084fc",
    "regain": "#fbbf24",
    "other": "#94a3b8",
}
ZONE_CENTROIDS = {
    "FBL": (-28.0, 22.0),
    "CB": (-36.0, 0.0),
    "FBR": (-28.0, -22.0),
    "WL": (-4.0, 26.0),
    "DM": (-10.0, 0.0),
    "WR": (-4.0, -26.0),
    "CM": (8.0, 0.0),
    "AM": (24.0, 0.0),
    "IBWL": (40.0, 24.0),
    "IB": (42.0, 0.0),
    "IBWR": (40.0, -24.0),
}
_league_lock = threading.Lock()
_league_running: set[str] = set()


def _impect():
    from app import main as impect_main

    return impect_main


def action_label(action: str) -> str:
    key = str(action or "").strip().upper() or "OTHER"
    if key in ACTION_LABELS:
        return ACTION_LABELS[key]
    text = key.replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:] if text else "Other"


def action_family(action: str) -> str:
    key = str(action or "").strip().upper()
    if "CROSS" in key:
        return "cross"
    if key in {"CORNER", "FREE_KICK", "THROW_IN", "GOAL_KICK", "PENALTY", "PENALTY_KICK"}:
        return "setPiece"
    if "DRIBBLE" in key or key == "TAKE_ON":
        return "dribble"
    if "SHOT" in key or key in {"HEADER", "ONE_ON_ONE"}:
        return "shot"
    if any(token in key for token in ("BALL_WIN", "INTERCEPT", "REGAIN", "TACKLE", "DUEL")):
        return "regain"
    if "PASS" in key or key in {"LAY_OFF", "THROUGH_BALL", "SWITCH"}:
        return "pass"
    return "other"


def _player_name(player: dict[str, Any] | None) -> str:
    player = player or {}
    name = str(player.get("commonname") or player.get("commonName") or player.get("name") or "").strip()
    if name:
        return name
    return f"{player.get('firstname') or ''} {player.get('lastname') or ''}".strip()


def _coords(point: dict[str, Any] | None) -> tuple[float, float] | None:
    coords = (point or {}).get("adjCoordinates") or (point or {}).get("coordinates") or {}
    try:
        return float(coords["x"]), float(coords["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _zone_code(point: dict[str, Any] | None) -> str:
    raw = str((point or {}).get("packingZone") or "").strip().upper()
    return PACKING_ZONE_TO_DISPLAY.get(raw, raw) if raw else ""


def threat_by_event(event_kpis: list[dict[str, Any]]) -> dict[int, float]:
    totals: dict[int, float] = defaultdict(float)
    for row in event_kpis:
        try:
            kpi_id = int(row.get("kpiId") if row.get("kpiId") is not None else -1)
            event_id = int(row.get("eventId") or 0)
            value = float(row.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if kpi_id not in THREAT_KPIS or event_id <= 0 or value <= 0:
            continue
        totals[event_id] += value
    return dict(totals)


def _empty_squad() -> dict[str, Any]:
    return {
        "total": 0.0, "count": 0, "actions": {}, "actionCounts": {}, "phases": {},
        "zonesStart": {}, "zonesEnd": {}, "players": {}, "passes": [],
    }


def summarize_match(events: list[dict[str, Any]], event_kpis: list[dict[str, Any]]) -> dict[str, Any]:
    threat = threat_by_event(event_kpis)
    squads: dict[str, dict[str, Any]] = {}
    for event in events:
        try:
            event_id = int(event.get("id") or 0)
            squad_id = int(event.get("squadId") or 0)
        except (TypeError, ValueError):
            continue
        pxt = float(threat.get(event_id) or 0.0)
        if event_id <= 0 or squad_id <= 0 or pxt <= 0:
            continue
        bucket = squads.setdefault(str(squad_id), _empty_squad())
        action = str(event.get("action") or event.get("actionType") or "OTHER").upper()
        attacking = event.get("currentAttackingSquadId")
        try:
            attacking_id = int(attacking) if attacking is not None else squad_id
        except (TypeError, ValueError):
            attacking_id = squad_id
        phase = _phase_bucket(str(event.get("phase") or "") or None, attacking_id, squad_id) or "OTHER"
        start = event.get("start") if isinstance(event.get("start"), dict) else {}
        end = event.get("end") if isinstance(event.get("end"), dict) else {}
        start_zone = _zone_code(start)
        end_zone = _zone_code(end)
        player = event.get("player") if isinstance(event.get("player"), dict) else {}
        try:
            player_id = int(player.get("id") or event.get("playerId") or 0)
        except (TypeError, ValueError):
            player_id = 0
        name = _player_name(player)
        family = action_family(action)
        bucket["total"] += pxt
        bucket["count"] += 1
        bucket["actions"][action] = float(bucket["actions"].get(action) or 0) + pxt
        bucket["actionCounts"][action] = int(bucket["actionCounts"].get(action) or 0) + 1
        bucket["phases"][phase] = float(bucket["phases"].get(phase) or 0) + pxt
        if start_zone:
            bucket["zonesStart"][start_zone] = float(bucket["zonesStart"].get(start_zone) or 0) + pxt
        if end_zone:
            bucket["zonesEnd"][end_zone] = float(bucket["zonesEnd"].get(end_zone) or 0) + pxt
        if player_id:
            row = bucket["players"].setdefault(
                str(player_id),
                {"id": player_id, "name": name or f"Player {player_id}", "pxt": 0.0, "count": 0},
            )
            if name:
                row["name"] = name
            row["pxt"] += pxt
            row["count"] += 1
        start_xy = _coords(start)
        end_xy = _coords(end)
        if start_xy and not end_xy and family == "shot":
            end_xy = (52.5, start_xy[1] * 0.35)
        if start_xy and end_xy and pxt >= MIN_MAP_PXT:
            bucket["passes"].append({
                "id": event_id, "action": action, "label": action_label(action), "family": family,
                "color": FAMILY_COLORS.get(family, FAMILY_COLORS["other"]), "pxt": round(pxt, 4),
                "x1": round(start_xy[0], 2), "y1": round(start_xy[1], 2),
                "x2": round(end_xy[0], 2), "y2": round(end_xy[1], 2),
                "phase": phase, "player": name, "playerId": player_id,
                "startZone": start_zone, "endZone": end_zone,
            })
    for bucket in squads.values():
        bucket["passes"].sort(key=lambda row: float(row["pxt"]), reverse=True)
        bucket["passes"] = bucket["passes"][:MAX_MAP_EVENTS]
        bucket["total"] = round(float(bucket["total"]), 4)
        for key in ("actions", "phases", "zonesStart", "zonesEnd"):
            bucket[key] = {name: round(float(value), 4) for name, value in bucket[key].items()}
        for row in bucket["players"].values():
            row["pxt"] = round(float(row["pxt"]), 4)
    return {"squads": squads}


def _merge_number_map(into: dict[str, float], extra: dict[str, Any]) -> None:
    for key, value in (extra or {}).items():
        into[str(key)] = float(into.get(str(key)) or 0) + float(value or 0)


def merge_summaries(parts: list[dict[str, Any]], *, keep_passes: bool) -> dict[str, Any]:
    merged = _empty_squad()
    for part in parts:
        if not part:
            continue
        merged["total"] += float(part.get("total") or 0)
        merged["count"] += int(part.get("count") or 0)
        _merge_number_map(merged["actions"], part.get("actions") or {})
        _merge_number_map(merged["actionCounts"], part.get("actionCounts") or {})
        _merge_number_map(merged["phases"], part.get("phases") or {})
        _merge_number_map(merged["zonesStart"], part.get("zonesStart") or {})
        _merge_number_map(merged["zonesEnd"], part.get("zonesEnd") or {})
        for key, row in (part.get("players") or {}).items():
            current = merged["players"].setdefault(
                str(key),
                {"id": int(row.get("id") or key), "name": row.get("name") or f"Player {key}", "pxt": 0.0, "count": 0},
            )
            if row.get("name"):
                current["name"] = row["name"]
            current["pxt"] += float(row.get("pxt") or 0)
            current["count"] += int(row.get("count") or 0)
        if keep_passes:
            merged["passes"].extend(list(part.get("passes") or []))
    merged["passes"].sort(key=lambda row: float(row.get("pxt") or 0), reverse=True)
    merged["passes"] = merged["passes"][:MAX_MAP_EVENTS]
    merged["total"] = round(merged["total"], 4)
    return merged


def _rank_desc(values: dict[int, float]) -> dict[int, int]:
    ordered = sorted(values.items(), key=lambda item: (-float(item[1]), int(item[0])))
    return {squad_id: index for index, (squad_id, _) in enumerate(ordered, start=1)}


def _per_game(total: float, games: int) -> float:
    return round(float(total) / games, 3) if games > 0 else 0.0


def _share(part: float, total: float) -> float:
    return round(100.0 * float(part) / float(total), 1) if total > 0 else 0.0


def _zone_rows(totals: dict[str, float], games: int) -> list[dict[str, Any]]:
    grand = sum(float(value) for value in totals.values())
    rows = []
    for code, value in totals.items():
        centre = ZONE_CENTROIDS.get(code)
        rows.append({
            "id": code,
            "label": ZONE_LABELS.get(code, action_label(code)),
            "total": round(float(value), 3),
            "perGame": _per_game(float(value), games),
            "share": _share(float(value), grand),
            "x": centre[0] if centre else None,
            "y": centre[1] if centre else None,
        })
    rows.sort(key=lambda row: (-float(row["total"]), str(row["label"])))
    return rows


def _action_rows(summary: dict[str, Any], games: int, league_ranks: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    total = float(summary.get("total") or 0)
    counts = summary.get("actionCounts") or {}
    rows = []
    for action, value in (summary.get("actions") or {}).items():
        family = action_family(str(action))
        league = (league_ranks or {}).get(action) or {}
        rows.append({
            "action": action,
            "label": action_label(str(action)),
            "family": family,
            "color": FAMILY_COLORS.get(family, FAMILY_COLORS["other"]),
            "total": round(float(value), 3),
            "perGame": _per_game(float(value), games),
            "share": _share(float(value), total),
            "count": int(float(counts.get(action) or 0)),
            "rank": league.get("rank"),
            "of": league.get("of"),
            "leaguePerGame": league.get("leaguePerGame"),
        })
    rows.sort(key=lambda row: (-float(row["total"]), str(row["label"])))
    return rows


def _phase_rows(summary: dict[str, Any], games: int, league_ranks: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    total = float(summary.get("total") or 0)
    order = {key: index for index, key in enumerate(PHASE_ORDER)}
    rows = []
    for phase, value in (summary.get("phases") or {}).items():
        if float(value) <= 0:
            continue
        league = (league_ranks or {}).get(phase) or {}
        rows.append({
            "id": phase,
            "label": PHASE_LABELS.get(phase, action_label(str(phase))),
            "color": PHASE_COLORS.get(phase, "#94a3b8"),
            "total": round(float(value), 3),
            "perGame": _per_game(float(value), games),
            "share": _share(float(value), total),
            "rank": league.get("rank"),
            "of": league.get("of"),
            "leaguePerGame": league.get("leaguePerGame"),
        })
    rows.sort(key=lambda row: (order.get(str(row["id"]), 99), -float(row["total"])))
    return rows


def _player_rows(summary: dict[str, Any], games: int) -> list[dict[str, Any]]:
    rows = [{
        "id": int(row.get("id") or 0),
        "name": row.get("name") or "Player",
        "total": round(float(row.get("pxt") or 0), 3),
        "perGame": _per_game(float(row.get("pxt") or 0), games),
        "count": int(row.get("count") or 0),
        "share": _share(float(row.get("pxt") or 0), float(summary.get("total") or 0)),
    } for row in (summary.get("players") or {}).values()]
    rows.sort(key=lambda item: (-float(item["total"]), str(item["name"])))
    return rows[:18]


def build_league_table(kpi_table: dict[int, dict[int, float]], played: dict[int, int], names: dict[int, str], focus_squad_id: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for squad_id, stats in kpi_table.items():
        games = int(played.get(int(squad_id)) or 0)
        if games <= 0:
            continue
        item: dict[str, Any] = {
            "squadId": int(squad_id),
            "club": names.get(int(squad_id)) or f"Squad {squad_id}",
            "focus": int(squad_id) == int(focus_squad_id),
            "played": games,
            "attack": round(float(stats.get(KPI_PXT_ATTACK) or 0), 3),
        }
        component_total = 0.0
        for spec in COMPONENT_SPECS:
            value = float(stats.get(int(spec["kpiId"])) or 0)
            item[str(spec["id"])] = round(value, 3)
            component_total += value
        item["componentTotal"] = round(component_total, 3)
        rows.append(item)
    attack_rank = _rank_desc({int(row["squadId"]): float(row["attack"]) for row in rows})
    component_ranks = {
        str(spec["id"]): _rank_desc({int(row["squadId"]): float(row[spec["id"]]) for row in rows})
        for spec in COMPONENT_SPECS
    }
    for row in rows:
        squad_id = int(row["squadId"])
        row["rank"] = attack_rank.get(squad_id)
        row["componentRanks"] = {key: ranks.get(squad_id) for key, ranks in component_ranks.items()}
    rows.sort(key=lambda row: (int(row["rank"] or 99), str(row["club"])))

    def _avg(key: str) -> float | None:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return round(sum(values) / len(values), 3) if values else None

    focus = next((row for row in rows if row["focus"]), None)
    components = []
    if focus:
        for spec in COMPONENT_SPECS:
            key = str(spec["id"])
            components.append({
                "id": key,
                "label": spec["label"],
                "value": focus.get(key),
                "rank": (focus.get("componentRanks") or {}).get(key),
                "of": len(rows),
                "leagueAvg": _avg(key),
                "share": _share(float(focus.get(key) or 0), float(focus.get("componentTotal") or 0)),
            })
    leader = rows[0] if rows else None
    return {
        "rows": rows,
        "of": len(rows),
        "leagueAvg": _avg("attack"),
        "focus": focus,
        "leader": {"club": leader["club"], "attack": leader["attack"], "rank": 1} if leader else None,
        "components": components,
    }


def league_slice_ranks(by_squad: dict[int, dict[str, float]], games: dict[int, int], focus_squad_id: int) -> dict[str, dict[str, Any]]:
    keys: set[str] = set()
    for totals in by_squad.values():
        keys.update(totals)
    out: dict[str, dict[str, Any]] = {}
    for key in keys:
        per_game = {
            squad_id: _per_game(float(totals.get(key) or 0), int(games.get(squad_id) or 0))
            for squad_id, totals in by_squad.items()
            if int(games.get(squad_id) or 0) > 0
        }
        if focus_squad_id not in per_game:
            continue
        ranks = _rank_desc(per_game)
        values = list(per_game.values())
        out[key] = {
            "rank": ranks.get(focus_squad_id),
            "of": len(per_game),
            "leaguePerGame": round(sum(values) / len(values), 3) if values else None,
        }
    return out


def _cache_read(kind: str, key: str) -> dict | None:
    from app.analysis_cache import click_json
    payload = click_json(kind, key)
    return payload if isinstance(payload, dict) else None


def _cache_write(kind: str, key: str, data: dict) -> None:
    from app.analysis_cache import write_json
    write_json(kind, key, data)


def _unwrap(payload):
    from app.pre_match import _unwrap_items
    return [row for row in _unwrap_items(payload) if isinstance(row, dict)]


def _fetch_events(match_id: int) -> list:
    from app.analysis_cache import click_list
    cached = click_list("xg-events", str(match_id))
    if cached:
        return [row for row in cached if isinstance(row, dict)]
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{int(match_id)}/events")["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    return _unwrap(raw)


def _fetch_event_kpis(match_id: int) -> list:
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/matches/{int(match_id)}/event-kpis")["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    return _unwrap(raw)


def match_summary(match_id: int) -> dict:
    key = str(int(match_id))
    cached = _cache_read("at-match", key)
    if cached and isinstance(cached.get("squads"), dict):
        return cached
    summary = summarize_match(_fetch_events(int(match_id)), _fetch_event_kpis(int(match_id)))
    summary["matchId"] = int(match_id)
    for squad in (summary.get("squads") or {}).values():
        for row in squad.get("passes") or []:
            row["matchId"] = int(match_id)
    _cache_write("at-match", key, summary)
    return summary


def _flatten_kpis(iteration_id: int) -> dict:
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/iterations/{int(iteration_id)}/squad-kpis")["data"]
    table = {}
    for row in _unwrap(raw):
        squad_id = row.get("squadId")
        if squad_id is None:
            continue
        stats = {}
        for item in row.get("kpis") or []:
            kpi_id = item.get("kpiId") if item.get("kpiId") is not None else item.get("id")
            value = item.get("value")
            if kpi_id is None or value is None:
                continue
            stats[int(kpi_id)] = float(value)
        table[int(squad_id)] = stats
    return table


def _iteration_matches(iteration_id: int) -> list:
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}/iterations/{int(iteration_id)}/matches")["data"]
    return _unwrap(raw)


def _completed(matches: list) -> list:
    from app.pre_match import _match_is_complete
    done = [match for match in matches if match.get("id") is not None and _match_is_complete(match)]
    done.sort(key=lambda row: str(row.get("scheduledDate") or ""))
    return done


def _games_played(matches: list) -> dict:
    played: dict[int, int] = defaultdict(int)
    for match in matches:
        for key in ("homeSquadId", "awaySquadId"):
            try:
                squad_id = int(match.get(key) or 0)
            except (TypeError, ValueError):
                continue
            if squad_id > 0:
                played[squad_id] += 1
    return dict(played)


def _vale_fixtures(matches: list, vale_id: int, names: dict) -> list:
    fixtures = []
    for match in matches:
        try:
            home_id = int(match.get("homeSquadId") or 0)
            away_id = int(match.get("awaySquadId") or 0)
            match_id = int(match.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if vale_id not in {home_id, away_id} or match_id <= 0:
            continue
        opponent_id = away_id if home_id == vale_id else home_id
        goals = match.get("goals") or {}
        home_goals = (goals.get("home") or {}).get("fullTime")
        away_goals = (goals.get("away") or {}).get("fullTime")
        score = f"{home_goals}-{away_goals}" if home_goals is not None and away_goals is not None else ""
        fixtures.append({
            "matchId": match_id,
            "date": str(match.get("scheduledDate") or ""),
            "opponent": names.get(opponent_id) or f"Squad {opponent_id}",
            "opponentId": opponent_id,
            "home": home_id == vale_id,
            "score": score,
        })
    return fixtures


def _select_fixtures(fixtures: list, scope: str, match_id: int | None) -> list:
    if scope == "match":
        chosen = match_id or (fixtures[-1]["matchId"] if fixtures else None)
        return [row for row in fixtures if int(row["matchId"]) == int(chosen or 0)]
    if scope == "last6":
        return fixtures[-6:]
    return list(fixtures)


def _resolve_season(season: str | None) -> dict:
    from app.pre_match import _resolve_port_vale_squad_id
    from app.squad_review import _resolve_port_vale_iteration
    iteration = _resolve_port_vale_iteration(season)
    impect = _impect()
    names = impect._fetch_squad_names(int(iteration["id"]))
    vale_id = _resolve_port_vale_squad_id(int(iteration["id"]))
    if vale_id is None:
        raise ValueError("Port Vale were not found in this season.")
    return {
        "iterationId": int(iteration["id"]),
        "season": str(iteration.get("season") or season or ""),
        "competition": str(iteration.get("competition_name") or iteration.get("competition") or "League Two"),
        "valeId": int(vale_id),
        "names": {int(key): str(value) for key, value in names.items()},
    }


def _load_summaries(match_ids: list) -> dict:
    loaded = {}
    pending = []
    for match_id in match_ids:
        cached = _cache_read("at-match", str(match_id))
        if cached and isinstance(cached.get("squads"), dict):
            loaded[match_id] = cached
        else:
            pending.append(match_id)
    if not pending:
        return loaded
    workers = min(2, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(match_summary, match_id): match_id for match_id in pending}
        for future in as_completed(futures):
            match_id = futures[future]
            try:
                loaded[match_id] = future.result()
            except Exception:
                logger.exception("Attacking threat match %s failed", match_id)
    return loaded


def _detail_from_summaries(summaries, vale_id: int, games: int, action_ranks=None, phase_ranks=None) -> dict:
    parts = []
    for summary in summaries:
        part = (summary.get("squads") or {}).get(str(vale_id))
        if part:
            parts.append(part)
    merged = merge_summaries(parts, keep_passes=True)
    passes = []
    for row in merged.get("passes") or []:
        item = dict(row)
        item["phaseLabel"] = PHASE_LABELS.get(str(item.get("phase") or ""), action_label(str(item.get("phase") or "")))
        passes.append(item)
    return {
        "games": games,
        "total": merged["total"],
        "perGame": _per_game(float(merged["total"]), games),
        "count": int(merged["count"]),
        "actions": _action_rows(merged, games, action_ranks),
        "phases": _phase_rows(merged, games, phase_ranks),
        "zones": {
            "start": _zone_rows(merged.get("zonesStart") or {}, games),
            "end": _zone_rows(merged.get("zonesEnd") or {}, games),
        },
        "players": _player_rows(merged, games),
        "passes": passes,
    }


def _aggregate_league(summaries: dict):
    actions: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    phases: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[int, int] = defaultdict(int)
    for summary in summaries.values():
        seen = set()
        for squad_key, part in (summary.get("squads") or {}).items():
            try:
                squad_id = int(squad_key)
            except (TypeError, ValueError):
                continue
            if float(part.get("total") or 0) <= 0:
                continue
            seen.add(squad_id)
            for action, value in (part.get("actions") or {}).items():
                actions[squad_id][str(action)] += float(value or 0)
            for phase, value in (part.get("phases") or {}).items():
                phases[squad_id][str(phase)] += float(value or 0)
        for squad_id in seen:
            games[squad_id] += 1
    return (
        {squad_id: dict(totals) for squad_id, totals in actions.items()},
        {squad_id: dict(totals) for squad_id, totals in phases.items()},
        dict(games),
    )


def league_squad_table(summaries: dict) -> dict[str, dict[str, Any]]:
    """Per-club threat per game by family, plus threatening crosses per game."""
    totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[int, int] = defaultdict(int)
    for summary in summaries.values():
        for squad_key, part in (summary.get("squads") or {}).items():
            try:
                squad_id = int(squad_key)
            except (TypeError, ValueError):
                continue
            if float(part.get("total") or 0) <= 0:
                continue
            games[squad_id] += 1
            counts = part.get("actionCounts") or {}
            for action, value in (part.get("actions") or {}).items():
                family = action_family(str(action))
                totals[squad_id][family] += float(value or 0)
                if family == "cross":
                    totals[squad_id]["crossCount"] += float(counts.get(action) or 0)
    out = {}
    for squad_id, row in totals.items():
        played = games.get(squad_id) or 0
        if not played:
            continue
        out[str(squad_id)] = {"games": played, **{key: round(value / played, 3) for key, value in row.items()}}
    return out


def _league_cache_key(iteration_id: int, match_ids: list) -> str:
    return f"{int(iteration_id)}-{len(match_ids)}-{match_ids[-1] if match_ids else 0}"


def build_league_detail(iteration_id: int, match_ids: list, vale_id: int) -> dict:
    key = _league_cache_key(iteration_id, match_ids)
    cached = _cache_read("at-league", key)
    if cached and cached.get("actions") is not None and cached.get("squads"):
        return cached
    summaries = _load_summaries(match_ids)
    actions, phases, games = _aggregate_league(summaries)
    payload = {
        "squads": league_squad_table(summaries),
        "status": "ready",
        "matches": len(summaries),
        "expected": len(match_ids),
        "actions": league_slice_ranks(actions, games, vale_id),
        "phases": league_slice_ranks(phases, games, vale_id),
        "builtAt": datetime.now(UTC).isoformat(),
    }
    if len(summaries) >= max(1, int(len(match_ids) * 0.8)):
        _cache_write("at-league", key, payload)
    return payload


def _kick_league_build(iteration_id: int, match_ids: list, vale_id: int, cache_key: str) -> None:
    def _run() -> None:
        try:
            build_league_detail(iteration_id, match_ids, vale_id)
        except Exception:
            logger.exception("Attacking threat league build failed")
        finally:
            with _league_lock:
                _league_running.discard(cache_key)

    with _league_lock:
        if cache_key in _league_running:
            return
        _league_running.add(cache_key)
    threading.Thread(target=_run, name=f"at-league-{cache_key}", daemon=True).start()


def league_detail_status(iteration_id: int, match_ids: list, vale_id: int) -> dict:
    """Disk only. Opening the page must not start an Impect read."""
    del vale_id
    key = _league_cache_key(iteration_id, match_ids)
    cached = _cache_read("at-league", key)
    if cached and cached.get("status") == "ready":
        return cached
    return {"status": "empty", "matches": 0, "expected": len(match_ids), "actions": {}, "phases": {}}


def _scope(scope: str | None) -> str:
    normalized = (scope or "season").strip().lower()
    if normalized not in {"match", "last6", "season"}:
        raise ValueError("scope must be match, last6, or season")
    return normalized


LAKE_EMPTY = (
    "Attacking threat is saved in the data lake. This page only reads that saved pack. "
    "Nothing is stored for this view yet — use Refresh data on the hub, then come back."
)


def report_cache_key(season: str | None, scope: str, match_id: int | None = None) -> str:
    season_key = str(season or "default").replace("/", "-")
    if scope == "match" and match_id:
        return f"{season_key}-match-{int(match_id)}"
    return f"{season_key}-{scope}"


def empty_attacking_threat(season: str | None, scope: str, match_id: int | None = None) -> dict:
    return {
        "ready": False,
        "fromLake": True,
        "season": season or ALLOWED_SEASONS[0],
        "scope": scope,
        "matchId": match_id,
        "why": WHY,
        "message": LAKE_EMPTY,
        "matchCount": 0,
        "fixtures": [],
        "headline": {},
        "table": [],
        "components": [],
        "detail": {
            "games": 0,
            "actions": [],
            "phases": [],
            "zones": {"start": [], "end": []},
            "players": [],
            "passes": [],
        },
        "leagueDetail": {"status": "empty"},
    }


def _store_report(report: dict) -> dict:
    payload = dict(report)
    payload["ready"] = True
    payload["fromLake"] = True
    key = report_cache_key(payload.get("season"), str(payload.get("scope") or "season"), payload.get("matchId"))
    _cache_write("at-report", key, payload)
    return payload


def _league_rows_with_families(rows: list, squads: dict) -> list:
    if not squads:
        return [dict(row) for row in rows]
    out = []
    for row in rows:
        item = dict(row)
        extra = squads.get(str(item.get("squadId"))) or {}
        item["cross"] = extra.get("cross")
        item["crossCount"] = extra.get("crossCount")
        out.append(item)
    for key in ("cross", "crossCount"):
        values = {index: float(item[key]) for index, item in enumerate(out) if item.get(key) is not None}
        ranks = _rank_desc(values)
        for index, item in enumerate(out):
            item[f"{key}Rank"] = ranks.get(index)
    return out


def _with_badges(rows: list) -> list:
    """Crest per club from disk or FotMob ids. No Impect."""
    from app.handout_badges import hydrate_team_badge
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["badge"] = hydrate_team_badge({"id": item.get("squadId"), "name": item.get("club")}).get("badge_url")
        except Exception:
            item["badge"] = None
        out.append(item)
    return out


def read_attacking_threat_report(season: str | None, scope: str | None, match_id: int | None = None) -> dict:
    """Click path. Never calls Impect."""
    normalized = _scope(scope)
    key = report_cache_key(season, normalized, match_id if normalized == "match" else None)
    cached = _cache_read("at-report", key)
    if not cached:
        from app.analysis_cache import all_json

        wanted = str(season or "").replace("/", "-")
        for row in all_json("at-report"):
            if str(row.get("scope") or "") != normalized:
                continue
            stored_season = str(row.get("season") or "").replace("/", "-")
            if wanted and stored_season and stored_season != wanted:
                continue
            if normalized == "match" and match_id and int(row.get("matchId") or 0) not in {0, int(match_id)}:
                continue
            cached = row
            break
    if not cached:
        payload = empty_attacking_threat(season, normalized, match_id)
        progress = _cache_read("at-progress", "default")
        if progress and progress.get("stage") != "done" and _progress_is_live(progress):
            payload["progress"] = progress
            payload["message"] = (
                "Saving Port Vale's attacking threat into the data lake now. "
                "This view fills in on its own in a few minutes."
            )
        return payload
    payload = dict(cached)
    payload["table"] = _with_badges(payload.get("table") or [])
    payload["ready"] = True
    payload["fromLake"] = True
    return payload


def read_attacking_threat_meta() -> dict:
    cached = _cache_read("at-meta", "default")
    if cached and cached.get("seasons"):
        payload = dict(cached)
        payload["fromLake"] = True
        return payload
    return {
        "seasons": [{"value": value, "label": value} for value in ALLOWED_SEASONS],
        "defaultSeason": ALLOWED_SEASONS[0],
        "why": WHY,
        "ready": False,
        "fromLake": True,
        "message": LAKE_EMPTY,
    }


def read_attacking_threat_fixtures(season: str | None) -> dict:
    key = str(season or "default").replace("/", "-")
    cached = _cache_read("at-fixtures", key)
    if cached:
        payload = dict(cached)
        payload["fromLake"] = True
        return payload
    report = read_attacking_threat_report(season, "season", None)
    fixtures = list(report.get("fixtures") or [])
    return {
        "season": report.get("season") or season or "",
        "fixtures": fixtures,
        "defaultMatchId": fixtures[-1]["matchId"] if fixtures else None,
        "ready": bool(fixtures),
        "fromLake": True,
    }


def season_base(season: str | None) -> dict:
    """One Impect read of the season: squads, completed matches, squad KPIs."""
    ctx = _resolve_season(season)
    completed = _completed(_iteration_matches(ctx["iterationId"]))
    table = build_league_table(_flatten_kpis(ctx["iterationId"]), _games_played(completed), ctx["names"], ctx["valeId"])
    base = {
        "iterationId": ctx["iterationId"],
        "season": ctx["season"],
        "competition": ctx["competition"],
        "valeId": ctx["valeId"],
        "table": table,
        "fixtures": _vale_fixtures(completed, ctx["valeId"], ctx["names"]),
        "allIds": [int(match["id"]) for match in completed if match.get("id") is not None],
    }
    _cache_write("at-base", str(base["season"]).replace("/", "-"), base)
    base["players"] = _player_names(ctx["iterationId"])
    return base


def base_from_lake(season: str) -> dict | None:
    """Rebuild inputs without Impect: saved base, or the saved season report."""
    from app.analysis_cache import all_json
    key = str(season).replace("/", "-")
    base = _cache_read("at-base", key)
    if not base:
        report = _cache_read("at-report", f"{key}-season")
        if not report or not report.get("table"):
            return None
        rows = report["table"]
        focus = next((row for row in rows if row.get("focus")), None)
        if not focus:
            return None
        league = next(iter(all_json("at-league")), None)
        base = {
            "iterationId": 0,
            "season": report.get("season") or season,
            "competition": report.get("competition") or "League Two",
            "valeId": int(focus["squadId"]),
            "table": {
                "rows": rows, "of": len(rows), "focus": focus,
                "leagueAvg": (report.get("headline") or {}).get("leagueAvg"),
                "leader": (report.get("headline") or {}).get("leader"),
                "components": report.get("components") or [],
            },
            "fixtures": report.get("fixtures") or [],
            "allIds": [],
            "league": league,
        }
    base = dict(base)
    names = _cache_read("at-players", str(base.get("iterationId") or "")) or {}
    if not names:
        wanted = {str(row.get("id")) for row in ((_cache_read("at-report", f"{key}-season") or {}).get("detail") or {}).get("players") or []}
        options = all_json("at-players")
        names = max(options, key=lambda row: len(wanted & set(row)), default={}) if options else {}
    base["players"] = {int(k): str(v) for k, v in names.items() if str(k).isdigit()}
    return base


def rebuild_attacking_threat_from_lake(season: str | None = None) -> dict[str, Any]:
    """Recompute every stored view from lake data only. No Impect calls."""
    seasons = [season] if season else list(ALLOWED_SEASONS)
    done = {}
    for item in seasons:
        base = base_from_lake(item)
        if not base:
            done[item] = "no saved season"
            continue
        _store_vale_views(base, lake_only=True)
        done[item] = len(base["fixtures"])
    return done


def _player_names(iteration_id: int) -> dict[int, str]:
    from app.pre_match import _player_names_map
    impect = _impect()
    key = str(int(iteration_id))
    try:
        names = _player_names_map(_unwrap(impect._impect_get(impect._players_path(int(iteration_id)))["data"]))
        if names:
            _cache_write("at-players", key, {str(k): v for k, v in names.items()})
            return names
    except Exception:
        logger.exception("Attacking threat player names failed for %s", iteration_id)
    cached = _cache_read("at-players", key) or {}
    return {int(k): str(v) for k, v in cached.items() if str(k).isdigit()}


def match_events_pack(match_id: int) -> list[dict]:
    """Compact events + threat for one match, saved in the lake as at-events."""
    from app.analysis_cache import click_list, write_list
    from app.attacking_threat_chains import compact_events
    key = str(int(match_id))
    cached = click_list("at-events", key)
    if cached:
        return [row for row in cached if isinstance(row, dict)]
    events = _fetch_events(int(match_id))
    event_kpis = _fetch_event_kpis(int(match_id))
    pack = compact_events(events, event_kpis)
    write_list("at-events", key, pack)
    if not _cache_read("at-match", key):
        summary = summarize_match(events, event_kpis)
        summary["matchId"] = int(match_id)
        for squad in (summary.get("squads") or {}).values():
            for row in squad.get("passes") or []:
                row["matchId"] = int(match_id)
        _cache_write("at-match", key, summary)
    return pack


def _load_packs(match_ids: list) -> dict[int, list]:
    from app.analysis_cache import click_list
    loaded: dict[int, list] = {}
    pending = []
    for match_id in match_ids:
        cached = click_list("at-events", str(match_id))
        if cached:
            loaded[int(match_id)] = cached
        else:
            pending.append(int(match_id))
    if pending:
        with ThreadPoolExecutor(max_workers=min(2, len(pending))) as pool:
            futures = {pool.submit(match_events_pack, match_id): match_id for match_id in pending}
            for future in as_completed(futures):
                try:
                    loaded[futures[future]] = future.result()
                except Exception:
                    logger.exception("Attacking threat events pack %s failed", futures[future])
    return loaded


def _chains_and_links(base: dict, selected: list, detail: dict, *, lake_only: bool = False) -> dict:
    from app.attacking_threat_chains import analyse_chains, analyse_links, chain_record, player_profiles, possessions
    names = base.get("players") or {}
    if lake_only:
        from app.analysis_cache import click_list
        packs = {int(row["matchId"]): click_list("at-events", str(row["matchId"])) or [] for row in selected}
    else:
        packs = _load_packs([int(row["matchId"]) for row in selected])
    possession_list = []
    for row in selected:
        pack = packs.get(int(row["matchId"]))
        if pack:
            possession_list.extend(possessions(pack, base["valeId"], int(row["matchId"])))
    games = len([row for row in selected if packs.get(int(row["matchId"]))])
    if not possession_list:
        return {"chains": None, "links": None}
    chains = [chain_record(item, action_label, action_family) for item in possession_list]
    fixtures = {int(row["matchId"]): row for row in selected}
    chain_view = analyse_chains(chains, games, names, fixtures, labeler=action_label, familier=action_family, colors=FAMILY_COLORS)
    links = analyse_links(possession_list, games, names, labeler=action_label)
    detail["players"] = player_profiles(detail.get("players") or [], links, chains, names)
    links.pop("received", None)
    return {"chains": chain_view, "links": links}


def _apply_player_names(detail: dict, names: dict) -> None:
    if not names:
        return
    for row in detail.get("players") or []:
        name = names.get(int(row.get("id") or 0))
        if name:
            row["name"] = name
    for row in detail.get("passes") or []:
        name = names.get(int(row.get("playerId") or 0))
        if name:
            row["player"] = name


def match_trend(selected: list, loaded: dict, vale_id: int) -> list[dict[str, Any]]:
    """Event threat created vs conceded in each Port Vale match of the window."""
    rows = []
    for fixture in selected:
        summary = loaded.get(int(fixture["matchId"])) or {}
        squads = summary.get("squads") or {}
        if not squads:
            continue
        ours = squads.get(str(vale_id)) or {}
        theirs = squads.get(str(fixture.get("opponentId"))) or {}
        actions = ours.get("actions") or {}
        top = max(actions.items(), key=lambda item: float(item[1] or 0))[0] if actions else None
        goals_for = goals_against = None
        try:
            home_goals, away_goals = (int(part) for part in str(fixture.get("score") or "").split("-"))
            goals_for, goals_against = (home_goals, away_goals) if fixture.get("home") else (away_goals, home_goals)
        except ValueError:
            pass
        rows.append({
            "matchId": int(fixture["matchId"]),
            "date": fixture.get("date"),
            "opponent": fixture.get("opponent"),
            "opponentId": fixture.get("opponentId"),
            "home": bool(fixture.get("home")),
            "goalsFor": goals_for,
            "goalsAgainst": goals_against,
            "created": round(float(ours.get("total") or 0), 3),
            "conceded": round(float(theirs.get("total") or 0), 3),
            "topAction": action_label(top) if top else None,
        })
    return rows


def build_attacking_threat_report(
    season: str | None = None,
    scope: str | None = "season",
    match_id: int | None = None,
    *,
    wait_for_league: bool = False,
    base: dict | None = None,
    lake_only: bool = False,
) -> dict:
    """Impect build. Only the data-lake refresh may call this."""
    normalized = _scope(scope)
    base = base or season_base(season)
    table = base["table"]
    selected = _select_fixtures(base["fixtures"], normalized, match_id)
    if lake_only:
        loaded = {int(row["matchId"]): _cache_read("at-match", str(row["matchId"])) for row in selected}
        loaded = {mid: value for mid, value in loaded.items() if value}
    else:
        loaded = _load_summaries([int(row["matchId"]) for row in selected])
    summaries = [loaded[int(row["matchId"])] for row in selected if int(row["matchId"]) in loaded]
    if base.get("league") and not wait_for_league:
        detail_status = base["league"]
    elif normalized == "season" and wait_for_league:
        detail_status = build_league_detail(base["iterationId"], base["allIds"], base["valeId"])
    else:
        detail_status = league_detail_status(base["iterationId"], base["allIds"], base["valeId"])
    ready = detail_status.get("status") == "ready" and normalized == "season"
    detail = _detail_from_summaries(
        summaries,
        base["valeId"],
        len(selected),
        detail_status.get("actions") if ready else None,
        detail_status.get("phases") if ready else None,
    )
    _apply_player_names(detail, base.get("players") or {})
    extras = _chains_and_links(base, selected, detail, lake_only=lake_only)
    fixture_by_id = {int(row["matchId"]): row for row in selected}
    for row in detail["passes"]:
        fixture = fixture_by_id.get(int(row.get("matchId") or 0))
        if fixture:
            row["opponent"] = fixture.get("opponent")
    rows_out = _league_rows_with_families(table.get("rows") or [], detail_status.get("squads") or {})
    focus = table.get("focus") or {}
    report = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "season": base["season"],
        "competition": base["competition"],
        "scope": normalized,
        "why": WHY,
        "matchCount": len(selected),
        "fixtures": selected,
        "trend": match_trend(selected, loaded, base["valeId"]),
        "headline": {
            "club": focus.get("club") or "Port Vale",
            "rank": focus.get("rank"),
            "of": table.get("of"),
            "attack": focus.get("attack"),
            "played": focus.get("played"),
            "leagueAvg": table.get("leagueAvg"),
            "leader": table.get("leader"),
        },
        "table": rows_out,
        "components": table.get("components") or [],
        "detail": detail,
        "leagueDetail": {
            "status": detail_status.get("status"),
            "matches": detail_status.get("matches"),
            "expected": detail_status.get("expected"),
        },
        "chains": extras["chains"],
        "links": extras["links"],
        "ready": True,
        "fromLake": False,
        "matchId": int(selected[-1]["matchId"]) if normalized == "match" and selected else None,
    }
    report["insights"] = build_insights(report)
    return report


def _progress_is_live(progress: dict, max_age_seconds: int = 15 * 60) -> bool:
    try:
        started = datetime.fromisoformat(str(progress.get("at")))
    except ValueError:
        return False
    return (datetime.now(UTC) - started).total_seconds() < max_age_seconds


def _progress(stage: str, **extra) -> None:
    _cache_write("at-progress", "default", {"stage": stage, "at": datetime.now(UTC).isoformat(), **extra})


def _store_vale_views(base: dict, *, lake_only: bool = False) -> dict:
    """Season, last 6 and every Port Vale match — all from the same saved match packets."""
    season = base["season"]
    season_report = _store_report(build_attacking_threat_report(season, "season", base=base, lake_only=lake_only))
    fixtures = list(base["fixtures"])
    _cache_write(
        "at-fixtures",
        str(season).replace("/", "-"),
        {
            "season": season,
            "fixtures": fixtures,
            "defaultMatchId": fixtures[-1]["matchId"] if fixtures else None,
            "ready": True,
        },
    )
    _store_report(build_attacking_threat_report(season, "last6", base=base, lake_only=lake_only))
    for row in fixtures:
        _store_report(build_attacking_threat_report(season, "match", int(row["matchId"]), base=base, lake_only=lake_only))
    return season_report


def warm_attacking_threat(*, include_previous: bool = True) -> dict[str, Any]:
    try:
        return _warm_attacking_threat(include_previous=include_previous)
    except Exception:
        _progress("failed")
        raise


def _warm_attacking_threat(*, include_previous: bool = True) -> dict[str, Any]:
    """Write the Attacking Threat pack into the data lake. Not used on page open.

    Port Vale views are saved first so the page fills in minutes; the
    league-wide action/phase ranks follow, then last season.
    """
    meta = attacking_threat_meta()
    meta["ready"] = True
    _cache_write("at-meta", "default", meta)
    season = str(meta.get("defaultSeason") or "")
    base = season_base(season)
    vale_ids = [int(row["matchId"]) for row in base["fixtures"]]
    _progress("vale", season=base["season"], matches=len(vale_ids))
    _load_summaries(vale_ids)
    season_report = _store_vale_views(base)
    _progress("league", season=base["season"], matches=len(base["allIds"]))
    build_league_detail(base["iterationId"], base["allIds"], base["valeId"])
    season_report = _store_report(build_attacking_threat_report(season, "season", base=base))
    result = {
        "ok": True,
        "season": base["season"],
        "matches": season_report.get("matchCount"),
        "league": (season_report.get("leagueDetail") or {}).get("status"),
    }
    if include_previous:
        for row in meta.get("seasons") or []:
            other = str(row.get("value") or "")
            if not other or other == season:
                continue
            try:
                _progress("previous", season=other)
                other_base = season_base(other)
                _load_summaries([int(item["matchId"]) for item in other_base["fixtures"]])
                _store_vale_views(other_base)
                result.setdefault("previous", []).append(other)
            except Exception as exc:
                logger.exception("Attacking threat warm for %s failed", other)
                result.setdefault("previousErrors", {})[other] = str(exc)
    _progress("done", season=base["season"])
    return result


def attacking_threat_meta() -> dict:
    return {
        "seasons": [{"value": value, "label": value} for value in ALLOWED_SEASONS],
        "defaultSeason": ALLOWED_SEASONS[0],
        "why": WHY,
    }


def attacking_threat_fixtures(season: str | None) -> dict:
    ctx = _resolve_season(season)
    fixtures = _vale_fixtures(_completed(_iteration_matches(ctx["iterationId"])), ctx["valeId"], ctx["names"])
    return {
        "season": ctx["season"],
        "fixtures": fixtures,
        "defaultMatchId": fixtures[-1]["matchId"] if fixtures else None,
    }


def register_attacking_threat_routes(app: FastAPI) -> None:
    @app.get("/attacking-threat")
    def attacking_threat_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "attacking-threat.html")

    @app.get("/api/attacking-threat/meta")
    def attacking_threat_meta_route() -> dict:
        return read_attacking_threat_meta()

    @app.get("/api/attacking-threat/fixtures")
    def attacking_threat_fixtures_route(season: str | None = Query(None)) -> dict:
        return read_attacking_threat_fixtures(season)

    @app.get("/api/attacking-threat/report")
    def attacking_threat_report_route(
        season: str | None = Query(None),
        scope: str | None = Query("season"),
        match_id: int | None = Query(None, alias="matchId"),
    ) -> JSONResponse:
        try:
            payload = read_attacking_threat_report(season, scope, match_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @app.get("/api/attacking-threat/league")
    def attacking_threat_league_route(season: str | None = Query(None)) -> JSONResponse:
        report = read_attacking_threat_report(season, "season", None)
        payload = dict(report.get("leagueDetail") or {"status": "empty"})
        payload["fromLake"] = True
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})
