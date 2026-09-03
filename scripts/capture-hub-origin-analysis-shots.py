"""Capture Performance Analysis screenshots for Hub Origin Story."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BASE = os.environ.get("BOARD_SHOTS_BASE", "http://178.128.161.215:8080")
USER = os.environ.get("TEAM_USERNAME", "")
PASSWORD = os.environ.get("TEAM_PASSWORD", "")
OUT = ROOT / "static" / "hub-origin"
OUT.mkdir(parents=True, exist_ok=True)


def hide_chrome(page) -> None:
    page.evaluate(
        """() => {
          for (const id of ['hubFeedbackFab', 'hubFeedbackModal']) {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
          }
        }"""
    )


def login(page) -> None:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill("#username", USER)
    page.fill("#password", PASSWORD)
    page.click("#submitBtn")
    page.wait_for_url(lambda url: "/login" not in url, timeout=20000)


def shot(page, name: str) -> None:
    hide_chrome(page)
    dest = OUT / name
    page.screenshot(path=str(dest), type="png")
    print(f"wrote {dest.name} ({dest.stat().st_size // 1024} kb)")


def wait_gone(page, text: str, timeout: int = 90000) -> None:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="hidden", timeout=timeout)
    except Exception:
        pass


def click_filmstrip(page, label: str) -> bool:
    btn = page.locator(".filmstrip__item", has_text=label).first
    if btn.count() == 0:
        print(f"  missing filmstrip: {label}")
        return False
    btn.click()
    page.wait_for_timeout(1200)
    return True


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        login(page)

        # Blocks Analysis — wait for posters
        page.goto(f"{BASE}/blocks-analysis", wait_until="domcontentloaded", timeout=45000)
        try:
            page.locator(".ba-poster").first.wait_for(state="visible", timeout=90000)
            page.wait_for_timeout(2500)
        except Exception:
            page.wait_for_timeout(45000)
        shot(page, "blocks-analysis.png")

        # Post-match — wait for Impect pull, then grab key slides
        page.goto(f"{BASE}/post-match", wait_until="domcontentloaded", timeout=45000)
        wait_gone(page, "Pulling live Impect data")
        page.wait_for_timeout(4000)
        # Prefer a league game with full slides if available
        try:
            page.locator(".match-chip, .match-strip__item, [data-match-id]").nth(1).click(timeout=5000)
            wait_gone(page, "Pulling live Impect data")
            page.wait_for_timeout(5000)
        except Exception:
            pass

        shot(page, "post-match.png")

        for label, name in (
            ("Shots", "post-match-shots.png"),
            ("Crosses", "post-match-crosses.png"),
            ("Duels", "post-match-duels.png"),
            ("Press", "post-match-press.png"),
            ("Pressure", "post-match-press.png"),
        ):
            if click_filmstrip(page, label):
                page.wait_for_timeout(800)
                shot(page, name)

        # Pre-match as supporting analysis shot
        page.goto(f"{BASE}/pre-match", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(35000)
        wait_gone(page, "Loading", timeout=20000)
        shot(page, "pre-match.png")

        browser.close()


if __name__ == "__main__":
    main()
