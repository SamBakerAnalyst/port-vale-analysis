from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

TEAM_BADGE_DIR = Path(__file__).resolve().parent.parent / "static" / "handout-badges"
HANDOUT_BADGE_DIR = TEAM_BADGE_DIR
PORT_VALE_BADGE_URL = "/standalone/port-vale-badge.png?v=2"
TEAM_BADGE_API_PREFIX = "/api/team-badge"
_BADGES_JSON = Path(__file__).resolve().parent.parent / "data" / "efl-transfer-badges.json"

_fotmob_by_key: dict[str, int] | None = None


def _is_port_vale_name(name: str) -> bool:
    return "port vale" in str(name or "").casefold().replace(".", "")


def _club_lookup_key(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())
    return re.sub(r"^fc", "", text)


def _load_fotmob_club_ids() -> dict[str, int]:
    global _fotmob_by_key
    if _fotmob_by_key is not None:
        return _fotmob_by_key
    mapping: dict[str, int] = {}
    try:
        payload = json.loads(_BADGES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _fotmob_by_key = mapping
        return mapping
    if not isinstance(payload, dict):
        _fotmob_by_key = mapping
        return mapping
    for slug, row in payload.items():
        if not isinstance(row, dict):
            continue
        try:
            fotmob_id = int(row.get("fotmob_id") or 0)
        except (TypeError, ValueError):
            fotmob_id = 0
        if fotmob_id <= 0:
            continue
        for token in (slug, row.get("name"), str(slug).replace("-", " ")):
            key = _club_lookup_key(str(token or ""))
            if key:
                mapping[key] = fotmob_id
    _fotmob_by_key = mapping
    return mapping


def fotmob_team_id_for_club(club_name: str | None) -> int | None:
    key = _club_lookup_key(club_name or "")
    if not key:
        return None
    mapping = _load_fotmob_club_ids()
    if key in mapping:
        return mapping[key]
    for candidate, fotmob_id in mapping.items():
        if candidate in key or key in candidate:
            return fotmob_id
    return None


def fotmob_crest_url_for_club(club_name: str | None) -> str | None:
    fotmob_id = fotmob_team_id_for_club(club_name)
    if not fotmob_id:
        return None
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_id}.png"


def _badge_file(squad_id: int) -> Path:
    return TEAM_BADGE_DIR / f"{int(squad_id)}.png"


def local_badge_url(squad_id: int | None) -> str | None:
    try:
        squad_id = int(squad_id or 0)
    except (TypeError, ValueError):
        return None
    if squad_id <= 0:
        return None
    path = _badge_file(squad_id)
    if path.is_file() and path.stat().st_size > 0:
        return f"{TEAM_BADGE_API_PREFIX}/{squad_id}"
    return None


def _download_badge(image_url: str) -> bytes | None:
    try:
        response = requests.get(
            image_url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        data = response.content
        if len(data) < 64:
            return None
        return data
    except requests.RequestException:
        return None


def ensure_handout_badge_cached(
    squad_id: int,
    iteration_id: int,
    *,
    squad_name: str = "",
) -> Path | None:
    squad_id = int(squad_id)
    TEAM_BADGE_DIR.mkdir(parents=True, exist_ok=True)
    target = _badge_file(squad_id)
    if target.is_file() and target.stat().st_size > 0:
        return target

    image_url = None
    if iteration_id:
        try:
            from app.pre_match import _squads_map

            squad = _squads_map(int(iteration_id)).get(squad_id, {})
            image_url = squad.get("imageUrl") or squad.get("image_url")
            if not squad_name:
                squad_name = str(squad.get("name") or "")
        except Exception:
            image_url = None

    candidates = [str(image_url or "").strip()]
    fotmob = fotmob_crest_url_for_club(squad_name)
    if fotmob:
        candidates.append(fotmob)

    for url in candidates:
        if not url.startswith("http"):
            continue
        data = _download_badge(url)
        if not data:
            continue
        target.write_bytes(data)
        return target
    return None


def resolve_handout_badge_url(
    squad_id: int | None,
    iteration_id: int,
    squad_name: str = "",
) -> str | None:
    if _is_port_vale_name(squad_name):
        return PORT_VALE_BADGE_URL
    local = local_badge_url(squad_id)
    if local:
        return local
    if squad_id is None:
        return fotmob_crest_url_for_club(squad_name)

    squad_id = int(squad_id)
    if ensure_handout_badge_cached(squad_id, iteration_id, squad_name=squad_name):
        return f"{TEAM_BADGE_API_PREFIX}/{squad_id}"
    return fotmob_crest_url_for_club(squad_name)


def hydrate_team_badge(team: dict[str, Any], iteration_id: int = 0) -> dict[str, Any]:
    """Attach a crest URL without calling Impect — disk cache, then FotMob."""
    enriched = dict(team)
    name = str(enriched.get("name") or "")
    try:
        squad_id = int(enriched.get("id") or 0)
    except (TypeError, ValueError):
        squad_id = 0
    if _is_port_vale_name(name):
        enriched["badge_url"] = PORT_VALE_BADGE_URL
        enriched["image_url"] = PORT_VALE_BADGE_URL
        return enriched
    badge_url = local_badge_url(squad_id) or fotmob_crest_url_for_club(name)
    if badge_url:
        enriched["badge_url"] = badge_url
        if not str(enriched.get("image_url") or "").startswith("/"):
            enriched["image_url"] = badge_url
    return enriched


def enrich_team_badge(team: dict[str, Any], iteration_id: int) -> dict[str, Any]:
    squad_id = int(team.get("id") or 0)
    name = str(team.get("name") or "")
    badge_url = resolve_handout_badge_url(squad_id or None, iteration_id, name)
    enriched = dict(team)
    if badge_url:
        enriched["badge_url"] = badge_url
        enriched["image_url"] = badge_url
    return enriched


def register_team_badge_routes(app: FastAPI) -> None:
    @app.get(f"{TEAM_BADGE_API_PREFIX}/{{squad_id}}")
    def team_badge(squad_id: int) -> FileResponse:
        path = _badge_file(int(squad_id))
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Badge not found.")
        return FileResponse(path, media_type="image/png")
