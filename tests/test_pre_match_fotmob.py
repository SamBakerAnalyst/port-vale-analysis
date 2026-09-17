from __future__ import annotations

from app.pre_match import _pick_next_fixture, _slot_pitch_to_formation
from app.pre_match_fotmob import (
    apply_fotmob_live_overlay,
    overlay_fotmob_vale_fixtures,
    overlay_two_match,
    parse_last_xi,
    parse_next_match,
    parse_recent_results,
    parse_top_players,
    pick_fotmob_next_fixture,
)


WALSALL_PAYLOAD = {
    "details": {"id": 10006, "name": "Walsall"},
    "overview": {
        "nextMatch": {
            "id": 5837942,
            "home": {"id": 10006, "name": "Walsall"},
            "away": {"id": 9799, "name": "Port Vale"},
            "status": {
                "utcTime": "2026-09-19T11:30:00.000Z",
                "finished": False,
            },
            "tournament": {"name": "League Two"},
        },
        "topPlayers": {
            "byGoals": {
                "players": [
                    {"id": 1, "name": "Aaron Pressley", "value": 4},
                    {"id": 2, "name": "Harrison Burke", "value": 1},
                    {"id": 3, "name": "Isaac Moore", "value": 1},
                ]
            },
            "byAssists": {
                "players": [
                    {"id": 4, "name": "Reece Smith", "value": 2},
                    {"id": 5, "name": "Mason Hancock", "value": 1},
                    {"id": 6, "name": "Courtney Clarke", "value": 1},
                ]
            },
        },
        "teamForm": [
            {
                "resultString": "D",
                "imageUrl": "https://images.fotmob.com/image_resources/logo/teamlogo/9833.png",
                "linkToMatch": "/matches/exeter-city-vs-walsall/396dnt#5837912",
                "date": {"utcTime": "2026-09-05T14:00:00.000Z"},
                "tooltipText": {
                    "utcTime": "2026-09-05T14:00:00.000Z",
                    "homeScore": 0,
                    "awayScore": 0,
                },
                "tournamentName": "League Two",
                "home": {"id": 9833, "name": "Exeter City", "isOurTeam": False},
                "away": {"id": 10006, "name": "Walsall", "isOurTeam": True},
            },
            {
                "resultString": "D",
                "imageUrl": "https://images.fotmob.com/image_resources/logo/teamlogo/8493.png",
                "linkToMatch": "/matches/rochdale-vs-walsall/2tvsb7#5837929",
                "date": {"utcTime": "2026-09-12T14:00:00.000Z"},
                "tooltipText": {
                    "utcTime": "2026-09-12T14:00:00.000Z",
                    "homeScore": 0,
                    "awayScore": 0,
                },
                "tournamentName": "League Two",
                "home": {"id": 10006, "name": "Walsall", "isOurTeam": True},
                "away": {"id": 8493, "name": "Rochdale", "isOurTeam": False},
            },
        ],
        "lastLineupStats": {
            "formation": "4-2-3-1",
            "lastMatch": {
                "matchId": 5837929,
                "homeTeamName": "Walsall",
                "awayTeamName": "Rochdale",
            },
            "starters": [
                {
                    "id": 11,
                    "name": "Jed Ward",
                    "shirtNumber": "1",
                    "usualPlayingPositionId": 0,
                    "positionId": 11,
                    "verticalLayout": {"x": 0.5, "y": 0.1},
                },
                {
                    "id": 22,
                    "name": "Elicha Ahui",
                    "shirtNumber": "22",
                    "usualPlayingPositionId": 1,
                    "positionId": 32,
                    "verticalLayout": {"x": 0.125, "y": 0.292},
                },
                {
                    "id": 3,
                    "name": "Mason Hancock",
                    "shirtNumber": "3",
                    "usualPlayingPositionId": 1,
                    "positionId": 38,
                    "verticalLayout": {"x": 0.875, "y": 0.292},
                },
                {
                    "id": 25,
                    "name": "Declan Skura",
                    "shirtNumber": "25",
                    "usualPlayingPositionId": 1,
                    "positionId": 36,
                    "verticalLayout": {"x": 0.625, "y": 0.292},
                },
                {
                    "id": 19,
                    "name": "Aaron Pressley",
                    "shirtNumber": "19",
                    "usualPlayingPositionId": 3,
                    "positionId": 115,
                    "verticalLayout": {"x": 0.5, "y": 0.87},
                },
            ],
        },
    },
}

