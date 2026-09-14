"""PA Meeting Slides — video title cards for performance analysis meetings.

Pick an opponent (badges), choose topics such as Attacking / Defensive Corners,
pull high-quality Port Vale photos, then download a PNG pack for the video.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.handout_badges import (
    PORT_VALE_BADGE_URL,
    fotmob_crest_url_for_club,
    hydrate_team_badge,
)
from app.opponent_photos import WEB_HEADERS, _normalize_name_key
from app.paths import DATA_ROOT, HUB_ROOT, STANDALONE_DIR, ensure_data_dirs

PORT_VALE_NAME = "Port Vale"
_BADGES_JSON = HUB_ROOT / "data" / "efl-transfer-badges.json"
_STORE_PATH = DATA_ROOT / "pa-meeting-slides.json"
_STORE_LOCK = threading.Lock()
_PHOTO_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_PHOTO_TTL = 30 * 60
_CLUBS_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_CLUBS_TTL = 6 * 60 * 60

PHOTO_SEASON = "26/27"
PHOTO_SEASON_YEAR = "2026"
BING_AGE_RECENT = "lt-6m"
BING_AGE_YEAR = "lt-1y"
_STALE_YEAR_RE = re.compile(r"(?:^|[^0-9])(201[5-9]|202[0-5])(?:[^0-9]|$)")
_SEASON_TOKEN_RE = re.compile(r"26/?27|26-27|2026[-/]27|2026_27")
_EARLY_2026_RE = re.compile(
    r"(?:2026[-/_.]0[1-5]|monthly_2026_0[1-5]|/2026/0[1-5]/)"
)
_IN_SEASON_2026_RE = re.compile(
    r"(?:2026[-/_.]0[6-9]|monthly_2026_0[6-9]|/2026/0[6-9]/|"
    r"2026[-/_.]1[0-2]|monthly_2026_1[0-2]|/2026/1[0-2]/)"
)
_LAST_SEASON_NAME_RE = re.compile(
    r"(?:\d{2}\s+\d{2}\s+25)|(?:20)?25[-/ ]09[-/ ]25|carabao|2025[-/]"
)
_MATCH_FILENAME_RE = re.compile(
    r"\([ha]\)|shutterstock_editorial|(?:^|/)img_|(?:^|/)dsc|0a5a|pxl_|training|friendly",
    re.I,
)
_JUNK_PHOTO_RE = re.compile(
    r"logo|crest|badge|wappen|favicon|fixture|wallpaper|kit|shirt|thumbnail|thumb|"
    r"pvtv|webwatch|weblisten|signing|potm|membership|holding|officials|sponsor|"
    r"percbar|predictz|infographic|poster|banner|maxresdefault|share-image|"
    r"og/en/soccer|squad.?numbers|hall.of.fame|pre-season-header|png\.jpeg",
    re.I,
)
_JUNK_PHOTO_HOSTS = (
    "ytimg.com",
    "predictz.",
    "sofascore.",
    "espncdn.com",
    "footballkitarchive.",
    "footyheadlines.",
    "transfermarkt.",
    "worldsoccerdata.",
    "soccerpunter.",
    "happeningnext.",
    "timeoutdoors.",
    "lovepirate.",
    "recoveryvoices.",
    "tourist.org.uk",
    "tvvestjylland.",
    "thekitman.",
    "scores24.",
    "lenspredict.",
    "chelseafc.",
)
_TRUSTED_PHOTO_HOSTS = (
    "port-vale.co.uk",
    "onevalefan.co.uk",
    "gettyimages.",
    "imago-images.",
    "pa.media",
    "paimages",
    "offside",
    "actionimages",
    "stokesentinel",
    "reachplc.com",
    "bbc.co.uk",
    "skysports",
)
_CLUB_NEWS_URL = "https://www.port-vale.co.uk/news"
_CLUB_CDN_STYLES = ("cc_2000x1125", "cc_1600x900", "cc_1280x720", "cc_960x540")
_BING_PHOTO_QFT = "filterui:photo-photo+filterui:imagesize-large+filterui:aspect-wide"

PACKS: dict[str, dict[str, Any]] = {
    "set-plays": {
        "id": "set-plays",
        "label": "Set Plays",
        "topics": [
            "Attacking Corners",
            "Defensive Corners",
            "Attacking Free Kicks",
            "Defensive Free Kicks",
            "Throw-ins",
        ],
        "extraTopics": [
            "Penalties",
            "Long Throws",
            "Kick-offs",
            "Goal Kicks",
        ],
    },
    "in-possession": {
        "id": "in-possession",
        "label": "In Possession",
        "topics": [
            "Build-up",
            "Progression",
            "Final Third",
            "Crossing",
            "Finishing",
        ],
        "extraTopics": ["Combinations", "Switches"],
    },
    "out-of-possession": {
        "id": "out-of-possession",
        "label": "Out of Possession",
        "topics": [
            "Press",
            "Mid-block",
            "Low Block",
            "Rest Defence",
            "Transitions Against",
        ],
        "extraTopics": ["Duels", "Box Defence"],
    },
    "post-match": {
        "id": "post-match",
        "label": "Post-Match",
        "topics": [
            "What Went Well",
            "What To Fix",
            "Goals For",
            "Goals Against",
            "Set Plays",
        ],
        "extraTopics": ["Individuals", "Next Fixture"],
    },
}

LEAGUE_LABELS = {
    "league-one": "League One",
    "league-two": "League Two",
    "championship": "Championship",
    "national-league": "National League",
    "national-league-north": "National League North",
    "national-league-south": "National League South",
    "scottish-premiership": "Scottish Prem",
}


def _proxy_photo_url(url: str) -> str:
    token = str(url or "").strip()
    if not token:
        return ""
    if token.startswith("/"):
        return token
    return f"/api/pa-meeting-slides/image-proxy?url={quote(token, safe='')}"


def _rewrite_photo_proxies(photos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in photos:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        raw = str(item.get("url") or "").strip()
        item["proxyUrl"] = _proxy_photo_url(raw) if raw.startswith("http") else (item.get("proxyUrl") or raw)
        out.append(item)
    return out


def _load_badge_catalog() -> dict[str, Any]:
    try:
        payload = json.loads(_BADGES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _club_row(slug: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    try:
        fotmob_id = int(raw.get("fotmob_id") or 0)
    except (TypeError, ValueError):
        fotmob_id = 0
    league_key = str(raw.get("league") or "").strip()
    badge = fotmob_crest_url_for_club(name)
    if not badge and fotmob_id > 0:
        badge = f"https://images.fotmob.com/image_resources/logo/teamlogo/{fotmob_id}.png"
    hydrated = hydrate_team_badge({"name": name, "id": fotmob_id})
    badge_url = str(hydrated.get("badge_url") or badge or "")
    return {
        "id": slug,
        "name": name,
        "league": LEAGUE_LABELS.get(league_key, league_key.replace("-", " ").title()),
        "leagueKey": league_key,
        "fotmobId": fotmob_id or None,
        "badgeUrl": badge_url,
        "badgeProxyUrl": _proxy_photo_url(badge_url) if badge_url.startswith("http") else badge_url,
        "portVale": "port vale" in name.casefold(),
    }


def list_clubs(*, q: str = "", league: str | None = None) -> list[dict[str, Any]]:
    global _CLUBS_CACHE
    now = time.time()
    if _CLUBS_CACHE and now - _CLUBS_CACHE[0] < _CLUBS_TTL:
        rows = list(_CLUBS_CACHE[1])
    else:
        rows = []
        for slug, raw in _load_badge_catalog().items():
            if not isinstance(raw, dict):
                continue
            row = _club_row(str(slug), raw)
            if row:
                rows.append(row)
        rows.sort(key=lambda item: str(item.get("name") or "").casefold())
        _CLUBS_CACHE = (now, rows)

    needle = str(q or "").strip().casefold()
    league_key = str(league or "").strip().casefold()
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("portVale"):
            continue
        if league_key and str(row.get("leagueKey") or "").casefold() != league_key:
            continue
        if needle:
            blob = f"{row.get('name') or ''} {row.get('league') or ''} {row.get('id') or ''}".casefold()
            if needle not in blob:
                continue
        out.append(row)
    return out


def port_vale_club() -> dict[str, Any]:
    return {
        "id": "port-vale",
        "name": PORT_VALE_NAME,
        "league": "League Two",
        "leagueKey": "league-two",
        "fotmobId": 9799,
        "badgeUrl": PORT_VALE_BADGE_URL,
        "badgeProxyUrl": PORT_VALE_BADGE_URL,
        "portVale": True,
    }


def resolve_club(token: str) -> dict[str, Any] | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    if "port vale" in raw.casefold():
        return port_vale_club()
    key = re.sub(r"[^a-z0-9]+", "", raw.casefold())
    for row in list_clubs():
        hay = re.sub(r"[^a-z0-9]+", "", str(row.get("name") or "").casefold())
        slug = re.sub(r"[^a-z0-9]+", "", str(row.get("id") or "").casefold())
        if raw.casefold() in {str(row.get("id") or "").casefold(), str(row.get("name") or "").casefold()}:
            return row
        if key and (key == hay or key == slug or key in hay or hay in key):
            return row
    return None


def default_slides(pack_id: str, opponent_name: str = "") -> list[dict[str, Any]]:
    pack = PACKS.get(pack_id) or PACKS["set-plays"]
    cover_title = str(pack["label"])
    slides = [
        {
            "id": "cover",
            "kind": "cover",
            "title": cover_title,
            "subtitle": opponent_name,
            "selected": True,
        }
    ]
    for index, title in enumerate(pack["topics"]):
        slides.append(
            {
                "id": f"topic-{index + 1}",
                "kind": "topic",
                "title": title,
                "subtitle": cover_title,
                "selected": True,
            }
        )
    return slides


def meta_payload() -> dict[str, Any]:
    vale = port_vale_club()
    return {
        "title": "PA Meeting Slides",
        "portVale": vale,
        "badgeUrl": vale["badgeUrl"],
        "slideSize": {"width": 1920, "height": 1080},
        "packs": list(PACKS.values()),
        "defaultPack": "set-plays",
        "photoSeason": PHOTO_SEASON,
        "leagues": [
            {"id": "league-two", "label": "League Two"},
            {"id": "league-one", "label": "League One"},
            {"id": "championship", "label": "Championship"},
        ],
    }


def _load_store() -> dict[str, Any]:
    ensure_data_dirs()
    if not _STORE_PATH.is_file():
        return {"decks": {}}
    try:
        payload = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"decks": {}}
    if not isinstance(payload, dict):
        return {"decks": {}}
    decks = payload.get("decks")
    if not isinstance(decks, dict):
        payload["decks"] = {}
    return payload


def _persist_store(payload: dict[str, Any]) -> None:
    ensure_data_dirs()
    tmp = _STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(_STORE_PATH)


def list_decks() -> list[dict[str, Any]]:
    store = _load_store()
    rows = []
    for key, row in (store.get("decks") or {}).items():
        if not isinstance(row, dict):
            continue
        opponent = row.get("opponent") if isinstance(row.get("opponent"), dict) else {}
        rows.append(
            {
                "id": key,
                "title": row.get("title") or "",
                "packId": row.get("packId") or "set-plays",
                "opponentName": opponent.get("name") or row.get("opponentName") or "",
                "updatedAt": row.get("updatedAt") or "",
            }
        )
    rows.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return rows


def load_deck(deck_id: str) -> dict[str, Any] | None:
    store = _load_store()
    row = (store.get("decks") or {}).get(str(deck_id))
    return dict(row) if isinstance(row, dict) else None


def save_deck(deck_id: str, body: dict[str, Any]) -> dict[str, Any]:
    key = re.sub(r"[^a-z0-9-]+", "-", str(deck_id or "").strip().casefold()).strip("-")
    if not key:
        raise HTTPException(status_code=400, detail="Missing deck id.")
    doc = {
        "id": key,
        "title": str(body.get("title") or "").strip(),
        "packId": str(body.get("packId") or "set-plays"),
        "opponent": body.get("opponent") if isinstance(body.get("opponent"), dict) else {},
        "slides": body.get("slides") if isinstance(body.get("slides"), list) else [],
        "photoAssignments": (
            body.get("photoAssignments")
            if isinstance(body.get("photoAssignments"), dict)
            else {}
        ),
        "updatedAt": datetime.now(UTC).isoformat(),
    }
    with _STORE_LOCK:
        store = _load_store()
        store.setdefault("decks", {})[key] = doc
        _persist_store(store)
    return doc


def photo_url_is_stale(url: str) -> bool:
    """True when a URL itself dates the shot before 26/27 (2015–25, or Jan–May 2026)."""
    low = unquote(html.unescape(str(url or ""))).casefold()
    if _SEASON_TOKEN_RE.search(low) and not _EARLY_2026_RE.search(low):
        return False
    if _EARLY_2026_RE.search(low) or _LAST_SEASON_NAME_RE.search(low):
        return True
    return bool(_STALE_YEAR_RE.search(low))


def photo_url_is_match_shot(url: str) -> bool:
    """Keep 26/27 match photography; drop kits, fixtures, logos, thumbs, GIFs."""
    raw = unquote(html.unescape(str(url or "").strip()))
    if not raw.startswith(("http://", "https://")):
        return False
    low = raw.casefold()
    host = (urlparse(raw).hostname or "").casefold()
    path = urlparse(raw).path.casefold()
    if photo_url_is_stale(raw):
        return False
    if any(token in host for token in _JUNK_PHOTO_HOSTS):
        return False
    if _JUNK_PHOTO_RE.search(low):
        return False
    if not re.search(r"\.(jpe?g)(?:$|\?)", path):
        return False
    for width, height in re.findall(r"(?:[-_/]|cc_)(\d{2,4})x(\d{2,4})", low):
        if int(width) <= 480 or int(height) <= 320:
            return False
    filename = path.rsplit("/", 1)[-1]
    club_host = "port-vale.co.uk" in host
    if club_host:
        if not re.search(r"2026-0[7-9]|2026-1[0-2]|2027-", low):
            return False
        return bool(_MATCH_FILENAME_RE.search(filename) or _MATCH_FILENAME_RE.search(low))
    if any(token in host for token in _TRUSTED_PHOTO_HOSTS):
        return True
    return bool(_MATCH_FILENAME_RE.search(filename))


def _photo_season_rank(url: str) -> int:
    low = html.unescape(str(url or "")).casefold()
    if re.search(r"\([ha]\)", low):
        return 0
    if "shutterstock_editorial" in low:
        return 1
    if re.search(r"img_|dsc|0a5a|pxl_", low):
        return 2
    if photo_url_is_stale(url):
        return 9
    return 3


def _with_season(extra: str) -> str:
    token = str(extra or "").strip()
    low = token.casefold()
    if (
        PHOTO_SEASON_YEAR in token
        or "2027" in token
        or PHOTO_SEASON in token
        or "26/27" in low
        or "2026/27" in token
        or "26-27" in low
    ):
        return token
    return f"{token} {PHOTO_SEASON_YEAR}".strip() if token else PHOTO_SEASON_YEAR


def season_photo_queries(
    club_name: str,
    extra_query: str | None = None,
) -> list[tuple[str, str, str, str]]:
    """Tight Bing fallbacks — recent matches, not kit/fixture infographics."""
    name = str(club_name or "").strip()
    extra = str(extra_query or "").strip()
    is_vale = "port vale" in name.casefold() or name.casefold() == "valiants"
    queries: list[tuple[str, str, str, str]] = []
    if extra:
        queries.append((name, f"{_with_season(extra)} match action", "action", extra))
    if is_vale:
        for opponent in ("vs Salford", "vs Crewe", "vs Swindon", "vs Tranmere", "vs Oldham"):
            queries.append(("Port Vale", f"{opponent} 2026", "action", opponent))
        queries.append(("Port Vale", "match action 2026", "action", "Match action"))
        queries.append(("Port Vale", "site:port-vale.co.uk", "action", "Club site"))
    else:
        queries.extend(
            [
                (name, "match action 2026", "action", "Match action"),
                (name, "vs Port Vale 2026", "action", "vs Vale"),
            ]
        )
    return queries


def _club_photo_file_key(url: str) -> str:
    match = re.search(r"/public/(20\d{2}-\d{2}/[^?]+)", html.unescape(url), re.I)
    if match:
        return html.unescape(match.group(1)).casefold()
    return html.unescape(url).split("?")[0].casefold()


def _club_photo_label(url: str) -> str:
    match = re.search(r"/public/20\d{2}-\d{2}/([^/?]+)", unquote(html.unescape(url)), re.I)
    if not match:
        return "Club 26/27"
    name = html.unescape(match.group(1))
    name = re.sub(r"\.(?:jpe?g|png).*$", "", name, flags=re.I)
    name = re.sub(r"-\d+$", "", name).strip()
    if len(name) < 3 or len(name) > 42:
        return "Club 26/27"
    return name


def parse_club_news_photos(page_html: str) -> list[str]:
    """Largest 26/27 match photos from a port-vale.co.uk news listing."""
    style_rank = {style: index for index, style in enumerate(_CLUB_CDN_STYLES)}
    best: dict[str, tuple[int, str]] = {}
    for style in _CLUB_CDN_STYLES:
        pattern = (
            rf"(https://cdn\.port-vale\.co\.uk/sites/default/files/styles/"
            rf"{re.escape(style)}/public/20\d{{2}}-\d{{2}}/[^\"\s?]+(?:\?[^\"\s]*)?)"
        )
        for raw in re.findall(pattern, page_html, flags=re.I):
            url = html.unescape(raw).replace("&amp;", "&")
            if not photo_url_is_match_shot(url):
                continue
            key = _club_photo_file_key(url)
            rank = style_rank.get(style, 99)
            current = best.get(key)
            if current is None or rank < current[0]:
                best[key] = (rank, url)
    ranked = sorted(best.values(), key=lambda row: (_photo_season_rank(row[1]), row[0]))
    return [url for _rank, url in ranked]


def _fetch_club_news_photos(*, pages: int = 5) -> list[str]:
    headers = {
        **WEB_HEADERS,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.port-vale.co.uk/",
    }
    found: list[str] = []
    seen: set[str] = set()
    for page in range(pages):
        url = _CLUB_NEWS_URL if page == 0 else f"{_CLUB_NEWS_URL}?page={page}"
        try:
            response = requests.get(url, timeout=20, headers=headers)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue
        for photo in parse_club_news_photos(response.text):
            key = _club_photo_file_key(photo)
            if key in seen:
                continue
            seen.add(key)
            found.append(photo)
    return found


def search_club_photos(
    club_name: str,
    *,
    extra_query: str | None = None,
    refresh: bool = False,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """26/27 match photos — club galleries first, Bing only as a filtered fallback."""
    from app.meeting_front_pages import _add_photo, _bing_photo_urls

    name = str(club_name or "").strip()
    if len(name) < 2:
        return []
    extra = str(extra_query or "").strip()
    is_vale = "port vale" in name.casefold() or name.casefold() == "valiants"
    cache_key = f"{_normalize_name_key(name)}|{_normalize_name_key(extra)}|2627-clubv2"
    now = time.time()
    if not refresh:
        cached = _PHOTO_CACHE.get(cache_key)
        if cached and now - cached[0] < _PHOTO_TTL and len(cached[1]) >= 6:
            return _rewrite_photo_proxies(cached[1])

    photos: list[dict[str, Any]] = []
    seen: set[str] = set()
    if is_vale and not extra:
        for url in _fetch_club_news_photos():
            _add_photo(
                photos,
                seen,
                url=url,
                source="club",
                label=_club_photo_label(url),
                kind="action",
            )
            if len(photos) >= limit:
                break

    if len(photos) < max(12, limit // 2):
        for club_q, extra_q, kind, label in season_photo_queries(name, extra):
            for url in _bing_photo_urls(
                club_q,
                None,
                query_extra=extra_q,
                limit=8,
                loose=False,
                age_filter=BING_AGE_RECENT,
                extra_qft=_BING_PHOTO_QFT,
            ):
                if not photo_url_is_match_shot(url):
                    continue
                _add_photo(photos, seen, url=url, source="bing", label=label, kind=kind)
            if len(photos) >= limit:
                break

    photos.sort(key=lambda row: _photo_season_rank(str(row.get("url") or "")))
    photos = [row for row in photos if photo_url_is_match_shot(str(row.get("url") or ""))][:limit]
    if len(photos) >= 4:
        _PHOTO_CACHE[cache_key] = (now, photos)
    return _rewrite_photo_proxies(photos)


def proxy_image(url: str) -> Response:
    token = str(url or "").strip()
    if not token.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid image URL.")
    host = (urlparse(token).hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="Invalid image host.")

    headers = {
        **WEB_HEADERS,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.google.com/",
    }
    if "transfermarkt" in token.casefold():
        headers["Referer"] = "https://www.transfermarkt.co.uk/"
    elif "bing." in token.casefold() or "msn.com" in token.casefold():
        headers["Referer"] = "https://www.bing.com/"
    elif "fotmob" in token.casefold():
        headers["Referer"] = "https://www.fotmob.com/"
    elif "portvale" in token.casefold():
        headers["Referer"] = "https://www.portvale.co.uk/"

    try:
        upstream = requests.get(token, timeout=25, headers=headers, stream=True)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Could not fetch image.") from exc
    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail="Image unavailable.")

    chunks: list[bytes] = []
    total = 0
    for chunk in upstream.iter_content(64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > 10 * 1024 * 1024:
            raise HTTPException(status_code=502, detail="Image too large.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=502, detail="Image unavailable.")

    content_type = upstream.headers.get("Content-Type") or "image/jpeg"
    if "image" not in content_type and "octet-stream" not in content_type:
        if content[:3] == b"\xff\xd8\xff":
            content_type = "image/jpeg"
        elif content[:8] == b"\x89PNG\r\n\x1a\n":
            content_type = "image/png"
        elif content[:4] == b"RIFF":
            content_type = "image/webp"
        else:
            raise HTTPException(status_code=502, detail="Upstream was not an image.")

    return Response(
        content=content,
        media_type=content_type.split(";")[0].strip(),
        headers={"Cache-Control": "public, max-age=86400"},
    )


def register_pa_meeting_slides_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "pa-meeting-slides.html"

    @app.get("/pa-meeting-slides", response_class=HTMLResponse)
    def pa_meeting_slides_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="PA Meeting Slides page missing.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/pa-meeting-slides/meta")
    def pa_meeting_slides_meta() -> dict[str, Any]:
        return meta_payload()

    @app.get("/api/pa-meeting-slides/clubs")
    def pa_meeting_slides_clubs(
        q: str = Query(""),
        league: str | None = Query(None),
    ) -> JSONResponse:
        clubs = list_clubs(q=q, league=league)
        return JSONResponse(
            {
                "clubs": clubs,
                "count": len(clubs),
                "portVale": port_vale_club(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/pa-meeting-slides/pack")
    def pa_meeting_slides_pack(
        opponent: str = Query(..., min_length=2),
        pack: str = Query("set-plays"),
    ) -> JSONResponse:
        club = resolve_club(opponent)
        if club is None:
            raise HTTPException(status_code=404, detail="Club not found — try Exeter City.")
        pack_id = pack if pack in PACKS else "set-plays"
        return JSONResponse(
            {
                "portVale": port_vale_club(),
                "opponent": club,
                "packId": pack_id,
                "pack": PACKS[pack_id],
                "slides": default_slides(pack_id, club["name"]),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/pa-meeting-slides/photos")
    def pa_meeting_slides_photos(
        club: str = Query("Port Vale"),
        q: str | None = Query(None),
        refresh: int = Query(0),
    ) -> JSONResponse:
        photos = search_club_photos(club, extra_query=q, refresh=bool(refresh))
        return JSONResponse(
            {"club": club, "query": q, "count": len(photos), "photos": photos},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/pa-meeting-slides/image-proxy")
    def pa_meeting_slides_image_proxy(url: str = Query(...)) -> Response:
        return proxy_image(url)

    @app.get("/api/pa-meeting-slides/decks")
    def pa_meeting_slides_decks() -> JSONResponse:
        return JSONResponse({"decks": list_decks()}, headers={"Cache-Control": "no-store"})

    @app.get("/api/pa-meeting-slides/decks/{deck_id}")
    def pa_meeting_slides_deck_get(deck_id: str) -> JSONResponse:
        row = load_deck(deck_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Deck not found.")
        return JSONResponse(row, headers={"Cache-Control": "no-store"})

    @app.put("/api/pa-meeting-slides/decks/{deck_id}")
    def pa_meeting_slides_deck_put(
        deck_id: str,
        body: dict[str, Any] = Body(...),
    ) -> JSONResponse:
        return JSONResponse(save_deck(deck_id, body if isinstance(body, dict) else {}))
