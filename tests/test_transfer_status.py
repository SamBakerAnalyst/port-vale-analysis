"""A player who has already moved should not read as available.

Gbemi Arubi stayed in the Centre-forward pool as a Dundalk player after signing
for Burton Albion. These pin the matching either side of that: confirmed moves
must be caught, and a namesake must not be painted as gone.
"""

from __future__ import annotations

import json

import pytest

from app import transfer_status as ts

# Captured before the autouse fixture redirects it at a temp file.
SHIPPED_CANDIDATES = ts.TRANSFER_REPORT_CANDIDATES

REPORT = {
    "updated": "2026-09-07",
    "window": "Summer 2026 (15 June – 1/3 September)",
    "season": "2026/27",
    "leagues": [
        {
            "name": "League One",
            "teams": [
                {
                    "name": "Burton Albion",
                    "signed": [
                        {"player": "Gbemi Arubi", "other": "Dundalk", "fee": "Undisclosed"}
                    ],
                },
                {
                    "name": "Wigan Athletic",
                    "signed": [
                        {"player": "Seamus O'Ceallaigh", "other": "Bohemians", "fee": "Free"},
                        {"player": "Andy Yiadom", "other": "unattached", "fee": "Free"},
                    ],
                },
            ],
        },
        {
            "name": "League Two",
            "teams": [
                {
                    "name": "Barnet",
                    "signed": [
                        {
                            "player": "Harry Wood",
                            "other": "Hull City",
                            "kind": "undisclosed",
                            "fee": "Undisclosed",
                        }
                    ],
                },
                {
                    "name": "Rochdale",
                    "signed": [
                        {
                            "player": "Charlie Tasker",
                            "other": "Brighton & Hove Albion",
                            "kind": "loan",
                            "fee": "Loan",
                        }
                    ],
                },
                {
                    "name": "Hartlepool United",
                    "signed": [
                        {
                            "player": "Max Merrick",
                            "other": "Chelsea",
                            "kind": "loan",
                            "fee": "Loan",
                        }
                    ],
                },
            ],
        },
    ]
}


@pytest.fixture(autouse=True)
def _report(tmp_path, monkeypatch):
    path = tmp_path / "efl-transfer-report-2026.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (path,))
    ts.reset_cache()
    yield path
    ts.reset_cache()


def test_the_player_who_started_this():
    moved = ts.lookup("Gbemi Arubi", "Dundalk FC")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Burton Albion"
    assert moved["league"] == "League One"
    assert moved["from"] == "Dundalk"


def test_a_club_written_two_ways_still_matches():
    """The pool says "Dundalk FC", the report says "Dundalk"."""
    assert ts.lookup("Gbemi Arubi", "Dundalk")["status"] == ts.GONE
    assert ts.lookup("Gbemi Arubi", "Dundalk Football Club")["status"] == ts.GONE


def test_bohemian_and_bohemians_are_the_same_club():
    """Impect writes "Bohemian Football Club"; the transfer feed writes
    "Bohemians". Requiring an exact string here would miss the move."""
    moved = ts.lookup("Seamus O'Ceallaigh", "Bohemian Football Club")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Wigan Athletic"


def test_an_accent_does_not_hide_a_move():
    assert ts.lookup("Séamus O'Ceallaigh", "Bohemians") is not None


def test_a_loan_arrival_names_the_parent_club():
    """Max Merrick's case, and the reason `kind` cannot be dropped.

    The row says Hartlepool United and it is right — he plays there. But he is
    Chelsea's player, so a permanent deal is with Chelsea. Clearing the row
    silently threw away the one fact that decides whether he is signable at all.
    """
    moved = ts.lookup("Max Merrick", "Hartlepool United")
    assert moved["status"] == ts.LOAN_IN
    assert moved["from"] == "Chelsea"


def test_a_loan_is_never_reported_as_sold():
    """32 rows were shown as permanent moves when they were loans."""
    out = ts.lookup("Charlie Tasker", "Brighton & Hove Albion U21")
    assert out["status"] == ts.LOAN_OUT
    assert out["status"] != ts.GONE
    assert out["club"] == "Rochdale"


