from __future__ import annotations

from app.apps_manifest import LIVE_ESSENTIAL_IDS, is_app_live
from app.handout_badges import fotmob_crest_url_for_club, hydrate_team_badge
from app.opponent_photos import attach_pitch_player_photos, opponent_photo_api_url
from app.player_cards import _resolve_card_photo_urls
from app.pre_match import (
    PreMatchReportRequest,
    _hydrate_cached_pre_match_report,
    _merge_fixture_rows,
    build_pre_match_fixtures,
    build_pre_match_report,
)
import app.analysis_cache as analysis_cache


def test_post_match_is_live_essential():
    assert "post-match" in LIVE_ESSENTIAL_IDS
    assert is_app_live("post-match") is True


def test_hydrate_badge_uses_fotmob_without_impect():
    row = hydrate_team_badge({"id": 2157, "name": "Salford City"})
    assert row["badge_url"]
    assert "fotmob.com" in row["badge_url"] or row["badge_url"].startswith("/api/team-badge/")


def test_fotmob_crest_covers_league_two_clubs():
    assert fotmob_crest_url_for_club("Tranmere Rovers")
    assert fotmob_crest_url_for_club("Crewe Alexandra")
    assert fotmob_crest_url_for_club("Grimsby Town")
    assert "9799" in (fotmob_crest_url_for_club("Port Vale") or "")


def test_pitch_photos_always_expose_proxy_url():
    players = attach_pitch_player_photos(
        [{"name": "Josh Davison", "shirt_number": 9}],
        club_name="Tranmere Rovers",
        season="26/27",
        warm=False,
    )
    assert players[0]["photo_url"]
    assert players[0]["photo_url"].startswith("/api/pre-match/player-photo?")
    assert "Josh" in players[0]["photo_url"]


def test_player_card_photo_prefers_same_origin_proxy():
    primary, _fotmob, fallbacks = _resolve_card_photo_urls(
        "Josh Davison",
        "Tranmere Rovers",
        "26/27",
        {"photo_url": "https://cdn.example/blocked.jpg", "fotmob_player_id": 123, "shirt_number": 9},
    )
    assert primary == opponent_photo_api_url(
        "Josh Davison",
        club_name="Tranmere Rovers",
        season="26/27",
        shirt_number=9,
    )
    assert primary == fallbacks[0]


def test_cached_two_pager_gets_last_game_badges_and_photos():
    report = _hydrate_cached_pre_match_report(
        {
            "iteration_id": 2120,
            "season": "26/27",
            "opponent": {"id": 8313, "name": "Tranmere Rovers"},
            "two_match": {
                "matches": [
                    {
                        "opponent": "Salford City",
                        "opponent_id": 2157,
                        "score": "1-0",
                        "pitch_players": [{"name": "Josh Davison", "shirt_number": 9}],
                    }
                ],
                "last_xi": [{"name": "Josh Davison"}],
            },
            "form": [{"opponent": "Crewe Alexandra", "opponent_id": 1042}],
        }
    )
    match = report["two_match"]["matches"][0]
    assert match["opponent_badge_url"]
    assert report["two_match"]["last_xi"][0]["photo_url"]
    assert report["form"][0]["opponent_image_url"]
    assert report["opponent"]["badge_url"]


def test_stale_missing_disk_badge_falls_back_to_fotmob(monkeypatch):
    monkeypatch.setattr("app.handout_badges.local_badge_url", lambda *_a, **_k: None)
    report = _hydrate_cached_pre_match_report(
        {
            "two_match": {
                "matches": [
                    {
                        "opponent": "FC Barnet",
                        "opponent_id": 939,
                        "opponent_badge_url": "/api/team-badge/939",
                    }
                ]
            },
            "form": [
                {
                    "opponent": "FC Walsall",
                    "opponent_id": 922,
                    "opponent_image_url": "/api/team-badge/922",
                }
            ],
        }
    )
    assert "fotmob.com" in report["two_match"]["matches"][0]["opponent_badge_url"]
    assert "fotmob.com" in report["form"][0]["opponent_image_url"]


