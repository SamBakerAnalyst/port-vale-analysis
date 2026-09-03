"""Public-web enrichment for player dossiers (Transfermarkt + best-effort FBRef)."""

from __future__ import annotations

import html as html_lib
import re
import time
from typing import Any
from urllib.parse import urljoin

import requests

from app.opponent_photos import TM_HEADERS, _normalize_name_key, _name_tokens
from app.set_piece_pre_match import _height_label_from_cm, _parse_tm_height_cm

_TM_PROFILE_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_FBREF_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_CACHE_TTL = 6 * 60 * 60

FBREF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://fbref.com/",
}


def _clean_text(value: str) -> str:
    text = html_lib.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ·|")


def _search_transfermarkt_player_url(player_name: str, club_name: str | None = None) -> str | None:
    queries = [f"{player_name} {club_name or ''}".strip(), player_name]
    seen: set[str] = set()
    for query in queries:
        if not query or query in seen:
            continue
        seen.add(query)
        try:
            response = requests.get(
                "https://www.transfermarkt.co.uk/schnellsuche/ergebnis/schnellsuche",
                params={"query": query},
                timeout=25,
                headers=TM_HEADERS,
            )
            if response.status_code >= 400:
                continue
            html = response.text
        except requests.RequestException:
            continue

        links = re.findall(
            r'href="(/[a-z0-9\-]+/profil/spieler/(\d+))"',
            html,
            flags=re.I,
        )
        if not links:
            continue

        surname = _name_tokens(player_name)[1]
        first = _name_tokens(player_name)[0]
        ranked: list[tuple[int, str]] = []
        for path, _player_id in links:
            slug = path.strip("/").split("/")[0]
            score = 0
            slug_key = _normalize_name_key(slug)
            if surname and surname in slug_key:
                score += 3
            if first and first[:3] in slug_key:
                score += 1
            if slug_key == _normalize_name_key(player_name):
                score += 4
            ranked.append((score, f"https://www.transfermarkt.co.uk{path}"))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if ranked and ranked[0][0] > 0:
            return ranked[0][1]
        return f"https://www.transfermarkt.co.uk{links[0][0]}"
    return None


def _parse_transfermarkt_profile(html: str, profile_url: str) -> dict[str, Any]:
    info: dict[str, str] = {}
    for match in re.finditer(
        r'class="info-table__content info-table__content--regular"[^>]*>(.*?)</span>\s*'
        r'<span class="info-table__content info-table__content--bold"[^>]*>(.*?)</span>',
        html,
        flags=re.S | re.I,
    ):
        label = _clean_text(match.group(1)).rstrip(":")
        value = _clean_text(match.group(2))
        if label and value:
            info[label.casefold()] = value

    height_raw = info.get("height") or ""
    if not height_raw:
        hdr = re.search(
            r'Height:.*?<span[^>]*class="data-header__content"[^>]*>(.*?)</span>',
            html,
            flags=re.S | re.I,
        )
        height_raw = _clean_text(hdr.group(1)) if hdr else ""
    if not height_raw:
        # UK TM often shows imperial in the header row ("5 ft 10 in").
        ft = re.search(
            r"(\d+)\s*ft\s*(\d{1,2})\s*in",
            html,
            flags=re.I,
        )
        if ft:
            height_raw = f"{ft.group(1)} ft {ft.group(2)} in"
    height_cm = _parse_tm_height_cm(height_raw)

    market_value = None
    mv_match = re.search(
        r'class="data-header__market-value-wrapper"[^>]*>(.*?)</a>',
        html,
        flags=re.S | re.I,
    )
    if mv_match:
        mv_text = _clean_text(mv_match.group(1))
        mv_text = re.sub(r"Last update:.*$", "", mv_text, flags=re.I).strip()
        if mv_text:
            market_value = mv_text

    photo = None
    img_match = re.search(
        r'src="(https://img\.a\.transfermarkt\.technology/portrait/(?:header|big|medium)/[^"]+)"',
        html,
        flags=re.I,
    )
    if img_match:
        photo = img_match.group(1)

    citizenship = info.get("citizenship") or info.get("nationality")
    if citizenship:
        parts = [p for p in re.split(r"\s*/\s*|\s{2,}", citizenship) if p]
        cleaned: list[str] = []
        for part in parts:
            token = re.sub(r"\s+", " ", part).strip()
            if token.casefold() == "the":
                continue
            if token.casefold() == "gambia" and cleaned and cleaned[-1].casefold() == "the gambia":
                continue
            if token.casefold() == "gambia":
                token = "The Gambia"
            if token and token not in cleaned:
                cleaned.append(token)
        citizenship = " / ".join(cleaned) if cleaned else None

    foot = info.get("foot") or ""
    if foot.lower().startswith("right"):
        foot = "R"
    elif foot.lower().startswith("left"):
        foot = "L"
    elif foot.lower().startswith("both"):
        foot = "Both"

    labeled_height = _height_label_from_cm(height_cm) if height_cm else None
    if not labeled_height and height_raw:
        # Only keep raw if it looks like a real height (not placeholder).
        if re.search(r"\d", height_raw) and not re.match(r"^0+(\s*'|\s*ft)", height_raw.strip(), re.I):
            labeled_height = height_raw

    return {
        "source": "transfermarkt",
        "profile_url": profile_url,
        "full_name": info.get("name in home country") or info.get("name"),
        "height": labeled_height,
        "height_cm": height_cm,
        "foot": foot or None,
        "citizenship": citizenship or None,
        "position": info.get("position") or None,
        "current_club": info.get("current club") or None,
        "market_value": market_value,
        "contract_expires": info.get("contract expires") or None,
        "on_loan_from": info.get("on loan from") or None,
        "photo_url": photo,
        "date_of_birth": info.get("date of birth/age") or info.get("date of birth"),
    }