def test_loan_statuses_are_grouped_for_callers():
    """The UI colours on this set, so it has to hold both directions."""
    assert ts.LOAN_IN in ts.LOAN_STATUSES
    assert ts.LOAN_OUT in ts.LOAN_STATUSES
    assert ts.GONE not in ts.LOAN_STATUSES
    assert ts.CHECK not in ts.LOAN_STATUSES


def test_a_permanent_sale_is_still_red():
    """The loan work must not soften a real transfer."""
    assert ts.lookup("Gbemi Arubi", "Dundalk FC")["status"] == ts.GONE


def test_a_player_already_at_the_club_he_signed_for_is_not_flagged():
    """The row is right, so there is nothing to say.

    Missing this flagged 866 players on Staging. Max Merrick appeared as
    "Hartlepool United -> Hartlepool United (from Chelsea)", which is not a
    warning, it is just where he plays now. At that volume nobody reads the
    colour at all.
    """
    assert ts.lookup("Gbemi Arubi", "Burton Albion") is None
    assert ts.lookup("Harry Wood", "Barnet") is None


def test_a_player_who_moved_twice_is_caught_at_the_middle_club(_report):
    """Selling club is checked before destination, so a stop-off still flags."""
    twice = json.loads(_report.read_text())
    twice["leagues"][1]["teams"][0]["signed"].append(
        {"player": "Rory Feely", "other": "Barnet", "fee": "Undisclosed"}
    )
    twice["leagues"][0]["teams"][0]["signed"].append(
        {"player": "Rory Feely", "other": "Waterford", "fee": "Free"}
    )
    _report.write_text(json.dumps(twice), encoding="utf-8")
    ts.reset_cache()

    # Sitting at Barnet in the pool: he arrived there, then left for Burton.
    moved = ts.lookup("Rory Feely", "Barnet")
    assert moved is not None, "the second move must still register"
    assert moved["status"] == ts.GONE


def test_a_namesake_is_flagged_to_check_not_painted_red():
    """Harry Wood of Shelbourne is in the winger pool; the Harry Wood who signed
    for Barnet came from Hull City. Same name, different player — so ask a human
    rather than telling a scout to drop him."""
    moved = ts.lookup("Harry Wood", "Shelbourne FC")
    assert moved["status"] == ts.CHECK
    assert moved["club"] == "Barnet"


def test_mk_dons_and_milton_keynes_dons_are_one_club():
    """An abbreviation sharing no word with the full name needs spelling out.

    Impect writes "Milton Keynes Dons", the transfer feed writes "MK Dons".
    Substring matching cannot bridge that, and it alone put seven players on
    Staging's amber list who were simply at the club they had just joined.
    """
    assert ts._clubs_match("MK Dons", "Milton Keynes Dons") is True
    assert ts.club_key("MK Dons") == ts.club_key("Milton Keynes Dons")


def test_derry_city_and_cork_city_are_not_confused():
    """Both reduce to something containing "city"; they must not match."""
    assert ts._clubs_match("Derry City", "Cork City") is False
    assert ts._clubs_match("Derry City", "Derry City FC") is True


def test_galway_and_galway_united_stay_distinct_words():
    """Stripping "United" as noise would merge two different clubs."""
    assert ts.club_key("Galway United") == "galway united"


def test_a_free_agent_signing_still_counts_as_gone():
    """No selling club to check against, but the move is on record."""
    moved = ts.lookup("Andy Yiadom", "Reading")
    assert moved["status"] == ts.GONE
    assert moved["club"] == "Wigan Athletic"


def test_a_player_with_no_move_gets_nothing():
    assert ts.lookup("Eoin Kenny", "Dundalk FC") is None


def test_a_blank_name_is_not_a_lookup():
    assert ts.lookup("", "Dundalk") is None
    assert ts.lookup(None, None) is None


def test_annotate_leaves_untouched_players_alone():
    row = {"name": "Eoin Kenny", "club": "Dundalk FC"}
    assert "transfer" not in ts.annotate(row)

    moved = ts.annotate({"name": "Gbemi Arubi", "club": "Dundalk FC"})
    assert moved["transfer"]["club"] == "Burton Albion"


def test_between_windows_the_note_says_what_is_covered():
    from datetime import date

    meta = ts.report_meta(date(2026, 9, 8))

    assert meta["available"] is True
    assert meta["stale"] is False
    assert "League Two" in meta["detail"], "must state the coverage limit"


