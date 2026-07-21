from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from app.paths import STANDALONE_DIR
from app.scouting import SCOUTING_DIR
from app.post_match.config import DEFAULT_ITERATION_ID, DEFAULT_MATCH_ID, PORT_VALE_SQUAD_ID
from app.post_match.export_pdf import build_export_pdf, build_export_pdf_from_png_bytes
from app.post_match.report import build_match_report
from app.post_match.season_matches import build_season_matches
from app.post_match.squad_badges import ensure_badge_cached, warm_iteration_badges

_warm_started = False
_warm_lock = threading.Lock()


def _warm_badges_once() -> None:
    global _warm_started
    with _warm_lock:
        if _warm_started:
            return
        _warm_started = True

    def _run() -> None:
        try:
            warm_iteration_badges(DEFAULT_ITERATION_ID)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


class ExportPdfPage(BaseModel):
    imageData: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ExportPdfBody(BaseModel):
    pages: list[ExportPdfPage] = Field(min_length=1)
    documentTitle: str | None = None


def register_post_match_routes(app: FastAPI) -> None:
    @app.get("/post-match", response_class=HTMLResponse)
    @app.get("/post-match/", response_class=HTMLResponse)
    def post_match_dashboard() -> HTMLResponse:
        html_path = SCOUTING_DIR / "post-match.html"
        if not html_path.is_file():
            html_path = STANDALONE_DIR / "post-match.html"
        if not html_path.is_file():
            raise HTTPException(status_code=503, detail="Post-match page not found.")
        _warm_badges_once()
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )

    @app.get("/api/post-match/config")
    def post_match_config() -> dict[str, int]:
        return {
            "defaultMatchId": DEFAULT_MATCH_ID,
            "defaultIterationId": DEFAULT_ITERATION_ID,
            "portValeSquadId": PORT_VALE_SQUAD_ID,
        }

    @app.get("/api/post-match/badges/{squad_id}")
    def post_match_squad_badge(
        squad_id: int,
        iteration_id: int = DEFAULT_ITERATION_ID,
    ) -> FileResponse:
        path = ensure_badge_cached(squad_id, iteration_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Badge not available for this squad")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/post-match/badges/warm/{iteration_id}")
    def post_match_warm_badges(iteration_id: int) -> dict[str, Any]:
        try:
            return warm_iteration_badges(iteration_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/post-match/iterations/{iteration_id}/matches")
    def post_match_season_matches(
        iteration_id: int,
        squad_id: int = PORT_VALE_SQUAD_ID,
    ) -> dict[str, Any]:
        try:
            matches = build_season_matches(iteration_id, squad_id)
            return {
                "iterationId": iteration_id,
                "focusSquadId": squad_id,
                "matches": matches,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/post-match/match/{match_id}/report")
    def post_match_report(
        match_id: int,
        squad_id: int = PORT_VALE_SQUAD_ID,
        iteration_id: int | None = None,
    ) -> dict[str, Any]:
        try:
            return build_match_report(
                match_id,
                focus_squad_id=squad_id,
                iteration_id=iteration_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/post-match/export-pdf")
    def post_match_export_pdf(body: ExportPdfBody) -> Response:
        try:
            pdf_bytes = build_export_pdf(body.pages, document_title=body.documentTitle)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=post-match-report.pdf"},
        )

    @app.post("/api/post-match/export-pdf-pages")
    async def post_match_export_pdf_pages(
        pages: list[UploadFile] = File(...),
        document_title: str = Form("Post-Match Report"),
    ) -> Response:
        try:
            images: list[bytes] = []
            for upload in pages:
                data = await upload.read()
                if data:
                    images.append(data)
            pdf_bytes = build_export_pdf_from_png_bytes(
                images,
                document_title=document_title,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=post-match-report.pdf"},
        )
