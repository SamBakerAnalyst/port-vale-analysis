from __future__ import annotations

from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.pdf_report import decode_image_data


class ScoutingA4PDF(FPDF):
    """A4 landscape — one full-page image per app-rendered export page."""

    def __init__(self) -> None:
        super().__init__(orientation="L", unit="mm", format="A4")
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)

    def add_page_image(self, image_data: str) -> None:
        self.add_page()
        self.image(
            BytesIO(decode_image_data(image_data)),
            x=0,
            y=0,
            w=self.w,
            h=self.h,
        )


def build_scouting_export_pdf(body: Any) -> bytes:
    pages = getattr(body, "pages", None) or []
    if not pages:
        raise ValueError("No export pages to render.")

    pdf = ScoutingA4PDF()
    for page in pages:
        image_data = getattr(page, "image_data", None) or getattr(page, "imageData", "")
        if not image_data:
            continue
        pdf.add_page_image(image_data)

    if pdf.page_no() == 0:
        raise ValueError("No export pages to render.")

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
