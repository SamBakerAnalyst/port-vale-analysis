"""Loans Watch — every club's current loanees with playing time and score."""

from __future__ import annotations

from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS, required_sidebar_titles
from app.efl_transfer_report import load_report
from app.loans_watch import (
    build_loans_watch,
    infer_matches,
    infer_starts,
    loan_playing_minutes,
    loan_position_group,
    loan_watch_score,
    playing_time,
)
from app.paths import STANDALONE_DIR
from app import transfer_status


def test_loans_watch_is_a_recruitment_rail_tool():
    titles = required_sidebar_titles()
    assert "Loans Watch" in titles
    assert "loans-watch" in LIVE_ESSENTIAL_IDS
    row = next(app for app in APPS if app["id"] == "loans-watch")
    assert row["href"] == "/loans-watch"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is not False
    assert "scouts" in tuple(row["roles"])
    assert row["router"] == "loans_watch"
    assert "/api/loans-watch" in tuple(row["api_prefixes"])


def test_page_lists_age_starts_matches_minutes_and_score():
    html = (STANDALONE_DIR / "loans-watch.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "loans-watch.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "loans-watch.js").read_text(encoding="utf-8")
    assert "Loans Watch" in html
    assert 'id="lwBoard"' in html
    assert 'data-view="club"' in html
    assert 'data-view="ranked"' in html
    assert "Starts" in html
    assert "Regulars" in html
    assert "/api/loans-watch" in js
    assert "row.starts" in js
    assert "row.matches" in js
    assert "row.minutes" in js
    assert "row.overall" in js
    assert "row.age" in js
    assert "Age" in js
    assert 'id="lwPositions"' in html
    assert 'data-position="st"' in html
    assert "row.position_group" in js
    assert 'id="lwSortDir"' in html
    assert 'data-dir="asc"' in html
    assert 'data-sort="from"' in html
    assert 'data-sort="matches"' in html
    assert "setSort" in js
    assert "sortDir" in js
    assert "sortHeader" in js
    assert 'data-sort="club"' in html
    assert ".lw-col.is-asc" in css
    assert ".lw-col.is-desc" in css
    assert ".lw-ranked .lw-table__head" in css
    assert "row.profile_minutes" in js
    assert "lw-score__mins" in js
    assert "html2canvas" not in js
    assert ".lw-row" in css
    assert ".lw-score.is-hot" in css
    assert "is-vale" in css
    assert "22rem" in css
    assert "minmax(210px, 1.5fr)" not in css


def test_infer_matches_prefers_impect_count():
    assert infer_matches(720, 8) == (8, False)
    assert infer_matches(180, None) == (2, True)
    assert infer_matches(0, None) == (None, False)


def test_infer_starts_treats_high_average_minutes_as_all_starts():
    assert infer_starts(720, 8) == (8, True)
    assert infer_starts(80, 8) == (0, True)
    starts, estimated = infer_starts(400, 8)
    assert estimated is True
    assert 2 <= starts <= 6
    assert infer_starts(720, 8, starts=7) == (7, False)


def test_position_group_maps_impect_codes_and_labels():
    assert loan_position_group("CENTER_FORWARD", "Centre-forward") == "st"
    assert loan_position_group("CF", "") == "st"
    assert loan_position_group("W", "") == "w"
    assert loan_position_group("RIGHT_WINGBACK_DEFENDER", "Right back") == "fb"
    assert loan_position_group("GOALKEEPER", "") == "gk"
    assert loan_position_group("", "Attacking midfield") == "am"
    assert loan_position_group("", "") == ""


def test_minutes_are_total_played_and_score_keeps_profile_minutes():
    total, profile = loan_playing_minutes(
        [
            {"position": "CENTER_FORWARD", "minutes": 219, "overall": 56.2},
            {"position": "LEFT_WINGER", "minutes": 410, "overall": 48.0},
        ],
        {"position": "CENTER_FORWARD", "minutes": 219, "overall": 56.2},
    )
    assert total == 629
    assert profile == 219


def test_playing_time_and_watch_score_reward_regulars():
    regular = playing_time(minutes=720, match_count=8, starts=8)
    unused = playing_time(minutes=0, match_count=0, starts=0)
    assert regular["starts"] == 8
    assert regular["matches"] == 8
    assert unused["minutes"] == 0
    hot = loan_watch_score(overall=78, minutes=720, starts=8, matches=8, age=21)
    cold = loan_watch_score(overall=78, minutes=0, starts=0, matches=0, age=21)
    assert hot is not None and cold is not None
    assert hot > cold


