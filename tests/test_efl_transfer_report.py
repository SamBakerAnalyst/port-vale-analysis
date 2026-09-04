"""EFL Transfer Report lives on the Presentations gallery."""

from app.apps_manifest import APPS, presentation_decks, required_sidebar_titles
from app.efl_transfer_report import load_report
from app.paths import STANDALONE_DIR


def test_efl_transfer_report_is_personal_presentation():
    titles = required_sidebar_titles()
    assert "EFL Transfer Report" not in titles
    row = next(app for app in APPS if app["id"] == "efl-transfer-report")
    assert row["href"] == "/efl-transfer-report"
    assert row["group"] == "presentations"
    assert row.get("sidebar") is False
    assert tuple(row["roles"]) == ("admin",)
    assert any(app["id"] == "efl-transfer-report" for app in presentation_decks())


def test_efl_transfer_report_html_and_data():
    html = STANDALONE_DIR / "efl-transfer-report.html"
    assert html.is_file()
    text = html.read_text(encoding="utf-8")
    assert "EFL Transfer Report" in text
    assert "Download PDF" in text
    assert "Present" in text
    assert 'id="deck"' in text
    assert "/static/wysiwyg-export.js" in text
    js = (STANDALONE_DIR.parent / "static" / "efl-transfer-report.js").read_text()
    assert "/api/efl-transfer-report" in js
    assert "/api/wysiwyg-export-pdf" in js
    assert "captureSlideHtmlPages" in js
    assert "Transferred" in js
    assert "End of loan" in js
    assert "Permanents" in js
    assert "in-cols" in js
    assert "out-cols" in js
    assert "Also left" not in js
    assert "left-strip" not in js
    assert "html2canvas" not in js
    assert "slidesForLeague" in js
    assert "leaguePdfFilename" in js
    assert "Port-Vale-EFL-Transfer-Report-2026-League-Two.pdf" in js or "League-Two" in js
    assert 'data-league-pdf="league-one"' in text
    assert 'data-league-pdf="league-two"' in text
    assert 'data-league-pdf="national-league"' in text
    assert 'data-league-pdf="scottish-prem"' in text
    assert 'id="exportPdfMenu"' in text
    assert "League One" in text
    assert "League Two" in text
    assert "National League" in text
    assert "Scottish Premiership" in text
    assert "One league" in text

    report = load_report()
    assert report["title"] == "EFL Transfer Report"
    leagues = {league["id"]: league for league in report["leagues"]}
    assert set(leagues) == {"league-one", "league-two", "national-league", "scottish-prem"}
    assert len(leagues["league-one"]["teams"]) == 24
    assert len(leagues["league-two"]["teams"]) == 24
    assert len(leagues["national-league"]["teams"]) == 24
    assert len(leagues["scottish-prem"]["teams"]) == 12

    vale = next(team for team in leagues["league-two"]["teams"] if team["id"] == "port-vale")
    signed = {row["player"] for row in vale["signed"]}
    assert "Aaron McGowan" in signed
    assert "Kyle Dempsey" in signed
    assert "Jasper Moon" in signed
    left = {row["player"] for row in vale["left"]}
    assert "Jayden Stockley" in left
    assert vale["badge_url"] == "/standalone/port-vale-badge.png?v=2"
    wimbledon = next(team for team in leagues["league-one"]["teams"] if team["id"] == "afc-wimbledon")
    assert wimbledon["badge_url"] == "/static/transfer-badges/afc-wimbledon.png"

    badge_dir = STANDALONE_DIR.parent / "static" / "transfer-badges"
    clubs = [team["id"] for league in report["leagues"] for team in league["teams"]]
    assert len(clubs) == 84
    missing = [club_id for club_id in clubs if not (badge_dir / f"{club_id}.png").is_file()]
    assert missing == []


def test_efl_transfer_report_per_league_pdf_export():
    html = (STANDALONE_DIR / "efl-transfer-report.html").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "efl-transfer-report.js").read_text(encoding="utf-8")
    assert 'id="exportPdf"' in html
    assert 'id="exportPdfMenu"' in html
    assert 'id="exportPdfMenuBtn"' in html
    for league_id, label in (
        ("league-one", "League One"),
        ("league-two", "League Two"),
        ("national-league", "National League"),
        ("scottish-prem", "Scottish Premiership"),
    ):
        assert f'data-league-pdf="{league_id}"' in html
        assert label in html
    assert "slidesForLeague" in js
    assert "leaguePdfFilename" in js
    assert "LEAGUE_PDF" in js
    assert "captureSlideHtmlPages" in js
    assert "downloadPdf" in js
    assert "/api/wysiwyg-export-pdf" in js
    assert "html2canvas" not in js
    assert "Port-Vale-EFL-Transfer-Report-2026-${league.file}.pdf" in js
    assert 'file: "League-Two"' in js
    report = load_report()
    expected = {
        league["id"]: 1 + 1 + len(league["teams"]) + 1 for league in report["leagues"]
    }
    assert expected == {
        "league-one": 27,
        "league-two": 27,
        "national-league": 27,
        "scottish-prem": 15,
    }
