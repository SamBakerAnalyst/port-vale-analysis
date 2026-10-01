"""Impect reads for Set Plays. Only the data-lake refresh calls these."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _impect():
    from app import main as impect_main

    return impect_main


def _unwrap(payload) -> list[dict]:
    from app.pre_match import _unwrap_items

    return [row for row in _unwrap_items(payload) if isinstance(row, dict)]


def _get(path: str):
    impect = _impect()
    raw = impect._impect_get(f"/v5/{impect._api_prefix()}{path}")["data"]
    if isinstance(raw, dict) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    return raw


def fetch_events(match_id: int) -> list[dict]:
    from app.analysis_cache import click_list

    cached = click_list("xg-events", str(int(match_id)))
    if cached:
        return [row for row in cached if isinstance(row, dict)]
    return _unwrap(_get(f"/matches/{int(match_id)}/events"))


def fetch_event_kpis(match_id: int) -> list[dict]:
    return _unwrap(_get(f"/matches/{int(match_id)}/event-kpis"))


def iteration_matches(iteration_id: int) -> list[dict]:
    return _unwrap(_get(f"/iterations/{int(iteration_id)}/matches"))


def resolve_season(season: str | None) -> dict:
    from app.pre_match import _resolve_port_vale_squad_id
    from app.squad_review import _resolve_port_vale_iteration

    iteration = _resolve_port_vale_iteration(season)
    names = _impect()._fetch_squad_names(int(iteration["id"]))
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


def player_names(iteration_id: int) -> dict[int, str]:
    from app.analysis_cache import click_json, write_json
    from app.pre_match import _player_names_map

    impect = _impect()
    key = str(int(iteration_id))
    try:
        names = _player_names_map(_unwrap(impect._impect_get(impect._players_path(int(iteration_id)))["data"]))
        if names:
            write_json("sp-players", key, {str(k): v for k, v in names.items()})
            return names
    except Exception:
        logger.exception("Set plays player names failed for %s", iteration_id)
    cached = click_json("sp-players", key) or {}
    return {int(k): str(v) for k, v in cached.items() if str(k).isdigit()}
