from __future__ import annotations

import re
import time
import unicodedata
from typing import Any
from urllib.parse import quote

import requests

from app.squad_photos import resolve_squad_photo_url

PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.transfermarkt.co.uk/",
}

# First-team Transfermarkt club IDs for League One clubs we commonly face.
KNOWN_CLUB_IDS: dict[str, int] = {
    "wycombewanderers": 2805,
    "afcwimbledon": 3884,
    "wiganathletic": 1071,
    "exetercity": 6699,
    "portvale": 1211,
    "fcportvale": 1211,
    "cardiffcity": 603,
    "huddersfieldtown": 1110,
    "mansfieldtown": 3820,
    "blackpool": 1181,
    "fcblackpool": 1181,
    "barnsley": 349,
    "fcbarnsley": 349,
    "stockportcounty": 1098,
    "lincolncity": 1198,
    "bradfordcity": 1027,
    "doncasterrovers": 2454,
    "boltonwanderers": 355,
    "lutontown": 1031,
    "stevenage": 3684,
    "fcstevenage": 3684,
    "rotherhamunited": 1194,
    "burtonalbion": 2963,
    "northamptontown": 1302,
    "reading": 1032,
    "fcreading": 1032,
    "peterboroughunited": 1072,
    "leytonorient": 1150,
    "plymouthargyle": 2262,
}

_club_id_cache: dict[str, tuple[float, int | None]] = {}
_squad_photo_cache: dict[tuple[int, int, int], tuple[float, dict[str, dict[str, str]]]] = {}
_SQUAD_CACHE_VERSION = 4


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


def _season_year(season: str | None) -> int:
    text = str(season or "").strip()
    match = re.search(r"(20)?(\d{2})\s*/\s*(20)?(\d{2})", text)
    if match:
        start = int(match.group(2))
        return 2000 + start if start < 100 else start
    match = re.search(r"(20\d{2})", text)
    if match:
        return int(match.group(1))
    return 2025


def _club_search_key(club_name: str) -> str:
    key = _normalize_name_key(club_name)
    key = re.sub(r"^fc", "", key)
    return key


def resolve_transfermarkt_club_id(club_name: str) -> int | None:
    key = _normalize_name_key(club_name)
    search_key = _club_search_key(club_name)
    for candidate in (key, search_key, f"fc{search_key}"):
        if candidate in KNOWN_CLUB_IDS:
            return KNOWN_CLUB_IDS[candidate]

    cached = _club_id_cache.get(key)
    now = time.time()
    if cached and now - cached[0] < PHOTO_CACHE_TTL_SECONDS:
        return cached[1]

    query = re.sub(r"^FC\s+", "", str(club_name or "").strip(), flags=re.I)
    if not query:
        _club_id_cache[key] = (now, None)
        return None

    try:
        response = requests.get(
            "https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche",
            params={"query": query},
            timeout=25,
            headers=TM_HEADERS,
        )
        if response.status_code >= 400:
            _club_id_cache[key] = (now, None)
            return None
    except requests.RequestException:
        _club_id_cache[key] = (now, None)
        return None

    found = re.findall(
        r'href="(/[\w\-]+/startseite/verein/(\d+)[^"]*)"[^>]*>\s*([^<]+)<',
        response.text,
    )
    club_id: int | None = None
    for _, raw_id, label in found:
        if re.search(r"U1[89]|U2[01]|Youth|\bII\b|\bB\b", label, re.I):
            continue
        club_id = int(raw_id)
        break
    if club_id is None and found:
        club_id = int(found[0][1])

    _club_id_cache[key] = (now, club_id)
    return club_id


def _upgrade_portrait_url(url: str) -> str:
    return re.sub(r"/portrait/(?:small|medium)/", "/portrait/header/", url)


