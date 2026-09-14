"""PA Meeting Slides — analysis video title cards."""

from __future__ import annotations

from app.apps_manifest import APPS, required_sidebar_titles, role_path_prefixes
from app.auth import _path_allowed_for_role
from app.pa_meeting_slides import (
    PACKS,
    default_slides,
    list_clubs,
    meta_payload,
    port_vale_club,
    resolve_club,
    save_deck,
)
from app.paths import STANDALONE_DIR


def test_pa_meeting_slides_is_an_analysis_rail_tool():
    titles = required_sidebar_titles()
    assert "PA Meeting Slides" in titles
    row = next(app for app in APPS if app["id"] == "pa-meeting-slides")
    assert row["href"] == "/pa-meeting-slides"
    assert row["group"] == "analysis"
    assert row.get("sidebar") is not False
    assert "analysis" in tuple(row["roles"])
    assert "scouts" not in tuple(row["roles"])
    assert row["router"] == "pa_meeting_slides"
    assert "/api/pa-meeting-slides" in tuple(row["api_prefixes"])


def test_analysis_role_can_open_pa_meeting_slides_and_scouts_cannot():
    for path in ("/pa-meeting-slides", "/api/pa-meeting-slides/clubs", "/api/pa-meeting-slides/photos"):
        assert _path_allowed_for_role(path, "analysis"), f"analysis blocked from {path}"
        assert not _path_allowed_for_role(path, "scouts"), f"{path} leaked to scouts"
    assert "/api/pa-meeting-slides" in role_path_prefixes("analysis")


def test_page_is_a_meeting_pack_with_badges_topics_and_photos():
    html = (STANDALONE_DIR / "pa-meeting-slides.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "pa-meeting-slides.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "pa-meeting-slides.js").read_text(encoding="utf-8")
    assert "PA Meeting Slides" in html
    assert "Performance analysis" in html
    assert 'id="clubSearch"' in html
    assert "Exeter City" in html
    assert "Refresh 26/27 match photos" in html
    assert "Find opponent photos" in html
    assert "Download PNG pack" in html
    assert 'id="packPills"' in html
    assert "/api/pa-meeting-slides" in js
    assert "loadPhotos(\"Port Vale\"" in js
    assert "Finding 26/27 match photos" in js
    assert "autoAssignDistinctPhotos" not in js
    assert "slides stay blank until you pick one" in js
    assert "No photo — click a picture below" in js
    assert "pams-slide__crest" in css
    assert "168px" in css
    assert "justify-content: center" in css
    assert "text-align: center" in css
    assert "pams-slide__stage" in css
    assert "pams-slide__stage" in js
    assert "slide.kind === \"cover\" && opponent ? opponent.name : \"\"" in js


def test_exeter_is_in_the_club_catalog_with_a_badge():
    clubs = list_clubs(q="exeter")
    assert clubs
    exeter = next((row for row in clubs if "exeter" in str(row["name"]).casefold()), None)
    assert exeter is not None
    assert exeter["name"] == "Exeter City"
    assert exeter["badgeUrl"]
    assert "fotmob" in str(exeter["badgeUrl"]) or str(exeter["badgeUrl"]).startswith("/")
    resolved = resolve_club("Exeter City")
    assert resolved is not None
    assert resolved["name"] == "Exeter City"


def test_set_plays_pack_has_attacking_and_defensive_corners():
    pack = PACKS["set-plays"]
    titles = [str(t).casefold() for t in pack["topics"]]
    assert "attacking corners" in titles
    assert "defensive corners" in titles
    slides = default_slides("set-plays", "Exeter City")
    kinds = [row["kind"] for row in slides]
    assert kinds[0] == "cover"
    assert slides[0]["title"] == "Set Plays"
    assert slides[0]["subtitle"] == "Exeter City"
    topic_titles = [row["title"] for row in slides if row["kind"] == "topic"]
    assert "Attacking Corners" in topic_titles
    assert "Defensive Corners" in topic_titles
    assert "Attacking Free Kicks" in topic_titles
    assert "Defensive Free Kicks" in topic_titles


