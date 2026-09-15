"""Watch list — filters and a permanent loan/move legend, not a flash banner."""

from pathlib import Path

from app.apps_manifest import APPS, required_sidebar_titles
from app.paths import STANDALONE_DIR

ROOT = STANDALONE_DIR.parent


def test_watch_list_is_a_live_recruitment_tool():
    titles = required_sidebar_titles()
    assert "Watch list" in titles
    row = next(app for app in APPS if app["id"] == "watch-list")
    assert row["href"] == "/watch-list"
    assert row["group"] == "recruitment"


def test_watch_list_has_league_loan_and_situation_filters():
    html = (STANDALONE_DIR / "watch-list.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "watch-list.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "watch-list.js").read_text(encoding="utf-8")

    assert 'id="wlPanel"' in html
    assert 'id="wlLegend"' in html
    assert 'id="wlLeagueGroup"' in html
    assert 'id="wlPositionGroup"' in html
    assert 'id="wlSituationGroup"' in html
    assert "aria-label=\"League\"" in html
    assert "aria-label=\"Situation\"" in html

    assert "function matchesFilters" in js
    assert "function situationOf" in js
    assert 'situation === "loan"' in js or 'situationOf(target) !== situation' in js
    assert 'data-value="loan"' in js
    assert "On loan" in js
    assert "Signed elsewhere" in js
    assert "uniqueLeagues" in js
    assert "wl-legend__chip--loan" in js
    assert "Of the players you track" not in js
    assert "on loan (blue)" not in js

    assert ".wl-legend" in css
    assert ".wl-filter__btn" in css
    assert ".wl-legend__chip--loan" in css
    assert ".wl-panel" in css
    assert "/api/who-to-scout/loans" not in js
    assert "function applyTransfermarktLoans" not in js