def _parse_squad_photos(page_html: str) -> dict[str, dict[str, str]]:
    """Parse Transfermarkt kader rows (photos, shirt numbers, positions).

    Current TM markup uses unquoted ``class=rn_nummer``, lazy ``data-src``
    portraits, and the position label in the second ``inline-table`` row.
    Players on loan out show the loan club badge in the registered-club cell.
    """
    entries: dict[str, dict[str, str]] = {}
    row_pattern = re.compile(
        r'<td[^>]*rueckennummer[^>]*title="([^"]*)"[^>]*>\s*'
        r'<div\s+class=["\']?rn_nummer["\']?>([^<]*)</div>\s*</td>\s*'
        r'<td[^>]*class="[^"]*posrela[^"]*"[^>]*>\s*'
        r'<table[^>]*inline-table[^>]*>\s*'
        r"(.*?)</table>\s*</td>"
        r"(.*?)</tr>",
        flags=re.S | re.I,
    )
    for title, number, table_html, rest_html in row_pattern.findall(page_html):
        name_match = re.search(
            r'alt="([^"]+)"',
            table_html,
            flags=re.I,
        ) or re.search(
            r'class="hauptlink"[^>]*>\s*<a[^>]*>\s*([^<]+?)\s*</a>',
            table_html,
            flags=re.S | re.I,
        )
        if not name_match:
            continue
        clean_name = re.sub(r"\s+", " ", name_match.group(1)).strip()
        key = _normalize_name_key(clean_name)
        if not key:
            continue

        url_match = re.search(
            r'(?:data-src|src)="(https://img\.a\.transfermarkt\.technology/portrait/'
            r'(?:header|medium|small)/[^"]+)"',
            table_html,
            flags=re.I,
        )
        position_match = re.search(
            r"<tr>\s*<td>\s*([^<]+?)\s*</td>\s*</tr>\s*$",
            table_html,
            flags=re.S | re.I,
        )
        position = ""
        if position_match:
            position = re.sub(r"\s+", " ", position_match.group(1)).strip()
        if not position:
            position = re.sub(r"\s+", " ", str(title or "")).strip()

        club_match = re.search(
            r'<a title="([^"]+)" href="/[^"]+/startseite/verein/(\d+)"'
            r'><img[^>]*wappen',
            rest_html,
            flags=re.I,
        )
        club_name = ""
        club_id = ""
        if club_match:
            club_name = re.sub(r"\s+", " ", club_match.group(1)).strip()
            # TM sometimes concatenates the title ("Without ClubWithout Club").
            if len(club_name) % 2 == 0:
                half = len(club_name) // 2
                if club_name[:half] == club_name[half:]:
                    club_name = club_name[:half]
            club_id = str(club_match.group(2))

        bucket: dict[str, str] = {
            "name": clean_name,
            "url": _upgrade_portrait_url(url_match.group(1)) if url_match else "",
            "position": position,
            "registered_club": club_name,
            "registered_club_id": club_id,
        }
        try:
            bucket["shirt_number"] = str(int(str(number).strip()))
        except ValueError:
            pass
        if bucket["url"] or bucket.get("position") or bucket.get("shirt_number"):
            entries[key] = bucket

    # Fallback: any remaining portrait URLs not caught via kader rows.
    for raw_url, name in re.findall(
        r'(https://img\.a\.transfermarkt\.technology/portrait/'
        r'(?:header|medium|small)/[^"\']+).*?alt="([^"]+)"',
        page_html,
        flags=re.S,
    ):
        clean_name = re.sub(r"\s+", " ", name).strip()
        if not clean_name or "default.jpg" in raw_url:
            continue
        key = _normalize_name_key(clean_name)
        if not key:
            continue
        bucket = entries.setdefault(key, {"name": clean_name, "url": ""})
        if not bucket.get("url"):
            bucket["url"] = _upgrade_portrait_url(raw_url)
        bucket["name"] = clean_name

    return entries


def transfermarkt_entry_is_loaned_out(
    entry: dict[str, str] | None,
    *,
    parent_club_id: int | None,
) -> bool:
    """True when the kader row badge is a club other than the parent squad."""
    if not entry or not parent_club_id:
        return False
    raw_id = str(entry.get("registered_club_id") or "").strip()
    if not raw_id.isdigit():
        return False
    return int(raw_id) != int(parent_club_id)


