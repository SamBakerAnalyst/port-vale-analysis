"""Games to Watch — rank fixtures by young, high-scoring players."""

from __future__ import annotations

from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS, required_sidebar_titles
from app.games_to_watch import (
    U27_MAX_AGE,
    adjust_profile_for_league,
    apply_league_relative_watch,
    combine_side_scores,
    score_fixture_players,
    score_side,
    youth_weight,
)
from app.paths import STANDALONE_DIR


def _player(name: str, *, age: int, overall: float, minutes: int = 900, club: str = "Club") -> dict:
    return {
        "player_id": abs(hash(name)) % 100000,
        "name": name,
        "age": age,
        "overall": overall,
        "minutes": minutes,
        "club": club,
        "u27": age <= U27_MAX_AGE,
        "watch_value": round(overall * youth_weight(age), 1),
    }


def test_games_to_watch_is_a_recruitment_rail_tool():
    titles = required_sidebar_titles()
    assert "Games to Watch" in titles
    row = next(app for app in APPS if app["id"] == "games-to-watch")
    assert row["href"] == "/games-to-watch"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is not False
    assert "scouts" in tuple(row["roles"])
    assert row["router"] == "games_to_watch"
    assert "/api/games-to-watch" in tuple(row["api_prefixes"])
    assert row["id"] in LIVE_ESSENTIAL_IDS


def test_page_is_a_ranked_list_with_team_sheet_and_planner_assign():
    html = (STANDALONE_DIR / "games-to-watch.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "games-to-watch.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "games-to-watch.js").read_text(encoding="utf-8")
    assert "Games to Watch" in html
    assert 'id="gwList"' in html
    assert 'id="gwSheet"' in html
    assert 'id="gwLeagues"' in html
    assert 'id="gwRecency"' in html
    assert "Haven't watched recently" in html
    assert "assign Video into Fixture Planner" in html
    assert 'data-phase="played"' in html
    assert 'id="gwPhase"' in html
    assert 'id="gwLook"' in html
    assert 'data-look="scores"' in html
    assert 'data-look="both"' in html
    assert 'data-look="young"' in html
    assert "High scores" in html
    assert ">Both<" in html
    assert "Young players" in html
    assert "gw-filter--league" in html
    assert "Ranked by high scores" in html
    assert "This season" in html
    assert 'data-window="all"' in html
    assert "U27s (26 and under)" in html
    assert "pct >= 70" in js
    assert "pct >= 40" in js
    assert "/api/games-to-watch" in js
    assert "game.played" in js
    assert 'phase: "played"' in js
    assert 'look: "scores"' in js
    assert "score_pct" in js
    assert "young_pct" in js
    assert "both_pct" in js
    assert "score_mix_pct" in js
    assert "both_mix_pct" in js
    assert "mixingLeagues" in js
    assert 'look === "both"' in js
    assert "Math.abs(days)" in js
    assert "/api/games-to-watch/assign" in js
    assert "/api/games-to-watch/fixture" in js
    assert "/api/games-to-watch/watched" in js
    assert "Mark watched" in js
    assert "staleGames" in js
    assert "last_watched_at" in js
    assert "renderRecency" in js
    assert "/player-reports?fixture=" in js
    assert "Player Reports →" in js
    assert "VIDEO" in js
    assert "watch_pct" in js
    assert "is-loan" in js
    assert "is-moved" in js
    assert "annotate_all" in (
        STANDALONE_DIR.parent / "app" / "games_to_watch.py"
    ).read_text(encoding="utf-8")
    assert ".gw-row" in css
    assert ".gw-filter--league" in css
    assert ".gw-recency" in css
    assert ".gw-mark-watched" in css
    assert ".gw-team" in css
    assert "tr.is-loan" in css
    assert "tr.is-moved" in css
    assert "html2canvas" not in js


def test_youth_weight_puts_u27s_ahead_of_veterans():
    assert youth_weight(19) == 1.0
    assert youth_weight(23) == 0.90
    assert youth_weight(26) == 0.78
    assert youth_weight(27) < youth_weight(26)
    assert youth_weight(32) == 0.08
    assert youth_weight(None) < youth_weight(21)


