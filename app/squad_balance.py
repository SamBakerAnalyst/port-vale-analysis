from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.scouting import SCOUTING_DIR
from app.squad_planner import (
    SquadBalanceExportRequest,
    SquadPlannerPlayerRequest,
    build_squad_planner_player,
    squad_planner_meta,
)


def register_squad_balance_routes(app: FastAPI) -> None:
    @app.get("/squad-balance", response_class=HTMLResponse)
    def squad_balance_page() -> HTMLResponse:
        html_path = SCOUTING_DIR / "squad-balance.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Squad balance UI not found.")
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/squad-balance/meta")
    def squad_balance_meta_route() -> dict[str, Any]:
        return squad_planner_meta()

    @app.post("/api/squad-balance/player")
    def squad_balance_player_route(body: SquadPlannerPlayerRequest) -> dict[str, Any]:
        return build_squad_planner_player(body)

    @app.post("/api/squad-balance/export-pdf")
    def squad_balance_export_pdf(body: SquadBalanceExportRequest) -> Response:
        from app.squad_balance_pdf import build_squad_balance_pdf

        payload = body.model_dump()
        try:
            pdf_bytes = build_squad_balance_pdf(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="squad-balance.pdf"'
            },
        )
