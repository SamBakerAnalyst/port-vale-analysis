"""Hub origin story Present deck — how Player Comparison on leave became the platform."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR


def register_hub_origin_routes(app: FastAPI) -> None:
    @app.get("/hub-origin", response_class=HTMLResponse)
    @app.get("/hub-origin/", response_class=HTMLResponse)
    def hub_origin_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "hub-origin.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="Hub origin deck missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
