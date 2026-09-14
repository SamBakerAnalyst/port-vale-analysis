"""EFL Transfer Report still exists, nested under Transfer Centre."""

import importlib.util
from pathlib import Path

from app.apps_manifest import APPS, presentation_decks, required_sidebar_titles
from app.efl_transfer_report import load_report
from app.paths import STANDALONE_DIR

_BUILDER = Path(__file__).resolve().parents[1] / "scripts" / "build_efl_transfer_report.py"
_SPEC = importlib.util.spec_from_file_location("build_efl_transfer_report", _BUILDER)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MOD)


def test_efl_transfer_report_is_nested_under_transfer_centre():
    titles = required_sidebar_titles()
    assert "EFL Transfer Report" not in titles
    assert "Transfer Centre" in titles
    row = next(app for app in APPS if app["id"] == "efl-transfer-report")
    assert row["href"] == "/efl-transfer-report"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is False
    assert "scouts" in tuple(row["roles"])
    assert all(app["id"] != "efl-transfer-report" for app in presentation_decks())


def test_efl_transfer_report_html_and_data():
    html = STANDALONE_DIR / "efl-transfer-report.html"
    assert html.is_file()
    text = html.read_text(encoding="utf-8")
    assert "EFL Transfer Report" in text
    assert "/transfer-centre" in text
    assert "/presentations" not in text
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
    extras = STANDALONE_DIR.parent / "data" / "efl-transfer-sources" / "transfer-extras.txt"
    assert extras.is_file()
    extra_text = extras.read_text(encoding="utf-8")
    assert "Abdul Abdulmalik" in extra_text
    assert "Danny Cashman" in extra_text

    report = load_report()
    assert report["title"] == "EFL Transfer Report"
    leagues = {league["id"]: league for league in report["leagues"]}
    assert set(leagues) == {"league-one", "league-two", "national-league", "scottish-prem"}
    assert len(leagues["league-one"]["teams"]) == 24
    assert len(leagues["league-two"]["teams"]) == 24
    assert len(leagues["national-league"]["teams"]) == 24
    assert len(leagues["scottish-prem"]["teams"]) == 12

    wood = next(
        team for team in leagues["national-league"]["teams"] if team["id"] == "boreham-wood"
    )
    wood_left = {row["player"]: row for row in wood["left"]}
    wood_in = {row["player"]: row for row in wood["signed"]}
    assert wood_left["Abdul Abdulmalik"]["other"].startswith("Djurgarden")
    assert wood_in["Danny Cashman"]["kind"] == "loan"
    assert wood_in["Danny Cashman"]["other"] == "Crawley Town"

    vale = next(team for team in leagues["league-two"]["teams"] if team["id"] == "port-vale")
    signed = {row["player"] for row in vale["signed"]}
    assert "Aaron McGowan" in signed
    assert "Kyle Dempsey" in signed
    assert "Jasper Moon" in signed
    released = {row["player"] for row in vale["released"]}
    assert {"Ben Amos", "Mitch Clark", "Jesse Debrah", "Funso Ojo", "Andre Gray"} <= released
    left = {row["player"] for row in vale["left"]}
    assert "Jayden Stockley" in left
    assert "Ben Amos" not in left
    assert vale["released_count"] >= 11
    assert vale["badge_url"] == "/standalone/port-vale-badge.png?v=2"
    empty_released = [
        team["name"]
        for league in report["leagues"]
        if league["id"] != "scottish-prem"
        for team in league["teams"]
        if team["released_count"] == 0
    ]
    assert len(empty_released) <= 8, empty_released
    wimbledon = next(team for team in leagues["league-one"]["teams"] if team["id"] == "afc-wimbledon")
    assert wimbledon["badge_url"] == "/static/transfer-badges/afc-wimbledon.png"

    badge_dir = STANDALONE_DIR.parent / "static" / "transfer-badges"
    clubs = [team["id"] for league in report["leagues"] for team in league["teams"]]
    assert len(clubs) == 84
    missing = [club_id for club_id in clubs if not (badge_dir / f"{club_id}.png").is_file()]
    assert missing == []


def test_nickname_and_accent_spellings_are_the_same_player():
    assert _MOD.same_player("Oliver Sanderson", "Olly Sanderson")
    assert _MOD.same_player("Oliver Sanderson", "Ollie Sanderson")
    assert _MOD.same_player("Thimothee Lo-Tutala", "Thimothée Lo-Tutala")
    assert _MOD.same_player("Joe Bursik", "Josef Bursik")
    assert _MOD.same_player("Andrew Dallas", "Andy Dallas")
    assert _MOD.same_player("Jonathan Russell", "Jon Russell")
    assert _MOD.same_player("Ciarán Kelly", "Ciaran Kelly")
    assert _MOD.same_player("Oliver Whatmuff", "Oli Whatmuff")
    assert _MOD.same_player("Matthew Dennis", "Matty Dennis")
    assert _MOD.same_player("Ruiri Paton", "Ruari Paton")
    assert _MOD.same_player("Ismael Kabia", "Ismeal Kabia")
    assert _MOD.same_player("Shim Mheuka", "Shumaira Mheuka")
    assert not _MOD.same_player("James Tilley", "Jayden Stockley")
    assert not _MOD.same_player("Josh Earl", "Josh Magennis")
    assert not _MOD.same_player("Archie Harris", "Luke Harris")


def test_report_does_not_list_the_same_signing_twice():
    report = load_report()
    stevenage = next(
        team
        for league in report["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "stevenage"
    )
    colchester = next(
        team
        for league in report["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "colchester-united"
    )
    wimbledon = next(
        team
        for league in report["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
    )
    stevenage_names = [row["player"] for row in stevenage["signed"]]
    colchester_names = [row["player"] for row in colchester["signed"]]
    wimbledon_names = [row["player"] for row in wimbledon["signed"]]
    assert sum("Sanderson" in name for name in stevenage_names) == 1
    assert sum("Lo-Tutala" in name or "Lo Tutala" in name for name in colchester_names) == 1
    assert sum("Bursik" in name for name in wimbledon_names) == 1
    stockport = next(
        team
        for league in report["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "stockport-county"
    )
    burton = next(
        team
        for league in report["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "burton-albion"
    )
    assert sum("Whatmuff" in row["player"] for row in stockport["signed"]) == 1
    assert sum(row["other"] == "Man City" for row in stockport["signed"]) == 0
    assert sum("Dennis" in row["player"] for row in burton["signed"]) == 1
    for league in report["leagues"]:
        for team in league["teams"]:
            names = [row["player"] for row in team["signed"]]
            for index, name in enumerate(names):
                for other in names[index + 1 :]:
                    assert not _MOD.same_player(name, other), (team["name"], name, other)


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
