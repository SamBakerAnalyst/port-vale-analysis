"""Squad Availability matrix groups and public status facts for 26/27."""

from __future__ import annotations

from datetime import date

from app.availability_squad import (
    CLUB_FIRST_TEAM_26_27,
    apply_public_match_facts,
    canonical_roster_key,
    injury_badge,
    position_group_for_name,
    reconcile_26_27_roster,
)
from app.availability_tracker import _effective_entry
from app.squad_photos import _parse_club_squad_roster_page


SCREENSHOT_ROSTER = [
    ("Jasper Moon", "MID"),
    ("George Byers", "MID"),
    ("Ben Garrity", "MID"),
    ("Kyle Dempsey", "MID"),
    ("Ryan Croasdale", "MID"),
    ("Jack Shorrock", "MID"),
    ("Matthew Craig", "MID"),
    ("Charlie Bussell", "MID"),
    ("Ben Waine", "MID"),
    ("Jaheim Headley", "ATT"),
    ("Onel Hernández", "ATT"),
    ("George Hall", "ATT"),
    ("Rhys Anthony Walters", "ATT"),
    ("Mo Faal", "ATT"),
    ("Oliver Lynch", "ATT"),
    ("Max Watters", "ATT"),
    ("Tyreece Simpson", "ATT"),
]


def _roster(rows: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "id": f"p-{index}",
            "name": name,
            "position_group": group,
            "sort_order": index,
            "active": True,
        }
        for index, (name, group) in enumerate(rows)
    ]


def _names(roster: list[dict]) -> list[str]:
    return [str(player["name"]) for player in roster if player.get("active", True) is not False]


def test_club_snapshot_matches_requested_groups():
    groups = {row["name"]: row["position_group"] for row in CLUB_FIRST_TEAM_26_27}
    assert groups["Jaheim Headley"] == "DEF"
    assert groups["Jasper Moon"] == "DEF"
    assert groups["Rhys Walters"] == "MID"
    assert groups["George Hall"] == "MID"
    assert groups["Onel Hernández"] == "MID"
    assert groups["Ben Waine"] == "ATT"
    for name in (
        "George Byers",
        "Ben Garrity",
        "Kyle Dempsey",
        "Ryan Croasdale",
        "Jack Shorrock",
        "Matty Craig",
        "Charlie Bussell",
    ):
        assert groups[name] == "MID"
    for name in ("Mo Faal", "Oliver Lynch", "Max Watters", "Tyreece Simpson"):
        assert groups[name] == "ATT"
    assert groups["Maleace Asamoah"] == "MID"
    assert groups["Keyrol Figueroa"] == "ATT"
    assert groups["Liam Gordon"] == "DEF"
    assert groups["Jackson Smith"] == "GK"
    assert groups["Marko Maroši"] == "GK"
    assert "Keaton Moseley" not in groups


def test_impect_wingers_stay_attack_while_club_lists_hernandez_midfield():
    from app.availability_tracker import IMPECT_POSITION_TO_GROUP

    assert IMPECT_POSITION_TO_GROUP["LEFT_WINGER"] == "ATT"
    assert IMPECT_POSITION_TO_GROUP["RIGHT_WINGER"] == "ATT"
    assert position_group_for_name("Onel Hernández") == "MID"


def test_reconcile_moves_screenshot_players_and_adds_missing_squad():
    roster = _roster(SCREENSHOT_ROSTER)
    store: dict = {"roster": {"26/27": roster}}
    assert reconcile_26_27_roster(store, roster) is True

    by_name = {player["name"]: player for player in roster}
    assert by_name["Jaheim Headley"]["position_group"] == "DEF"
    assert by_name["Jasper Moon"]["position_group"] == "DEF"
    assert by_name["Rhys Anthony Walters"]["position_group"] == "MID"
    assert by_name["George Hall"]["position_group"] == "MID"
    assert by_name["Onel Hernández"]["position_group"] == "MID"
    assert by_name["Ben Waine"]["position_group"] == "ATT"
    assert by_name["Matthew Craig"]["position_group"] == "MID"
    assert by_name["Charlie Bussell"]["position_group"] == "MID"

    names = _names(roster)
    assert names.count("Rhys Anthony Walters") == 1
    assert "Rhys Walters" not in names
    assert names.count("Matthew Craig") == 1
    assert "Matty Craig" not in names
    for name in (
        "Maleace Asamoah",
        "Keyrol Figueroa",
        "Liam Gordon",
        "Kyle John",
        "Connor Hall",
        "Jordan Gabriel",
        "Lewis Montsma",
        "Cameron Humphreys",
        "Aaron McGowan",
        "Jackson Smith",
        "Marko Maroši",
        "Joe Williams",
    ):
        assert name in names
    assert "Keaton Moseley" not in names
    assert by_name["Maleace Asamoah"]["highlight"] == "loan_in"
    assert by_name["Keyrol Figueroa"]["highlight"] == "loan_in"
    assert by_name["Keyrol Figueroa"]["position_group"] == "ATT"
    assert by_name["Liam Gordon"]["position_group"] == "DEF"
    assert canonical_roster_key("Rhys Anthony Walters") == canonical_roster_key("Rhys Walters")


