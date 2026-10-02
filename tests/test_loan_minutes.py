"""Shared loan minutes: one club, one season, the same numbers on every page."""

from __future__ import annotations

import json

from app.club_identity import canonical_club_id, same_club
from app.loans_watch import build_loans_watch
from app.player_minutes import (
    aggregate_player_minutes,
    apply_scoped_minutes,
    attach_scoped_totals,
    same_player_name,
)
from app import transfer_status as ts


def _report(*teams: dict) -> dict:
    return {
        "season": "2026/27",
        "leagues": [
            {
                "id": "league-two",
                "name": "League Two",
                "teams": list(teams) or [{"id": "host-town", "name": "Host Town", "signed": []}],
            }
        ],
    }


def _team(name: str, team_id: str | None = None) -> dict:
    return {
        "id": team_id or name.lower().replace(" ", "-"),
        "name": name,
        "signed": [],
    }


def _stat(
    *,
    name: str,
    club: str,
    minutes: int,
    position: str,
    player_id: int,
    season: str = "26/27",
    match_count: int | None = None,
    starts: int | None = None,
    overall: float = 60.0,
    age: int = 20,
    competition: str = "100",
    transfer: dict | None = None,
) -> dict:
    row = {
        "name": name,
        "club": club,
        "minutes": minutes,
        "position": position,
        "positionLabel": position,
        "playerId": player_id,
        "season": season,
        "overall": overall,
        "age": age,
        "id": f"{competition}:{player_id}",
        "competitionId": competition,
    }
    if match_count is not None:
        row["matchCount"] = match_count
    if starts is not None:
        row["starts"] = starts
    if transfer is not None:
        row["transfer"] = transfer
    return row


def _loans(snapshot, players, teams=None):
    return build_loans_watch(
        report=_report(*(teams or [_team("Host Town")])),
        snapshot=snapshot,
        players=players,
    )


def _only(board, name: str) -> dict:
    hits = [row for row in board["loans"] if row["player"] == name]
    assert len(hits) == 1, hits
    return hits[0]


def test_same_player_name_accepts_short_forms_and_rejects_a_shared_surname():
    assert same_player_name("Nick Quarrel", "Nicholas Quarrel")
    assert same_player_name("Ollie Quarrel", "Oliver Quarrel")
    assert same_player_name("Ruiri Quarrel", "Ruari Quarrel")
    assert not same_player_name("Joe Keep", "Reggie Keep")


def test_place_tag_and_legal_suffix_share_an_id_but_a_distinguisher_does_not():
    assert same_club("Y Glasgow", "Y")
    assert same_club("Glasgow Y", "Y")
    assert canonical_club_id("X United FC") == canonical_club_id("X United")
    assert not same_club("X United FC", "X")
    assert not same_club("Northtown", "Northtown United")
    assert not same_club("Northtown", "Northtown United FC")


def test_parent_rows_are_left_out_of_the_loan_club_total():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=80, position="CM", player_id=11, match_count=2, starts=1),
        _stat(
            name="Quentin Quarrel",
            club="Parent Athletic U21",
            minutes=400,
            position="CM",
            player_id=11,
            competition="pl2",
            transfer={"status": "loan_out", "from": "Parent Athletic", "club": "Host Town"},
        ),
    ]
    board = _loans(
        {"Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}]},
        players,
    )
    row = _only(board, "Quentin Quarrel")
    assert row["minutes"] == 80
    assert row["profile_minutes"] == 80
    assert row["parent_minutes"] == 400
    assert row["profile_minutes"] <= row["minutes"]


def test_parent_only_rows_do_not_become_the_loan_minutes():
    players = [
        _stat(
            name="Quentin Quarrel",
            club="Parent Athletic U21",
            minutes=400,
            position="ST",
            player_id=12,
            transfer={"status": "loan_out", "from": "Parent Athletic", "club": "Host Town"},
        )
    ]
    board = _loans(
        {"Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}]},
        players,
    )
    row = _only(board, "Quentin Quarrel")
    assert row["minutes"] is None
    assert row["profile_minutes"] is None
    assert row["overall"] is None


def test_two_calendar_years_at_one_club_are_not_summed():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=100, position="CM", player_id=13, season="2025", competition="old"),
        _stat(name="Quentin Quarrel", club="Host Town", minutes=200, position="CM", player_id=13, season="2026", competition="new"),
    ]
    summary = aggregate_player_minutes(players, "Host Town")
    assert summary["total"] is None