def test_a_report_built_before_the_open_window_reads_as_stale():
    """The January case. Nothing rebuilds this file on its own, so the page has
    to say so rather than let a clean row imply availability."""
    from datetime import date

    meta = ts.report_meta(date(2027, 1, 12))

    assert meta["stale"] is True
    assert "January" in meta["detail"]
    assert "missing" in meta["detail"]


def test_no_report_says_nobody_will_be_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (tmp_path / "gone.json",))
    ts.reset_cache()

    meta = ts.report_meta()

    assert meta["available"] is False
    assert "not be flagged" in meta["detail"]


def test_a_namesake_is_cleared_once_the_real_mover_is_identified():
    """Two Cameron Humphreys exist, with the exact same name.

    Ours is 28 and at Port Vale; the other is 22 and at Huddersfield on loan
    from Ipswich. A name cannot separate them, so ours was flagged amber — a
    query against a player who is not going anywhere. But the pool holds the
    other man at the club in the record, which identifies him positively and
    leaves nothing to ask about ours.
    """
    rows = [
        {"name": "Harry Wood", "club": "Barnet"},  # the man in the record
        {"name": "Harry Wood", "club": "Shelbourne FC"},  # a different player
    ]

    ts.annotate_all(rows)

    assert "transfer" not in rows[0], "already at Barnet — the row is correct"
    assert "transfer" not in rows[1], "identified elsewhere, so nothing to check"


def test_without_a_positive_match_the_doubt_is_kept():
    """Nobody in the squad sits at either club, so amber is the honest answer."""
    rows = [{"name": "Harry Wood", "club": "Shelbourne FC"}]

    ts.annotate_all(rows)

    assert rows[0]["transfer"]["status"] == ts.CHECK


def test_a_confirmed_move_survives_a_namesake():
    """Only amber is cleared this way. Red never rested on the name alone."""
    rows = [
        {"name": "Gbemi Arubi", "club": "Dundalk FC"},  # sold from here
        {"name": "Gbemi Arubi", "club": "Sligo Rovers"},  # some other player
    ]

    ts.annotate_all(rows)

    assert rows[0]["transfer"]["status"] == ts.GONE, "a real sale must stand"
    assert "transfer" not in rows[1]


def test_a_roster_settles_names_the_rows_alone_cannot():
    """The Watch list holds twelve players; the pool holds four thousand.

    Judged on its own the Watch list would show amber where Who To Scout shows
    nothing, and two tools disagreeing about a player is how people stop
    believing either of them.
    """
    watch_list = [{"name": "Harry Wood", "club": "Shelbourne FC"}]
    pool = [{"name": "Harry Wood", "club": "Barnet"}]

    ts.annotate_all(watch_list, roster=pool)

    assert "transfer" not in watch_list[0]


def test_an_empty_roster_falls_back_to_caution():
    """A missing pool costs precision, never correctness."""
    watch_list = [{"name": "Harry Wood", "club": "Shelbourne FC"}]

    ts.annotate_all(watch_list, roster=[])

    assert watch_list[0]["transfer"]["status"] == ts.CHECK


def test_a_missing_report_is_silent_not_fatal(monkeypatch, tmp_path):
    """No report should mean no flags, never a broken pool."""
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", (tmp_path / "gone.json",))
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_a_corrupt_report_is_silent_not_fatal(_report):
    _report.write_text("{ not json", encoding="utf-8")
    ts.reset_cache()
    assert ts.lookup("Gbemi Arubi", "Dundalk") is None


def test_we_look_where_the_report_actually_lives():
    """The first cut of this looked only under DATA_ROOT.

    On the server DATA_ROOT is the mounted volume, while the report ships inside
    the image at HUB_ROOT/data. So Staging found no file, flagged nobody, and
    looked identical to a window with no transfers in it. Sharing the report
    page's candidate list means the two cannot drift apart again.
    """
    from app.efl_transfer_report import REPORT_CANDIDATES

    assert SHIPPED_CANDIDATES == REPORT_CANDIDATES
    assert len(REPORT_CANDIDATES) >= 2