def test_public_standing_facts_and_do_not_repeat():
    roster = _roster(SCREENSHOT_ROSTER)
    store: dict = {"roster": {"26/27": roster}}
    reconcile_26_27_roster(store, roster)
    injuries = store["injuries"]["26/27"]
    by_name = {player["name"]: player for player in roster}

    shorrock = injuries[by_name["Jack Shorrock"]["id"]]
    assert shorrock["status"] == "LOAN"
    assert shorrock["since"] == "2026-07-28"
    assert "Sligo Rovers" in shorrock["notes"]
    assert shorrock["away_from_club"] is False

    faal = injuries[by_name["Mo Faal"]["id"]]
    assert faal["status"] == "INJ"
    assert faal["since"] == "2026-08-23"
    assert faal["return_date"] == "2026-12-31"
    assert faal["away_from_club"] is False
    assert "end of 2026" in faal["notes"]

    waine = injuries[by_name["Ben Waine"]["id"]]
    assert waine["status"] == "INT"
    assert waine["since"] == "2026-09-21"
    assert waine["ended_at"] == "2026-10-04"
    assert "New Zealand" in waine["notes"]

    simpson = injuries[by_name["Tyreece Simpson"]["id"]]
    assert simpson["status"] == "INT"
    assert "Saint Kitts" in simpson["notes"]
    assert "Fitness rebuilding" in simpson["notes"]

    gordon = injuries[by_name["Liam Gordon"]["id"]]
    assert gordon["status"] == "INT"
    assert "Guyana" in gordon["notes"]

    figueroa = injuries[by_name["Keyrol Figueroa"]["id"]]
    assert figueroa["status"] == "INT"
    assert "Honduras" in figueroa["notes"]

    smith = injuries[by_name["Jackson Smith"]["id"]]
    assert smith["status"] == "INJ"
    assert smith["since"] == "2026-09-19"
    assert smith["ended_at"] == "2026-09-19"
    assert "concussion" in smith["notes"].casefold()
    assert injury_badge(smith, today=date(2026, 9, 22)) is None
    assert injury_badge(waine, today=date(2026, 9, 22)) is not None

    assert by_name["Charlie Bussell"]["id"] not in injuries

    faal["return_date"] = "2026-09-01"
    faal["notes"] = "Staff note"
    assert reconcile_26_27_roster(store, roster) is False
    assert injuries[by_name["Mo Faal"]["id"]]["return_date"] == "2026-09-01"
    assert injuries[by_name["Mo Faal"]["id"]]["notes"] == "Staff note"
    assert _names(roster).count("Jaheim Headley") == 1


def test_walters_unused_matches_stay_n_not_int():
    roster = _roster([("Rhys Anthony Walters", "MID")])
    player_id = roster[0]["id"]
    sessions = [
        {
            "id": "salford",
            "type": "match",
            "date": "2026-09-05",
            "label": "Salford City (A)",
            "opponent": "Salford City",
            "match_id": 101,
            "complete": True,
            "entries": {player_id: {"status": "INT"}},
        },
        {
            "id": "exeter",
            "type": "match",
            "date": "2026-09-12",
            "label": "Exeter (H)",
            "opponent": "Exeter City",
            "match_id": 102,
            "complete": True,
            "entries": {player_id: {"status": "INJ"}},
        },
    ]
    store: dict = {"sessions": {"26/27": []}}
    assert apply_public_match_facts(store, roster, sessions) is True
    assert sessions[0]["entries"][player_id]["status"] == "N"
    assert sessions[1]["entries"][player_id]["status"] == "N"

    salford = _effective_entry(
        player_id=player_id,
        session=sessions[0],
        manual_entries=sessions[0]["entries"],
        injuries={},
        play_minutes=0,
        has_player_identity=True,
    )
    exeter = _effective_entry(
        player_id=player_id,
        session=sessions[1],
        manual_entries=sessions[1]["entries"],
        injuries={},
        play_minutes=None,
        has_player_identity=True,
    )
    assert salford["status"] == "N"
    assert exeter["status"] == "N"

    played = _effective_entry(
        player_id=player_id,
        session=sessions[0],
        manual_entries={player_id: {"status": "N"}},
        injuries={},
        play_minutes=63,
        has_player_identity=True,
    )
    assert played["status"] == "63"
    assert apply_public_match_facts(store, roster, sessions) is False