def fetch_transfermarkt_player_profile(
    player_name: str,
    *,
    club_name: str | None = None,
) -> dict[str, Any] | None:
    cache_key = f"{_normalize_name_key(player_name)}|{_normalize_name_key(club_name or '')}"
    cached = _TM_PROFILE_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    profile_url = _search_transfermarkt_player_url(player_name, club_name)
    if not profile_url:
        _TM_PROFILE_CACHE[cache_key] = (now, None)
        return None
    try:
        response = requests.get(profile_url, timeout=30, headers=TM_HEADERS)
        if response.status_code >= 400:
            _TM_PROFILE_CACHE[cache_key] = (now, None)
            return None
        payload = _parse_transfermarkt_profile(response.text, profile_url)
    except requests.RequestException:
        _TM_PROFILE_CACHE[cache_key] = (now, None)
        return None

    _TM_PROFILE_CACHE[cache_key] = (now, payload)
    return payload


def _search_fbref_player_url_via_bing(player_name: str) -> str | None:
    query = f"site:fbref.com/en/players {player_name}"
    try:
        response = requests.get(
            "https://www.bing.com/search",
            params={"q": query},
            timeout=20,
            headers={
                "User-Agent": FBREF_HEADERS["User-Agent"],
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )
        if response.status_code >= 400:
            return None
        html = html_lib.unescape(response.text)
    except requests.RequestException:
        return None

    first, surname = _name_tokens(player_name)
    ranked: list[tuple[int, str]] = []
    for path in re.findall(r"fbref\.com(/en/players/[a-f0-9]+/[A-Za-z0-9\-]+)", html, flags=re.I):
        clean = path.split("?")[0]
        leaf = clean.rstrip("/").rsplit("/", 1)[-1].casefold()
        if leaf in {"all", "matchlogs", "scout", "passing", "shooting", "defense", "possession", "misc"}:
            continue
        slug_key = _normalize_name_key(leaf.replace("-", " "))
        score = 0
        if surname and surname in slug_key:
            score += 3
        if first and first in slug_key:
            score += 2
        if slug_key == _normalize_name_key(player_name):
            score += 5
        ranked.append((score, f"https://fbref.com{clean}"))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    return ranked[0][1] if ranked else None


def _search_fbref_player_url_via_wikidata(player_name: str) -> str | None:
    """Resolve FBref URL via Wikidata (P5750) — reliable when CF blocks FBref search."""
    try:
        search = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": player_name,
                "language": "en",
                "format": "json",
                "limit": 8,
            },
            timeout=20,
            headers={"User-Agent": FBREF_HEADERS["User-Agent"], "Accept": "application/json"},
        )
        if search.status_code >= 400:
            return None
        entities = search.json().get("search") or []
    except (requests.RequestException, ValueError, TypeError):
        return None

    first, surname = _name_tokens(player_name)
    ranked: list[tuple[int, str]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        qid = str(entity.get("id") or "")
        if not qid:
            continue
        label = str(entity.get("label") or "")
        desc = str(entity.get("description") or "").casefold()
        label_key = _normalize_name_key(label)
        score = 0
        if label_key == _normalize_name_key(player_name):
            score += 6
        if surname and surname in label_key:
            score += 2
        if first and first in label_key:
            score += 1
        if any(token in desc for token in ("football", "soccer", "association football")):
            score += 4
        if "disambiguation" in desc:
            score -= 5
        ranked.append((score, qid))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 4:
        return None

    for _score, qid in ranked[:3]:
        try:
            ent = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbgetentities",
                    "ids": qid,
                    "props": "claims",
                    "format": "json",
                },
                timeout=20,
                headers={"User-Agent": FBREF_HEADERS["User-Agent"], "Accept": "application/json"},
            )
            if ent.status_code >= 400:
                continue
            claims = ((ent.json().get("entities") or {}).get(qid) or {}).get("claims") or {}
        except (requests.RequestException, ValueError, TypeError):
            continue

        # P5750 = FBref player ID (8-char hex). P8912 sometimes holds the slug.
        fbref_id = None
        slug = None
        for prop in ("P5750",):
            rows = claims.get(prop) or []
            if not rows:
                continue
            try:
                fbref_id = str(rows[0]["mainsnak"]["datavalue"]["value"])
            except (KeyError, TypeError, IndexError):
                fbref_id = None
        slug_rows = claims.get("P8912") or []
        if slug_rows:
            try:
                slug = str(slug_rows[0]["mainsnak"]["datavalue"]["value"])
            except (KeyError, TypeError, IndexError):
                slug = None
        if not fbref_id:
            continue
        if not slug:
            slug = "-".join(p.capitalize() for p in str(player_name).split())
            slug = re.sub(r"[^A-Za-z0-9\-]+", "", slug.replace(" ", "-"))
        return f"https://fbref.com/en/players/{fbref_id}/{slug}"
    return None