def test_port_vale_badge_is_the_local_crest():
    vale = port_vale_club()
    assert vale["name"] == "Port Vale"
    assert "port-vale-badge" in vale["badgeUrl"]
    meta = meta_payload()
    assert meta["defaultPack"] == "set-plays"
    assert meta["photoSeason"] == "26/27"
    assert any(pack["id"] == "set-plays" for pack in meta["packs"])


def test_save_deck_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("app.pa_meeting_slides._STORE_PATH", tmp_path / "pa-meeting-slides.json")
    doc = save_deck(
        "exeter-city-set-plays",
        {
            "title": "Set Plays",
            "packId": "set-plays",
            "opponent": {"name": "Exeter City"},
            "slides": default_slides("set-plays", "Exeter City"),
        },
    )
    assert doc["id"] == "exeter-city-set-plays"
    assert doc["opponent"]["name"] == "Exeter City"
    from app.pa_meeting_slides import load_deck, list_decks

    loaded = load_deck("exeter-city-set-plays")
    assert loaded is not None
    assert loaded["title"] == "Set Plays"
    assert any(row["id"] == "exeter-city-set-plays" for row in list_decks())


def test_photo_search_keeps_2627_match_shots_and_drops_junk():
    from app.pa_meeting_slides import (
        parse_club_news_photos,
        photo_url_is_match_shot,
        photo_url_is_stale,
        season_photo_queries,
    )

    extras = " ".join(row[1] for row in season_photo_queries("Port Vale"))
    assert "vs Salford 2026" in extras
    assert "match action 2026" in extras
    assert "League Two 2026" not in extras
    assert "26/27" not in extras
    custom = season_photo_queries("Port Vale", "corners")
    assert "corners 2026 match action" in custom[0][1]

    match = (
        "https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/public/"
        "2026-09/Salford%20%28A%29-105.jpg"
    )
    crewe = (
        "https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/public/"
        "2026-08/Crewe%20%28H%29-16.jpg"
    )
    assert photo_url_is_match_shot(match)
    assert photo_url_is_match_shot(crewe)
    assert not photo_url_is_stale(match)
    assert photo_url_is_stale("https://cdn.example/port-vale-2019-kit.jpg")
    assert photo_url_is_stale("https://cdn.port-vale.co.uk/2026-05/Retained-List.jpg")
    assert photo_url_is_stale(
        "https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/public/"
        "2026-07/Doncaster%20%28H%29%2023%2008%2025-90.jpg"
    )
    assert not photo_url_is_match_shot(
        "https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/public/"
        "2026-06/26-27-Fixtures-16-9.png.jpeg"
    )
    assert not photo_url_is_match_shot(
        "https://www.footballkitarchive.com/cdn/2026/06/14/x/port-vale-2026-27-home-kit.jpg"
    )
    assert not photo_url_is_match_shot("https://i.ytimg.com/vi/xxx/maxresdefault.jpg")
    assert not photo_url_is_match_shot("https://www.predictz.com/images/percbar1.gif")
    assert not photo_url_is_match_shot(
        "https://cdn.the72.co.uk/wp-content/uploads/2026/09/neimo6mCcdW7-380x280.webp"
    )

    html = (
        '<img src="https://cdn.port-vale.co.uk/sites/default/files/styles/cc_320x180/'
        'public/2026-08/Crewe%20%28H%29-16.jpg?itok=a" />'
        '<img src="https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/'
        'public/2026-08/Crewe%20%28H%29-16.jpg?itok=b" />'
        '<img src="https://cdn.port-vale.co.uk/sites/default/files/styles/cc_2000x1125/'
        'public/2026-06/26-27-Fixtures-16-9.png.jpeg?itok=c" />'
    )
    parsed = parse_club_news_photos(html)
    assert len(parsed) == 1
    assert "cc_2000x1125" in parsed[0]
    assert "Crewe" in parsed[0]
