"""Transfer Centre — recruitment market board + nested transfer reports."""

from __future__ import annotations

from app.apps_manifest import APPS, required_sidebar_titles
from app.efl_transfer_report import load_report
from app.paths import STANDALONE_DIR
from app.transfer_centre import (
    FLAG_IDS,
    INTEREST_IDS,
    add_incoming_note,
    apply_incoming_patch,
    build_market_board,
    clean_report_name,
    incoming_row_id,
    label_to_board_position,
    merge_position_suggestions,
    transfer_reports,
)


def test_transfer_centre_is_a_recruitment_rail_tool():
    titles = required_sidebar_titles()
    assert "Transfer Centre" in titles
    row = next(app for app in APPS if app["id"] == "transfer-centre")
    assert row["href"] == "/transfer-centre"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is not False
    assert "scouts" in tuple(row["roles"])
    assert row["router"] == "transfer_centre"


def test_transfer_centre_html_has_board_and_reports():
    html = (STANDALONE_DIR / "transfer-centre.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "transfer-centre.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "transfer-centre.js").read_text(encoding="utf-8")
    assert "Transfer Centre" in html
    assert "Market board" in html
    assert "Reports" in html
    assert 'id="tcBoard"' in html
    assert 'id="tcReports"' in html
    assert 'id="tcDrawer"' in html
    assert "Save note" in html
    assert "/api/transfer-centre" in js
    assert "/notes" in js
    assert "manager_liked" in js
    assert "recruitment_liked" in js
    assert '"Yes"' in js
    assert '"No"' in js
    assert "tc-name" in js
    assert "clear_name" in js
    assert "clear_position" in js
    assert "Filled automatically" in js
    assert "positions_pending" in js
    assert "data-field=\"interest\"" in js
    assert "not_interested" in js
    assert "unrealistic" in js
    assert "is-out" in js
    assert "✓" not in js
    assert ".tc-table" in css
    assert ".tc-row.is-out" in css
    assert "html2canvas" not in js


def test_market_board_lists_incomings_only_grouped_by_club():
    report = load_report()
    board = build_market_board(report, {"version": 1, "players": {}}, suggestions={})
    leagues = {league["id"]: league for league in board["leagues"]}
    assert set(leagues) == {"league-one", "league-two", "national-league", "scottish-prem"}
    vale = next(team for team in leagues["league-two"]["teams"] if team["id"] == "port-vale")
    names = {row["player"] for row in vale["incomings"]}
    assert "Aaron McGowan" in names
    assert "Kyle Dempsey" in names
    assert "Jayden Stockley" not in names
    assert all(row["flags"]["manager_liked"] is False for row in vale["incomings"])
    assert all(row["interest"] == "" for row in vale["incomings"])
    assert all(row["is_out"] is False for row in vale["incomings"])
    assert INTEREST_IDS == ("interested", "not_interested", "unrealistic", "released_by_us")
    assert board["totals"]["teams"] == 84
    assert board["totals"]["incomings"] > 400
    assert set(board["flags"][0]) >= {"id", "label", "short", "color"}
    assert FLAG_IDS == (
        "manager_liked",
        "recruitment_liked",
        "too_expensive_transfer",
        "too_expensive_wages",
        "player_turned_down",
    )


def test_ticks_and_position_age_persist_when_the_report_refreshes():
    report = load_report()
    seen: dict[str, int] = {}
    player_id = incoming_row_id("port-vale", "Aaron McGowan", "Tranmere Rovers", "free", seen)
    store = {"version": 1, "players": {}}
    apply_incoming_patch(
        store,
        player_id,
        flags={"manager_liked": True, "too_expensive_wages": True},
        position="RB",
        age=28,
        staff="Sam Baker",
    )
    board = build_market_board(report, store, suggestions={})
    vale = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
    )
    aaron = next(row for row in vale["incomings"] if row["player"] == "Aaron McGowan")
    assert aaron["id"] == player_id
    assert aaron["position"] == "RB"
    assert aaron["age"] == 28
    assert aaron["flags"]["manager_liked"] is True
    assert aaron["flags"]["too_expensive_wages"] is True
    assert aaron["flags"]["recruitment_liked"] is False
    assert aaron["updated_by"] == "Sam Baker"
    dempsey = next(row for row in vale["incomings"] if row["player"] == "Kyle Dempsey")
    assert dempsey["flags"]["manager_liked"] is False
    assert dempsey["position"] == ""
    assert board["totals"]["manager_liked"] >= 1