def _search_fbref_player_url(player_name: str) -> str | None:
    # 1) Wikidata P5750 — most reliable from the droplet.
    url = _search_fbref_player_url_via_wikidata(player_name)
    if url:
        return url

    # 2) Direct FBref search (often Cloudflare-blocked from servers).
    try:
        response = requests.get(
            "https://fbref.com/en/search/search.fcgi",
            params={"search": player_name},
            timeout=8,
            headers=FBREF_HEADERS,
            allow_redirects=True,
        )
        if response.status_code < 400 and "Just a moment" not in response.text[:400]:
            if "/players/" in response.url and response.url.rstrip("/").count("/") >= 5:
                return response.url.split("?")[0].split("/all")[0].rstrip("/")
            match = re.search(r'href="(/en/players/[a-f0-9]+/[A-Za-z0-9\-]+)"', response.text)
            if match:
                return urljoin("https://fbref.com", match.group(1))
    except requests.RequestException:
        pass

    # 3) Bing / DuckDuckGo HTML fallbacks.
    return _search_fbref_player_url_via_bing(player_name) or _search_fbref_player_url_via_ddg(
        player_name
    )


def _search_fbref_player_url_via_ddg(player_name: str) -> str | None:
    query = f"site:fbref.com/en/players {player_name}"
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=25,
            headers={
                "User-Agent": FBREF_HEADERS["User-Agent"],
                "Accept-Language": "en-GB,en;q=0.9",
            },
        )
        if response.status_code >= 400:
            return None
        html = html_lib.unescape(response.text)
    except requests.RequestException:
        return None

    first, surname = _name_tokens(player_name)
    ranked: list[tuple[int, str]] = []
    for path in re.findall(r"fbref\.com(/en/players/[a-f0-9]+/[A-Za-z0-9\-]+)", html, flags=re.I):
        clean = path.split("?")[0]
        # Skip non-profile tabs.
        leaf = clean.rstrip("/").rsplit("/", 1)[-1].casefold()
        if leaf in {"all", "matchlogs", "scout", "passing", "shooting", "defense", "possession", "misc"}:
            continue
        slug_key = _normalize_name_key(leaf.replace("-", " "))
        score = 0
        if surname and surname in slug_key:
            score += 3
        if first and first in slug_key:
            score += 2
        if slug_key == _normalize_name_key(player_name):
            score += 5
        ranked.append((score, f"https://fbref.com{clean}"))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked and ranked[0][0] > 0:
        return ranked[0][1]
    return ranked[0][1] if ranked else None