def test_a_real_report_is_readable_from_this_checkout(monkeypatch):
    """Guards the wiring end to end, against the file we actually ship.

    A fixture proves the matching works; only the shipped file proves we can
    find it. On Staging the file sat at /app/data while the code looked in
    /data, and every test still passed.
    """
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", SHIPPED_CANDIDATES)
    ts.reset_cache()

    assert ts._report_path() is not None, "no EFL transfer report in the repo"
    assert len(ts._load_index()) > 100
    assert ts.lookup("Gbemi Arubi", "Dundalk FC")["club"] == "Burton Albion"


def test_loan_detection_matches_the_shipped_report(monkeypatch):
    """`kind` is the only thing marking a loan, so it has to be trustworthy.

    In the report we ship, `kind == "loan"` and a fee reading "loan" agree on
    every one of the 723 signings. If a future source change breaks that, loans
    would quietly start showing as permanent sales — the exact error this whole
    change was correcting — so it fails here instead.
    """
    import json as _json

    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", SHIPPED_CANDIDATES)
    ts.reset_cache()
    report = _json.loads(ts._report_path().read_text(encoding="utf-8"))

    disagreements = [
        signing
        for league in report["leagues"]
        for team in league.get("teams") or []
        for signing in team.get("signed") or []
        if (((signing.get("kind") or "").lower() == "loan")
            != ("loan" in (signing.get("fee") or "").lower()))
    ]

    assert not disagreements, f"kind/fee disagree on {len(disagreements)} signings"

    loans = sum(
        1
        for league in report["leagues"]
        for team in league.get("teams") or []
        for signing in team.get("signed") or []
        if (signing.get("kind") or "").lower() == "loan"
    )
    assert loans > 100, "loans have stopped being marked in the source"


def test_loan_arrivals_are_at_many_clubs_not_just_exeter(monkeypatch):
    """On loan in Who To Scout used to show Exeter and nobody else."""
    monkeypatch.setattr(ts, "TRANSFER_REPORT_CANDIDATES", SHIPPED_CANDIDATES)
    ts.reset_cache()
    clubs = {
        rec["club"]
        for rows in ts._load_index().values()
        for rec in rows
        if rec.get("loan") and rec.get("club")
    }
    assert len(clubs) > 20, f"only {sorted(clubs)[:8]} have loan arrivals"
    assert not all("exeter" in str(name).lower() for name in clubs)


def test_who_to_scout_on_loan_filter_uses_transfer_loan_ins():
    from pathlib import Path

    js = Path("static/who-to-scout.js").read_text(encoding="utf-8")
    start = js.index("function loanInfoForPlayer")
    chunk = js[start : start + 900]
    assert 'move?.status === "loan_in"' in chunk
    assert "rankedPool({ ignoreLoan: true })" in js


def test_who_to_scout_annotates_the_whole_pool_at_once():
    """Wiring check, and it has to be the pool rather than the row.

    A single row cannot tell two Cameron Humphreys apart; the pool can, because
    it holds them both. It also stays at serve time rather than being baked into
    the cached payload — the standouts rebuild takes four minutes, and a
    transfer correction should not wait on it.
    """
    import inspect

    import app.main  # noqa: F401 - resolve the router imports
    from app import who_to_scout
    from app.who_to_scout import _who_to_scout_player

    source = inspect.getsource(who_to_scout.build_who_to_scout_data)
    assert "annotate_all(players)" in source, "pool-wide annotation was removed"

    # The trim itself stays a trim: no per-row flagging behind the pool's back.
    row = _who_to_scout_player({"name": "Gbemi Arubi", "club": "Dundalk FC"})
    assert "transfer" not in row

    rows = [dict(row)]
    ts.annotate_all(rows)
    assert rows[0]["transfer"]["club"] == "Burton Albion"
    assert rows[0]["transfer"]["status"] == ts.GONE


def test_the_index_reloads_when_the_report_changes(_report):
    assert ts.lookup("Gbemi Arubi", "Dundalk")["club"] == "Burton Albion"

    amended = json.loads(_report.read_text())
    amended["leagues"][0]["teams"][0]["name"] = "Burton Albion Reserves"
    import os
    import time

    _report.write_text(json.dumps(amended), encoding="utf-8")
    os.utime(_report, (time.time() + 5, time.time() + 5))

    # A transfer correction must not have to wait on the four-minute
    # standouts rebuild.
    assert ts.lookup("Gbemi Arubi", "Dundalk")["club"] == "Burton Albion Reserves"
