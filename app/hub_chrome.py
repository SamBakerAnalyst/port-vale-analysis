"""Shared hub chrome (club masthead) for every staff tool page.

The hub home sets the look: crest masthead with a Rift-style
condensed italic headline, gold on slate. Tool pages are separate HTML files,
so the server injects the same chrome into their HTML responses instead of
each page carrying its own copy.

Slide decks and print layouts are left alone: their Present mode and PDF
capture size themselves to the full viewport.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from starlette.responses import Response

from app.apps_manifest import APP_GROUPS, APPS

BASE_DIR = Path(__file__).resolve().parent.parent
CHROME_CSS = BASE_DIR / "static" / "hub-chrome.css"
CHROME_JS = BASE_DIR / "static" / "hub-chrome.js"
MARKER = "data-pv-hub-chrome"

# Full-viewport decks, print sheets and the match-day clock.
CHROME_EXCLUDED_APP_IDS = frozenset(
    {
        "pre-match",
        "opposition-reports",
        "set-piece-pre-match",
        "post-match",
        "pa-meeting-slides",
        "meeting-front-pages",
        "player-cards",
        "match-day-countdown",
    }
)


def _href_parts(href: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(href)
    query = {k: v[0] for k, v in parse_qs(parts.query).items() if v}
    return parts.path.rstrip("/") or "/", query


def chrome_apps() -> list[dict[str, Any]]:
    return [
        app
        for app in APPS
        if app["id"] not in CHROME_EXCLUDED_APP_IDS
        and app.get("sidebar") is not False
        and str(app.get("href") or "").startswith("/")
    ]


def chrome_paths() -> frozenset[str]:
    return frozenset(_href_parts(app["href"])[0] for app in chrome_apps())


def app_for_request(path: str, query: dict[str, str]) -> dict[str, Any] | None:
    """Most specific manifest app for this page (``?view=`` picks among siblings)."""
    clean = path.rstrip("/") or "/"
    best: dict[str, Any] | None = None
    best_score = -1
    for app in chrome_apps():
        app_path, app_query = _href_parts(app["href"])
        if app_path != clean:
            continue
        if any(query.get(k) != v for k, v in app_query.items()):
            score = 0
        else:
            score = 1 + len(app_query)
        if score > best_score:
            best, best_score = app, score
    return best


def _asset_version(path: Path) -> str:
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return "1"


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def chrome_markup(
    app: dict[str, Any],
    *,
    display_name: str,
    brand: dict[str, Any],
) -> str:
    group = next((g for g in APP_GROUPS if g["id"] == app["group"]), {"title": ""})
    badge = brand.get("badge") or "/standalone/port-vale-badge.png?v=2"
    org = brand.get("org_short") or brand.get("org") or "Port Vale FC"
    name = display_name.strip() or "Port Vale"
    initials = "".join(part[0] for part in name.replace("_", " ").split()[:2]).upper() or "PV"
    return f"""
<div class="pvc" {MARKER}>
  <header class="pvc-masthead" id="pvcMasthead">
    <div class="pvc-masthead__art" aria-hidden="true">
      <span class="pvc-masthead__slash"></span>
      <img class="pvc-masthead__crest" src="{_esc(badge)}" alt="" />
    </div>
    <div class="pvc-masthead__bar">
      <a class="pvc-masthead__home" href="/">
        <img class="pvc-masthead__badge" src="{_esc(badge)}" alt="" />Home
      </a>
      <p class="pvc-masthead__crumbs">
        <a href="/">{_esc(org)}</a><span aria-hidden="true">/</span><span>{_esc(group["title"])}</span>
      </p>
      <span class="pvc-masthead__user" title="Signed in">
        <span class="pvc-masthead__avatar">{_esc(initials)}</span>
        <span class="pvc-masthead__user-name">{_esc(name)}</span>
      </span>
    </div>
    <div class="pvc-masthead__body">
      <div class="pvc-masthead__hello">
        <p class="pvc-masthead__salute">{_esc(group["title"])}</p>
        <h1 class="pvc-masthead__name">{_esc(app["title"])}</h1>
        <p class="pvc-masthead__date">
          <span id="pvcDate">Today</span>
          <span class="pvc-masthead__dot" aria-hidden="true"></span>
          <span class="pvc-masthead__time" id="pvcTime">--:--</span>
          <span class="pvc-masthead__league" id="pvcLeague" hidden></span>
        </p>
      </div>
      <a class="pvc-next" id="pvcNext" href="/" hidden>
        <span class="pvc-next__label">Next up</span>
        <span class="pvc-next__main">
          <span class="pvc-next__crest" id="pvcNextCrest"></span>
          <span class="pvc-next__text">
            <span class="pvc-next__opp"><span class="pvc-next__ha" id="pvcNextHa">H</span><span id="pvcNextOpp">TBC</span></span>
            <span class="pvc-next__meta" id="pvcNextMeta"></span>
          </span>
          <span class="pvc-next__count"><strong id="pvcNextCount">—</strong><span id="pvcNextUnit">days</span></span>
        </span>
      </a>
    </div>
    <span class="pvc-masthead__kit" aria-hidden="true"></span>
  </header>
</div>
"""


def inject_chrome(page: str, markup: str, app: dict[str, Any]) -> str:
    if MARKER in page or "</head>" not in page:
        return page
    meta = json.dumps({"id": app["id"], "title": app["title"], "group": app["group"]})
    head = (
        f'<link rel="stylesheet" href="/static/hub-chrome.css?v={_asset_version(CHROME_CSS)}" />'
        f"<script>window.PV_HUB_CHROME={meta};</script>"
        f'<script defer src="/static/hub-chrome.js?v={_asset_version(CHROME_JS)}"></script>'
    )
    page = page.replace("</head>", f"{head}</head>", 1)
    lower = page.lower()
    body_at = lower.find("<body")
    if body_at < 0:
        return page
    body_end = page.find(">", body_at)
    if body_end < 0:
        return page
    return page[: body_end + 1] + markup + page[body_end + 1 :]


def register_hub_chrome(app: FastAPI) -> None:
    """Must be registered before SessionMiddleware so ``request.session`` exists."""
    paths = chrome_paths()

    @app.middleware("http")
    async def hub_chrome_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or response.status_code != 200:
            return response
        path = request.url.path.rstrip("/") or "/"
        if path not in paths:
            return response
        if not response.headers.get("content-type", "").startswith("text/html"):
            return response
        tool = app_for_request(path, dict(request.query_params))
        if tool is None:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            page = body.decode("utf-8")
        except UnicodeDecodeError:
            return _rebuild(response, body)

        from app.auth import auth_enabled, current_user_payload
        from app.brand import current_brand

        user = current_user_payload(request) if auth_enabled() else {}
        markup = chrome_markup(
            tool,
            display_name=str(user.get("display_name") or ""),
            brand=current_brand().as_dict(),
        )
        return _rebuild(response, inject_chrome(page, markup, tool).encode("utf-8"))


def _rebuild(response: Response, body: bytes) -> Response:
    out = Response(content=body, status_code=response.status_code)
    out.raw_headers = [
        (k, v) for k, v in response.raw_headers if k.lower() != b"content-length"
    ] + [(b"content-length", str(len(body)).encode())]
    return out
