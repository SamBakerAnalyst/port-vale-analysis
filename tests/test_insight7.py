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


def test_continuation_page_with_narrower_monthly_chart_keeps_stat_columns():
    header = ["", None, "Age", "Primary\nPosition", "Club", "Contract", "League Mins", "League GT", "Monthly\n(Aug - May)"]
    header += [None] * 9 + ["Goals /\nCS", "Assists", "International", "Debut", "Agent", "Career Note", "Mins per G / A"]
    mapping = insight7._header_map(header)
    # Next page: no header, and the monthly chart spans 4 columns instead of 10.
    row = ["", "Connor Harris**", "19", "08-CM", "Bracknell Town", "30/06/26", "1105", "29%", "", None, "", ""]
    row += ["1", "0", "", "", "", "AFC Wimbledon > Farnborough (08/08/25)", "1105"]
    record = insight7._row_record(row, mapping)
    assert (record["goals"], record["assists"], record["mins_per_ga"]) == (1, 0, 1105)
    assert record["league_mins"] == 1105 and record["league_gt"] == 29
    assert record["career_note"].startswith("AFC Wimbledon")


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
    assert data["coverage"][0]["latest_month"] == "2026-09"
    assert data["coverage"][0]["previous_month"] == "2026-08"
    players = {p["name"]: p for p in data["players"]}
    assert set(players) == {"Cruz Ibeh", "New Kid"}
    assert players["Cruz Ibeh"]["change"]["league_mins"] == 153
    assert players["Cruz Ibeh"]["change"]["ga"] == 3
    assert players["Cruz Ibeh"]["months_listed"] == 2
    assert players["New Kid"]["is_new"] is True
    assert players["Cruz Ibeh"]["is_new"] is False
    assert [p["name"] for p in data["dropped"]] == ["Gone Player"]

    # A late-September release is the same edition as an early-October one, so it replaces it.
    monkeypatch.setattr(insight7, "_parse_pdf", _fake_parse(octo[:1]))
    meta = insight7.save_upload("ENG PL2 - EFL Clubs - Emerging Talent Bulletin 2026.09.29.pdf", b"%PDF-1", "Scout B")
    assert meta["replaced"] == 1
    assert meta["month"] == "2026-09"
    assert len(insight7.consolidated()["reports"]) == 2


def test_edition_month_and_season_rules():
    assert insight7._edition_month("2026-10-03") == "2026-09"
    assert insight7._edition_month("2026-09-25") == "2026-09"
    assert insight7._edition_month("2026-10-30") == "2026-10"
    assert insight7._season_for("", "SCO League One", "2026-09") == "2026-27"
    assert insight7._season_for("", "SCO League One", "2026-04") == "2025-26"
    assert insight7._season_for("", "IRE Premier Division", "2026-07") == "2026"
    assert insight7._season_for("2026-27", "anything", "2026-04") == "2026-27"
    for line, league, season in (
        ("SCOTTISH LEAGUE ONE 2026-27", "SCOTTISH LEAGUE ONE", "2026-27"),
        ("PL2 - EFL Clubs - 2026-27", "PL2 - EFL Clubs", "2026-27"),
        ("PREMIER DIVISION 2026", "PREMIER DIVISION", "2026"),
    ):
        match = insight7._SEASON_LINE.match(line)
        assert match and match.group("league") == league and match.group("season") == season
    assert insight7._SEASON_LINE.match("Achieving 75% Game Time") is None


def test_new_season_does_not_compare_against_last_season(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    may = [{"name": "Owen Foster", "age": 19, "club": "Alloa Athletic", "league_mins": 2700, "goals": 9, "assists": 2}]
    sept = [{"name": "Owen Foster", "age": 20, "club": "Alloa Athletic", "league_mins": 720, "goals": 2, "assists": 0}]
    for players, name in ((may, "2026.05.07"), (sept, "2026.10.01")):
        parse = _fake_parse(players, league_line="SCOTTISH LEAGUE ONE")

        def no_season(_bytes, parse=parse):
            return {**parse(_bytes), "season": ""}

        monkeypatch.setattr(insight7, "_parse_pdf", no_season)
        insight7.save_upload(f"SCO League One - Emerging Talent Bulletin {name}.pdf", b"%PDF-1", "Scout A")
    data = insight7.consolidated()
    cov = data["coverage"][0]
    assert cov["league"] == "SCO League One"
    assert cov["latest_season"] == "2026-27"
    assert cov["previous_month"] is None
    owen = data["players"][0]
    assert owen["change"] is None and owen["is_new"] is False
    assert owen["months_listed"] == 2


def test_migration_rereads_old_uploads(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "abc123def456.pdf").write_bytes(b"%PDF-1")
    insight7._save({"reports": {"abc123def456": {
        "id": "abc123def456", "league": "SCO League One", "league_key": "sco-league-one", "season": "",
        "month": "2026-10", "report_date": "2026-10-01",
        "filename": "SCO League One - Emerging Talent Bulletin 2026.10.01.pdf",
        "sections": ["SCOTTISH LEAGUE ONE 2026-27"], "players": [], "player_count": 0,
    }}})
    monkeypatch.setattr(insight7, "_parse_pdf", lambda _b: {
        "league_line": "SCOTTISH LEAGUE ONE", "season": "2026-27", "footer_date": "",
        "sections": ["Achieving 75% Game Time"], "players": [{"name": "Owen Foster", "age": 20, "club": "Alloa Athletic"}],
    })
    assert insight7.migrate_reports() == 1
    report = insight7._load()["reports"]["abc123def456"]
    assert report["month"] == "2026-09"
    assert report["season"] == "2026-27"
    assert report["sections"] == ["Achieving 75% Game Time"]
    assert report["player_count"] == 1
    assert insight7.migrate_reports() == 0
