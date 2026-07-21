from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from app.paths import STATIC_DIR
from app.post_match.impect_client import extract_rows, impect_get, v5_path

BADGE_DIR = STATIC_DIR / "post-match-badges"
_BADGE_URL_CACHE: dict[tuple[int, int], str | None] = {}


def _safe_filename(squad_id: int) -> str:
    return f"{int(squad_id)}.png"


def badge_api_path(squad_id: int) -> str:
    return f"/api/post-match/badges/{int(squad_id)}"


def _squad_image_url(iteration_id: int, squad_id: int) -> str | None:
    cache_key = (int(iteration_id), int(squad_id))
    if cache_key in _BADGE_URL_CACHE:
        return _BADGE_URL_CACHE[cache_key]

    raw = impect_get(v5_path(f"/iterations/{iteration_id}/squads"))
    image_url: str | None = None
    for row in extract_rows(raw["data"]):
        if int(row.get("id") or 0) == int(squad_id):
            image_url = row.get("imageUrl")
            break
    _BADGE_URL_CACHE[cache_key] = image_url
    return image_url


def _download_image(url: str) -> bytes:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    content_type = (response.headers.get("content-type") or "").lower()
    if "image" not in content_type and not url.lower().endswith(".png"):
        raise ValueError(f"Unexpected badge content type: {content_type or 'unknown'}")
    return response.content


def ensure_badge_cached(squad_id: int, iteration_id: int) -> Path | None:
    """Fetch Impect squad image once and cache on disk. Returns path if available."""
    squad_id = int(squad_id)
    iteration_id = int(iteration_id)
    BADGE_DIR.mkdir(parents=True, exist_ok=True)
    target = BADGE_DIR / _safe_filename(squad_id)

    if target.is_file() and target.stat().st_size > 0:
        return target

    image_url = _squad_image_url(iteration_id, squad_id)
    if not image_url:
        return None

    try:
        data = _download_image(image_url)
    except (requests.RequestException, ValueError):
        return None

    if len(data) < 64:
        return None

    target.write_bytes(data)
    return target


def resolve_badge_url(squad_id: int | None, iteration_id: int | None) -> str | None:
    """Return same-origin badge URL when we can serve a cached/proxied image."""
    if squad_id is None or iteration_id is None:
        return None
    squad_id = int(squad_id)
    iteration_id = int(iteration_id)
    cached = BADGE_DIR / _safe_filename(squad_id)
    if cached.is_file() and cached.stat().st_size > 0:
        return badge_api_path(squad_id)
    if ensure_badge_cached(squad_id, iteration_id):
        return badge_api_path(squad_id)
    return None


def warm_iteration_badges(iteration_id: int) -> dict[str, Any]:
    """Pre-download all squad badges for an iteration."""
    raw = impect_get(v5_path(f"/iterations/{iteration_id}/squads"))
    rows = extract_rows(raw["data"])
    cached = 0
    missing = 0
    failed = 0
    for row in rows:
        squad_id = int(row.get("id") or 0)
        if not squad_id:
            continue
        path = ensure_badge_cached(squad_id, int(iteration_id))
        if path:
            cached += 1
        elif row.get("imageUrl"):
            failed += 1
        else:
            missing += 1
    return {
        "iterationId": int(iteration_id),
        "total": len(rows),
        "cached": cached,
        "missingSource": missing,
        "failed": failed,
    }


def squad_initials(name: str | None) -> str:
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", str(name or "")).strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part.lower() not in {"fc", "afc", "the"}]
    if not parts:
        parts = text.split()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return "".join(part[0] for part in parts[:2]).upper()


def enrich_squad(squad: dict[str, Any], squad_id: int, iteration_id: int | None) -> dict[str, Any]:
    enriched = dict(squad)
    enriched["initials"] = squad_initials(enriched.get("name"))
    enriched["badgeUrl"] = resolve_badge_url(squad_id, iteration_id)
    return enriched
