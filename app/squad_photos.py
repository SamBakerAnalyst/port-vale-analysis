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
CLUB_SQUAD_PAGES: dict[str, str] = {
    "port vale": SQUAD_PAGE_URL,
    "lincoln city": "https://www.weareimps.com/squad/122",
    "lincoln": "https://www.weareimps.com/squad/122",
    "wycombe wanderers": "https://www.wycombewanderers.co.uk/squad/70",
    "wycombe": "https://www.wycombewanderers.co.uk/squad/70",
    "stevenage": "https://www.stevenagefc.com/squad/70",
    "stevenage fc": "https://www.stevenagefc.com/squad/70",
    "bolton wanderers": "https://www.bwfc.co.uk/squad/70",
    "bolton": "https://www.bwfc.co.uk/squad/70",
    "huddersfield town": "https://www.htafc.com/squad/70",
    "huddersfield": "https://www.htafc.com/squad/70",
    "blackpool": "https://www.blackpoolfc.co.uk/squad/70",
    "fc blackpool": "https://www.blackpoolfc.co.uk/squad/70",
    "barnsley": "https://www.barnsleyfc.co.uk/squad/70",
    "fc barnsley": "https://www.barnsleyfc.co.uk/squad/70",
    "stockport county": "https://www.stockportcounty.com/squad/70",
    "stockport": "https://www.stockportcounty.com/squad/70",
    "reading": "https://www.readingfc.co.uk/squad/70",
    "fc reading": "https://www.readingfc.co.uk/squad/70",
    "peterborough united": "https://www.theposh.com/squad/70",
    "peterborough": "https://www.theposh.com/squad/70",
    "the posh": "https://www.theposh.com/squad/70",
    "leyton orient": "https://www.leytonorientfc.com/squad/70",
    "orient": "https://www.leytonorientfc.com/squad/70",
    "plymouth argyle": "https://www.pafc.co.uk/squad/70",
    "plymouth": "https://www.pafc.co.uk/squad/70",
    "pafc": "https://www.pafc.co.uk/squad/70",
    "cardiff city": "https://www.cardiffcityfc.co.uk/squad/70",
    "cardiff": "https://www.cardiffcityfc.co.uk/squad/70",
    "luton town": "https://www.lutontown.co.uk/squad/70",
    "luton": "https://www.lutontown.co.uk/squad/70",
    "rotherham united": "https://www.themillers.co.uk/squad/70",
    "rotherham": "https://www.themillers.co.uk/squad/70",
    "the millers": "https://www.themillers.co.uk/squad/70",
    "burton albion": "https://www.burtonalbionfc.co.uk/squad/70",
    "burton": "https://www.burtonalbionfc.co.uk/squad/70",
    "northampton town": "https://www.ntfc.co.uk/squad/70",
    "northampton": "https://www.ntfc.co.uk/squad/70",
    "ntfc": "https://www.ntfc.co.uk/squad/70",
    "mansfield town": "https://www.mtblazers.co.uk/squad/70",
    "mansfield": "https://www.mtblazers.co.uk/squad/70",
    "doncaster rovers": "https://www.drfc.co.uk/squad/70",
    "doncaster": "https://www.drfc.co.uk/squad/70",
    "bradford city": "https://www.bradfordcityafc.com/squad/70",
    "bradford": "https://www.bradfordcityafc.com/squad/70",
    "wigan athletic": "https://www.wiganathletic.com/squad/70",
    "wigan": "https://www.wiganathletic.com/squad/70",
    "afc wimbledon": "https://www.afcwimbledon.co.uk/squad/70",
    "wimbledon": "https://www.afcwimbledon.co.uk/squad/70",
}
PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
PHOTO_STYLE = "cc_960x1280"
PHOTO_STYLE_FALLBACKS = ("cc_640x852", "cc_320x424", "medium")


def _club_page_key(club_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(club_name or "").casefold())


