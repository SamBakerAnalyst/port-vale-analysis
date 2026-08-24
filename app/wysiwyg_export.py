"""Shared Playwright WYSIWYG PDF export for coaching slide decks."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field


class WysiwygExportRequest(BaseModel):
    html_pages: list[str] = Field(default_factory=list)
    html_filenames: list[str] = Field(default_factory=list)
    width: int = 1920
    height: int = 1080
    scale: float = 2.0
    filename: str | None = None
    document_title: str | None = None
    opponent_name: str | None = None


def build_wysiwyg_pdf(body: WysiwygExportRequest | Any) -> bytes:
    pages = list(getattr(body, "html_pages", None) or [])
    if not pages:
        raise ValueError("No HTML pages provided for WYSIWYG export.")
    from app.wysiwyg_capture import WysiwygCaptureError, capture_html_documents, pngs_to_pdf

    try:
        pngs = capture_html_documents(
            pages,
            width=int(getattr(body, "width", None) or 1920),
            height=int(getattr(body, "height", None) or 1080),
            scale=float(getattr(body, "scale", None) or 2.0),
            selector=".pv-export-frame",
        )
    except WysiwygCaptureError as exc:
        raise ValueError(str(exc)) from exc
    return pngs_to_pdf(pngs)


def register_wysiwyg_export_routes(app: FastAPI) -> None:
    @app.post("/api/wysiwyg-export-pdf")
    def wysiwyg_export_pdf(body: WysiwygExportRequest) -> Response:
        from app.main import _safe_export_filename, _save_export_to_desktop

        if not body.html_pages:
            raise HTTPException(status_code=400, detail="No HTML pages provided.")
        try:
            pdf_bytes = build_wysiwyg_pdf(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        stem = re.sub(r"[^\w\s\-]+", "", str(body.document_title or body.opponent_name or "export"))
        stem = re.sub(r"\s+", "-", stem).strip("-") or "export"
        default_name = f"port-vale-{stem.lower()}-whatsapp.pdf"
        filename = _safe_export_filename(body.filename or default_name, default_ext=".pdf")
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
        saved_path = _save_export_to_desktop(pdf_bytes, filename)
        if saved_path is not None:
            headers["X-Saved-Desktop-Path"] = str(saved_path)
        return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