def test_a_previous_clubs_calendar_season_is_not_added():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=110, position="W", player_id=13, season="26/27"),
        _stat(
            name="Quentin Quarrel",
            club="Previous Rovers",
            minutes=300,
            position="W",
            player_id=13,
            season="2026",
            competition="irish",
        ),
    ]
    summary = aggregate_player_minutes(players, "Host Town", "26/27")
    assert summary["total"] == 110
    board = _loans(
        {"Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}]},
        players,
    )
    assert _only(board, "Quentin Quarrel")["minutes"] == 110


def test_listed_position_is_the_top_one_at_the_loan_club():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=40, position="AM", player_id=14, overall=70),
        _stat(name="Quentin Quarrel", club="Host Town", minutes=90, position="CM", player_id=14, overall=50, competition="101"),
        _stat(name="Quentin Quarrel", club="Host Town", minutes=30, position="CM", player_id=14, overall=48, competition="102"),
        _stat(
            name="Quentin Quarrel",
            club="Parent Athletic",
            minutes=500,
            position="ST",
            player_id=14,
            competition="parent",
            transfer={"status": "loan_out", "from": "Parent Athletic", "club": "Host Town"},
        ),
    ]
    summary = aggregate_player_minutes(players, "Host Town")
    assert summary["position"] == "CM"
    assert summary["profile_minutes"] == 120
    assert summary["total"] == 160
    assert 0 <= summary["profile_minutes"] <= summary["total"]
    assert sum(item["minutes"] for item in summary["by_position"] if item["position"] == "CM") == 120
    board = _loans(
        {"Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}]},
        players,
    )
    row = _only(board, "Quentin Quarrel")
    assert row["position"] == "CM"
    assert row["profile_minutes"] == 120
    assert row["minutes"] == 160


def test_league_and_cup_rows_at_the_loan_club_are_summed():
    players = [
        _stat(
            name="Quentin Quarrel",
            club="Host Town",
            minutes=300,
            position="CM",
            player_id=15,
            match_count=8,
            starts=8,
            competition="league",
        ),
        _stat(
            name="Quentin Quarrel",
            club="Host Town",
            minutes=90,
            position="CM",
            player_id=15,
            match_count=2,
            starts=1,
            competition="cup",
        ),
        _stat(
            name="Quentin Quarrel",
            club="Host Town",
            minutes=27,
            position="AM",
            player_id=15,
            match_count=1,
            starts=0,
            competition="cup",
        ),
    ]
    summary = aggregate_player_minutes(players, "Host Town")
    assert summary["total"] == 417
    assert summary["profile_minutes"] == 390
    assert summary["appearances"] == 10
    assert summary["starts"] == 9
    assert summary["appearances_estimated"] is False
    assert summary["starts_estimated"] is False


def test_missing_appearance_counts_are_marked_estimated():
    summary = aggregate_player_minutes(
        [_stat(name="Quentin Quarrel", club="Host Town", minutes=200, position="ST", player_id=16)],
        "Host Town",
    )
    assert summary["appearances_estimated"] is True
    assert summary["starts_estimated"] is True
    js = open("static/loans-watch.js", encoding="utf-8").read()
    assert "est." in js


def test_alias_pairs_resolve_to_one_loan_row():
    players = [
        _stat(name="Pia Place", club="Y Glasgow", minutes=240, position="CB", player_id=21, match_count=4, starts=3),
        _stat(name="Uma United", club="X United FC", minutes=180, position="ST", player_id=22, match_count=3, starts=2),
    ]
    board = _loans(
        {
            "Y": [{"name": "Pia Place", "from": "Parent Athletic"}],
            "Y Glasgow": [{"name": "Pia Place", "from": "Parent Athletic"}],
            "X": [{"name": "Uma United", "from": "Parent Athletic"}],
            "X United": [{"name": "Uma United", "from": "Parent Athletic"}],
            "X United FC": [{"name": "Uma United", "from": "Parent Athletic"}],
        },
        players,
        teams=[_team("Y"), _team("X United"), _team("X")],
    )
    pia = [row for row in board["loans"] if row["player"] == "Pia Place"]
    uma = [row for row in board["loans"] if row["player"] == "Uma United"]
    assert len(pia) == 1
    assert pia[0]["minutes"] == 240
    assert canonical_club_id(pia[0]["club"]) == canonical_club_id("Y")
    assert len(uma) == 1
    assert uma[0]["minutes"] == 180
    assert canonical_club_id(uma[0]["club"]) == canonical_club_id("X United")


def test_colliding_ids_do_not_share_one_players_minutes():
    players = [
        _stat(name="Joe Keep", club="Host Town", minutes=40, position="GK", player_id=7, age=30),
        _stat(name="Reggie Keep", club="Host Town", minutes=90, position="CM", player_id=7, age=21, competition="101"),
    ]
    board = _loans(
        {
            "Host Town": [
                {"name": "Joe Keep", "from": "Parent Athletic"},
                {"name": "Reggie Keep", "from": "Other Athletic"},
            ]
        },
        players,
    )
    joe = _only(board, "Joe Keep")
    reggie = _only(board, "Reggie Keep")
    assert joe["minutes"] == 40
    assert reggie["minutes"] == 90
    assert not joe["player_id"]
    assert not reggie["player_id"]
    assert joe["player_id"] != 7 or reggie["player_id"] != 7


def test_name_variants_with_one_id_are_one_row():
    players = [
        _stat(
            name="Nicholas Quarrel",
            club="Host Town",
            minutes=180,
            position="CB",
            player_id=5,
            age=19,
            transfer={"status": "loan_in", "from": "Parent Athletic", "club": "Host Town"},
        )
    ]
    board = _loans(
        {
            "Host Town": [
                {"name": "Nick Quarrel", "from": "Parent Athletic"},
                {"name": "Nicholas Quarrel", "from": "Parent Athletic"},
            ]
        },
        players,
    )
    row = _only(board, "Nick Quarrel") if any(r["player"] == "Nick Quarrel" for r in board["loans"]) else _only(board, "Nicholas Quarrel")
    assert sum(1 for r in board["loans"] if "Quarrel" in r["player"]) == 1
    assert row["minutes"] == 180
    assert row["player_id"] == 5


def test_loans_watch_who_to_scout_and_watch_list_agree():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=200, position="CM", player_id=31, match_count=4, starts=3),
        _stat(
            name="Quentin Quarrel",
            club="Host Town",
            minutes=50,
            position="AM",
            player_id=31,
            match_count=1,
            starts=0,
            competition="cup",
        ),
        _stat(
            name="Quentin Quarrel",
            club="Parent Athletic U21",
            minutes=900,
            position="CM",
            player_id=31,
            competition="pl2",
            transfer={"status": "loan_out", "from": "Parent Athletic", "club": "Host Town"},
        ),
    ]
    summary = aggregate_player_minutes(players, "Host Town")
    board = _loans(
        {"Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}]},
        players,
    )
    loan = _only(board, "Quentin Quarrel")
    pool = [dict(row) for row in players]
    attach_scoped_totals(pool)
    scout = next(row for row in pool if row["club"] == "Host Town" and row["position"] == "CM")
    target = {
        "player_id": 31,
        "name": "Quentin Quarrel",
        "club": "Host Town",
        "position": summary["position"],
        "minutes": 1,
        "manual": False,
        "transfer": {"status": "loan_in", "from": "Parent Athletic"},
    }
    apply_scoped_minutes(target, players, feed_loaded=True)
    assert loan["minutes"] == summary["total"] == scout["total_minutes"] == target["total_minutes"]
    assert loan["profile_minutes"] == summary["profile_minutes"] == target["minutes"]
    assert scout["position_minutes"] == summary["profile_minutes"]


def test_watch_list_refresh_updates_a_loanee_and_flags_a_club_with_no_rows():
    target = {
        "player_id": 41,
        "name": "Quentin Quarrel",
        "club": "Host Town",
        "position": "CM",
        "minutes": 64,
        "total_minutes": 64,
        "manual": False,
        "transfer": {"status": "loan_in", "from": "Parent Athletic"},
        "stats_updated_at": "2020-01-01T00:00:00+00:00",
    }
    first = [_stat(name="Quentin Quarrel", club="Host Town", minutes=64, position="CM", player_id=41)]
    apply_scoped_minutes(target, first, feed_loaded=True)
    assert target["minutes"] == 64
    assert target["total_minutes"] == 64
    second = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=300, position="CM", player_id=41),
        _stat(
            name="Quentin Quarrel",
            club="Host Town",
            minutes=117,
            position="AM",
            player_id=41,
            competition="cup",
        ),
    ]
    apply_scoped_minutes(target, second, feed_loaded=True)
    assert target["minutes"] == 300
    assert target["total_minutes"] == 417
    assert target["stats_club_missing"] is False
    assert target["stats_updated_at"] != "2020-01-01T00:00:00+00:00"

    stale = {
        "player_id": 42,
        "name": "Absent Quarrel",
        "club": "Host Town",
        "position": "ST",
        "minutes": 500,
        "manual": False,
        "transfer": {"status": "loan_in", "from": "Parent Athletic"},
    }
    apply_scoped_minutes(stale, second, feed_loaded=True)
    assert stale["minutes"] is None
    assert stale["total_minutes"] is None
    assert stale["stats_club_missing"] is True