def test_force_refresh_does_not_wipe_pre_match_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    analysis_cache.write_json("pre-match", "keep_me", {"opponent": {"name": "Bromley"}})
    analysis_cache.write_json("xg-report", "drop_me", {"shotCount": 1})
    analysis_cache.write_json(
        "pre-match-fixtures",
        "fixtures_2120",
        {"fixtures": [{"opponent": {"name": "Exeter City"}, "played": False}]},
    )
    counts = analysis_cache.clear_volatile()
    assert "pre-match" not in counts
    assert "pre-match-fixtures" in counts
    assert analysis_cache.read_json("pre-match", "keep_me", ttl=1, allow_stale=True)["opponent"]["name"] == "Bromley"
    assert analysis_cache.read_json("xg-report", "drop_me", ttl=1, allow_stale=True) is None
    assert (
        analysis_cache.read_json(
            "pre-match-fixtures", "fixtures_2120", ttl=1, allow_stale=True
        )
        is None
    )


def test_played_fixtures_keep_their_own_row():
    merged = _merge_fixture_rows(
        [
            {
                "match_id": 1,
                "played": True,
                "kickoff_label": "2-1",
                "opponent": {"id": 10, "name": "Bromley", "badge_url": "/api/team-badge/10"},
            }
        ],
        [
            {
                "match_id": 2,
                "played": False,
                "kickoff_label": "A Sat 3pm",
                "opponent": {"id": 11, "name": "Grimsby"},
            }
        ],
    )
    assert len(merged) == 2
    assert {row["opponent"]["name"] for row in merged} == {"Bromley", "Grimsby"}


def test_hydrated_cache_still_counts_as_click_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    analysis_cache.write_json(
        "pre-match",
        "report_2120_55_99",
        {
            "iteration_id": 2120,
            "opponent": {"id": 55, "name": "Salford City"},
            "two_match": {"matches": [{"opponent": "Bromley"}]},
        },
    )
    monkeypatch.setattr("app.pre_match._build_pre_match_report_uncached", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no impect")))
    report = build_pre_match_report(
        PreMatchReportRequest(iteration_id=2120, squad_id=55, match_id=99, refresh=False)
    )
    assert report["cache"]["hit"] is True
    assert report["opponent"]["badge_url"]
    assert report["two_match"]["matches"][0]["opponent_badge_url"]


def test_played_score_beats_upcoming_kickoff_for_same_match():
    merged = _merge_fixture_rows(
        [
            {
                "match_id": 270696,
                "played": False,
                "kickoff_label": "H Sat 22 Aug · 15:00",
                "opponent": {"id": 1509, "name": "Tranmere Rovers"},
            }
        ],
        [
            {
                "match_id": 270696,
                "played": True,
                "kickoff_label": "1-1",
                "opponent": {"id": 1509, "name": "Tranmere Rovers", "badge_url": "/api/team-badge/1509"},
            }
        ],
    )
    assert len(merged) == 1
    assert merged[0]["played"] is True
    assert merged[0]["kickoff_label"] == "1-1"


def test_pre_match_bar_recovers_played_xg_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis_cache, "ANALYSIS_CACHE_DIR", tmp_path)
    monkeypatch.setattr("app.set_piece_pre_match.SET_PIECE_CACHE_DIR", tmp_path / "sp")
    (tmp_path / "sp").mkdir(parents=True, exist_ok=True)
    analysis_cache.write_json(
        "pre-match-fixtures",
        "fixtures_2120",
        {
            "fixtures": [
                {
                    "match_id": 270770,
                    "match_day": 5,
                    "played": False,
                    "kickoff_label": "H Sat 12 Sep · 15:00",
                    "opponent": {"id": 881, "name": "Exeter City"},
                }
            ]
        },
    )
    analysis_cache.write_json(
        "xg-fixtures",
        "26-27",
        {
            "fixtures": [
                {
                    "matchId": 270696,
                    "matchDay": 2,
                    "kickoffLabel": "1-1",
                    "isHome": True,
                    "score": "1-1",
                    "opponent": {
                        "id": 1509,
                        "name": "Tranmere Rovers",
                        "badge_url": "/api/team-badge/1509",
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.pre_match._build_pre_match_fixtures_uncached",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no impect")),
    )
    fixtures = build_pre_match_fixtures(2120, refresh=False)
    names = [row["opponent"]["name"] for row in fixtures]
    assert names[0] == "Tranmere Rovers"
    assert "Exeter City" in names
    tranmere = fixtures[0]
    assert tranmere["played"] is True
    assert tranmere["opponent"]["badge_url"]
