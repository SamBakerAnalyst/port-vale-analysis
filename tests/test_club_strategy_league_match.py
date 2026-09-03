from app.club_strategy import (
    _claim_fotmob_score,
    _dedupe_standings_matches,
    _is_league_match,
    _match_kickoff_passed,
    _with_fotmob_full_time,
)


def test_league_match_accepts_numbered_matchday():
    match = {"matchDay": {"name": "1", "index": 1}}
    assert _is_league_match(match, "League Two") is True


def test_league_match_accepts_competition_label():
    match = {"matchDay": {"name": "League Two", "index": 1}}
    assert _is_league_match(match, "League Two") is True


def test_league_match_rejects_playoffs_and_cups():
    assert _is_league_match({"matchDay": {"name": "Play-Off Semi"}}, "League Two") is False
    assert _is_league_match({"matchDay": {"name": "EFL Cup"}}, "League Two") is False


def test_claim_fotmob_score_matches_impect_fc_prefix_once():
    index = {
        ("tranmere rovers", "bristol rovers"): [("2026-09-01", 2, 1)],
        ("rochdale", "shrewsbury town"): [("2026-09-01", 0, 1)],
    }
    assert _claim_fotmob_score(
        index,
        home_name="Tranmere Rovers",
        away_name="Bristol Rovers",
        scheduled_date="2026-09-01T18:45:00Z",
    ) == (2, 1)
    # Same FotMob result cannot fill a second Impect gap.
    assert (
        _claim_fotmob_score(
            index,
            home_name="Tranmere Rovers",
            away_name="Bristol Rovers",
            scheduled_date="2026-09-01T18:45:00Z",
        )
        is None
    )
    assert _claim_fotmob_score(
        index,
        home_name="AFC Rochdale",
        away_name="Shrewsbury Town",
        scheduled_date="2026-09-01T18:45:00Z",
    ) == (0, 1)


def test_with_fotmob_full_time_marks_match_complete():
    filled = _with_fotmob_full_time(
        {"id": 1, "available": False, "goals": {}},
        3,
        1,
    )
    assert filled["available"] is True
    assert filled["goals"]["home"]["fullTime"] == 3
    assert filled["goals"]["away"]["fullTime"] == 1
    assert filled["_score_source"] == "fotmob"


def test_match_kickoff_passed_uses_buffer_after_kickoff():
    from datetime import UTC, datetime

    now = datetime(2026, 9, 1, 21, 0, tzinfo=UTC)
    early = {"scheduledDate": "2026-09-01T18:45:00Z"}
    assert _match_kickoff_passed(early, now=now) is True
    future = {"scheduledDate": "2026-09-05T11:30:00Z"}
    assert _match_kickoff_passed(future, now=now) is False


def test_dedupe_standings_matches_prefers_impect_over_fotmob_fill():
    squads = {1: "FC Port Vale", 2: "Swindon Town"}
    impect = {
        "id": 10,
        "homeSquadId": 2,
        "awaySquadId": 1,
        "scheduledDate": "2026-09-01T18:45:00Z",
        "goals": {"home": {"fullTime": 3}, "away": {"fullTime": 1}},
    }
    fotmob_fill = _with_fotmob_full_time(
        {
            "id": 10,
            "homeSquadId": 2,
            "awaySquadId": 1,
            "scheduledDate": "2026-09-01T18:45:00Z",
            "goals": {},
        },
        3,
        1,
    )
    rows = _dedupe_standings_matches([fotmob_fill, impect], squads)
    assert len(rows) == 1
    assert rows[0].get("_score_source") != "fotmob"
    assert rows[0]["goals"]["home"]["fullTime"] == 3


def test_dedupe_standings_matches_blocks_same_fixture_different_ids():
    squads = {1: "Tranmere Rovers", 2: "Bristol Rovers"}
    left = {
        "id": 101,
        "homeSquadId": 1,
        "awaySquadId": 2,
        "scheduledDate": "2026-09-01T18:45:00Z",
        "goals": {"home": {"fullTime": 2}, "away": {"fullTime": 1}},
    }
    right = {
        "id": 202,
        "homeSquadId": 1,
        "awaySquadId": 2,
        "scheduledDate": "2026-09-01T18:45:00Z",
        "goals": {"home": {"fullTime": 2}, "away": {"fullTime": 1}},
    }
    rows = _dedupe_standings_matches([left, right], squads)
    assert len(rows) == 1