def _fetch_fbref_html(page_url: str) -> tuple[str, str] | None:
    """Return (html, resolved_url). Prefer live FBref; fall back to Wayback Machine."""
    try:
        response = requests.get(page_url, timeout=8, headers=FBREF_HEADERS)
        if (
            response.status_code < 400
            and "Just a moment" not in response.text[:500]
            and 'data-stat="games"' in response.text
        ):
            return response.text, page_url
    except requests.RequestException:
        pass

    # Prefer concrete Wayback timestamps — soft year buckets often 503 from the droplet.
    archive_candidates = [
        f"https://web.archive.org/web/20240601000000/{page_url}",
        f"https://web.archive.org/web/20250101000000/{page_url}",
        f"https://web.archive.org/web/20241215000000/{page_url}",
    ]
    for archive_url in archive_candidates:
        try:
            response = requests.get(
                archive_url,
                timeout=30,
                headers={
                    "User-Agent": FBREF_HEADERS["User-Agent"],
                    "Accept-Language": "en-GB,en;q=0.9",
                },
                allow_redirects=True,
            )
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue
        if 'data-stat="games"' not in response.text:
            continue
        return response.text, page_url
    return None


def _fbref_cell(row_html: str, stat: str) -> str | None:
    m = re.search(
        rf'data-stat="{re.escape(stat)}"[^>]*>(.*?)</t[dh]>',
        row_html,
        flags=re.S | re.I,
    )
    if not m:
        return None
    text = _clean_text(m.group(1))
    return text or None