def test_every_loan_row_keeps_profile_minutes_inside_the_total_and_ids_unique():
    players = [
        _stat(name="Quentin Quarrel", club="Host Town", minutes=80, position="CM", player_id=51),
        _stat(name="Quentin Quarrel", club="Host Town", minutes=20, position="AM", player_id=51, competition="cup"),
        _stat(name="Pia Place", club="Y Glasgow", minutes=10, position="CB", player_id=52),
        _stat(
            name="Quentin Quarrel",
            club="Parent Athletic U21",
            minutes=600,
            position="ST",
            player_id=51,
            competition="pl2",
            transfer={"status": "loan_out", "from": "Parent Athletic", "club": "Host Town"},
        ),
    ]
    board = _loans(
        {
            "Host Town": [{"name": "Quentin Quarrel", "from": "Parent Athletic"}],
            "Y": [{"name": "Pia Place", "from": "Parent Athletic"}],
            "Y Glasgow": [{"name": "Pia Place", "from": "Parent Athletic"}],
        },
        players,
        teams=[_team("Host Town"), _team("Y")],
    )
    seen: set[tuple] = set()
    assert board["loans"]
    for row in board["loans"]:
        minutes = row["minutes"]
        profile = row["profile_minutes"]
        if minutes is not None and profile is not None:
            assert 0 <= profile <= minutes
        player_id = row.get("player_id")
        if player_id:
            key = (player_id, canonical_club_id(row["club"]))
            assert key not in seen
            seen.add(key)