def test_int_shows_in_window_and_not_on_earlier_unused_games():
    session = {"id": "future", "type": "match", "date": "2026-09-26", "complete": False}
    injury = {
        "status": "INT",
        "since": "2026-09-21",
        "ended_at": "2026-10-04",
        "notes": "New Zealand",
    }
    upcoming = _effective_entry(
        player_id="p-waine",
        session=session,
        manual_entries={},
        injuries={"p-waine": injury},
        play_minutes=None,
        has_player_identity=True,
    )
    assert upcoming["status"] == "INT"

    walsall = _effective_entry(
        player_id="p-waine",
        session={"id": "walsall", "type": "match", "date": "2026-09-19", "complete": True},
        manual_entries={},
        injuries={"p-waine": injury},
        play_minutes=61,
        has_player_identity=True,
    )
    assert walsall["status"] == "61"

    earlier_unused = _effective_entry(
        player_id="p-simpson",
        session={"id": "exeter", "type": "match", "date": "2026-09-12", "complete": True},
        manual_entries={},
        injuries={"p-simpson": injury},
        play_minutes=0,
        has_player_identity=True,
    )
    assert earlier_unused["status"] == "N"


def test_smith_concussion_marks_walsall_only():
    injury = {
        "status": "INJ",
        "since": "2026-09-19",
        "ended_at": "2026-09-19",
        "notes": "Concussion protocol — missed Walsall (19 Sep).",
    }
    walsall = _effective_entry(
        player_id="p-smith",
        session={"id": "walsall", "type": "match", "date": "2026-09-19", "complete": True},
        manual_entries={},
        injuries={"p-smith": injury},
        play_minutes=0,
        has_player_identity=True,
    )
    assert walsall["status"] == "INJ"

    later = _effective_entry(
        player_id="p-smith",
        session={"id": "next", "type": "match", "date": "2026-09-26", "complete": False},
        manual_entries={},
        injuries={"p-smith": injury},
        play_minutes=None,
        has_player_identity=True,
    )
    assert later["status"] == "AVAIL"


def test_bussell_unused_is_n_without_a_loan_or_injury():
    cell = _effective_entry(
        player_id="p-bussell",
        session={"id": "m", "type": "match", "date": "2026-09-19", "complete": True},
        manual_entries={},
        injuries={},
        play_minutes=0,
        has_player_identity=True,
    )
    assert cell["status"] == "N"


def test_section_heading_is_the_nearest_one_not_a_nav_mention():
    html = """
    <nav>Goalkeepers Defenders Midfielders Attackers</nav>
    <div class="o-players__list">
      <h2 class="o-players__list-heading">Defenders </h2>
      <div class="views-row o-players__list-item">
        <a href="/player/3"></a>
        <div class="m-playercard__name--first"><div class="field__item">Jaheim</div></div>
        <div class="m-playercard__name--last"><div class="field__item">Headley</div></div>
      </div>
    </div>
    <div class="o-players__list">
      <h2 class="o-players__list-heading">Midfielders </h2>
      <div class="views-row o-players__list-item">
        <a href="/player/11"></a>
        <div class="m-playercard__name--first"><div class="field__item">Onel</div></div>
        <div class="m-playercard__name--last"><div class="field__item">Hernández</div></div>
      </div>
    </div>
    <div class="o-players__list">
      <h2 class="o-players__list-heading">Attackers </h2>
      <div class="views-row o-players__list-item">
        <a href="/player/19"></a>
        <div class="m-playercard__name--first"><div class="field__item">Ben</div></div>
        <div class="m-playercard__name--last"><div class="field__item">Waine</div></div>
      </div>
    </div>
    """
    players = _parse_club_squad_roster_page(html, squad_url="https://www.port-vale.co.uk/squad/70")
    groups = {row["name"]: row["position_group"] for row in players}
    assert groups == {
        "Jaheim Headley": "DEF",
        "Onel Hernández": "MID",
        "Ben Waine": "ATT",
    }


def test_matrix_keeps_group_labels_pinned_under_the_header():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "static/availability-tracker.js").read_text(encoding="utf-8")
    css = (root / "static/availability-tracker.css").read_text(encoding="utf-8")
    assert "av-group-row" in js
    assert "head.getBoundingClientRect().height" in js
    assert "position: sticky" in css
    assert ".av-group-row td" in css