def test_notes_stay_on_the_player_when_flags_change():
    report = load_report()
    seen: dict[str, int] = {}
    player_id = incoming_row_id("port-vale", "Aaron McGowan", "Tranmere Rovers", "free", seen)
    store = {"version": 1, "players": {}}
    add_incoming_note(store, player_id, text="Manager wants a look on video.", staff="Sam Baker")
    apply_incoming_patch(store, player_id, flags={"recruitment_liked": True}, staff="Tommy")
    board = build_market_board(report, store, suggestions={})
    vale = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
    )
    aaron = next(row for row in vale["incomings"] if row["player"] == "Aaron McGowan")
    assert aaron["note_count"] == 1
    assert aaron["notes"][0]["text"] == "Manager wants a look on video."
    assert aaron["notes"][0]["author"] == "Sam Baker"
    assert aaron["flags"]["recruitment_liked"] is True


def test_impect_suggestions_fill_name_and_position_but_staff_can_override():
    report = load_report()
    seen: dict[str, int] = {}
    player_id = incoming_row_id(
        "afc-wimbledon",
        "Steve Seddon re-signing for the new season",
        "Released",
        "released",
        seen,
    )
    store = {"version": 1, "players": {}}
    suggestions = {
        "steveseddon": {"name": "Steve Seddon", "position": "LB", "age": 28, "impect_id": 1, "club_keys": set()},
        "jaydenstockley": {"name": "Jayden Stockley", "position": "ST", "age": 32, "impect_id": 2, "club_keys": set()},
    }
    board = build_market_board(report, store, suggestions=suggestions)
    wimbledon = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
    )
    seddon = next(row for row in wimbledon["incomings"] if "Seddon" in row["player"])
    assert clean_report_name("Steve Seddon re-signing for the new season") == "Steve Seddon"
    assert seddon["player"] == "Steve Seddon"
    assert seddon["position"] == "LB"
    assert seddon["age"] == 28
    assert seddon["name_source"] == "impect"
    assert seddon["position_source"] == "api"
    apply_incoming_patch(store, player_id, name="Steven Seddon", position="LWB", age=29, staff="Sam Baker")
    board = build_market_board(report, store, suggestions=suggestions)
    wimbledon = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
    )
    seddon = next(row for row in wimbledon["incomings"] if row["id"] == player_id)
    assert seddon["player"] == "Steven Seddon"
    assert seddon["position"] == "LWB"
    assert seddon["age"] == 29
    assert seddon["name_source"] == "staff"
    assert seddon["position_source"] == "staff"