def test_young_high_scorers_rank_near_100():
    home = [_player(f"Kid {i}", age=20, overall=95, minutes=900) for i in range(11)]
    away = [_player(f"Prospect {i}", age=21, overall=92, minutes=800) for i in range(11)]
    ranked = score_fixture_players(home, away)
    assert ranked is not None
    assert ranked["watch_pct"] >= 80
    assert ranked["u27_count"] == 22
    assert ranked["youth_pct"] == 100


def test_old_poor_profiles_rank_near_0():
    home = [_player(f"Vet {i}", age=33, overall=18, minutes=900) for i in range(11)]
    away = [_player(f"Old {i}", age=34, overall=12, minutes=800) for i in range(11)]
    ranked = score_fixture_players(home, away)
    assert ranked is not None
    assert ranked["watch_pct"] <= 15
    assert ranked["u27_count"] == 0
    assert ranked["youth_pct"] == 0


def test_mid_scoring_u21s_do_not_auto_rank_as_must_watch():
    """PL2-style: everyone is U21 but profiles sit around 50–55."""
    home = [_player(f"Kid {i}", age=19, overall=54, minutes=400) for i in range(11)]
    away = [_player(f"Boy {i}", age=20, overall=52, minutes=400) for i in range(11)]
    ranked = score_fixture_players(home, away)
    assert ranked is not None
    assert ranked["youth_pct"] == 100
    assert 45 <= ranked["watch_pct"] <= 60


def test_high_scoring_u23s_beat_mid_scoring_academy():
    academy = score_fixture_players(
        [_player(f"Kid {i}", age=19, overall=53, minutes=400) for i in range(11)],
        [_player(f"Boy {i}", age=20, overall=51, minutes=400) for i in range(11)],
        league="PL2",
    )
    senior = score_fixture_players(
        [_player(f"Irish {i}", age=22, overall=70, minutes=900) for i in range(11)],
        [_player(f"Vale {i}", age=23, overall=68, minutes=800) for i in range(11)],
        league="Irish Prem",
    )
    assert academy is not None and senior is not None
    assert senior["watch_pct"] > academy["watch_pct"] + 8


def test_pl2_percentiles_are_pulled_toward_senior_level():
    assert adjust_profile_for_league(70, league="League One", club_n=28) == 70
    pulled = adjust_profile_for_league(70, league="PL2", club_n=16)
    assert 48 <= pulled <= 58
    assert pulled < 65
    assert adjust_profile_for_league(70, league="Premier League Cup", club_n=16) < 65


def test_league_relative_lets_top_efl_sit_with_top_irish():
    rows = [
        {"league": "Irish Prem", "watch_pct": 58},
        {"league": "Irish Prem", "watch_pct": 52},
        {"league": "Irish Prem", "watch_pct": 44},
        {"league": "League One", "watch_pct": 50},
        {"league": "League One", "watch_pct": 46},
        {"league": "League One", "watch_pct": 40},
        {"league": "PL2", "watch_pct": 48},
        {"league": "PL2", "watch_pct": 40},
    ]
    apply_league_relative_watch(rows)
    irish_top = next(row for row in rows if row["watch_raw"] == 58)
    l1_top = next(row for row in rows if row["watch_raw"] == 50)
    irish_mid = next(row for row in rows if row["watch_raw"] == 52)
    pl2_top = next(row for row in rows if row["league"] == "PL2" and row["watch_raw"] == 48)
    assert irish_top["watch_pct"] >= 75
    assert l1_top["watch_pct"] >= 75
    assert abs(irish_top["watch_pct"] - l1_top["watch_pct"]) <= 5
    assert irish_mid["watch_pct"] < l1_top["watch_pct"]
    assert pl2_top["watch_pct"] < irish_top["watch_pct"]
    assert pl2_top["watch_pct"] < 90


def test_same_raw_scores_rank_pl2_below_league_one():
    xi = [_player(f"P{i}", age=21, overall=70, minutes=800) for i in range(14)]
    senior = score_fixture_players(xi, xi, league="League One")
    academy = score_fixture_players(xi, xi, league="PL2")
    assert senior is not None and academy is not None
    assert senior["watch_pct"] > academy["watch_pct"] + 8


