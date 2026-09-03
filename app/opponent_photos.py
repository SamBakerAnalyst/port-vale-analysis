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
    "tranmererovers": 1074,
    "fctranmere": 1074,
    "crewealexandra": 1042,
    "fccrewealexandra": 1042,
    "swindontown": 352,
    "fcswindontown": 352,
    "salfordcity": 34888,
    "fcsalfordcity": 34888,
}

_club_id_cache: dict[str, tuple[float, int | None]] = {}
_squad_photo_cache: dict[tuple[int, int, int], tuple[float, dict[str, dict[str, str]]]] = {}
_loan_arrival_cache: dict[tuple[int, int], tuple[float, dict[str, dict[str, str]]]] = {}
_club_site_photo_cache: dict[str, tuple[float, dict[str, dict[str, str]]]] = {}
_SQUAD_CACHE_VERSION = 5

# Official club sites on Gamechanger (squad photos via public football.web API).
# Key = normalized club name; value = services host (images.gc.<host>).
GC_CLUB_SERVICES: dict[str, str] = {
    "tranmererovers": "tranmereroversfcservices.co.uk",
    "fctranmere": "tranmereroversfcservices.co.uk",
    "crewealexandra": "crewealexandrafcservices.co.uk",
    "fccrewealexandra": "crewealexandrafcservices.co.uk",
    "swindontown": "swindontownfcservices.co.uk",
    "fcswindontown": "swindontownfcservices.co.uk",
    "salfordcity": "salfordcityfcservices.co.uk",
    "fcsalfordcity": "salfordcityfcservices.co.uk",
}
GC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}


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
    return current_transfermarkt_season_year()


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
        r"(.*?)"
        r"<table[^>]*inline-table[^>]*>\s*"
        r"(.*?)</table>\s*</td>"
        r"(.*?)</tr>",
        flags=re.S | re.I,
    )
    for title, number, posrela_prefix, table_html, rest_html in row_pattern.findall(page_html):
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

        loan_match = re.search(
            r'title="On loan from\s+([^"]+?)(?:\s+until[^"]*)?"',
            f"{posrela_prefix}{table_html}",
            flags=re.I,
        )
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
        if loan_match:
            from_club = re.sub(r"\s+", " ", loan_match.group(1)).strip()
            if from_club:
                bucket["on_loan_from"] = from_club
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
    if str(entry.get("on_loan_from") or "").strip():
        return False
    raw_id = str(entry.get("registered_club_id") or "").strip()
    if not raw_id.isdigit():
        return False
    return int(raw_id) != int(parent_club_id)


def current_transfermarkt_season_year() -> int:
    """EFL / TM saison_id — July onwards is the new season start year."""
    from datetime import date

    today = date.today()
    return today.year if today.month >= 7 else today.year - 1


def transfermarkt_loan_ins(club_name: str, *, season: str | None = None) -> dict[str, dict[str, str]]:
    """Players on loan at this club (current squad badge + TM loan arrivals)."""
    club_id = resolve_transfermarkt_club_id(club_name)
    if not club_id:
        return {}
    current_year = current_transfermarkt_season_year()
    years = {current_year, current_year - 1}
    if season:
        years.add(_season_year(season))

    loans: dict[str, dict[str, str]] = {}
    for year in sorted(years, reverse=True):
        entries = fetch_transfermarkt_squad_photos(club_id, season_year=year)
        for entry in entries.values():
            parent = str(entry.get("on_loan_from") or "").strip()
            name = str(entry.get("name") or "").strip()
            if parent and name:
                loans[_normalize_name_key(name)] = {
                    "name": name,
                    "on_loan_from": parent,
                }
        loans.update(_fetch_loan_arrivals(club_id, year))
    return loans


def _parse_loan_arrivals(page_html: str) -> dict[str, dict[str, str]]:
    heading = re.search(r"<h2[^>]*>\s*Arrivals\s*</h2>", page_html, flags=re.I)
    if not heading:
        return {}
    departures = re.search(r"<h2[^>]*>\s*Departures\s*</h2>", page_html, flags=re.I)
    chunk = page_html[heading.end() : departures.start() if departures else None]
    loans: dict[str, dict[str, str]] = {}
    skip = {"?", "loan transfer", "free transfer", "end of loan"}
    for match in re.finditer(r"loan transfer", chunk, flags=re.I):
        window = chunk[max(0, match.start() - 2500) : match.start()]
        if re.search(r"End of loan", window[-200:], flags=re.I):
            continue
        names = re.findall(
            r'href="/[^"]+/spieler/\d+[^"]*"[^>]*>\s*([^<]+)\s*</a>',
            window,
            flags=re.I,
        )
        name = ""
        for raw in reversed(names):
            candidate = re.sub(r"\s+", " ", raw).strip()
            if candidate and candidate.casefold() not in skip:
                name = candidate
                break
        if not name:
            continue
        from_match = None
        for raw in re.finditer(
            r'<a title="([^"]+)" href="/[^"]+/startseite/verein/\d+',
            window,
            flags=re.I,
        ):
            from_match = raw
        parent = ""
        if from_match:
            parent = re.sub(r"\s+", " ", from_match.group(1)).strip()
            if len(parent) % 2 == 0:
                half = len(parent) // 2
                if parent[:half] == parent[half:]:
                    parent = parent[:half]
        loans[_normalize_name_key(name)] = {
            "name": name,
            "on_loan_from": parent or "loan",
        }
    return loans