def test_board_lists_every_teams_loans_with_port_vale_stats():
    report = load_report()
    snapshot = transfer_status.load_loan_snapshot()
    players = [
        {
            "name": "Mo Faal",
            "club": "Port Vale",
            "league": "League Two",
            "age": 23,
            "minutes": 540,
            "matchCount": 7,
            "starts": 6,
            "overall": 71.2,
            "playerId": 922,
            "position": "CF",
            "positionLabel": "Centre-forward",
        },
        {
            "name": "Maleace Asamoah",
            "club": "Port Vale",
            "league": "League Two",
            "age": 23,
            "minutes": 210,
            "matchCount": 5,
            "starts": 2,
            "overall": 58.0,
            "playerId": 1001,
            "position": "W",
        },
        {
            "name": "Mo Faal",
            "club": "Port Vale",
            "league": "League Two",
            "age": 23,
            "minutes": 200,
            "matchCount": 4,
            "starts": 2,
            "overall": 49.0,
            "playerId": 922,
            "position": "W",
            "positionLabel": "Right winger",
        },
    ]
    board = build_loans_watch(report=report, snapshot=snapshot, players=players)
    leagues = {row["id"]: row for row in board["leagues"]}
    assert "league-two" in leagues
    vale = next(team for team in leagues["league-two"]["teams"] if team["id"] == "port-vale")
    names = {row["player"] for row in vale["loans"]}
    assert "Mo Faal" in names
    assert "Maleace Asamoah" in names
    assert "Keyrol Figueroa" in names
    assert "Mason Terry" not in names
    faal = next(row for row in vale["loans"] if row["player"] == "Mo Faal")
    assert faal["age"] == 23
    assert faal["starts"] == 6
    assert faal["matches"] == 7
    assert faal["minutes"] == 540
    assert faal["overall"] == 71.2
    assert faal["from_club"] == "Wrexham AFC"
    assert faal["dossier_href"] == "/player/922"
    assert faal["position_group"] == "st"
    asamoah = next(row for row in vale["loans"] if row["player"] == "Maleace Asamoah")
    assert asamoah["position_group"] == "w"
    assert board["totals"]["loans"] > 200
    assert board["totals"]["teams"] >= 80
    scored = [row for row in board["loans"] if row.get("overall") is not None]
    assert scored[0]["overall"] >= scored[-1]["overall"]


def test_html_entities_in_parent_club_are_cleaned():
    board = build_loans_watch(
        report={
            "season": "2026/27",
            "leagues": [
                {
                    "id": "league-one",
                    "name": "League One",
                    "teams": [{"id": "afc-wimbledon", "name": "AFC Wimbledon", "signed": []}],
                }
            ],
        },
        snapshot={
            "AFC Wimbledon": [
                {"name": "Freddie Simmonds", "from": "Brighton &amp; Hove Albion U21"}
            ]
        },
        players=[],
    )
    league = board["leagues"][0]
    player = league["teams"][0]["loans"][0]
    assert player["from_club"] == "Brighton & Hove Albion U21"
    assert "&amp;" not in player["from_club"]


def test_ended_report_loans_do_not_pad_a_club_that_has_live_tm_loans():
    board = build_loans_watch(
        report={
            "season": "2026/27",
            "leagues": [
                {
                    "id": "league-two",
                    "name": "League Two",
                    "teams": [
                        {
                            "id": "port-vale",
                            "name": "Port Vale",
                            "signed": [
                                {
                                    "player": "Mason Terry",
                                    "other": "West Ham United",
                                    "kind": "loan",
                                    "fee": "Loan",
                                },
                                {
                                    "player": "Mo Faal",
                                    "other": "Wrexham",
                                    "kind": "loan",
                                    "fee": "Loan",
                                },
                            ],
                        }
                    ],
                }
            ],
        },
        snapshot={"Port Vale": [{"name": "Mo Faal", "from": "Wrexham AFC"}]},
        players=[],
    )
    names = {row["player"] for row in board["leagues"][0]["teams"][0]["loans"]}
    assert names == {"Mo Faal"}