VALE_PAYLOAD = {
    "details": {"id": 9799, "name": "Port Vale"},
    "overview": {
        "nextMatch": {
            "id": 5837942,
            "home": {"id": 10006, "name": "Walsall"},
            "away": {"id": 9799, "name": "Port Vale"},
            "status": {
                "utcTime": "2026-09-19T11:30:00.000Z",
                "finished": False,
            },
            "tournament": {"name": "League Two"},
        },
        "teamForm": [
            {
                "linkToMatch": "/matches/exeter#1",
                "date": {"utcTime": "2026-09-05T14:00:00.000Z"},
                "tooltipText": {"homeScore": 1, "awayScore": 0},
                "home": {"id": 9799, "name": "Port Vale", "isOurTeam": True},
                "away": {"id": 9833, "name": "Exeter City", "isOurTeam": False},
            }
        ],
        "lastLineupStats": {"starters": []},
        "topPlayers": {},
    },
}


def test_fotmob_coords_put_gk_bottom_and_rb_right():
    xi, formation = parse_last_xi(WALSALL_PAYLOAD, club_name="Walsall", season="26/27")
    assert formation == "4-2-3-1"
    by_name = {row["short_name"]: row for row in xi}
    assert by_name["Ward"]["y_pct"] > 80
    assert by_name["Pressley"]["y_pct"] < 25
    assert by_name["Ahui"]["x_pct"] > 70
    assert by_name["Hancock"]["x_pct"] < 30
    assert by_name["Skura"]["source"] == "fotmob"


def test_fotmob_xi_is_not_reslotted_onto_template():
    xi, _formation = parse_last_xi(WALSALL_PAYLOAD, club_name="Walsall", season="26/27")
    slotted = _slot_pitch_to_formation(xi, "4-2-3-1")
    by_name = {row["short_name"]: row for row in slotted}
    assert by_name["Ahui"]["x_pct"] == xi[1]["x_pct"]


def test_recent_results_include_rochdale():
    rows = parse_recent_results(WALSALL_PAYLOAD)
    assert [row["opponent"] for row in rows] == ["Exeter City", "Rochdale"]
    assert rows[-1]["venue"] == "H"
    assert rows[-1]["score"] == "0-0"
    assert rows[-1]["result"] == "D"


def test_overlay_keeps_impect_xg_on_matching_game():
    two = overlay_two_match(
        {
            "matches": [
                {
                    "match_id": 99,
                    "date": "2026-09-05T14:00:00+00:00",
                    "opponent": "Exeter City",
                    "formation": "4-2-3-1",
                    "xg_for": 0.4,
                    "xg_against": 1.6,
                    "possession_pct": 54.0,
                    "pitch_players": [{"name": "Old XI"}],
                }
            ],
            "stat_leaders": [
                {"key": "goals", "label": "Most goals", "players": []},
                {"key": "ball_progression", "label": "Ball progression", "players": [{"name": "Crew"}]},
            ],
        },
        WALSALL_PAYLOAD,
        club_name="Walsall",
        season="26/27",
        squad_rows=[{"id": 31564, "name": "Aaron Pressley", "shirt_number": 19}],
    )
    assert two["matches"][0]["opponent"] == "Exeter City"
    assert two["matches"][0]["xg_for"] == 0.4
    assert two["matches"][1]["opponent"] == "Rochdale"
    assert "xg_for" not in two["matches"][1]
    assert two["last_xi"][0]["short_name"] == "Ward"
    goals = next(board for board in two["stat_leaders"] if board["key"] == "goals")
    assert goals["players"][0]["short_name"] == "Pressley"
    assert goals["players"][0]["value_label"] == "4"
    assert any(board["key"] == "ball_progression" for board in two["stat_leaders"])


