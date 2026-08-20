from app.club_strategy import _is_league_match


def test_league_match_accepts_numbered_matchday():
    match = {"matchDay": {"name": "1", "index": 1}}
    assert _is_league_match(match, "League Two") is True


def test_league_match_accepts_competition_label():
    match = {"matchDay": {"name": "League Two", "index": 1}}
    assert _is_league_match(match, "League Two") is True


def test_league_match_rejects_playoffs_and_cups():
    assert _is_league_match({"matchDay": {"name": "Play-Off Semi"}}, "League Two") is False
    assert _is_league_match({"matchDay": {"name": "EFL Cup"}}, "League Two") is False