def test_young_high_scores_beat_old_high_scores():
    young = score_side([_player("Kid", age=21, overall=88, minutes=900) for _ in range(11)])
    old = score_side([_player("Vet", age=32, overall=88, minutes=900) for _ in range(11)])
    assert young is not None and old is not None
    assert young["watch_pct"] > old["watch_pct"] + 40


def test_equal_team_weight_stops_a_big_squad_swamping_the_other_side():
    home = [_player("Star", age=20, overall=99, minutes=900, club="Home")]
    away = [_player(f"Pad {i}", age=34, overall=10, minutes=900, club="Away") for i in range(14)]
    ranked = combine_side_scores(score_side(home), score_side(away))
    assert ranked is not None
    # One excellent U21 XI-proxy vs a poor veteran squad should sit in the middle, not at 0.
    assert 40 <= ranked["watch_pct"] <= 60


def test_gone_players_do_not_headline_the_game():
    from app import transfer_status as ts

    home = [_player("Gbemi Arubi", age=22, overall=90, minutes=1800, club="Dundalk")]
    home[0]["transfer"] = {"status": ts.GONE, "club": "Burton Albion"}
    home.extend(
        [_player(f"Lily {i}", age=22, overall=55, minutes=800, club="Dundalk") for i in range(10)]
    )
    away = [_player(f"Away {i}", age=22, overall=50, minutes=800, club="Away") for i in range(11)]
    ranked = score_fixture_players(home, away)
    assert ranked is not None
    assert "Gbemi Arubi" not in [row["name"] for row in ranked["headlines"]]


def test_headlines_are_the_young_high_scorers():
    home = [
        _player("Young Star", age=21, overall=91, minutes=900, club="Home"),
        _player("Old Starter", age=32, overall=94, minutes=900, club="Home"),
    ]
    away = [_player("U23", age=22, overall=80, minutes=700, club="Away")]
    ranked = score_fixture_players(home, away)
    assert ranked is not None
    names = [row["name"] for row in ranked["headlines"]]
    assert "Young Star" in names
    assert "Old Starter" not in names
    score_names = [row["name"] for row in ranked["score_headlines"]]
    assert "Old Starter" in score_names
    assert "Young Star" in score_names


def test_high_scores_and_young_players_are_separate_ranks():
    rows = [
        {"league": "League Two", "watch_pct": 70, "quality_pct": 82, "youth_pct": 10},
        {"league": "League Two", "watch_pct": 55, "quality_pct": 50, "youth_pct": 95},
        {"league": "League Two", "watch_pct": 60, "quality_pct": 66, "youth_pct": 40},
    ]
    apply_league_relative_watch(rows)
    high = next(row for row in rows if row["quality_pct"] == 82)
    young = next(row for row in rows if row["youth_pct"] == 95)
    assert high["score_pct"] > young["score_pct"]
    assert young["young_pct"] > high["young_pct"]


def test_both_ranks_games_that_are_strong_on_scores_and_youth():
    rows = [
        {"league": "League Two", "watch_pct": 80, "quality_pct": 90, "youth_pct": 8},
        {"league": "League Two", "watch_pct": 45, "quality_pct": 42, "youth_pct": 96},
        {"league": "League Two", "watch_pct": 72, "quality_pct": 78, "youth_pct": 80},
        {"league": "League Two", "watch_pct": 50, "quality_pct": 55, "youth_pct": 30},
        {"league": "League Two", "watch_pct": 48, "quality_pct": 50, "youth_pct": 35},
        {"league": "League Two", "watch_pct": 52, "quality_pct": 58, "youth_pct": 40},
    ]
    apply_league_relative_watch(rows)
    high = next(row for row in rows if row["quality_pct"] == 90)
    young = next(row for row in rows if row["youth_pct"] == 96)
    both = next(row for row in rows if row["quality_pct"] == 78)
    assert both["both_pct"] > high["both_pct"]
    assert both["both_pct"] > young["both_pct"]
    assert both["both_pct"] == int(round((both["score_pct"] + both["young_pct"]) / 2))


