from app.scouting_monthly_report import (
    POTM_DEFAULT_LEAGUES,
    _compact_panels_per_page,
    _rank_by_profile,
    _rank_overall,
)


def test_potm_default_leagues_include_all_scouting_competitions():
    assert "League One" in POTM_DEFAULT_LEAGUES
    assert "League Two" in POTM_DEFAULT_LEAGUES
    assert "National League" in POTM_DEFAULT_LEAGUES
    assert "Scottish Prem" in POTM_DEFAULT_LEAGUES
    assert "PL2" in POTM_DEFAULT_LEAGUES
    assert "Irish Prem" in POTM_DEFAULT_LEAGUES


def test_compact_panels_per_page():
    cols, rows = _compact_panels_per_page()
    assert cols * rows >= 10


def test_rank_overall_and_by_profile():
    players = [
        {
            "name": "Alpha",
            "profileScores": {"PV_A": 80.0, "PV_B": 60.0},
        },
        {
            "name": "Beta",
            "profileScores": {"PV_A": 70.0, "PV_B": 90.0},
        },
        {
            "name": "Gamma",
            "profileScores": {"PV_A": None, "PV_B": 50.0},
        },
    ]

    # Overall is the equal-weighted average across profiles, so Beta (80) leads
    # Alpha (70) even though Alpha is ahead on the first profile. This assertion
    # used to read ["Alpha", "Beta"], which is the ordering you get from ranking
    # on one profile rather than the average.
    overall = _rank_overall(players, 2)
    assert [row["name"] for row in overall] == ["Beta", "Alpha"]
    assert [round(row["overall"], 1) for row in overall] == [80.0, 70.0]

    # Gamma has one profile score and still ranks, on the profiles he has.
    assert [row["name"] for row in _rank_overall(players, 3)][-1] == "Gamma"

    by_a = _rank_by_profile(players, "PV_A", 2)
    assert [row["name"] for row in by_a] == ["Alpha", "Beta"]

    by_b = _rank_by_profile(players, "PV_B", 2)
    assert [row["name"] for row in by_b] == ["Beta", "Alpha"]


def test_overall_matches_the_rest_of_the_hub():
    """One definition of Overall, or tools quietly disagree about a player."""
    from app.home_dashboard import _overall_from_profile_scores
    from app.scouting_monthly_report import _overall_score

    for scores in (
        {"PV_A": 80.0, "PV_B": 60.0},
        {"PV_A": None, "PV_B": 50.0},
        {"PV_A": 71.3, "PV_B": 64.8, "PV_C": 55.1},
        {},
    ):
        assert _overall_score(scores) == _overall_from_profile_scores(scores)