def _fetch_loan_arrivals(club_id: int, season_year: int) -> dict[str, dict[str, str]]:
    cache_key = (club_id, season_year)
    cached = _loan_arrival_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < PHOTO_CACHE_TTL_SECONDS:
        return cached[1]
    url = (
        f"https://www.transfermarkt.co.uk/startseite/transfers/verein/"
        f"{club_id}/saison_id/{season_year}"
    )
    loans: dict[str, dict[str, str]] = {}
    try:
        response = requests.get(url, timeout=30, headers=TM_HEADERS)
        if response.status_code < 400:
            loans = _parse_loan_arrivals(response.text)
    except requests.RequestException:
        loans = {}
    _loan_arrival_cache[cache_key] = (now, loans)
    return loans


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
    *,
    shirt_number: int | str | None = None,
) -> dict[str, str] | None:
    if not entries:
        return None

    if player_name:
        direct = entries.get(_normalize_name_key(player_name))
        if direct:
            return direct

        first, last = _name_tokens(player_name)
        if last:
            candidates: list[dict[str, str]] = []
            for entry in entries.values():
                candidate_first, candidate_last = _name_tokens(entry["name"])
                if candidate_last != last:
                    continue
                if first and candidate_first:
                    if candidate_first.startswith(first[:3]) or first.startswith(
                        candidate_first[:3]
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

    if shirt_number is not None and str(shirt_number).strip() != "":
        try:
            want = str(int(str(shirt_number).strip()))
        except ValueError:
            want = str(shirt_number).strip()
        hits = [
            entry
            for entry in entries.values()
            if str(entry.get("shirt_number") or "") == want
        ]
        # Surname aliases can surface the same player twice in entries.values().
        unique_hits: list[dict[str, str]] = []
        seen: set[str] = set()
        for entry in hits:
            signature = str(entry.get("url") or entry.get("name") or "")
            if not signature or signature in seen:
                continue
            seen.add(signature)
            unique_hits.append(entry)
        if len(unique_hits) == 1:
            return unique_hits[0]
    return None


_web_photo_cache: dict[str, tuple[float, str | None]] = {}
WEB_PHOTO_CACHE_TTL_SECONDS = 6 * 60 * 60
WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def _wikipedia_player_photo_url(player_name: str, club_name: str | None = None) -> str | None:
    query = f"{player_name} {club_name or ''} footballer".strip()
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": query,
                "gsrlimit": 5,
                "prop": "pageimages|pageterms",
                "piprop": "thumbnail",
                "pithumbsize": 500,
                "wbptterms": "description",
            },
            timeout=20,
            headers=WEB_HEADERS,
        )
        if response.status_code >= 400:
            return None
        pages = ((response.json().get("query") or {}).get("pages") or {})
    except (requests.RequestException, ValueError, TypeError):
        return None

    surname = _name_tokens(player_name)[1]
    ranked: list[tuple[int, str]] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        thumb = ((page.get("thumbnail") or {}).get("source") or "").strip()
        if not thumb.startswith("http"):
            continue
        title = str(page.get("title") or "")
        desc = ""
        terms = page.get("terms") or {}
        if isinstance(terms, dict):
            desc_list = terms.get("description") or []
            if isinstance(desc_list, list) and desc_list:
                desc = str(desc_list[0])
        blob = f"{title} {desc}".casefold()
        if surname and surname not in _normalize_name_key(title):
            continue
        score = 0
        if "football" in blob or "soccer" in blob or "footballer" in blob:
            score += 3
        if club_name and _normalize_name_key(club_name)[:6] in _normalize_name_key(blob):
            score += 2
        if "disambiguation" in blob:
            score -= 5
        ranked.append((score, thumb))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked[0][0] >= 0 else None


