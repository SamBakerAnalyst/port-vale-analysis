"""Real-browser (Playwright) slide capture for WhatsApp / coaching PDFs.

Do not use html2canvas for shareable coaching decks — it collapses flex/grid and
strips spaces from notes. This module screenshots settled HTML in Chrome/Chromium.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


class WysiwygCaptureError(RuntimeError):
    """Raised when Playwright / browser capture is unavailable or fails."""


def playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def _launch_browser(playwright: Any) -> Any:
    """Prefer system Chrome (Mac); fall back to Playwright Chromium."""
    errors: list[str] = []
    launch_kwargs = [
        {"channel": "chrome", "headless": True},
        {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]},
        {"headless": True},
    ]
    for kwargs in launch_kwargs:
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001 — try next launcher
            errors.append(f"{kwargs}: {exc}")
    raise WysiwygCaptureError(
        "Could not launch Chrome/Chromium for WYSIWYG export. "
        "On this machine run: playwright install chromium. "
        + " | ".join(errors)
    )


def capture_html_documents(
    documents: list[str],
    *,
    width: int = 1920,
    height: int = 1080,
    scale: float = 2.0,
    selector: str = ".pm-slide",
    settle_ms: int = 400,
) -> list[bytes]:
    """Screenshot each full HTML document; return PNG bytes (device pixels)."""
    if not documents:
        raise WysiwygCaptureError("No HTML pages to capture.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        raise WysiwygCaptureError(
            "Playwright is not installed. pip install playwright && playwright install chromium"
        ) from exc

    pngs: list[bytes] = []
    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page = context.new_page()
            for index, html in enumerate(documents, start=1):
                if not str(html or "").strip():
                    raise WysiwygCaptureError(f"Page {index} has empty HTML.")
                page.set_content(str(html), wait_until="networkidle", timeout=120_000)
                try:
                    page.evaluate("() => document.fonts && document.fonts.ready")
                except Exception:
                    pass
                page.wait_for_timeout(max(settle_ms, 450))
                loc = page.locator(".pv-export-frame, .pm-export-frame").first
                if loc.count() == 0:
                    loc = page.locator(selector).first
                if loc.count() == 0:
                    # Full viewport fallback if slide class missing
                    pngs.append(page.screenshot(type="png", full_page=False))
                else:
                    loc.wait_for(state="visible", timeout=30_000)
                    pngs.append(loc.screenshot(type="png"))
            context.close()
        finally:
            browser.close()
    return pngs


def pngs_to_pdf(png_bytes_list: list[bytes]) -> bytes:
    """Stitch PNG pages into a normal 16:9 landscape PDF (WhatsApp-friendly).

    Do not let img2pdf use 1px=1pt — that makes ~60\" pages WhatsApp scales badly.
    """
    if not png_bytes_list:
        raise WysiwygCaptureError("No PNG pages to stitch.")
    try:
        import img2pdf

        # Keynote / WhatsApp landscape: 13.333\" × 7.5\" (16:9)
        page_w = img2pdf.in_to_pt(13.333333)
        page_h = img2pdf.in_to_pt(7.5)
        layout_fun = img2pdf.get_layout_fun((page_w, page_h))

        with TemporaryDirectory(prefix="wysiwyg-pdf-") as tmp:
            paths: list[str] = []
            root = Path(tmp)
            for index, data in enumerate(png_bytes_list, start=1):
                path = root / f"slide-{index:02d}.png"
                path.write_bytes(data)
                paths.append(str(path))
            return img2pdf.convert(paths, layout_fun=layout_fun)
    except Exception:
        # Fallback: fpdf full-bleed pages
        from app.pdf_report import SlideDeckPDF
        import base64

        pdf = SlideDeckPDF()
        for data in png_bytes_list:
            b64 = base64.b64encode(data).decode("ascii")
            pdf.add_full_bleed_image(f"data:image/png;base64,{b64}")
        output = pdf.output()
        if isinstance(output, bytearray):
            return bytes(output)
        if isinstance(output, bytes):
            return output
        return output.encode("latin-1")
