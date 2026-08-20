from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.pre_match import _is_port_vale, _squads_map

TEAM_BADGE_DIR = Path(__file__).resolve().parent.parent / "static" / "handout-badges"
HANDOUT_BADGE_DIR = TEAM_BADGE_DIR
PORT_VALE_BADGE_URL = "/standalone/port-vale-badge.png?v=2"
TEAM_BADGE_API_PREFIX = "/api/team-badge"


def _badge_file(squad_id: int) -> Path:
    return TEAM_BADGE_DIR / f"{int(squad_id)}.png"


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

    TEAM_BADGE_DIR.mkdir(parents=True, exist_ok=True)
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
        return f"{TEAM_BADGE_API_PREFIX}/{squad_id}"
    return None


def enrich_team_badge(team: dict[str, Any], iteration_id: int) -> dict[str, Any]:
    squad_id = int(team.get("id") or 0)
    name = str(team.get("name") or "")
    badge_url = resolve_handout_badge_url(squad_id or None, iteration_id, name)
    enriched = dict(team)
    if badge_url:
        enriched["badge_url"] = badge_url
    return enriched


def register_team_badge_routes(app: FastAPI) -> None:
    @app.get(f"{TEAM_BADGE_API_PREFIX}/{{squad_id}}")
    def team_badge(squad_id: int) -> FileResponse:
        path = _badge_file(int(squad_id))
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Badge not found.")
        return FileResponse(path, media_type="image/png")
