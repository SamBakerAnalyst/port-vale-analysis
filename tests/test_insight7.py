"""Insight7 — monthly Emerging Talent Bulletin uploads, consolidated per player."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.main  # noqa: F401 - initialise the app so the router imports resolve

from app import insight7
from app.apps_manifest import APPS
from app.paths import STANDALONE_DIR

SAMPLE_PDF = Path.home() / "Downloads" / "ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.10.03.pdf"


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(insight7, "INSIGHT7_DIR", tmp_path)
    monkeypatch.setattr(insight7, "INDEX_PATH", tmp_path / "reports.json")
    monkeypatch.setattr(insight7, "PDF_DIR", tmp_path / "pdfs")


def _fake_parse(players, league_line="PL2 - EFL Clubs"):
    def parse(_bytes):
        return {
            "league_line": league_line,
            "season": "2026-27",
            "footer_date": "",
            "sections": ["Top Goalscorers"],
            "players": [dict(p) for p in players],
        }

    return parse


def test_insight7_is_a_recruitment_rail_tool():
    row = next(app for app in APPS if app["id"] == "insight7")
    assert row["title"] == "Insight7"
    assert row["group"] == "recruitment"
    assert row["router"] == "insight7"
    assert "/api/insight7" in tuple(row["api_prefixes"])
    html = (STANDALONE_DIR / "insight7.html").read_text(encoding="utf-8")
    assert "/static/insight7.js" in html


def test_league_and_month_come_from_filename_and_pdf():
    name = "ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.10.03.pdf"
    assert insight7._league_label(name, "PL2 - EFL Clubs") == "ENG PL2 - EFL Clubs"
    assert insight7._league_label("bulletin.pdf", "PL2 - EFL Clubs") == "PL2 - EFL Clubs"
    assert insight7._report_date(name, "2026-10-02") == "2026-10-03"
    assert insight7._report_date("bulletin.pdf", "2026-10-02") == "2026-10-02"


def test_international_with_debut_date_is_split():
    mapping = {1: "name", 2: "age", 3: "position_code", 4: "club", 5: "international", 6: "debut"}
    row = ["", "Romeo Akachukwu", "20", "08-CM", "Southampton U21", "Republic of Ireland U21 14/11/25", ""]
    record = insight7._row_record(row, mapping)
    assert record["international"] == "Republic of Ireland U21"
    assert record["debut"] == "2025-11-14"
    assert record["position"] == "CM"


@pytest.mark.skipif(not SAMPLE_PDF.is_file(), reason="sample Insight7 PDF not on this machine")
def test_parses_real_bulletin():
    parsed = insight7._parse_pdf(SAMPLE_PDF.read_bytes())
    assert parsed["league_line"] == "PL2 - EFL Clubs"
    assert parsed["season"] == "2026-27"
    assert "Top Goalscorers" in parsed["sections"]
    assert len(parsed["players"]) > 80
    ntege = next(p for p in parsed["players"] if p["name"] == "Torin Ntege")
    assert ntege["club"] == "Reading U21"
    assert ntege["goals"] == 3 and ntege["league_mins"] == 355 and ntege["league_gt"] == 99
    assert set(ntege["sections"]) >= {"Achieving 95% Game Time", "Top Goalscorers"}
    wolves = next(p for p in parsed["players"] if p["name"] == "Alfie White")
    assert wolves["club"] == "Wolverhampton Wanderers U21"


def test_monthly_uploads_consolidate_with_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    sept = [
        {"name": "Cruz Ibeh", "age": 17, "club": "Middlesbrough U21", "league_mins": 180, "goals": 2, "assists": 0},
        {"name": "Gone Player", "age": 19, "club": "Stoke City U21", "league_mins": 90, "goals": 1, "assists": 0},
    ]
    octo = [
        {"name": "Cruz Ibeh", "age": 17, "club": "Middlesbrough U21", "league_mins": 333, "goals": 4, "assists": 1},
        {"name": "New Kid", "age": 16, "club": "Burnley U21", "league_mins": 60, "goals": 1, "assists": 0},
    ]
    monkeypatch.setattr(insight7, "_parse_pdf", _fake_parse(sept))
    insight7.save_upload("ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.09.02.pdf", b"%PDF-1", "Scout A")
    monkeypatch.setattr(insight7, "_parse_pdf", _fake_parse(octo))
    insight7.save_upload("ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.10.03.pdf", b"%PDF-1", "Scout A")

    data = insight7.consolidated()
    assert [c["league"] for c in data["coverage"]] == ["ENG PL2 - EFL Clubs"]
    assert data["coverage"][0]["latest_month"] == "2026-10"
    players = {p["name"]: p for p in data["players"]}
    assert set(players) == {"Cruz Ibeh", "New Kid"}
    assert players["Cruz Ibeh"]["change"]["league_mins"] == 153
    assert players["Cruz Ibeh"]["change"]["ga"] == 3
    assert players["Cruz Ibeh"]["months_listed"] == 2
    assert players["New Kid"]["is_new"] is True
    assert players["Cruz Ibeh"]["is_new"] is False
    assert [p["name"] for p in data["dropped"]] == ["Gone Player"]

    # Same league + month replaces the earlier upload.
    monkeypatch.setattr(insight7, "_parse_pdf", _fake_parse(octo[:1]))
    meta = insight7.save_upload("ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.10.05.pdf", b"%PDF-1", "Scout B")
    assert meta["replaced"] == 1
    assert len(insight7.consolidated()["reports"]) == 2
