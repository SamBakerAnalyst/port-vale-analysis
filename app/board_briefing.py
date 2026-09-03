"""Confidential board briefing — hub capability pack. Admin only, hidden from the staff rail."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR


def register_board_briefing_routes(app: FastAPI) -> None:
    @app.get("/board-briefing", response_class=HTMLResponse)
    @app.get("/board-briefing/", response_class=HTMLResponse)
    def board_briefing_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "board-briefing.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="Board briefing page missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
