"""Sporting Director onboarding Present deck (26/27, October 2026)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR


def register_sd_briefing_routes(app: FastAPI) -> None:
    @app.get("/sporting-director-briefing", response_class=HTMLResponse)
    @app.get("/sporting-director-briefing/", response_class=HTMLResponse)
    def sd_briefing_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "sd-briefing.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="Sporting Director briefing deck missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
