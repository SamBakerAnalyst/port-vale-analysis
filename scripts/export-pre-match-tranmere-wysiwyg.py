#!/usr/bin/env python3
"""Screenshot the live Staging two-pager (true WYSIWYG) → Desktop WhatsApp PDF.

No HTML rebuild / second layout. Opens Staging, loads Tranmere, forces the
1920×1080 Keynote frame at zoom=1, screenshots each .pm-slide, stitches a
13.33\"×7.5\" PDF.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from playwright.sync_api import sync_playwright  # noqa: E402
import img2pdf  # noqa: E402

SLIDE_W = 1920
SLIDE_H = 1080
SCALE = 2.0


def main() -> int:
    user = os.getenv("ANALYSIS_USERNAME", "").strip()
    password = os.getenv("ANALYSIS_PASSWORD", "").strip()
    if not user or not password:
        print("Missing ANALYSIS_USERNAME / ANALYSIS_PASSWORD in .env", file=sys.stderr)
        return 1

    base = os.getenv("STAGING_URL", "http://178.128.161.215:8080").rstrip("/")
    out_pdf = Path("/Users/AnalysisMac1/Desktop") / "Port-Vale-Pre-Match-Tranmere-Rovers-WhatsApp.pdf"
    tmp = ROOT / ".tmp-export-review" / "wysiwyg-tranmere"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("slide-*.png"):
        old.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": SLIDE_W + 40, "height": SLIDE_H + 160},
            device_scale_factor=SCALE,
        )
        page = context.new_page()
        page.goto(f"{base}/login", wait_until="networkidle", timeout=120_000)
        page.fill('input[name="username"], #username, input[type="text"]', user)
        page.fill('input[name="password"], #password, input[type="password"]', password)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_timeout(1500)
        page.goto(f"{base}/pre-match", wait_until="networkidle", timeout=180_000)
        page.wait_for_timeout(2000)

        two = page.locator("#deckModeTwoBtn")
        if two.count():
            two.click()
            page.wait_for_timeout(800)

        tran = page.locator(".pm-match-bar__item", has_text="Tranmere")
        if tran.count() == 0:
            tran = page.get_by_text("Tranmere", exact=False)
        tran.first.click()
        page.wait_for_selector(".pm-slide", timeout=180_000)
        for _ in range(90):
            text = page.locator(".pm-slide").first.inner_text()
            upper = text.upper()
            if ("TRANMERE" in upper or "PLAYING STYLE" in upper) and page.locator(".pm-slide").count() >= 3:
                break
            page.wait_for_timeout(1000)

        # Inject coach notes from the WhatsApp (6) export so page 2 matches the real brief.
        page.evaluate(
            """() => {
              const notes = {
                hurt_us: [
                  'Coutner attacked brilliant, especially after their goal. No life chaning pace in the team.',
                  'Set plays had great delivery, Vaulks as an incredibly dangerous throw that he uses from all over the pitch',
                  'Male has great distance on his kicking and linked well hitting Ironside with Whitaker and Ince landing on second balls',
                ].join('\\n'),
                hurt_them: [
                  'Heaps of space in central midfield, Vaulks was everywhere and Conlon seemed to stay slightly higher. We can find space here to exploit.',
                  'Backline lacked pace, Smith and Faulker can be exploited in behind',
                  'Whitaker and Davies left space behind them, allowing Shrewsbury to put a lot of crosses into the box, GK is small and didn\\'t deal with many.',
                ].join('\\n'),
                player_comments: [
                  'Whitaker is a very good player and scored, he can be a real threat.',
                  'Ince worked hard, Vaulks was excellent and Ironside was a handful.',
                  'Brough was the more attacking of the two fullbacks, was high allowing whitaker to come inside and has quality.',
                ].join('\\n'),
              };
              for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('pm-two-pager-notes:')) {
                  localStorage.setItem(key, JSON.stringify(notes));
                }
              }
              // Also write a wildcard key from current report if present
              const opp = document.querySelector('[data-opponent-id]')?.dataset?.opponentId
                || document.querySelector('.pm-match-bar__item--active')?.dataset?.opponentId;
              const iter = document.querySelector('#iterationId')?.value;
              if (iter && opp) {
                localStorage.setItem(`pm-two-pager-notes:${iter}:${opp}`, JSON.stringify(notes));
              }
            }"""
        )
        # Rebuild deck so notes paint
        page.evaluate(
            """() => {
              if (typeof rebuildSlides === 'function') { rebuildSlides(); }
              if (typeof paintDeck === 'function') { paintDeck(); }
              if (typeof applyPdfViewToSlides === 'function') { applyPdfViewToSlides(); }
            }"""
        )
        page.wait_for_timeout(1200)

        # Force real Keynote frame at 1:1 — capture what coaches see, no zoom soft-blur.
        page.evaluate(
            """({ w, h }) => {
              document.body.classList.add('is-two-pager', 'is-pdf-view', 'is-exporting');
              document.body.style.setProperty('--pm-pdf-scale', '1');
              document.querySelectorAll('.pm-slide').forEach((slide) => {
                slide.classList.add('pm-slide--export-capture', 'pm-slide--active');
                slide.style.setProperty('--pm-export-w', w + 'px');
                slide.style.setProperty('--pm-export-h', h + 'px');
                slide.style.setProperty('width', w + 'px', 'important');
                slide.style.setProperty('height', h + 'px', 'important');
                slide.style.setProperty('max-width', w + 'px', 'important');
                slide.style.setProperty('min-height', h + 'px', 'important');
                slide.style.setProperty('max-height', h + 'px', 'important');
                slide.style.setProperty('transform', 'none', 'important');
                slide.style.setProperty('margin', '0 auto', 'important');
              });
              const vp = document.querySelector('.pm-deck-viewport');
              if (vp) {
                vp.style.zoom = '1';
                vp.style.width = w + 'px';
              }
            }""",
            {"w": SLIDE_W, "h": SLIDE_H},
        )
        page.wait_for_timeout(500)

        # Warm images on every slide.
        page.evaluate(
            """async () => {
              const slides = [...document.querySelectorAll('.pm-slide')];
              for (const slide of slides) {
                slide.scrollIntoView({ block: 'center' });
                await Promise.all([...slide.querySelectorAll('img')].map((img) =>
                  img.complete && img.naturalWidth ? 1 : new Promise((r) => {
                    img.onload = () => r(1); img.onerror = () => r(0);
                    setTimeout(() => r(0), 5000);
                  })
                ));
              }
              if (document.fonts && document.fonts.ready) await document.fonts.ready;
            }"""
        )
        page.wait_for_timeout(400)

        # Grow page-2 notes to fill their boxes before screenshot.
        page.evaluate(
            """() => {
              document.querySelectorAll('.pm-slide--two-pager-2 .tp-note').forEach((note) => {
                const body = note.querySelector('.tp-note__body');
                const list = note.querySelector('.tp-note__list');
                if (!body || !list) return;
                body.style.overflow = 'hidden';
                list.style.display = 'block';
                list.style.height = 'auto';
                const items = [...note.querySelectorAll('.tp-note__item')];
                let fontPx = 28;
                let margin = 0.45;
                for (let i = 0; i < 50; i++) {
                  body.style.fontSize = fontPx + 'px';
                  body.style.lineHeight = '1.36';
                  items.forEach((li) => {
                    li.style.fontSize = fontPx + 'px';
                    li.style.lineHeight = '1.36';
                    li.style.marginBottom = margin + 'rem';
                    li.style.fontWeight = '700';
                  });
                  if (list.scrollHeight >= body.clientHeight - 20) {
                    fontPx -= 0.6;
                    margin = Math.max(0.25, margin - 0.04);
                    body.style.fontSize = fontPx + 'px';
                    items.forEach((li) => {
                      li.style.fontSize = fontPx + 'px';
                      li.style.marginBottom = margin + 'rem';
                    });
                    break;
                  }
                  fontPx += 0.9;
                  margin += 0.06;
                  if (fontPx > 42) break;
                }
              });
            }"""
        )
        page.wait_for_timeout(200)

        slides = page.locator(".pm-slide")
        count = slides.count()
        if count < 1:
            print("No slides found", file=sys.stderr)
            browser.close()
            return 1

        paths: list[Path] = []
        print(f"slides={count} frame={SLIDE_W}x{SLIDE_H} scale={SCALE} mode=live-dom")
        for i in range(count):
            slide = slides.nth(i)
            slide.scroll_into_view_if_needed()
            page.wait_for_timeout(250)
            path = tmp / f"slide-{i + 1:02d}.png"
            slide.screenshot(path=str(path), type="png")
            paths.append(path)
            print(f"shot={path.name} bytes={path.stat().st_size}")
        browser.close()

    page_w = img2pdf.in_to_pt(13.333333)
    page_h = img2pdf.in_to_pt(7.5)
    layout_fun = img2pdf.get_layout_fun((page_w, page_h))
    out_pdf.write_bytes(img2pdf.convert([str(p) for p in paths], layout_fun=layout_fun))
    print(f"pdf={out_pdf} bytes={out_pdf.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