def test_all_leagues_depth_stops_irish_flooding_the_top():
    rows = []
    for i in range(20):
        rows.append(
            {
                "league": "Irish Prem",
                "watch_pct": 80 - i,
                "quality_pct": 80 - i,
                "youth_pct": 70,
                "date": f"2026-03-{i + 1:02d}",
            }
        )
    for i in range(8):
        rows.append(
            {
                "league": "League Two",
                "watch_pct": 70 - i,
                "quality_pct": 70 - i,
                "youth_pct": 60,
                "date": f"2026-08-{i + 1:02d}",
            }
        )
    apply_league_relative_watch(rows)
    top12 = sorted(
        rows, key=lambda row: -(row.get("score_mix_pct") if row.get("score_mix_pct") is not None else -1)
    )[:12]
    irish_top = sum(1 for row in top12 if row["league"] == "Irish Prem")
    assert irish_top <= 7
    assert irish_top < 12
    irish = sorted(
        [row for row in rows if row["league"] == "Irish Prem"],
        key=lambda row: -(row["score_pct"] or 0),
    )
    l2 = sorted(
        [row for row in rows if row["league"] == "League Two"],
        key=lambda row: -(row["score_pct"] or 0),
    )
    assert irish[0]["score_mix_pct"] == irish[0]["score_pct"]
    assert irish[10]["score_mix_pct"] < l2[1]["score_mix_pct"]
    assert irish[10]["score_mix_pct"] < irish[10]["score_pct"]


def test_payload_puts_the_young_high_scoring_game_first(monkeypatch):
    from app import games_to_watch as gtw

    fixtures = [
        {
            "fixture_id": "old-game",
            "date": "2026-09-12",
            "league": "League Two",
            "home": {"name": "Old FC"},
            "away": {"name": "Ancient FC"},
        },
        {
            "fixture_id": "young-game",
            "date": "2026-09-12",
            "league": "League Two",
            "home": {"name": "Kids FC"},
            "away": {"name": "Youth FC"},
        },
    ]
    players: list[dict] = []
    for i in range(11):
        players.extend(
            [
                {
                    "playerId": i,
                    "name": f"Kid {i}",
                    "age": 20,
                    "overall": 90,
                    "minutes": 800,
                    "club": "Kids FC",
                },
                {
                    "playerId": 100 + i,
                    "name": f"Youth {i}",
                    "age": 21,
                    "overall": 88,
                    "minutes": 800,
                    "club": "Youth FC",
                },
                {
                    "playerId": 200 + i,
                    "name": f"Vet {i}",
                    "age": 33,
                    "overall": 20,
                    "minutes": 800,
                    "club": "Old FC",
                },
                {
                    "playerId": 300 + i,
                    "name": f"Ancient {i}",
                    "age": 34,
                    "overall": 15,
                    "minutes": 800,
                    "club": "Ancient FC",
                },
            ]
        )

    monkeypatch.setattr(gtw, "_watchable_fixtures", lambda season: fixtures)
    monkeypatch.setattr(
        gtw,
        "_load_player_index",
        lambda: (gtw._index_players_by_club(players), {"building": False}),
    )
    monkeypatch.setattr(gtw, "get_fixture_assignments", lambda: {"assignments": {}})

    payload = gtw.build_games_to_watch_payload()
    assert payload["games"][0]["fixture_id"] == "young-game"
    assert payload["games"][0]["score_pct"] > payload["games"][1]["score_pct"]
    assert payload["games"][0]["watch_pct"] > payload["games"][1]["watch_pct"]
    assert payload["games"][0]["watch_pct"] >= 75
    assert payload["games"][1]["watch_pct"] <= 30
    assert payload["scoring"]["notes"]["scores"]
    assert payload["scoring"]["notes"]["young"]
    assert payload["scoring"]["notes"]["both"]
    assert any(league["id"] == "League Two" for league in payload["leagues"])


