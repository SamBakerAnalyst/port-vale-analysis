"""Reports Library — saved scout reports, filterable by score."""

from __future__ import annotations

import app.main  # noqa: F401 - initialise the app so the router imports resolve

from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS, required_sidebar_titles
from app.paths import STANDALONE_DIR
from app import player_reports as reports


def test_reports_library_is_a_recruitment_rail_tool():
    titles = required_sidebar_titles()
    assert "Reports Library" in titles
    row = next(app for app in APPS if app["id"] == "reports-library")
    assert row["title"] == "Reports Library"
    assert row["href"] == "/reports-library"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is not False
    assert "scouts" in tuple(row["roles"])
    assert row["router"] == "reports_library"
    assert "/reports-library" in tuple(row["api_prefixes"])
    assert "/api/reports-library" in tuple(row["api_prefixes"])
    assert row["id"] in LIVE_ESSENTIAL_IDS


def test_library_page_filters_by_rating():
    html = (STANDALONE_DIR / "reports-library.html").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "reports-library.js").read_text(encoding="utf-8")
    assert "Reports Library" in html
    assert "/api/reports-library" in js
    assert 'data-rating="8"' in html
    assert 'desk=sheet' in js or "desk=sheet" in js or "player-reports" in js


def test_library_lists_saved_reports_with_general_score(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    reports.save_general_report(
        player_id=11,
        fixture_id="vale-barnet-1",
        name="Joe Smith",
        club="Barnet",
        fixture_label="Port Vale vs Barnet",
        position_in_game="CENTRAL_MIDFIELD",
        match_rating=8,
        pvfc_level="A",
        next_action="high_priority",
        staff="Dan",
    )
    reports.save_detailed_report(
        player_id=22,
        fixture_id="vale-barnet-1",
        name="Sam Jones",
        club="Barnet",
        fixture_label="Port Vale vs Barnet",
        position_in_game="CENTER_FORWARD",
        match_rating=6,
        pvfc_level="C",
        next_action="low_priority",
        staff="Josh",
    )
    payload = reports.list_library_reports()
    names = [row["name"] for row in payload["reports"]]
    assert "Joe Smith" in names
    assert "Sam Jones" in names
    joe = next(row for row in payload["reports"] if row["name"] == "Joe Smith")
    assert joe["match_rating"] == 8
    assert joe["pvfc_level"] == "A"
    assert joe["source"] == "general"
    assert joe["href"].endswith("desk=sheet")
    assert payload["reports"][0]["match_rating"] == 8