def _fbref_num(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text or text == "—":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_fbref_career(html: str) -> dict[str, Any]:
    """Career totals from the Standard Stats table footer (domestic leagues)."""
    # Avoid catastrophic regex over the full page — locate the table, then its tfoot.
    start = html.lower().find('id="stats_standard')
    if start < 0:
        start = html.lower().find("id='stats_standard")
    if start < 0:
        return {}
    window = html[start : start + 200_000]
    tfoot_match = re.search(r"<tfoot>(.*?)</tfoot>", window, flags=re.S | re.I)
    if not tfoot_match:
        return {}
    tfoot = tfoot_match.group(1)
    best: dict[str, Any] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", tfoot, flags=re.S | re.I):
        label = _clean_text(row[:240])
        label_cf = label.casefold()
        # Overall career footer looks like "10 Seasons 6 Clubs 3 Leagues …"
        # Skip club splits ("Crewe Alexandra (6 Seasons)") and league splits.
        is_overall = ("clubs" in label_cf and "seasons" in label_cf) or label_cf.startswith("career")
        if not is_overall:
            continue
        games = _fbref_num(_fbref_cell(row, "games"))
        starts = _fbref_num(_fbref_cell(row, "games_starts"))
        minutes = _fbref_num(_fbref_cell(row, "minutes"))
        goals = _fbref_num(_fbref_cell(row, "goals"))
        assists = _fbref_num(_fbref_cell(row, "assists"))
        if games is None and minutes is None:
            continue
        candidate = {
            "matches": int(games) if games is not None else None,
            "starts": int(starts) if starts is not None else None,
            "minutes": int(minutes) if minutes is not None else None,
            "goals": int(goals) if goals is not None else None,
            "assists": int(assists) if assists is not None else None,
            "label": label.rstrip("<").strip(),
        }
        if (candidate.get("minutes") or 0) >= (best.get("minutes") or 0):
            best = candidate
    return best


def _parse_fbref_summary(html: str, page_url: str) -> dict[str, Any]:
    """Pull season headline + career totals from an FBRef player page."""
    stats: dict[str, Any] = {"source": "fbref", "profile_url": page_url}

    # Latest season row — prefer the most recent year row without heavy backtracking.
    season_html = html
    std = html.lower().find('id="stats_standard')
    if std >= 0:
        season_html = html[std : std + 80_000]
    season_row: str | None = None
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", season_html, flags=re.S | re.I):
        row = m.group(0)
        if 'data-stat="year_id"' not in row:
            continue
        year_raw = _fbref_cell(row, "year_id") or ""
        if not re.search(r"\d{4}", year_raw):
            continue
        season_row = row
        break
    if season_row:
        mapping = {
            "season": "year_id",
            "squad": "team",
            "comp": "comp_level",
            "matches": "games",
            "starts": "games_starts",
            "minutes": "minutes",
            "goals": "goals",
            "assists": "assists",
            "goals_assists": "goals_assists",
            "xg": "xg",
            "xg_assist": "xg_assist",
            "npxg": "npxg",
            "shots": "shots",
            "shots_on_target": "shots_on_target",
            "progressive_carries": "progressive_carries",
            "progressive_passes": "progressive_passes",
        }
        for key, stat in mapping.items():
            raw = _fbref_cell(season_row, stat)
            if raw is None:
                continue
            if key in {"season", "squad", "comp"}:
                stats[key] = raw
                continue
            num = _fbref_num(raw)
            stats[key] = num if num is not None else raw

    career = _parse_fbref_career(html)
    if career:
        stats["career"] = career
        # Promote career totals to top-level keys used by Meeting Front Pages.
        for key in ("matches", "starts", "minutes", "goals", "assists"):
            if career.get(key) is not None:
                stats[f"career_{key}"] = career[key]

    # Scout summary percentiles — only scan a small overview window (full-page
    # regex over FBref HTML is catastrophically slow).
    overview_idx = html.casefold().find("scout summary")
    if overview_idx >= 0:
        overview = html[overview_idx : overview_idx + 20_000]
        scout: list[dict[str, Any]] = []
        for m in re.finditer(
            r'<th[^>]*scope="row"[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>.*?'
            r'class="[^"]*pips[^"]*"[^>]*style="[^"]*--pip:\s*(\d+)',
            overview,
            flags=re.S | re.I,
        ):
            label = _clean_text(m.group(1))
            value = _clean_text(m.group(2))
            try:
                pct = int(m.group(3))
            except ValueError:
                continue
            if label:
                scout.append({"label": label, "value": value, "pct": pct})
            if len(scout) >= 8:
                break
        if scout:
            stats["scout_pips"] = scout
    return stats


def fetch_fbref_player_summary(player_name: str) -> dict[str, Any] | None:
    cache_key = _normalize_name_key(player_name)
    cached = _FBREF_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    page_url = _search_fbref_player_url(player_name)
    if not page_url:
        _FBREF_CACHE[cache_key] = (now, None)
        return None

    fetched = _fetch_fbref_html(page_url)
    if not fetched:
        _FBREF_CACHE[cache_key] = (now, None)
        return None
    html, resolved_url = fetched
    payload = _parse_fbref_summary(html, resolved_url)

    usable_keys = (
        "goals",
        "assists",
        "xg",
        "minutes",
        "career_minutes",
        "career_matches",
        "matches",
    )
    if not any(isinstance(payload.get(k), (int, float)) for k in usable_keys):
        _FBREF_CACHE[cache_key] = (now, None)
        return None
    _FBREF_CACHE[cache_key] = (now, payload)
    return payload


def enrich_player_web(
    player_name: str,
    *,
    club_name: str | None = None,
) -> dict[str, Any]:
    tm = fetch_transfermarkt_player_profile(player_name, club_name=club_name)
    fbref = fetch_fbref_player_summary(player_name)
    return {
        "transfermarkt": tm,
        "fbref": fbref,
    }
