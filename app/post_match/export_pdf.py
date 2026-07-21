from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from fpdf import FPDF

# 16:9 Keynote / PowerPoint — same frame as pre-match WhatsApp PDFs (1920×1080).
SLIDE_WIDTH_MM = 338.67
SLIDE_HEIGHT_MM = 190.5

# Helvetica core font is Latin-1 only — map common Unicode punctuation used in titles.
_PDF_CHAR_MAP = str.maketrans(
    {
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u2212": "-",  # minus
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
        "\u2022": "-",
        "\u2713": "Y",
        "\u2717": "X",
        "\u26bd": "",
    }
)


def _pdf_safe_text(text: str) -> str:
    cleaned = (text or "").translate(_PDF_CHAR_MAP)
    # Drop any remaining non-latin1 so export never crashes on a single glyph.
    return cleaned.encode("latin-1", errors="replace").decode("latin-1")


def decode_image_data(data_url: str) -> bytes:
    payload = data_url.split(",", 1)[-1].strip()
    if not payload:
        raise ValueError("Export image data is missing.")
    return base64.b64decode(payload)


class SlideDeckPDF(FPDF):
    """Full-bleed 16:9 pages — slide bitmaps already include the footer."""

    def __init__(self, *, document_title: str | None = None) -> None:
        # FPDF swaps (w, h) for orientation L — pass wide×tall with orientation P.
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)
        self.set_display_mode(zoom="fullpage", layout="single")
        self.document_title = _pdf_safe_text(document_title or "Post-Match Report").strip()

    def add_slide_image_bytes(
        self,
        image_bytes: bytes,
        *,
        page_num: int,
        total_pages: int,
    ) -> None:
        del page_num, total_pages  # page label is already in the captured bitmap
        if not image_bytes:
            raise ValueError("Export page image is missing.")

        self.add_page()
        self.set_fill_color(12, 12, 12)
        self.rect(0, 0, self.w, self.h, style="F")
        self.image(
            BytesIO(image_bytes),
            x=0,
            y=0,
            w=self.w,
            h=self.h,
        )

    def add_slide_page(
        self,
        image_data: str,
        width_px: int,
        height_px: int,
        *,
        page_num: int,
        total_pages: int,
    ) -> None:
        del width_px, height_px
        self.add_slide_image_bytes(
            decode_image_data(image_data),
            page_num=page_num,
            total_pages=total_pages,
        )


def build_export_pdf_from_png_bytes(
    images: list[bytes],
    *,
    document_title: str | None = None,
) -> bytes:
    pages = [img for img in images if img]
    if not pages:
        raise ValueError("No export pages to render.")

    pdf = SlideDeckPDF(document_title=document_title)
    total_pages = len(pages)
    for index, image_bytes in enumerate(pages, start=1):
        pdf.add_slide_image_bytes(
            image_bytes,
            page_num=index,
            total_pages=total_pages,
        )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def build_export_pdf(
    pages: list[Any],
    *,
    document_title: str | None = None,
) -> bytes:
    if not pages:
        raise ValueError("No export pages to render.")

    images: list[bytes] = []
    for page in pages:
        if isinstance(page, dict):
            image_data = page.get("imageData") or page.get("image_data") or ""
        else:
            image_data = getattr(page, "image_data", None) or getattr(page, "imageData", "")
        if not image_data:
            continue
        images.append(decode_image_data(image_data))

    return build_export_pdf_from_png_bytes(images, document_title=document_title)
