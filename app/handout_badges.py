from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from app.pre_match import _is_port_vale, _squads_map

HANDOUT_BADGE_DIR = Path(__file__).resolve().parent.parent / "static" / "handout-badges"
PORT_VALE_BADGE_URL = "/standalone/port-vale-badge.png?v=2"


def _badge_file(squad_id: int) -> Path:
    return HANDOUT_BADGE_DIR / f"{int(squad_id)}.png"


def _download_badge(image_url: str) -> bytes | None:
    try:
        response = requests.get(image_url, timeout=20)
        response.raise_for_status()
        data = response.content
        if len(data) < 64:
            return None
        return data
    except requests.RequestException:
        return None


def ensure_handout_badge_cached(squad_id: int, iteration_id: int) -> Path | None:
    squad_id = int(squad_id)
    target = _badge_file(squad_id)
    if target.is_file() and target.stat().st_size > 0:
        return target

    squad = _squads_map(iteration_id).get(squad_id, {})
    image_url = squad.get("imageUrl")
    if not image_url:
        return None

    data = _download_badge(str(image_url))
    if not data:
        return None

    HANDOUT_BADGE_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def resolve_handout_badge_url(
    squad_id: int | None,
    iteration_id: int,
    squad_name: str = "",
) -> str | None:
    if _is_port_vale(squad_name):
        return PORT_VALE_BADGE_URL
    if squad_id is None:
        return None

    squad_id = int(squad_id)
    if ensure_handout_badge_cached(squad_id, iteration_id):
        return f"/api/pre-match-handout/badge/{squad_id}"
    return None


def enrich_team_badge(team: dict[str, Any], iteration_id: int) -> dict[str, Any]:
    squad_id = int(team.get("id") or 0)
    name = str(team.get("name") or "")
    badge_url = resolve_handout_badge_url(squad_id or None, iteration_id, name)
    enriched = dict(team)
    if badge_url:
        enriched["badge_url"] = badge_url
    return enriched