def test_a_mirrored_loan_departure_does_not_flip_the_direction(tmp_path, monkeypatch):
    report = {
        "updated": "2026-09-07",
        "season": "2026/27",
        "leagues": [
            {
                "name": "League One",
                "teams": [
                    {
                        "name": "Host Town",
                        "signed": [
                            {
                                "player": "Fin Example",
                                "other": "Parent Town",
                                "kind": "loan",
                                "fee": "Loan",
                            }
                        ],
                        "left": [
                            {
                                "player": "Fin Example",
                                "other": "Parent Town",
                                "kind": "loan",
                                "fee": "Loan",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "efl-transfer-report-2026.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (path,))
    ts.reset_cache()
    at_host = ts.lookup("Fin Example", "Host Town")
    at_parent = ts.lookup("Fin Example", "Parent Town")
    assert at_host["status"] == ts.LOAN_IN
    assert at_host["from"] == "Parent Town"
    assert at_parent["status"] == ts.LOAN_OUT
    assert at_parent["club"] == "Host Town"


def test_watch_list_shows_total_position_minutes_and_when_stats_were_updated():
    js = open("static/watch-list.js", encoding="utf-8").read()
    assert "total_minutes" in js
    assert "stats_updated_at" in js
    assert "stats_club_missing" in js
    assert "No current stats" in js
    assert "Pos mins" in js