def test_goals_and_assists_come_from_fotmob():
    goals = parse_top_players(WALSALL_PAYLOAD, "byGoals", club_name="Walsall", season="26/27")
    assists = parse_top_players(WALSALL_PAYLOAD, "byAssists", club_name="Walsall", season="26/27")
    assert [row["short_name"] for row in goals] == ["Pressley", "Burke", "Moore"]
    assert [row["short_name"] for row in assists] == ["Smith", "Hancock", "Clarke"]


def test_next_match_is_vale_away():
    nxt = parse_next_match(WALSALL_PAYLOAD)
    assert nxt["opponent"] == "Port Vale"
    assert nxt["is_home"] is True
    vale_next = parse_next_match(VALE_PAYLOAD)
    assert vale_next["opponent"] == "Walsall"
    assert vale_next["is_home"] is False


def test_apply_overlay_on_cached_report(monkeypatch):
    monkeypatch.setattr(
        "app.pre_match_fotmob.fetch_club_payload",
        lambda _name: WALSALL_PAYLOAD,
    )
    report = apply_fotmob_live_overlay(
        {
            "opponent": {"name": "Walsall"},
            "season": "26/27",
            "two_match": {
                "matches": [
                    {
                        "date": "2026-09-01T18:45:00+00:00",
                        "opponent": "Crewe Alexandra",
                        "score": "2-2",
                    },
                    {
                        "date": "2026-09-05T14:00:00+00:00",
                        "opponent": "Exeter City",
                        "score": "0-0",
                        "xg_for": 0.4,
                    },
                ],
                "last_xi": [{"name": "Leak"}],
                "stat_leaders": [],
            },
            "form": [
                {"date": "2026-09-05T14:00:00+00:00", "opponent": "Exeter City", "result": "D"}
            ],
            "fixture": {
                "opponent": {"name": "Walsall"},
                "port_vale": {"name": "Port Vale"},
                "is_home": True,
            },
        }
    )
    opponents = [row["opponent"] for row in report["two_match"]["matches"]]
    assert opponents == ["Exeter City", "Rochdale"]
    assert report["two_match"]["last_xi"][0]["short_name"] == "Ward"
    assert any(row.get("opponent") == "Rochdale" for row in report["form"])
    assert report["fixture"]["is_home"] is False
    assert report["fixture"]["scheduled_date"] == "2026-09-19T11:30:00.000Z"


def test_pick_next_fixture_prefers_fotmob_walsall(monkeypatch):
    monkeypatch.setattr(
        "app.pre_match_fotmob.fetch_fotmob_team_payload",
        lambda _team_id: VALE_PAYLOAD,
    )
    fixtures = [
        {
            "match_id": 1,
            "scheduled_date": "2026-09-05T14:00:00+00:00",
            "played": True,
            "opponent": {"id": 10, "name": "Exeter City"},
        },
        {
            "match_id": 2,
            "scheduled_date": "2026-09-19T11:30:00+00:00",
            "played": False,
            "opponent": {"id": 20, "name": "Walsall"},
        },
    ]
    picked = pick_fotmob_next_fixture(fixtures)
    assert picked["opponent"]["name"] == "Walsall"
    assert _pick_next_fixture(fixtures)["opponent"]["name"] == "Walsall"


def test_vale_fixtures_overlay_adds_missing_next(monkeypatch):
    monkeypatch.setattr(
        "app.pre_match_fotmob.fetch_fotmob_team_payload",
        lambda _team_id: VALE_PAYLOAD,
    )
    monkeypatch.setattr(
        "app.pre_match._squads_map",
        lambda _iteration_id: {20: {"id": 20, "name": "Walsall", "imageUrl": None}},
    )
    monkeypatch.setattr(
        "app.pre_match._enrich_team_crest",
        lambda team, _iteration_id: team,
    )
    rows = overlay_fotmob_vale_fixtures(
        [
            {
                "match_id": 1,
                "scheduled_date": "2026-09-05T14:00:00+00:00",
                "played": False,
                "opponent": {"id": 10, "name": "Exeter City"},
            }
        ],
        2120,
    )
    names = [row["opponent"]["name"] for row in rows]
    assert "Walsall" in names
    exeter = next(row for row in rows if row["opponent"]["name"] == "Exeter City")
    assert exeter["played"] is True
    assert exeter["kickoff_label"] == "1-0"
