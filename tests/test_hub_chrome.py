"""Hub chrome (masthead) is injected into tool pages, never into decks."""

from __future__ import annotations

from app import hub_chrome
from app.apps_manifest import APPS


def test_chrome_covers_every_rail_tool_except_decks():
    ids = {app["id"] for app in hub_chrome.chrome_apps()}
    rail = {app["id"] for app in APPS if app.get("sidebar") is not False}
    assert rail - ids == set(hub_chrome.CHROME_EXCLUDED_APP_IDS) & rail
    assert not ids & hub_chrome.CHROME_EXCLUDED_APP_IDS


def test_view_query_picks_the_matching_dashboard():
    picked = hub_chrome.app_for_request("/match-dashboards", {"view": "crosses"})
    assert picked["id"] == "crosses-dashboard"


def test_inject_adds_assets_and_markup_once():
    app = next(a for a in APPS if a["id"] == "games-to-watch")
    page = "<html><head><title>x</title></head><body class='a'><h1>Games to Watch</h1></body></html>"
    markup = hub_chrome.chrome_markup(app, display_name="Sam Smith", brand={})
    out = hub_chrome.inject_chrome(page, markup, app)
    assert out.count("/static/hub-chrome.css") == 1
    assert "<body class='a'>\n<div class=\"pvc\"" in out
    assert '<h1 class="pvc-masthead__name">Games to Watch</h1>' in out
    assert "pvc-rail" not in out
    assert ">SS<" in out
    assert hub_chrome.inject_chrome(out, markup, app) == out

