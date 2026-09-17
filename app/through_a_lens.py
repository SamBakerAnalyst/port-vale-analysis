"""Through a Lens Photography — Port Vale 26/27 match galleries for meeting slides.

Reads the public SmugMug gallery the club photographer publishes at
throughalensphotography.com/PVFC. Match folders (Oldham, Tranmere, …) are
listed as they appear on the site; staff pick a game and assign photos to
Meeting Front Pages slides.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any
from urllib.parse import quote, urljoin

import requests

from app.opponent_photos import WEB_HEADERS

SITE = "https://www.throughalensphotography.com"
GALLERY_PREFIX = "/PVFC/n-ns9wjB"
SEASON_PAGE = f"{GALLERY_PREFIX}/Season-2627"
SEASON_URL_PATH = "/PVFC/Season-2627"
MATCHES_URL_PATH = "/PVFC/Season-2627/Matches"
HEADSHOTS_URL_PATH = "/PVFC/Season-2627/Player-Headshots-Media-Day"

_GALLERY_TTL = 20 * 60
_PHOTO_TTL = 10 * 60
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()

_SIZE_PREFERENCE = (
    "ImageSizeX3Large",
    "ImageSizeX2Large",
    "ImageSizeXLarge",
    "ImageSizeOriginal",
    "ImageSizeLarge",
)
_THUMB_PREFERENCE = (
    "ImageSizeLarge",
    "ImageSizeMedium",
    "ImageSizeSmall",
    "ImageSizeThumb",
)


def _browser_headers(**extra: str) -> dict[str, str]:
    return {
        **WEB_HEADERS,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": f"{SITE}{SEASON_PAGE}",
        **extra,
    }


def gallery_web_url(url_path: str) -> str:
    """Turn a SmugMug UrlPath into the public custom-domain link."""
    path = str(url_path or "").strip()
    if not path:
        return f"{SITE}{SEASON_PAGE}"
    if path.startswith("http"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/PVFC/n-"):
        return urljoin(SITE, path)
    if path.startswith("/PVFC/"):
        path = "/PVFC/n-ns9wjB/" + path[len("/PVFC/") :]
    return urljoin(SITE, path)


def extract_public_api_key(html: str) -> str | None:
    match = re.search(r'var SM = \{env: \{"apiKey":"([^"]+)"', html)
    return match.group(1) if match else None


def extract_node_id_for_url_path(html: str, url_path: str) -> str | None:
    escaped = str(url_path or "").replace("/", r"\/")
    match = re.search(
        rf'"NodeID":"([^"]+)".{{0,260}}"UrlPath":"{re.escape(escaped)}"',
        html,
    )
    return match.group(1) if match else None


def album_key_from_uri(uri: str | None) -> str | None:
    token = str(uri or "")
    match = re.search(r"/album/([A-Za-z0-9]+)", token)
    return match.group(1) if match else None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _cache_get(key: str, ttl: float) -> Any | None:
    with _CACHE_LOCK:
        row = _CACHE.get(key)
    if not row:
        return None
    stored, payload = row
    if time.time() - stored > ttl:
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), payload)


def _fetch_html(path: str) -> str:
    url = path if str(path).startswith("http") else urljoin(SITE, path)
    response = requests.get(
        url,
        timeout=25,
        headers=_browser_headers(Accept="text/html,application/xhtml+xml"),
    )
    response.raise_for_status()
    return response.text


def _api_get(path: str, api_key: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = {
        "APIKey": api_key,
        "_accept": "application/json",
        "_verbosity": "1",
    }
    if params:
        query.update(params)
    response = requests.get(
        urljoin(SITE, path),
        params=query,
        timeout=25,
        headers=_browser_headers(Accept="application/json"),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _proxy_photo_url(url: str) -> str:
    token = str(url or "").strip()
    if not token:
        return ""
    if token.startswith("/"):
        return token
    return f"/api/meeting-front-pages/image-proxy?url={quote(token, safe='')}"


def _size_url(details: dict[str, Any] | None, preference: tuple[str, ...]) -> str:
    if not isinstance(details, dict):
        return ""
    for name in preference:
        row = details.get(name)
        if isinstance(row, dict):
            url = str(row.get("Url") or "").strip()
            if url.startswith("http"):
                return url
    template = str(details.get("ImageUrlTemplate") or "")
    if "#size#" in template:
        return template.replace("#size#", "X2")
    return ""


def _highlight_thumb(expansions: dict[str, Any], node_id: str) -> str:
    if not isinstance(expansions, dict) or not node_id:
        return ""
    highlight = None
    for key, value in expansions.items():
        if f"/highlight/node/{node_id}" in str(key).replace("\\", ""):
            highlight = value
            break
    image = None
    if isinstance(highlight, dict):
        image = highlight.get("Image") if isinstance(highlight.get("Image"), dict) else highlight
    if not isinstance(image, dict):
        return ""
    for field in ("ThumbnailUrl", "ArchivedUri"):
        url = str(image.get(field) or "").strip()
        if url.startswith("http"):
            return url
    image_key = str(image.get("ImageKey") or "")
    if not image_key:
        return ""
    details = expansions.get(f"/api/v2/image/{image_key}-0!sizedetails") or expansions.get(
        f"/api/v2/image/{image_key}-0!sizedetails?_shorturis="
    )
    nested = details.get("ImageSizeDetails") if isinstance(details, dict) else None
    return _size_url(nested if isinstance(nested, dict) else details if isinstance(details, dict) else None, _THUMB_PREFERENCE)


def _image_urls(image: dict[str, Any], expansions: dict[str, Any]) -> tuple[str, str]:
    image_key = str(image.get("ImageKey") or "")
    details = None
    if image_key and isinstance(expansions, dict):
        for key, value in expansions.items():
            if f"/image/{image_key}-0!sizedetails" in str(key).replace("\\", ""):
                details = value.get("ImageSizeDetails") if isinstance(value, dict) else value
                break
    if not isinstance(details, dict):
        details = None
    full = _size_url(details, _SIZE_PREFERENCE) or str(image.get("ArchivedUri") or "").strip()
    thumb = (
        _size_url(details, _THUMB_PREFERENCE)
        or str(image.get("ThumbnailUrl") or "").strip()
        or full
    )
    return thumb, full


def _session_key() -> tuple[str, str]:
    html = _fetch_html(SEASON_PAGE)
    api_key = extract_public_api_key(html)
    if not api_key:
        raise RuntimeError("Through a Lens gallery is missing a public client key.")
    season_node = extract_node_id_for_url_path(html, SEASON_URL_PATH)
    if not season_node:
        raise RuntimeError("Through a Lens 26/27 folder was not found.")
    return api_key, season_node


def _node_children(api_key: str, node_id: str, *, count: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {
        "count": str(count),
        "start": "1",
        "Type": "Folder Album Page",
        "_expand": "HighlightImage.ImageSizeDetails,Album",
    }
    try:
        payload = _api_get(f"/api/v2/node/{node_id}!children", api_key, params)
    except requests.RequestException:
        params.pop("_expand", None)
        payload = _api_get(f"/api/v2/node/{node_id}!children", api_key, params)
    response = payload.get("Response") if isinstance(payload.get("Response"), dict) else {}
    nodes = [row for row in _as_list(response.get("Node")) if isinstance(row, dict)]
    expansions = payload.get("Expansions") if isinstance(payload.get("Expansions"), dict) else {}
    return nodes, expansions


def _match_row(
    node: dict[str, Any],
    *,
    competition: str,
    expansions: dict[str, Any],
    kind: str,
) -> dict[str, Any]:
    node_id = str(node.get("NodeID") or "")
    url_path = str(node.get("UrlPath") or "").replace("\\/", "/")
    album_uri = ""
    uris = node.get("Uris") if isinstance(node.get("Uris"), dict) else {}
    album = uris.get("Album")
    if isinstance(album, str):
        album_uri = album
    elif isinstance(album, dict):
        album_uri = str(album.get("Uri") or album.get("Album") or "")
    return {
        "id": node_id or album_key_from_uri(album_uri) or url_path,
        "name": str(node.get("Name") or "Match").strip(),
        "competition": competition,
        "type": str(node.get("Type") or "Folder"),
        "path": url_path,
        "galleryUrl": gallery_web_url(url_path),
        "albumKey": album_key_from_uri(album_uri),
        "thumbUrl": _highlight_thumb(expansions, node_id),
        "kind": kind,
    }


def _resolve_album_key(api_key: str, match: dict[str, Any]) -> str | None:
    existing = str(match.get("albumKey") or "").strip()
    if existing:
        return existing
    if str(match.get("type") or "") == "Album":
        return None
    node_id = str(match.get("id") or "")
    if not node_id:
        return None
    children, _expansions = _node_children(api_key, node_id, count=10)
    for child in children:
        if str(child.get("Type") or "") != "Album":
            continue
        uris = child.get("Uris") if isinstance(child.get("Uris"), dict) else {}
        album = uris.get("Album")
        uri = album if isinstance(album, str) else str((album or {}).get("Uri") or "")
        key = album_key_from_uri(uri)
        if key:
            return key
    return None


def _child_node_id(nodes: list[dict[str, Any]], *, url_path: str | None = None, name: str | None = None) -> str | None:
    want_path = str(url_path or "").replace("\\/", "/").rstrip("/")
    want_name = str(name or "").casefold()
    for node in nodes:
        path = str(node.get("UrlPath") or "").replace("\\/", "/").rstrip("/")
        label = str(node.get("Name") or "").casefold()
        if want_path and path == want_path:
            return str(node.get("NodeID") or "") or None
        if want_name and label == want_name:
            return str(node.get("NodeID") or "") or None
    return None


def list_vale_galleries(*, refresh: bool = False) -> dict[str, Any]:
    cached = None if refresh else _cache_get("galleries", _GALLERY_TTL)
    if isinstance(cached, dict) and cached.get("matches"):
        return cached
    api_key, season_node = _session_key()
    season_children, _season_exp = _node_children(api_key, season_node, count=40)
    matches_node = _child_node_id(season_children, url_path=MATCHES_URL_PATH, name="Matches")
    headshots_node = _child_node_id(
        season_children,
        url_path=HEADSHOTS_URL_PATH,
        name="Player Headshots / Media Day",
    )
    competitions: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []

    if matches_node:
        comp_nodes, _exp = _node_children(api_key, matches_node, count=20)
        for comp in comp_nodes:
            name = str(comp.get("Name") or "").strip() or "Matches"
            node_id = str(comp.get("NodeID") or "")
            competitions.append({"id": node_id, "name": name, "path": str(comp.get("UrlPath") or "")})
            if not node_id:
                continue
            child_nodes, child_exp = _node_children(api_key, node_id, count=50)
            rows = [
                _match_row(child, competition=name, expansions=child_exp, kind="action")
                for child in child_nodes
            ]
            matches.extend(reversed(rows))

    if headshots_node:
        child_nodes, child_exp = _node_children(api_key, headshots_node, count=20)
        for child in child_nodes:
            matches.append(
                _match_row(
                    child,
                    competition="Headshots",
                    expansions=child_exp,
                    kind="portrait",
                )
            )
        if "Headshots" not in {c["name"] for c in competitions}:
            competitions.append({"id": headshots_node, "name": "Headshots", "path": HEADSHOTS_URL_PATH})

    used = {row["competition"] for row in matches}
    competitions = [row for row in competitions if row["name"] in used]

    payload = {
        "source": "through-a-lens",
        "galleryUrl": f"{SITE}{SEASON_PAGE}/Matches/League-",
        "competitions": competitions,
        "matches": matches,
        "count": len(matches),
    }
    if matches:
        _cache_set("galleries", payload)
    return payload


def photo_from_album_image(
    image: dict[str, Any],
    *,
    expansions: dict[str, Any] | None = None,
    match_name: str = "",
    kind: str = "action",
    index: int = 1,
) -> dict[str, Any] | None:
    if not isinstance(image, dict):
        return None
    thumb, full = _image_urls(image, expansions or {})
    url = full or thumb
    if not url.startswith("http"):
        return None
    image_key = str(image.get("ImageKey") or index)
    label_bits = [part for part in (match_name, str(image.get("FileName") or "").rsplit(".", 1)[0]) if part]
    return {
        "id": f"vale-{image_key}",
        "source": "through-a-lens",
        "label": " · ".join(label_bits) if label_bits else "Through a Lens",
        "kind": kind,
        "url": url,
        "thumbUrl": thumb or url,
        "proxyUrl": _proxy_photo_url(url),
        "proxyThumbUrl": _proxy_photo_url(thumb or url),
        "cutoutFriendly": kind == "portrait",
        "galleryUrl": str(image.get("WebUri") or "").replace("\\/", "/"),
    }


def list_vale_photos(
    *,
    node_id: str | None = None,
    album_key: str | None = None,
    match_name: str = "",
    kind: str = "action",
    start: int = 1,
    count: int = 40,
    refresh: bool = False,
) -> dict[str, Any]:
    start = max(1, int(start or 1))
    count = min(60, max(8, int(count or 40)))
    cache_key = f"photos|{album_key or ''}|{node_id or ''}|{start}|{count}|{kind}"
    cached = None if refresh else _cache_get(cache_key, _PHOTO_TTL)
    if isinstance(cached, dict) and cached.get("photos"):
        return cached

    api_key, _season_node = _session_key()
    resolved_key = str(album_key or "").strip() or None
    if not resolved_key and node_id:
        resolved_key = _resolve_album_key(
            api_key,
            {"id": node_id, "type": "Folder", "albumKey": album_key},
        )
        if not resolved_key:
            # The node itself may already be an album.
            children, _exp = _node_children(api_key, node_id, count=5)
            if not children:
                payload = _api_get(f"/api/v2/node/{node_id}", api_key)
                node = ((payload.get("Response") or {}).get("Node") or {})
                uris = node.get("Uris") if isinstance(node, dict) else {}
                album = (uris or {}).get("Album") if isinstance(uris, dict) else None
                uri = album if isinstance(album, str) else str((album or {}).get("Uri") or "")
                resolved_key = album_key_from_uri(uri)

    if not resolved_key:
        return {"photos": [], "count": 0, "start": start, "nextStart": None, "total": 0, "albumKey": None}

    payload = _api_get(
        f"/api/v2/album/{resolved_key}!images",
        api_key,
        {
            "count": str(count),
            "start": str(start),
            "_expand": "ImageSizeDetails",
        },
    )
    response = payload.get("Response") if isinstance(payload.get("Response"), dict) else {}
    expansions = payload.get("Expansions") if isinstance(payload.get("Expansions"), dict) else {}
    pages = response.get("Pages") if isinstance(response.get("Pages"), dict) else {}
    photos: list[dict[str, Any]] = []
    for index, image in enumerate(_as_list(response.get("AlbumImage")), start=start):
        row = photo_from_album_image(
            image,
            expansions=expansions,
            match_name=match_name,
            kind=kind,
            index=index,
        )
        if row:
            photos.append(row)
    next_start = None
    if pages.get("NextPage") and photos:
        next_start = start + len(photos)
    result = {
        "albumKey": resolved_key,
        "photos": photos,
        "count": len(photos),
        "start": start,
        "nextStart": next_start,
        "total": int(pages.get("Total") or len(photos) or 0),
        "galleryUrl": photos[0]["galleryUrl"] if photos and photos[0].get("galleryUrl") else "",
    }
    if photos:
        _cache_set(cache_key, result)
    return result
