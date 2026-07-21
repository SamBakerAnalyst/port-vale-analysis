from __future__ import annotations

import html
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAYER_PHOTOS_DIR = PROJECT_ROOT / "static" / "player-photos"
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")

SQUAD_PAGE_URL = "https://www.port-vale.co.uk/squad/70"
PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
PHOTO_STYLE = "cc_960x1280"
PHOTO_STYLE_FALLBACKS = ("cc_640x852", "cc_320x424", "medium")


def _extract_player_image(row: str) -> str | None:
    for style in (PHOTO_STYLE, *PHOTO_STYLE_FALLBACKS):
        match = re.search(
            rf"(https://cdn\.port-vale\.co\.uk/sites/default/files/styles/{style}/public/[^\"?]+(?:\?[^\"]+)?)",
            row,
        )
        if match:
            return match.group(1)
    return None

_photo_cache: dict[str, Any] = {"fetched_at": 0.0, "entries": []}


def _normalize_name_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _name_tokens(name: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].casefold(), ""
    return parts[0].casefold(), parts[-1].casefold()


def _fetch_squad_page() -> str:
    response = requests.get(
        SQUAD_PAGE_URL,
        timeout=25,
        headers={"User-Agent": "Mozilla/5.0 (Port Vale analysis dashboard)"},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Squad page request failed ({response.status_code})")
    return response.text


def _parse_squad_photos(page_html: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    rows = page_html.split("views-row o-players__list-item")

    for row in rows[1:]:
        first = re.search(
            r'm-playercard__name--first[\s\S]*?field__item">([^<]+)<',
            row,
        )
        last = re.search(
            r'm-playercard__name--last[\s\S]*?field__item">([^<]+)<',
            row,
        )
        image_url = _extract_player_image(row)
        if not first or not last or not image_url:
            continue

        display_name = html.unescape(f"{first.group(1).strip()} {last.group(1).strip()}")
        entries.append(
            {
                "key": _normalize_name_key(display_name),
                "name": display_name,
                "url": image_url,
            }
        )

    return entries


CLUB_SECTION_TO_GROUP: dict[str, str] = {
    "Goalkeepers": "GK",
    "Defenders": "CB",
    "Midfielders": "CM",
    "Attackers": "ATT",
}

# Wingbacks listed under Defenders on port-vale.co.uk
CLUB_WINGBACK_NAME_KEYS: frozenset[str] = frozenset(
    {
        _normalize_name_key(name)
        for name in (
            "Kyle John",
            "Jordan Gabriel",
            "Liam Gordon",
            "Jaheim Headley",
        )
    }
)


def _player_name_from_club_page(club_player_id: str) -> str | None:
    response = requests.get(
        f"https://www.port-vale.co.uk/player/{club_player_id}",
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (Port Vale analysis dashboard)"},
    )
    if response.status_code >= 400:
        return None
    match = re.search(r"<title>([^<|]+)", response.text)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def _position_group_for_club_player(section: str, name: str) -> str:
    group = CLUB_SECTION_TO_GROUP.get(section, "CM")
    if group == "CB" and _normalize_name_key(name) in CLUB_WINGBACK_NAME_KEYS:
        return "WB"
    return group


def fetch_club_squad_roster(*, force: bool = False) -> list[dict[str, Any]]:
    page_html = _fetch_squad_page()
    rows = page_html.split("views-row o-players__list-item")
    players: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for row in rows[1:]:
        row_start = page_html.find(row)
        preceding = page_html[:row_start] if row_start >= 0 else page_html
        section = "Midfielders"
        for label in CLUB_SECTION_TO_GROUP:
            if label in preceding:
                section = label

        first = re.search(
            r'm-playercard__name--first[\s\S]*?field__item">([^<]+)<',
            row,
        )
        last = re.search(
            r'm-playercard__name--last[\s\S]*?field__item">([^<]+)<',
            row,
        )
        player_id_match = re.search(r"/player/(\d+)", row)
        if not player_id_match:
            continue
        club_player_id = player_id_match.group(1)
        if club_player_id in seen_ids:
            continue
        seen_ids.add(club_player_id)

        if first and last:
            name = html.unescape(f"{first.group(1).strip()} {last.group(1).strip()}")
        else:
            resolved = _player_name_from_club_page(club_player_id)
            if not resolved:
                continue
            name = resolved

        loan_in = bool(re.search(r"In on loan", row, re.IGNORECASE))
        players.append(
            {
                "name": name,
                "club_player_id": club_player_id,
                "position_group": _position_group_for_club_player(section, name),
                "highlight": "loan_in" if loan_in else None,
            }
        )

    return players


def _refresh_photo_cache(force: bool = False) -> list[dict[str, str]]:
    now = time.time()
    if not force and _photo_cache["entries"] and now - float(_photo_cache["fetched_at"]) < PHOTO_CACHE_TTL_SECONDS:
        return _photo_cache["entries"]

    page_html = _fetch_squad_page()
    entries = _parse_squad_photos(page_html)

    _photo_cache["fetched_at"] = now
    _photo_cache["entries"] = entries
    return entries


def squad_photo_map(force: bool = False) -> dict[str, str]:
    return {entry["key"]: entry["url"] for entry in _refresh_photo_cache(force=force)}


def _name_slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def resolve_local_photo_path(name: str) -> Path | None:
    if not name or not PLAYER_PHOTOS_DIR.is_dir():
        return None

    candidates = {_normalize_name_key(name), _name_slug(name)}
    candidates.discard("")
    for candidate in candidates:
        for ext in PHOTO_EXTENSIONS:
            path = PLAYER_PHOTOS_DIR / f"{candidate}{ext}"
            if path.is_file():
                return path
    return None


def player_photo_available(name: str, *, force: bool = False) -> bool:
    if resolve_local_photo_path(name) is not None:
        return True
    return resolve_squad_photo_url(name, force=force) is not None


def resolve_player_photo_url(name: str, *, force: bool = False) -> str | None:
    if resolve_local_photo_path(name) is not None:
        return None
    return resolve_squad_photo_url(name, force=force)


def resolve_squad_photo_url(name: str, *, force: bool = False) -> str | None:
    entries = _refresh_photo_cache(force=force)
    if not name:
        return None

    direct_key = _normalize_name_key(name)
    for entry in entries:
        if entry["key"] == direct_key:
            return entry["url"]

    first, last = _name_tokens(name)
    if not last:
        return None

    candidates: list[dict[str, str]] = []
    for entry in entries:
        candidate_first, candidate_last = _name_tokens(entry["name"])
        if candidate_last != last:
            continue
        if first and candidate_first:
            if candidate_first.startswith(first[:3]) or first.startswith(candidate_first[:3]):
                candidates.append(entry)
        else:
            candidates.append(entry)

    if len(candidates) == 1:
        return candidates[0]["url"]

    for entry in candidates:
        candidate_first, _ = _name_tokens(entry["name"])
        if candidate_first == first:
            return entry["url"]

    return None


def local_photo_save_path(name: str) -> Path:
    PLAYER_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _name_slug(name) or _normalize_name_key(name)
    if not slug:
        raise ValueError("Player name is required.")
    return PLAYER_PHOTOS_DIR / f"{slug}.jpg"


def save_local_player_photo(name: str, image_bytes: bytes) -> Path:
    if not image_bytes:
        raise ValueError("Image data is empty.")
    if len(image_bytes) > 8 * 1024 * 1024:
        raise ValueError("Image is too large (max 8 MB).")
    path = local_photo_save_path(name)
    path.write_bytes(image_bytes)
    return path


def fetch_photo_bytes(url: str) -> tuple[bytes, str]:
    response = requests.get(
        url,
        timeout=25,
        headers={"User-Agent": "Mozilla/5.0 (Port Vale analysis dashboard)"},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Photo request failed ({response.status_code})")

    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return response.content, content_type