def test_payload_splits_veteran_quality_from_young_minutes(monkeypatch):
    from app import games_to_watch as gtw

    fixtures = [
        {
            "fixture_id": "vet-quality",
            "date": "2026-09-12",
            "league": "League Two",
            "home": {"name": "Vets FC"},
            "away": {"name": "Seniors FC"},
        },
        {
            "fixture_id": "young-minutes",
            "date": "2026-09-12",
            "league": "League Two",
            "home": {"name": "Kids FC"},
            "away": {"name": "Youth FC"},
        },
    ]
    players: list[dict] = []
    for i in range(11):
        players.extend(
            [
                {
                    "playerId": i,
                    "name": f"Kid {i}",
                    "age": 20,
                    "overall": 48,
                    "minutes": 800,
                    "club": "Kids FC",
                },
                {
                    "playerId": 100 + i,
                    "name": f"Youth {i}",
                    "age": 21,
                    "overall": 46,
                    "minutes": 800,
                    "club": "Youth FC",
                },
                {
                    "playerId": 200 + i,
                    "name": f"Vet {i}",
                    "age": 32,
                    "overall": 78,
                    "minutes": 800,
                    "club": "Vets FC",
                },
                {
                    "playerId": 300 + i,
                    "name": f"Senior {i}",
                    "age": 31,
                    "overall": 76,
                    "minutes": 800,
                    "club": "Seniors FC",
                },
            ]
        )

    monkeypatch.setattr(gtw, "_watchable_fixtures", lambda season: fixtures)
    monkeypatch.setattr(
        gtw,
        "_load_player_index",
        lambda: (gtw._index_players_by_club(players), {"building": False}),
    )
    monkeypatch.setattr(gtw, "get_fixture_assignments", lambda: {"assignments": {}})

    payload = gtw.build_games_to_watch_payload()
    by_id = {row["fixture_id"]: row for row in payload["games"]}
    assert by_id["vet-quality"]["score_pct"] > by_id["young-minutes"]["score_pct"]
    assert by_id["young-minutes"]["young_pct"] > by_id["vet-quality"]["young_pct"]
    assert payload["games"][0]["fixture_id"] == "vet-quality"


