"""Board briefing retired from the rail; Origin Story is the staff Present deck."""

from app.apps_manifest import APPS, required_sidebar_titles


def test_board_briefing_retired_from_sidebar():
    titles = required_sidebar_titles()
    assert "Hub Board Briefing" not in titles
    assert all(app["id"] != "board-briefing" for app in APPS)


def test_hub_origin_lives_on_presentations_gallery():
    titles = required_sidebar_titles()
    assert "Hub Origin Story" not in titles
    row = next(app for app in APPS if app["id"] == "hub-origin")
    assert row["href"] == "/hub-origin"
    assert row["group"] == "presentations"
    assert row.get("sidebar") is False
    assert tuple(row["roles"]) == ("admin",)


def test_board_briefing_html_still_exists_for_bookmarks():
    from pathlib import Path

    from app.paths import STANDALONE_DIR

    html = STANDALONE_DIR / "board-briefing.html"
    assert html.is_file()
    text = html.read_text(encoding="utf-8")
    assert "This level of organisation can drive the club forward." in text
