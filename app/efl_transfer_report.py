"""EFL Transfer Report — summer 2026 per-club signed / released."""

from __future__ import annotations

import json
from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.paths import DATA_ROOT, HUB_ROOT, STANDALONE_DIR, STATIC_DIR

REPORT_NAME = "efl-transfer-report-2026.json"
REPORT_CANDIDATES = (
    HUB_ROOT / "data" / REPORT_NAME,
    DATA_ROOT / REPORT_NAME,
)
VALE_BADGE = "/standalone/port-vale-badge.png?v=2"
BADGE_DIR = STATIC_DIR / "transfer-badges"


def load_report() -> dict:
    for path in REPORT_CANDIDATES:
        if path.is_file():
            return enrich_report(json.loads(path.read_text(encoding="utf-8")))
    raise FileNotFoundError("EFL transfer report data missing.")


def badge_url(club_id: str) -> str:
    if club_id == "port-vale":
        return VALE_BADGE
    if (BADGE_DIR / f"{club_id}.png").is_file():
        return f"/static/transfer-badges/{club_id}.png"
    return ""


def enrich_report(report: dict) -> dict:
    payload = deepcopy(report)
    for league in payload.get("leagues") or []:
        for team in league.get("teams") or []:
            team["badge_url"] = badge_url(str(team.get("id") or ""))
    return payload


def register_efl_transfer_report_routes(app: FastAPI) -> None:
    @app.get("/efl-transfer-report", response_class=HTMLResponse)
    @app.get("/efl-transfer-report/", response_class=HTMLResponse)
    def efl_transfer_report_page() -> HTMLResponse:
        html_path = STANDALONE_DIR / "efl-transfer-report.html"
        if not html_path.is_file():
            raise HTTPException(status_code=404, detail="EFL transfer report missing.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/efl-transfer-report")
    def efl_transfer_report_data() -> JSONResponse:
        try:
            return JSONResponse(load_report())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