def test_api_positions_fill_but_staff_can_clear_them():
    assert label_to_board_position("Centre-Back") == "CB"
    assert label_to_board_position("Right Winger") == "RW"
    assert label_to_board_position("Centre-Forward") == "ST"
    assert label_to_board_position("CENTER_FORWARD") == "ST"
    assert label_to_board_position("Left-Back") == "LB"
    report = load_report()
    suggestions = {
        "jamestilley": {
            "name": "James Tilley",
            "position": "",
            "age": 28,
            "impect_id": 9,
            "club_keys": set(),
        }
    }
    merge_position_suggestions(
        suggestions,
        {"jamestilley": {"name": "James Tilley", "position": "Right Winger"}},
    )
    assert suggestions["jamestilley"]["position"] == "RW"
    board = build_market_board(report, {"version": 1, "players": {}}, suggestions=suggestions)
    wimbledon = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
    )
    tilley = next(row for row in wimbledon["incomings"] if row["player"] == "James Tilley")
    assert tilley["position"] == "RW"
    assert tilley["position_source"] == "api"
    assert tilley["age"] == 28
    suggestions["josefbursik"] = {
        "name": "Josef Bursik",
        "position": "GK",
        "age": 25,
        "impect_id": 11,
        "club_keys": set(),
    }
    board = build_market_board(report, {"version": 1, "players": {}}, suggestions=suggestions)
    bursik = [
        row
        for league in board["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
        for row in team["incomings"]
        if "Bursik" in row["player"] or "Bursik" in row["source_name"]
    ]
    assert len(bursik) == 1
    assert bursik[0]["position"] == "GK"
    apply_incoming_patch(store := {"version": 1, "players": {}}, tilley["id"], position="AM", staff="Sam Baker")
    board = build_market_board(report, store, suggestions=suggestions)
    tilley = next(
        row
        for league in board["leagues"]
        if league["id"] == "league-one"
        for team in league["teams"]
        if team["id"] == "afc-wimbledon"
        for row in team["incomings"]
        if row["id"] == tilley["id"]
    )
    assert tilley["position"] == "AM"
    assert tilley["position_source"] == "staff"


def test_interest_marks_players_out_until_staff_want_them():
    report = load_report()
    seen: dict[str, int] = {}
    player_id = incoming_row_id("port-vale", "Aaron McGowan", "Tranmere Rovers", "free", seen)
    store = {"version": 1, "players": {}}
    apply_incoming_patch(store, player_id, interest="unrealistic", staff="Sam Baker")
    board = build_market_board(report, store, suggestions={})
    vale = next(
        team
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
    )
    aaron = next(row for row in vale["incomings"] if row["id"] == player_id)
    assert aaron["interest"] == "unrealistic"
    assert aaron["is_out"] is True
    apply_incoming_patch(store, player_id, interest="not_interested", staff="Sam Baker")
    board = build_market_board(report, store, suggestions={})
    aaron = next(
        row
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
        for row in team["incomings"]
        if row["id"] == player_id
    )
    assert aaron["interest"] == "not_interested"
    assert aaron["is_out"] is True
    apply_incoming_patch(store, player_id, flags={"manager_liked": True}, staff="Tommy")
    board = build_market_board(report, store, suggestions={})
    aaron = next(
        row
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
        for row in team["incomings"]
        if row["id"] == player_id
    )
    assert aaron["interest"] == "not_interested"
    assert aaron["flags"]["manager_liked"] is True
    apply_incoming_patch(store, player_id, interest="interested", staff="Sam Baker")
    board = build_market_board(report, store, suggestions={})
    aaron = next(
        row
        for league in board["leagues"]
        if league["id"] == "league-two"
        for team in league["teams"]
        if team["id"] == "port-vale"
        for row in team["incomings"]
        if row["id"] == player_id
    )
    assert aaron["interest"] == "interested"
    assert aaron["is_out"] is False
    assert board["interest_options"][0]["id"] == "interested"
    assert board["totals"]["interest_interested"] >= 1


def test_our_own_departures_can_be_marked_as_ours():
    """The board lists every club's signings, so our outgoings are on it too.

    Jayden Stockley signing for Wimbledon sits under Wimbledon, from Port Vale.
    Marking that "not interested" would be wrong twice over: it was our sale,
    and it says we looked at a player we had already sold.
    """
    from app.transfer_centre import OUT_INTEREST

    report = load_report()
    seen: dict[str, int] = {}
    player_id = incoming_row_id("afc-wimbledon", "Jayden Stockley", "Port Vale", "undisclosed", seen)
    store = {"version": 1, "players": {}}

    apply_incoming_patch(store, player_id, interest="released_by_us", staff="Sam Baker")
    board = build_market_board(report, store, suggestions={})
    row = next(
        row
        for league in board["leagues"]
        for team in league["teams"]
        for row in team["incomings"]
        if row["id"] == player_id
    )

    assert row["interest"] == "released_by_us"
    assert row["is_out"] is True, "settled business, so off the live list"
    assert board["totals"]["interest_released_by_us"] == 1
    assert "released_by_us" in OUT_INTEREST


def test_the_out_set_is_derived_from_the_options():
    """Kept in one place, so the board and the browser cannot drift apart."""
    from app.transfer_centre import INTEREST_OPTIONS, OUT_INTEREST

    assert OUT_INTEREST == {row["id"] for row in INTEREST_OPTIONS if row["out"]}
    assert all("out" in row for row in INTEREST_OPTIONS), "the browser reads this"


def test_a_typed_or_echoed_interest_label_still_lands():
    """Clients echo the label back, and people spell "transferred" both ways."""
    from app.transfer_centre import _clean_interest

    assert _clean_interest("Released / transferred by us") == "released_by_us"
    assert _clean_interest("released_by_us") == "released_by_us"
    assert _clean_interest("transfered by us") == "released_by_us"
    assert _clean_interest("Not interested") == "not_interested"
    assert _clean_interest("nonsense") == ""


def test_reports_dashboard_lists_the_efl_deck():
    reports = transfer_reports(load_report())
    assert reports[0]["id"] == "efl-transfer-report"
    assert reports[0]["href"] == "/efl-transfer-report"
    assert "EFL Transfer Report" in reports[0]["title"]
    assert "incomings" in reports[0]["meta"]
