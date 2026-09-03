"""Personal presentations index — admin only, off the daily rail."""

from __future__ import annotations

import html
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.apps_manifest import presentation_decks
from app.paths import STANDALONE_DIR

_CARDS_RE = re.compile(r"<!-- PRESENTATION_CARDS -->")


def _deck_card(app: dict) -> str:
    href = html.escape(str(app.get("href") or "/"), quote=True)
    icon = html.escape(str(app.get("icon") or "◆"))
    title = html.escape(str(app.get("title") or ""))
    desc = html.escape(str(app.get("description") or ""))
    return (
        f'<a class="deck" href="{href}">'
        f'<span class="deck__icon">{icon}</span>'
        f'<span class="deck__copy">'
        f'<span class="deck__title">{title}</span>'
        f'<span class="deck__desc">{desc}</span>'
        f"</span>"
        f'<span class="deck__go">Open</span>'
        f"</a>"
    )


def presentations_html() -> str:
    html_path = STANDALONE_DIR / "presentations.html"
    if not html_path.is_file():
        raise FileNotFoundError("Presentations page missing.")
    page = html_path.read_text(encoding="utf-8")
    cards = "\n          ".join(_deck_card(app) for app in presentation_decks())
    if not _CARDS_RE.search(page):
        return page
    return _CARDS_RE.sub(cards, page, count=1)


def register_presentations_routes(app: FastAPI) -> None:
    @app.get("/presentations", response_class=HTMLResponse)
    @app.get("/presentations/", response_class=HTMLResponse)
    def presentations_page() -> HTMLResponse:
        try:
            return HTMLResponse(presentations_html())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