def _duckduckgo_player_photo_url(player_name: str, club_name: str | None = None) -> str | None:
    """Image search fallback (same headshots Google usually surfaces for footballers)."""
    query = f"{player_name} {club_name or ''} football headshot".strip()
    try:
        home = requests.get(
            "https://duckduckgo.com/",
            params={"q": query},
            timeout=20,
            headers=WEB_HEADERS,
        )
        if home.status_code >= 400:
            return None
        match = re.search(r"vqd=([\"']?)([\w.\-]+)\1", home.text)
        if not match:
            match = re.search(r"vqd=([\w.\-]+)", home.text)
        if not match:
            return None
        vqd = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
        response = requests.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "uk-en",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": "1",
            },
            timeout=20,
            headers={**WEB_HEADERS, "Referer": "https://duckduckgo.com/"},
        )
        if response.status_code >= 400:
            return None
        results = response.json().get("results") or []
    except (requests.RequestException, ValueError, TypeError):
        return None

    surname = _name_tokens(player_name)[1]
    for row in results[:12]:
        if not isinstance(row, dict):
            continue
        image = str(row.get("image") or "").strip()
        title = str(row.get("title") or "")
        if not image.startswith("http"):
            continue
        if surname and surname not in _normalize_name_key(title) and surname not in _normalize_name_key(image):
            host = image.casefold()
            if not any(token in host for token in ("transfermarkt", "wikipedia", "wikimedia", "getty", "imago")):
                continue
        if any(bad in image.casefold() for bad in (".svg", "logo", "crest", "badge", "icon")):
            continue
        return image
    return None


def resolve_web_player_photo_url(
    player_name: str,
    *,
    club_name: str | None = None,
) -> str | None:
    cache_key = f"{_normalize_name_key(player_name)}|{_normalize_name_key(club_name or '')}"
    cached = _web_photo_cache.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < WEB_PHOTO_CACHE_TTL_SECONDS:
        return cached[1]

    url = _wikipedia_player_photo_url(player_name, club_name)
    if not url:
        url = _duckduckgo_player_photo_url(player_name, club_name)
    _web_photo_cache[cache_key] = (now, url)
    return url


def resolve_gc_club_services(club_name: str | None) -> str | None:
    """Return Gamechanger services host for a club official website, if known."""
    if not club_name:
        return None
    key = _normalize_name_key(club_name)
    search_key = _club_search_key(club_name)
    for candidate in (key, search_key, f"fc{search_key}"):
        if candidate in GC_CLUB_SERVICES:
            return GC_CLUB_SERVICES[candidate]
    return None


def _gc_image_url(services_url: str, image_key: str, *, size: int = 256) -> str | None:
    key = str(image_key or "").strip()
    if not key or key.lower() in {"null", "none"}:
        return None
    if not re.search(r"\.(jpe?g|png|webp)$", key, flags=re.I):
        key = f"{key}.jpg"
    return f"https://images.gc.{services_url}/fit-in/{size}x{size}/{key}"