def test_watchable_fixtures_include_the_whole_season_tape(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app import games_to_watch as gtw

    today = datetime.now(UTC).date()
    played_date = (today - timedelta(days=5)).isoformat()
    future_date = (today + timedelta(days=3)).isoformat()
    irish_early = "2026-02-14"
    too_far = (today + timedelta(days=60)).isoformat()
    monkeypatch.setattr(
        gtw,
        "build_fixture_planner_payload",
        lambda season: {
            "fixtures": [
                {
                    "fixture_id": "played",
                    "date": played_date,
                    "status": "completed",
                    "score": "2-1",
                    "league": "League Two",
                    "home": {"name": "Walsall"},
                    "away": {"name": "Rochdale"},
                },
                {
                    "fixture_id": "soon",
                    "date": future_date,
                    "status": "scheduled",
                    "league": "League Two",
                    "home": {"name": "Crewe"},
                    "away": {"name": "Stockport"},
                },
                {
                    "fixture_id": "irish-early",
                    "date": irish_early,
                    "status": "completed",
                    "score": "1-0",
                    "league": "Irish Prem",
                    "home": {"name": "Bohemian FC"},
                    "away": {"name": "Sligo Rovers"},
                },
                {
                    "fixture_id": "far",
                    "date": too_far,
                    "status": "scheduled",
                    "league": "Irish Prem",
                    "home": {"name": "Derry City"},
                    "away": {"name": "Shamrock Rovers"},
                },
            ]
        },
    )
    rows = gtw._watchable_fixtures("26/27")
    ids = {row["fixture_id"] for row in rows}
    assert "played" in ids
    assert "soon" in ids
    assert "irish-early" in ids
    assert "far" not in ids

    monkeypatch.setattr(gtw, "_load_player_index", lambda: ({}, {"building": False}))
    monkeypatch.setattr(gtw, "get_fixture_assignments", lambda: {"assignments": {}})
    payload = gtw.build_games_to_watch_payload()
    by_id = {row["fixture_id"]: row for row in payload["games"]}
    assert by_id["played"]["played"] is True
    assert by_id["played"]["score"] == "2-1"
    assert by_id["irish-early"]["played"] is True
    assert by_id["soon"]["played"] is False
    assert "far" not in by_id
    assert payload["played_count"] == 2
    assert payload["upcoming_count"] == 1


def test_club_aliases_match_man_city_u21_to_manchester_city_u21():
    from app.games_to_watch import _club_lookup_keys, _index_players_by_club, players_for_club

    players = [
        {
            "playerId": 1,
            "name": "Kid",
            "age": 19,
            "overall": 70,
            "minutes": 400,
            "club": "Man City U21",
        }
    ]
    index = _index_players_by_club(players)
    found = players_for_club("Manchester City U21", index)
    assert found and found[0]["name"] == "Kid"
    assert "manchestercityu21" in _club_lookup_keys("Man City U21")
    assert "manchestercityu21" in _club_lookup_keys("Manchester City U21")


def test_bohemian_fc_matches_impect_bohemian_football_club():
    from app.games_to_watch import _club_lookup_keys, _index_players_by_club, players_for_club

    players = [
        {
            "playerId": 9,
            "name": "Sadou Diallo",
            "age": 26,
            "overall": 62,
            "minutes": 900,
            "club": "Bohemian Football Club",
        }
    ]
    index = _index_players_by_club(players)
    found = players_for_club("Bohemian FC", index)
    assert found and found[0]["name"] == "Sadou Diallo"
    assert "bohemianfootballclub" in _club_lookup_keys("Bohemian FC")
    assert "bohemianfootballclub" in _club_lookup_keys("Bohemian Football Club")


def test_match_sheet_is_only_starters_and_players_who_came_on():
    from app.games_to_watch import players_from_match_squad

    squad = {
        "startingFormation": "4-2-3-1",
        "players": [
            {"id": 1, "shirtNumber": 1},
            {"id": 2, "shirtNumber": 10},
            {"id": 99, "shirtNumber": 7},
        ],
        "startingPositions": [
            {"playerId": 1, "position": "GOALKEEPER"},
            {"playerId": 2, "position": "CENTER_FORWARD"},
        ],
        "substitutions": [
            {
                "substitutionType": "SUB_ON",
                "playerId": 3,
                "toPosition": "LEFT_WINGER",
                "gameTime": {"gameTime": "54:00"},
            },
            {"substitutionType": "SUB_OFF", "playerId": 2, "exchangedPlayerId": 3},
        ],
    }
    names = {
        1: "Jack Byecroft",
        2: "Josh Gordon",
        3: "Ethan Brierley",
        99: "Jayden Wareham",
    }
    players, formation = players_from_match_squad(
        squad,
        club="Exeter City",
        names=names,
        profiles={99: {"name": "Jayden Wareham", "overall": 57, "club": "Exeter City"}},
    )
    assert formation == "4-2-3-1"
    assert {row["name"] for row in players} == {"Jack Byecroft", "Josh Gordon", "Ethan Brierley"}
    assert all(row["name"] != "Jayden Wareham" for row in players)
    assert next(row for row in players if row["player_id"] == 1)["started"] is True
    assert next(row for row in players if row["player_id"] == 3)["subbed_on"] is True
    assert next(row for row in players if row["player_id"] == 3)["match_minute"] == 54


def test_upcoming_fixture_sheet_does_not_dump_a_club_squad(monkeypatch):
    from app import games_to_watch as gtw

    monkeypatch.setattr(
        gtw,
        "_watchable_fixtures",
        lambda season: [
            {
                "fixture_id": "future",
                "date": "2026-10-01",
                "status": "scheduled",
                "league": "League Two",
                "home": {"name": "Exeter City", "id": 1},
                "away": {"name": "Port Vale", "id": 2},
            }
        ],
    )
    monkeypatch.setattr(gtw, "_load_player_index", lambda: ({}, {"building": False}))
    monkeypatch.setattr(gtw, "get_fixture_assignments", lambda: {"assignments": {}})
    monkeypatch.setattr(gtw, "build_fixture_planner_payload", lambda season: {"fixtures": []})

    def boom(*_args, **_kwargs):
        raise AssertionError("must not fall back to a club squad")

    monkeypatch.setattr(gtw, "_sheet_players", boom)
    sheet = gtw.build_fixture_sheet(season="26/27", fixture_id="future")
    assert sheet["home"]["players"] == []
    assert sheet["away"]["players"] == []
    assert sheet["home"]["lineup_status"] == "upcoming"


def test_cached_games_do_not_block_first_open(monkeypatch):
    import threading
    import time

    from app import games_to_watch as gtw

    gtw._games_payload_mem.clear()
    gtw._games_refreshing.clear()
    stuck = threading.Event()

    def never_finishes(*, season="26/27"):
        stuck.wait(2)
        return {"season": season, "games": [], "building": False}

    monkeypatch.setattr(gtw, "read_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(gtw, "write_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(gtw, "build_games_to_watch_payload", never_finishes)
    started = time.time()
    payload = gtw.cached_games_to_watch_payload(season="26/27")
    assert time.time() - started < 0.5
    assert payload["building"] is True
    assert payload["games"] == []
    stuck.set()


def test_assign_game_writes_video_into_fixture_planner(monkeypatch):
    from app import games_to_watch as gtw
    from app.games_to_watch import AssignBody

    captured: dict = {}

    def fake_upsert(body, **_kwargs):
        captured["body"] = body
        return {
            "assignments": {
                "game-1": {
                    "staff": ["Sam Baker"],
                    "watch_type": "VIDEO",
                    "watched_players": body.watched_players,
                }
            }
        }

    monkeypatch.setattr(gtw, "upsert_fixture_assignment", fake_upsert)
    result = gtw.assign_game(
        AssignBody(
            fixture_id="game-1",
            staff=["Sam Baker"],
            watch_type="VIDEO",
            home="Kids FC",
            away="Youth FC",
            watched_players=[{"player_id": 1, "player_name": "Kid 0"}],
        )
    )
    assert result["ok"] is True
    assert captured["body"].watch_type == "VIDEO"
    assert captured["body"].fixture_id == "game-1"
    assert result["assignment"]["watch_type"] == "VIDEO"


def test_mark_fixture_watched_persists_last_watched_at(tmp_path, monkeypatch):
    from app import games_to_watch as gtw
    from app.games_to_watch import MarkWatchedBody

    watched_path = tmp_path / "watched.json"
    monkeypatch.setattr(gtw, "WATCHED_PATH", watched_path)
    monkeypatch.setattr(gtw, "GAMES_TO_WATCH_DATA_DIR", tmp_path)
    monkeypatch.setattr(gtw, "ensure_data_dirs", lambda: None)

    marked = gtw.mark_fixture_watched(
        MarkWatchedBody(
            fixture_id="fx-stale-1",
            home="Kids FC",
            away="Youth FC",
            league="League One",
            date="2026-09-01",
        )
    )
    assert marked["ok"] is True
    assert marked["fixture_id"] == "fx-stale-1"
    assert marked["last_watched_at"]
    assert watched_path.is_file()

    store = gtw.get_watched_marks()
    assert store["recent_days"] == gtw.RECENT_WATCHED_DAYS
    assert store["watched"]["fx-stale-1"]["last_watched_at"] == marked["last_watched_at"]
    assert store["watched"]["fx-stale-1"]["home"] == "Kids FC"

    rows = [
        {"fixture_id": "fx-stale-1", "home": {"name": "Kids FC"}},
        {"fixture_id": "fx-never", "home": {"name": "Other FC"}},
    ]
    gtw._attach_watched_marks(rows)
    assert rows[0]["last_watched_at"] == marked["last_watched_at"]
    assert rows[1]["last_watched_at"] is None

    cleared = gtw.mark_fixture_watched(
        MarkWatchedBody(fixture_id="fx-stale-1", clear=True)
    )
    assert cleared["last_watched_at"] is None
    assert "fx-stale-1" not in gtw.get_watched_marks()["watched"]


def test_cached_payload_refreshes_watched_marks(monkeypatch):
    from app import games_to_watch as gtw

    monkeypatch.setattr(
        gtw,
        "_games_payload_mem",
        {
            "26/27": (
                __import__("time").time(),
                {
                    "season": "26/27",
                    "games": [
                        {"fixture_id": "a", "last_watched_at": None},
                        {"fixture_id": "b", "last_watched_at": None},
                    ],
                },
            )
        },
    )
    monkeypatch.setattr(
        gtw,
        "get_watched_marks",
        lambda: {
            "watched": {"a": {"last_watched_at": "2026-09-01T12:00:00+00:00"}},
            "updated_at": "2026-09-01T12:00:00+00:00",
            "recent_days": gtw.RECENT_WATCHED_DAYS,
        },
    )
    payload = gtw.cached_games_to_watch_payload(season="26/27")
    assert payload["recent_watched_days"] == gtw.RECENT_WATCHED_DAYS
    by_id = {row["fixture_id"]: row for row in payload["games"]}
    assert by_id["a"]["last_watched_at"] == "2026-09-01T12:00:00+00:00"
    assert by_id["b"]["last_watched_at"] is None
