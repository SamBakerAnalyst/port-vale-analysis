"""Recapture pages that were still loading on the first pass."""

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
OUT = ROOT / "static" / "board-briefing"

SHOTS = (
    ("pre-match.png", "/pre-match", 42000),
    ("set-piece.png", "/set-piece-pre-match", 42000),
    ("post-match.png", "/post-match", 25000),
    ("fixture-planner.png", "/fixture-planner", 25000),
    ("played-fixtures.png", "/played-fixtures", 20000),
    ("scout-summary.png", "/scout-summary", 20000),
    ("scoutable-teams.png", "/scoutable-teams", 20000),
    ("strategy-tracker.png", "/strategy-tracker", 25000),
    ("blocks-analysis.png", "/blocks-analysis", 20000),
)


def hide_chrome(page) -> None:
    page.evaluate(
        """() => {
          const fab = document.getElementById('hubFeedbackFab');
          if (fab) fab.style.display = 'none';
          const modal = document.getElementById('hubFeedbackModal');
          if (modal) modal.style.display = 'none';
        }"""
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=30000)
        page.fill("#username", USER)
        page.fill("#password", PASSWORD)
        page.click("#submitBtn")
        page.wait_for_url(lambda url: "/login" not in url, timeout=20000)

        for name, path, wait_ms in SHOTS:
            dest = OUT / name
            page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(wait_ms)
            hide_chrome(page)
            page.screenshot(path=str(dest), type="png")
            print(f"wrote {dest.name} ({dest.stat().st_size // 1024} kb)")

        browser.close()


if __name__ == "__main__":
    main()