def club_squad_page_url(club_name: str | None) -> str | None:
    if not club_name:
        return None
    key = _club_page_key(club_name)
    if not key:
        return None
    for token, url in CLUB_SQUAD_PAGES.items():
        token_key = _club_page_key(token)
        if token_key in key or key in token_key:
            return url
    return None


def _cdn_host_for_squad_url(squad_url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(squad_url).netloc.casefold()
    if host.startswith("www."):
        return f"cdn.{host[4:]}"
    return f"cdn.{host}"


def _extract_player_image(row: str, *, cdn_host: str) -> str | None:
    cdn_pattern = re.escape(cdn_host)
    for style in (PHOTO_STYLE, *PHOTO_STYLE_FALLBACKS):
        match = re.search(
            rf"(https://{cdn_pattern}/sites/default/files/styles/{style}/public/[^\"?]+(?:\?[^\"]+)?)",
            row,
        )
        if match:
            return match.group(1).replace("&amp;", "&")
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


def _fetch_squad_page(squad_url: str = SQUAD_PAGE_URL) -> str:
    response = requests.get(
        squad_url,
        timeout=25,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Squad page request failed ({response.status_code})")
    return response.text


def _parse_squad_photos(page_html: str, *, cdn_host: str) -> list[dict[str, str]]:
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
        image_url = _extract_player_image(row, cdn_host=cdn_host)
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


def _parse_club_squad_roster_page(
    page_html: str,
    *,
    squad_url: str,
) -> list[dict[str, Any]]:
    if "views-row o-players__list-item" not in page_html:
        return []

    cdn_host = _cdn_host_for_squad_url(squad_url)
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
            continue

        shirt_match = re.search(
            r'm-playercard__number[\s\S]*?field__item">([^<]+)<',
            row,
            flags=re.I,
        )
        shirt_number = None
        if shirt_match:
            raw_shirt = shirt_match.group(1).strip()
            if raw_shirt.isdigit():
                shirt_number = int(raw_shirt)

        image_url = _extract_player_image(row, cdn_host=cdn_host)
        loan_in = bool(re.search(r"In on loan", row, re.IGNORECASE))
        players.append(
            {
                "name": name,
                "club_player_id": club_player_id,
                "position_group": _position_group_for_club_player(section, name),
                "shirt_number": shirt_number,
                "photo_url": image_url,
                "highlight": "loan_in" if loan_in else None,
            }
        )

    return players


def fetch_club_squad_roster_for(club_name: str) -> list[dict[str, Any]]:
    """Scrape a club website squad page when configured (Clubcast Drupal sites)."""
    squad_url = club_squad_page_url(club_name)
    if not squad_url:
        return []
    try:
        page_html = _fetch_squad_page(squad_url)
    except requests.RequestException:
        return []
    return _parse_club_squad_roster_page(page_html, squad_url=squad_url)


def fetch_club_squad_roster(*, force: bool = False) -> list[dict[str, Any]]:
    del force  # always live-fetch; kept for call-site compatibility
    try:
        page_html = _fetch_squad_page()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach port-vale.co.uk ({exc})") from exc

    players = _parse_club_squad_roster_page(page_html, squad_url=SQUAD_PAGE_URL)
    if not players:
        marker_count = page_html.count("views-row o-players__list-item")
        raise RuntimeError(
            "port-vale.co.uk returned no squad players "
            f"(page markers={marker_count}, html={len(page_html)} bytes)."
        )

    return players


_club_photo_caches: dict[str, dict[str, Any]] = {}


def _refresh_club_photo_cache(
    squad_url: str,
    *,
    force: bool = False,
) -> list[dict[str, str]]:
    cache = _club_photo_caches.setdefault(
        squad_url,
        {"fetched_at": 0.0, "entries": []},
    )
    now = time.time()
    if (
        not force
        and cache["entries"]
        and now - float(cache["fetched_at"]) < PHOTO_CACHE_TTL_SECONDS
    ):
        return cache["entries"]

    page_html = _fetch_squad_page(squad_url)
    entries = _parse_squad_photos(page_html, cdn_host=_cdn_host_for_squad_url(squad_url))
    cache["fetched_at"] = now
    cache["entries"] = entries
    return entries


def _refresh_photo_cache(force: bool = False) -> list[dict[str, str]]:
    entries = _refresh_club_photo_cache(SQUAD_PAGE_URL, force=force)
    _photo_cache["fetched_at"] = time.time()
    _photo_cache["entries"] = entries
    return entries


def warm_club_squad_photo_cache(club_name: str, *, force: bool = False) -> bool:
    squad_url = club_squad_page_url(club_name)
    if not squad_url:
        return False
    _refresh_club_photo_cache(squad_url, force=force)
    return True


def squad_photo_map(force: bool = False, *, club_name: str | None = None) -> dict[str, str]:
    squad_url = club_squad_page_url(club_name) if club_name else SQUAD_PAGE_URL
    entries = _refresh_club_photo_cache(squad_url, force=force)
    return {entry["key"]: entry["url"] for entry in entries}


def _name_slug(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def _match_local_photo_path(name: str, paths: list[Path]) -> Path | None:
    if not name or not paths:
        return None

    direct_key = _normalize_name_key(name)
    slug = _name_slug(name)
    for path in paths:
        stem = path.stem
        if stem == slug or _normalize_name_key(stem) == direct_key:
            return path

    first, last = _name_tokens(name)
    if not last:
        return None

    matches: list[Path] = []
    for path in paths:
        stem_parts = path.stem.split("-")
        stem_last = stem_parts[-1] if stem_parts else ""
        if stem_last != last and last not in path.stem:
            continue
        if first and stem_parts:
            stem_first = stem_parts[0]
            if not (
                stem_first.startswith(first[:3])
                or first.startswith(stem_first[:3])
                or stem_first.startswith(first)
                or first.startswith(stem_first)
            ):
                continue
        matches.append(path)

    if len(matches) == 1:
        return matches[0]
    if first:
        for path in matches:
            if path.stem.split("-")[0] == first:
                return path
    return matches[0] if matches else None


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

    paths = [
        path
        for path in PLAYER_PHOTOS_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    ]
    return _match_local_photo_path(name, paths)


def local_player_photo_public_url(name: str) -> str | None:
    path = resolve_local_photo_path(name)
    if path is None:
        return None
    return f"/static/player-photos/{path.name}"


def player_photo_available(name: str, *, force: bool = False) -> bool:
    if resolve_local_photo_path(name) is not None:
        return True
    return resolve_squad_photo_url(name, force=force) is not None


def resolve_player_photo_url(name: str, *, force: bool = False) -> str | None:
    if resolve_local_photo_path(name) is not None:
        return None
    return resolve_squad_photo_url(name, force=force)


def _match_club_photo_entry(name: str, entries: list[dict[str, str]]) -> dict[str, str] | None:
    if not name or not entries:
        return None

    direct_key = _normalize_name_key(name)
    for entry in entries:
        if entry["key"] == direct_key:
            return entry

    first, last = _name_tokens(name)
    if not last:
        return None

    candidates: list[dict[str, str]] = []
    for entry in entries:
        candidate_first, candidate_last = _name_tokens(entry["name"])
        if candidate_last != last:
            continue
        if first and candidate_first:
            if (
                candidate_first.startswith(first[:3])
                or first.startswith(candidate_first[:3])
                or candidate_first.startswith(first)
                or first.startswith(candidate_first)
            ):
                candidates.append(entry)
        else:
            candidates.append(entry)

    if len(candidates) == 1:
        return candidates[0]

    for entry in candidates:
        candidate_first, _ = _name_tokens(entry["name"])
        if candidate_first == first:
            return entry

    return candidates[0] if candidates else None


def resolve_squad_photo_url(
    name: str,
    *,
    force: bool = False,
    club_name: str | None = None,
) -> str | None:
    squad_url = club_squad_page_url(club_name) if club_name else SQUAD_PAGE_URL
    entries = _refresh_club_photo_cache(squad_url, force=force)
    entry = _match_club_photo_entry(name, entries)
    return entry["url"] if entry else None


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