def _gc_first_team_id(services_url: str) -> str | None:
    try:
        response = requests.get(
            f"https://filters.football.web.gc.{services_url}/v2/filters",
            timeout=25,
            headers=GC_HEADERS,
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return None

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        slug = str(attrs.get("slugTeamName") or "").casefold()
        name = str(attrs.get("teamName") or "").casefold()
        # Most GC clubs use first-team; Salford (and some others) use mens-team.
        if slug in {"first-team", "mens-team", "men-s-team"} or name in {
            "first team",
            "mens team",
            "men's team",
            "men’s team",
        }:
            team_id = str(row.get("id") or "").strip()
            if team_id:
                return team_id
    for row in rows:
        if isinstance(row, dict) and row.get("type") == "team" and row.get("id"):
            return str(row["id"])
    return None


def fetch_club_website_squad_photos(
    club_name: str,
    *,
    force: bool = False,
) -> dict[str, dict[str, str]]:
    """Pull squad headshots from the club's official Gamechanger website API."""
    services_url = resolve_gc_club_services(club_name)
    if not services_url:
        return {}

    cache_key = services_url
    cached = _club_site_photo_cache.get(cache_key)
    now = time.time()
    if not force and cached and now - cached[0] < PHOTO_CACHE_TTL_SECONDS:
        return cached[1]

    team_id = _gc_first_team_id(services_url)
    if not team_id:
        _club_site_photo_cache[cache_key] = (now, {})
        return {}

    try:
        response = requests.get(
            f"https://teams.football.web.gc.{services_url}/v2/squads/opta",
            params={"teamID": team_id},
            timeout=30,
            headers=GC_HEADERS,
        )
        if response.status_code >= 400:
            _club_site_photo_cache[cache_key] = (now, {})
            return {}
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        _club_site_photo_cache[cache_key] = (now, {})
        return {}

    body = payload.get("body") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        _club_site_photo_cache[cache_key] = (now, {})
        return {}

    entries: dict[str, dict[str, str]] = {}
    for position, rows in body.items():
        if position == "staff" or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            first = str(row.get("firstName") or "").strip()
            surname = str(row.get("surname") or "").strip()
            known = str(row.get("knownName") or "").strip()
            full_name = known or " ".join(part for part in (first, surname) if part).strip()
            if not full_name:
                continue
            profile = row.get("playerProfileData") if isinstance(row.get("playerProfileData"), dict) else {}
            image_key = (
                profile.get("squadImageKey")
                or profile.get("playerProfileForegroundKey")
                or profile.get("profileImage")
                or profile.get("playerHeadshot")
                or row.get("imageSrc")
            )
            url = _gc_image_url(services_url, str(image_key or ""))
            if not url:
                continue
            key = _normalize_name_key(full_name)
            bucket: dict[str, str] = {
                "name": full_name,
                "url": url,
                "position": str(row.get("position") or position or ""),
                "source": "club_website",
            }
            shirt = row.get("shirtNumber")
            if shirt is not None and str(shirt).strip() != "":
                try:
                    bucket["shirt_number"] = str(int(str(shirt).strip()))
                except ValueError:
                    bucket["shirt_number"] = str(shirt).strip()
            entries[key] = bucket
            # Also index bare surname when unique enough for Impect short labels.
            if surname:
                surname_key = _normalize_name_key(surname)
                if surname_key and surname_key not in entries:
                    entries[surname_key] = dict(bucket)

    _club_site_photo_cache[cache_key] = (now, entries)
    return entries


def resolve_opponent_photo_source_url(
    player_name: str,
    *,
    club_name: str | None = None,
    season: str | None = None,
    force: bool = False,
    shirt_number: int | str | None = None,
) -> str | None:
    """Prefer Port Vale club photos, then official club site, then Transfermarkt."""
    if club_name and _is_port_vale_name(club_name):
        return resolve_squad_photo_url(player_name, force=force)

    if not club_name:
        return None

    club_site = fetch_club_website_squad_photos(club_name, force=force)
    if club_site:
        entry = _match_photo_entry(
            player_name,
            club_site,
            shirt_number=shirt_number,
        )
        if entry and entry.get("url"):
            return entry["url"]

    club_id = resolve_transfermarkt_club_id(club_name)
    if not club_id:
        return None

    entries = fetch_transfermarkt_squad_photos(
        club_id,
        season_year=_season_year(season),
        force=force,
    )
    entry = _match_photo_entry(
        player_name,
        entries,
        shirt_number=shirt_number,
    )
    return entry["url"] if entry and entry.get("url") else None


def _is_port_vale_name(name: str) -> bool:
    return "port vale" in str(name or "").casefold()


def opponent_photo_api_url(
    player_name: str,
    *,
    club_name: str | None = None,
    season: str | None = None,
    shirt_number: int | str | None = None,
) -> str | None:
    if not player_name:
        return None
    # Always expose the proxy URL for pitch markers; the route resolves the source.
    params = [f"name={quote(player_name)}"]
    if club_name:
        params.append(f"club={quote(club_name)}")
    if season:
        params.append(f"season={quote(str(season))}")
    if shirt_number is not None and str(shirt_number).strip() != "":
        params.append(f"shirt={quote(str(shirt_number))}")
    return "/api/pre-match/player-photo?" + "&".join(params)


def attach_pitch_player_photos(
    pitch_players: list[dict[str, Any]],
    *,
    club_name: str,
    season: str | None,
) -> list[dict[str, Any]]:
    if not pitch_players:
        return pitch_players

    # Warm club-site + Transfermarkt maps once so matching is free per player.
    if not _is_port_vale_name(club_name):
        fetch_club_website_squad_photos(club_name)
        club_id = resolve_transfermarkt_club_id(club_name)
        if club_id:
            fetch_transfermarkt_squad_photos(club_id, season_year=_season_year(season))

    for player in pitch_players:
        name = str(player.get("name") or "")
        shirt = player.get("shirt_number")
        source = resolve_opponent_photo_source_url(
            name,
            club_name=club_name,
            season=season,
            shirt_number=shirt,
        )
        if source:
            player["photo_url"] = opponent_photo_api_url(
                name,
                club_name=club_name,
                season=season,
                shirt_number=shirt,
            )
        else:
            player["photo_url"] = None
    return pitch_players


def fetch_opponent_photo_bytes(source_url: str) -> tuple[bytes, str]:
    headers = dict(TM_HEADERS)
    if "images.gc." in source_url:
        referer = "https://www.tranmererovers.co.uk/"
        if "crewealexandrafcservices" in source_url:
            referer = "https://www.crewealex.net/"
        elif "swindontownfcservices" in source_url:
            referer = "https://www.swindontownfc.co.uk/"
        elif "salfordcityfcservices" in source_url:
            referer = "https://www.salfordcityfc.co.uk/"
        headers = {
            "User-Agent": GC_HEADERS["User-Agent"],
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer,
        }
    response = requests.get(source_url, timeout=25, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"Photo request failed ({response.status_code})")
    content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    return response.content, content_type
