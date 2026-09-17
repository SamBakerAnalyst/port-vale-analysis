"""Match slide templates on Meeting Front Pages."""

from __future__ import annotations

from app.meeting_front_pages import (
    MATCH_SLIDE_PACKS,
    build_match_slide_pack,
    parse_vale_match_label,
)
from app.paths import STANDALONE_DIR, STATIC_DIR


def test_parse_vale_match_label_splits_home_and_away():
    home = parse_vale_match_label("Exeter (H)")
    assert home["opponent"] == "Exeter"
    assert home["venue"] == "H"
    away = parse_vale_match_label("Oldham (A)")
    assert away["opponent"] == "Oldham"
    assert away["venue"] == "A"
    assert parse_vale_match_label("Wolves")["opponent"] == "Wolves"


def test_pre_match_pack_has_vale_and_exeter_badges():
    pack = build_match_slide_pack(
        name="Exeter (H)",
        competition="League",
        pack_id="pre-match",
    )
    assert pack["portVale"]["name"] == "Port Vale"
    assert pack["portVale"]["badgeProxyUrl"]
    assert "exeter" in pack["opponent"]["name"].casefold()
    assert pack["opponent"]["badgeUrl"]
    assert "image-proxy" in pack["opponent"]["badgeProxyUrl"] or pack["opponent"]["badgeProxyUrl"].startswith("/")
    titles = [slide["title"] for slide in pack["slides"]]
    assert titles[0] == "Pre-Match"
    assert "Keys to the game" in titles
    assert pack["slides"][0]["id"] == "cover"
    assert "Port Vale vs" in pack["match"]["fixture"]


def test_post_match_and_set_plays_templates():
    post = build_match_slide_pack(name="Salford (A)", pack_id="post-match")
    assert post["pack"]["id"] == "post-match"
    titles = [slide["title"] for slide in post["slides"]]
    assert "What went well" in titles
    assert "Goals against" in titles
    assert post["match"]["venue"] == "A"

    set_plays = build_match_slide_pack(name="Crewe (H)", pack_id="set-plays")
    topics = [slide["title"] for slide in set_plays["slides"]]
    assert "Attacking corners" in topics
    assert "Throw-ins" in topics


def test_wolves_cup_opponent_gets_a_crest():
    pack = build_match_slide_pack(name="Wolves (A)", competition="Carabao Cup", pack_id="pre-match")
    assert "wanderers" in pack["opponent"]["name"].casefold() or pack["opponent"]["name"] == "Wolves"
    assert pack["opponent"]["badgeUrl"]
    assert "10260" in pack["opponent"]["badgeUrl"] or pack["opponent"]["badgeProxyUrl"]


def test_match_packs_are_the_three_meeting_types():
    assert set(MATCH_SLIDE_PACKS) == {"pre-match", "post-match", "set-plays"}


def test_html_and_js_have_match_slide_mode():
    html = (STANDALONE_DIR / "meeting-front-pages.html").read_text(encoding="utf-8")
    js = (STATIC_DIR / "meeting-front-pages.js").read_text(encoding="utf-8")
    assert 'data-mode="match"' in html
    assert 'id="matchPackPills"' in html
    assert "/api/meeting-front-pages/match-pack" in js
    assert "loadMatchPack" in js
    assert "data-drop-slide" in js
    assert 'draggable="true"' in js
    assert "contenteditable" in js
    assert "mfp-match__photo" in js
    assert "mfp-match__photo-edge" in js
    assert "addStatSlideBtn" in js
    assert "addStatsSlideBtn" in js
    assert "is-positive" in js
    assert "is-negative" in js
    assert 'kind: "stat"' in js
    assert 'kind: "stats"' in js
    assert "no-photo" in js
    assert 'pagesPerRequest: 1' in js
    assert '"is-active-target"' in js
    assert "wysiwyg-export.js?v=3" in html
    assert "meeting-front-pages.js?v=46" in html
    assert "meeting-front-pages.css?v=45" in html
    assert "is-mixed" in js
    css = (STATIC_DIR / "meeting-front-pages.css").read_text(encoding="utf-8")
    assert "is-stats.is-positive" in css
    assert "is-stats.is-negative" in css
