"""Personal Presentations gallery is the only rail link; decks stay off Strategy."""

from app.apps_manifest import (
    APPS,
    apps_for_role,
    manifest_payload,
    presentation_decks,
    required_sidebar_titles,
)
from app.presentations import presentations_html


DECK_TITLES = {
    "League Two Strategy Report",
    "Players Strategy Report",
    "Staff Strategy Report",
    "Values Report",
    "Season Progress Report",
    "Hub Origin Story",
    "Summer Window Review",
}


def test_presentations_is_the_only_rail_item_in_that_group():
    titles = required_sidebar_titles()
    assert "Presentations" in titles
    for title in DECK_TITLES:
        assert title not in titles
    visible = [app for app in APPS if app.get("group") == "presentations" and app.get("sidebar") is not False]
    assert [app["id"] for app in visible] == ["presentations"]


def test_strategy_rail_is_dashboards_only():
    strategy = [
        app["title"]
        for app in APPS
        if app["group"] == "strategy" and app.get("sidebar") is not False
    ]
    assert strategy == [
        "Squad Comparison",
        "Squad Availability",
        "What Wins Games",
        "Club Strategy",
    ]


def test_decks_are_admin_only_and_listed_on_the_gallery():
    decks = presentation_decks()
    assert {app["title"] for app in decks} == DECK_TITLES
    for app in decks:
        assert app["group"] == "presentations"
        assert app.get("sidebar") is False
        assert tuple(app.get("roles") or ()) == ("admin",)

    analysis_titles = {app["title"] for app in apps_for_role("analysis")}
    assert "Presentations" not in analysis_titles
    assert DECK_TITLES.isdisjoint(analysis_titles)

    payload = manifest_payload(role="analysis")
    assert all(group["id"] != "presentations" for group in payload["groups"])


def test_gallery_html_lists_every_deck():
    page = presentations_html()
    assert "Personal" in page
    for app in presentation_decks():
        assert app["title"] in page
        assert app["href"] in page
