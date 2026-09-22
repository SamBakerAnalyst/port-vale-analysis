"""Reports Library — browse every saved Player Report by score."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR
from app.player_reports import list_library_reports


def register_reports_library_routes(app: FastAPI) -> None:
    @app.get("/reports-library", response_class=HTMLResponse)
    def reports_library_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "reports-library.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Reports Library UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/reports-library")
    def reports_library_list() -> dict[str, Any]:
        return list_library_reports()