def player_on_transfermarkt_squad(
    player_name: str,
    entries: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    """Return the Transfermarkt squad entry for a player name, if any."""
    return _match_photo_entry(player_name, entries)


def transfermarkt_first_team_roster(
    club_name: str,
    season: str | None,
) -> dict[str, dict[str, str]]:
    """Name-keyed Transfermarkt first-team roster for a club/season."""
    club_id = resolve_transfermarkt_club_id(club_name)
    if not club_id:
        return {}
    return fetch_transfermarkt_squad_photos(club_id, season_year=_season_year(season))


def fetch_transfermarkt_squad_photos(
    club_id: int,
    *,
    season_year: int,
    force: bool = False,
) -> dict[str, dict[str, str]]:
    cache_key = (club_id, season_year, _SQUAD_CACHE_VERSION)
    cached = _squad_photo_cache.get(cache_key)
    now = time.time()
    if not force and cached and now - cached[0] < PHOTO_CACHE_TTL_SECONDS:
        return cached[1]

    url = (
        f"https://www.transfermarkt.co.uk/startseite/kader/verein/"
        f"{club_id}/saison_id/{season_year}"
    )
    entries: dict[str, dict[str, str]] = {}
    try:
        response = requests.get(url, timeout=30, headers=TM_HEADERS)
        if response.status_code < 400:
            entries = _parse_squad_photos(response.text)
    except requests.RequestException:
        entries = {}

    _squad_photo_cache[cache_key] = (now, entries)
    return entries


def _match_photo_entry(
    player_name: str,
    entries: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    if not player_name or not entries:
        return None

    direct = entries.get(_normalize_name_key(player_name))
    if direct:
        return direct

    first, last = _name_tokens(player_name)
    if not last:
        return None

    candidates: list[dict[str, str]] = []
    for entry in entries.values():
        candidate_first, candidate_last = _name_tokens(entry["name"])
        if candidate_last != last:
            continue
        if first and candidate_first:
            if candidate_first.startswith(first[:3]) or first.startswith(candidate_first[:3]):
                candidates.append(entry)
        else:
            candidates.append(entry)

    if len(candidates) == 1:
        return candidates[0]
    for entry in candidates:
        candidate_first, _ = _name_tokens(entry["name"])
        if candidate_first == first:
            return entry
    return None


def resolve_opponent_photo_source_url(
    player_name: str,
    *,
    club_name: str | None = None,
    season: str | None = None,
    force: bool = False,
) -> str | None:
    """Prefer Port Vale club photos when applicable, otherwise Transfermarkt."""
    if club_name and _is_port_vale_name(club_name):
        return resolve_squad_photo_url(player_name, force=force)

    if not club_name:
        return None

    club_id = resolve_transfermarkt_club_id(club_name)
    if not club_id:
        return None

    entries = fetch_transfermarkt_squad_photos(
        club_id,
        season_year=_season_year(season),
        force=force,
    )
    entry = _match_photo_entry(player_name, entries)
    return entry["url"] if entry else None


def _is_port_vale_name(name: str) -> bool:
    return "port vale" in str(name or "").casefold()


def opponent_photo_api_url(
    player_name: str,
    *,
    club_name: str | None = None,
    season: str | None = None,
) -> str | None:
    if not player_name:
        return None
    # Always expose the proxy URL for pitch markers; the route resolves the source.
    params = [f"name={quote(player_name)}"]
    if club_name:
        params.append(f"club={quote(club_name)}")
    if season:
        params.append(f"season={quote(str(season))}")
    return "/api/pre-match/player-photo?" + "&".join(params)


def attach_pitch_player_photos(
    pitch_players: list[dict[str, Any]],
    *,
    club_name: str,
    season: str | None,
) -> list[dict[str, Any]]:
    if not pitch_players:
        return pitch_players

    # Warm the squad photo map once so matching is free per player.
    club_id = resolve_transfermarkt_club_id(club_name)
    if club_id and not _is_port_vale_name(club_name):
        fetch_transfermarkt_squad_photos(club_id, season_year=_season_year(season))

    for player in pitch_players:
        name = str(player.get("name") or "")
        source = resolve_opponent_photo_source_url(
            name,
            club_name=club_name,
            season=season,
        )
        if source:
            player["photo_url"] = opponent_photo_api_url(
                name,
                club_name=club_name,
                season=season,
            )
        else:
            player["photo_url"] = None
    return pitch_players


def fetch_opponent_photo_bytes(source_url: str) -> tuple[bytes, str]:
    response = requests.get(source_url, timeout=25, headers=TM_HEADERS)
    if response.status_code >= 400:
        raise RuntimeError(f"Photo request failed ({response.status_code})")
    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return response.content, content_type
