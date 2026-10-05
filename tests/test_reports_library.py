"""Reports Library — every general and detailed report filed from Match Scouting."""

from __future__ import annotations

import json

import app.main  # noqa: F401 - initialise the app so the router imports resolve

from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS, required_sidebar_titles
from app.paths import STANDALONE_DIR
from app import player_reports as reports
from app import reports_library as library


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    monkeypatch.setattr(library._PlayerFallback, "lookup", lambda self, pid: {})


def test_reports_library_is_a_recruitment_rail_tool():
    assert "Reports Library" in required_sidebar_titles()
    row = next(app for app in APPS if app["id"] == "reports-library")
    assert row["href"] == "/reports-library"
    assert row["group"] == "recruitment"
    assert row["router"] == "reports_library"
    assert "scouts" in tuple(row["roles"])
    assert "/api/reports-library" in tuple(row["api_prefixes"])
    assert row["id"] in LIVE_ESSENTIAL_IDS
    html = (STANDALONE_DIR / "reports-library.html").read_text(encoding="utf-8")
    assert "Reports Library" in html
    assert "/static/reports-library.js" in html


def test_saved_reports_keep_player_and_fixture_details(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    reports.save_general_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        notes="Bright first half.",
        match_rating=7.5,
        pvfc_level="B",
        staff="Scout A",
        meta={"name": "Test Player", "club": "Barnet", "league": "National League", "age": 22,
              "fixture_label": "Barnet vs Accrington Stanley"},
    )
    reports.save_general_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        notes="Edited.",
        staff="Scout B",
        meta={},
    )
    stored = json.loads((tmp_path / "player-reports.json").read_text())["general_reports"]["922:barnet-accrington-1"]
    assert stored["name"] == "Test Player"
    assert stored["club"] == "Barnet"
    assert stored["age"] == 22
    assert stored["created_by"] == "Scout A"
    assert stored["updated_by"] == "Scout B"


def test_library_lists_general_and_detailed_with_filters_data(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    meta = {"name": "Test Player", "club": "Barnet", "league": "National League",
            "fixture_label": "Barnet vs Accrington Stanley"}
    reports.save_general_report(
        player_id=922, fixture_id="f1", notes="Quick look.", position_in_game="CENTER_FORWARD",
        match_rating=6.5, staff="Scout A", meta=meta,
    )
    reports.save_detailed_report(
        player_id=922, fixture_id="f1", write_up="Full write-up.", position_in_game="CENTER_FORWARD",
        pvfc_level="A", next_action="sign", staff="Scout A", meta=meta,
    )
    payload = library.list_reports()
    assert payload["counts"] == {"total": 2, "general": 1, "detailed": 1, "players": 1, "manual": 0}
    detailed = next(row for row in payload["reports"] if row["kind"] == "detailed")
    assert detailed["name"] == "Test Player"
    assert detailed["home_away"] == "Home"
    assert detailed["position_short"] == "ST"
    assert detailed["pvfc_level_label"] == "Starter"
    assert detailed["next_action_label"] == "Sign"
    assert detailed["has_general"] and detailed["has_detailed"]
    assert detailed["excerpt"] == "Full write-up."


def test_older_reports_without_details_still_list(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "player-reports.json").write_text(json.dumps({
        "version": 1,
        "match_conditions": {"f9": {"fixture_id": "f9", "fixture_label": "Crewe vs Walsall", "weather": "dry"}},
        "general_reports": {"55:f9": {"notes": "Old note.", "updated_by": "Scout C", "updated_at": "2026-08-01T10:00:00+00:00"}},
        "detailed_reports": {"55:f9": {"write_up": ""}},
        "cms": {},
    }))
    payload = library.list_reports()
    assert payload["counts"]["total"] == 1
    row = payload["reports"][0]
    assert row["name"] == "Player 55"
    assert row["fixture_label"] == "Crewe vs Walsall"
    assert row["scout"] == "Scout C"


def test_report_detail_returns_full_report_and_companion(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    reports.save_match_conditions(fixture_id="f1", fixture_label="Barnet vs Accrington Stanley", weather="dry")
    reports.save_general_report(player_id=922, fixture_id="f1", notes="Quick look.", meta={"name": "Test Player"})
    detail = library.report_detail("general", 922, "f1")
    assert detail["report"]["notes"] == "Quick look."
    assert detail["meta"]["name"] == "Test Player"
    assert detail["match_conditions"]["weather_label"] == "Dry"
    assert detail["companion"] == {"kind": "detailed", "available": False}
